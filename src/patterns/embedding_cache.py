# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Persistence for the dense retrieval leg (embedding-vector snapshot).

The server rebuilds its dense leg on every start: ``_build_retrievers``
embeds one text per unique domain slug (~250) through the configured
embedder.  This module snapshots that index next to a manifest, so a later
start loads the vectors instead of recomputing them, while any change that
would invalidate the vectors forces a full rebuild.

Snapshot layout (llama-index ``StorageContext.persist``)::

    <cache_dir>/docstore.json                 node text + metadata
    <cache_dir>/index_store.json              index metadata
    <cache_dir>/default__vector_store.json    the FAISS binary
    <cache_dir>/graph_store.json              empty placeholder
    <cache_dir>/image__vector_store.json      empty placeholder
    <cache_dir>/manifest.json                 commit marker (see CacheManifest)

``manifest.json`` is written LAST (temp file + ``os.replace``) and removed
FIRST, so a crash mid-persist leaves no manifest and the next start treats
the directory as a miss instead of trusting a half-written snapshot.

Invalidation contract — any of these forces a rebuild:

* embedding-function fingerprint change (provider, base_url, model name,
  query/text instruction prefixes) — a different vector space;
* corpus hash change (a slug was added to or removed from the catalogue);
* probe-vector mismatch — a *different* model is served behind an unchanged
  configuration (the ``tei`` provider has no model field in the config, so a
  redeployed sidecar is invisible to the fingerprint).

Concurrency: ONE server process per cache directory.  There is no locking;
if two processes share a directory the last writer wins and the other may
read metadata that does not match its own build.  Deployments run a single
server per host, which is why a lock is not worth its failure modes here.

Every failure mode degrades to the embed-from-scratch path with a warning —
``load_cached_index`` and ``persist_index`` never raise into callers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
from llama_index.core import StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.vector_stores.faiss import FaissVectorStore

logger = logging.getLogger(__name__)

CACHE_FORMAT_VERSION = 1
ENV_CACHE_DIR = "EMBEDDING_CACHE"
DEFAULT_CACHE_DIR = "~/.config/architecture-pattern-mcp/embedding-index"
MANIFEST_FILENAME = "manifest.json"
# Single source of the dimension probe: nodes.build_vector_index imports it,
# and the pipeline embeds it once per start for the cache check.
PROBE_TEXT = "dimension-probe"
PROBE_SIMILARITY_THRESHOLD = 0.999
# Part of the fingerprint: a change of normalization would silently alter
# every vector while leaving provider/model untouched.
EMBEDDING_NORMALIZATION_TAG = "l2-normalized"
_DISABLE_VALUES = frozenset({"", "0", "false", "off", "no"})


def resolve_cache_dir() -> str | None:
    """Return the effective cache directory, or ``None`` when caching is off.

    Mirrors the ``ARCHITECTURE_PATTERN_JOBS_DB`` convention: the environment
    variable is re-read on every call (test isolation, container overrides).

    Returns:
        Expanded absolute path, or ``None`` when the variable is set to one of
        ``""``, ``0``, ``false``, ``off``, ``no`` (case-insensitive).
    """
    raw = os.environ.get(ENV_CACHE_DIR)
    if raw is None:
        return os.path.expanduser(DEFAULT_CACHE_DIR)
    value = raw.strip()
    if value.lower() in _DISABLE_VALUES:
        return None
    return os.path.expanduser(os.path.expandvars(value))


def _length_prefixed(value: str) -> bytes:
    """Encode a string unambiguously: byte length, colon, UTF-8 payload."""
    data = value.encode("utf-8")
    return str(len(data)).encode("ascii") + b":" + data


def compute_fingerprint(
    provider: str,
    base_url: str,
    model_name: str,
    query_instruction: str,
    text_instruction: str,
) -> str:
    """Hash the embedding function's identity (everything that changes vectors).

    ``api_key`` and ``embed_batch_size`` are excluded on purpose: neither
    alters the vector produced for a given text.

    Returns:
        Hex sha256 digest.
    """
    parts = [
        str(CACHE_FORMAT_VERSION),
        EMBEDDING_NORMALIZATION_TAG,
        provider,
        base_url,
        model_name,
        query_instruction,
        text_instruction,
    ]
    digest = hashlib.sha256()
    for part in parts:
        digest.update(_length_prefixed(part))
    return digest.hexdigest()


def corpus_fingerprint(domains: list[str]) -> str:
    """Hash the ordered domain-slug list (the embedded corpus).

    Catalogue load order is deterministic, so the same slug list always
    yields the same digest.

    Returns:
        Hex sha256 digest.
    """
    digest = hashlib.sha256()
    digest.update(_length_prefixed(str(len(domains))))
    for domain in domains:
        digest.update(_length_prefixed(domain))
    return digest.hexdigest()


@dataclass(frozen=True)
class CacheManifest:
    """Metadata committed alongside a snapshot; its presence means "usable"."""

    format_version: int
    fingerprint: str
    corpus_sha256: str
    dim: int
    probe_vector: list[float]

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-serialisable form."""
        return {
            "format_version": self.format_version,
            "fingerprint": self.fingerprint,
            "corpus_sha256": self.corpus_sha256,
            "dim": self.dim,
            "probe_vector": list(self.probe_vector),
        }


def _manifest_from_object(raw: object) -> CacheManifest:
    """Validate a decoded manifest document.

    Raises:
        TypeError: When a field has the wrong JSON type.
        ValueError: When a field has an unsupported value (version, lengths).
    """
    if not isinstance(raw, dict):
        raise TypeError("manifest is not a JSON object")
    mapping = cast("dict[str, object]", raw)

    format_version = mapping.get("format_version")
    if format_version != CACHE_FORMAT_VERSION or isinstance(format_version, bool):
        raise ValueError(f"unsupported manifest format_version {format_version!r}")

    fingerprint = mapping.get("fingerprint")
    corpus_sha256 = mapping.get("corpus_sha256")
    if not isinstance(fingerprint, str) or not isinstance(corpus_sha256, str):
        raise TypeError("manifest fingerprint fields missing or not strings")

    dim = mapping.get("dim")
    if not isinstance(dim, int) or isinstance(dim, bool):
        raise TypeError("manifest dim missing or not an int")

    raw_probe = mapping.get("probe_vector")
    if not isinstance(raw_probe, list):
        raise TypeError("manifest probe_vector missing or not a list")

    probe_vector: list[float] = []
    for entry in cast("list[object]", raw_probe):
        if not isinstance(entry, int | float) or isinstance(entry, bool):
            raise TypeError("manifest probe_vector contains a non-numeric entry")
        probe_vector.append(float(entry))
    if len(probe_vector) != dim:
        raise ValueError("manifest probe_vector length does not match dim")

    return CacheManifest(
        format_version=CACHE_FORMAT_VERSION,
        fingerprint=fingerprint,
        corpus_sha256=corpus_sha256,
        dim=dim,
        probe_vector=probe_vector,
    )


def load_manifest(cache_dir: str) -> CacheManifest | None:
    """Read ``<cache_dir>/manifest.json``.

    A missing, truncated, or malformed manifest is an ordinary cache miss.

    Returns:
        The manifest, or ``None`` when it is absent or unusable.
    """
    path = Path(cache_dir) / MANIFEST_FILENAME
    try:
        with path.open(encoding="utf-8") as handle:
            raw = json.load(handle)
        return _manifest_from_object(raw)
    except (OSError, ValueError, TypeError) as exc:
        logger.debug("Embedding index manifest unusable at %s (%s)", path, exc)
        return None


def remove_manifest(cache_dir: str) -> None:
    """Delete the commit marker; an absent manifest is not an error."""
    (Path(cache_dir) / MANIFEST_FILENAME).unlink(missing_ok=True)


def _write_manifest(cache_dir: str, manifest: CacheManifest) -> None:
    """Write the manifest atomically (temp file + rename)."""
    path = Path(cache_dir) / MANIFEST_FILENAME
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
    os.replace(temp_path, path)


def probe_matches(probe_vector: list[float], manifest: CacheManifest) -> bool:
    """Check that the live embedder still produces the cached probe vector.

    Catches a different model served behind an unchanged configuration (the
    fingerprint cannot see it).  Cosine similarity on the L2-normalised
    embeddings; a zero-norm vector never matches.
    """
    if len(probe_vector) != manifest.dim or len(manifest.probe_vector) != manifest.dim:
        return False
    left = np.asarray(probe_vector, dtype=np.float64)
    right = np.asarray(manifest.probe_vector, dtype=np.float64)
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0.0 or right_norm == 0.0:
        return False
    similarity = float(np.dot(left, right) / (left_norm * right_norm))
    return similarity >= PROBE_SIMILARITY_THRESHOLD


def load_cached_index(cache_dir: str, embed_model: BaseEmbedding) -> VectorStoreIndex | None:
    """Load the persisted dense index; ``None`` if it cannot be used.

    The FAISS store is restored from the snapshot directory and the index is
    rebuilt around it, so no text is re-embedded.  Query embeddings route
    through ``embed_model``, the live one.
    """
    try:
        vector_store = FaissVectorStore.from_persist_dir(persist_dir=cache_dir)
        storage_context = StorageContext.from_defaults(persist_dir=cache_dir, vector_store=vector_store)
        index = load_index_from_storage(storage_context, embed_model=embed_model)
    except Exception as exc:  # noqa: BLE001 — every failure degrades to a rebuild
        logger.warning("Embedding index snapshot unreadable (%s); rebuilding", exc)
        return None
    if not isinstance(index, VectorStoreIndex):
        logger.warning(
            "Embedding index snapshot holds %s, not a VectorStoreIndex; rebuilding",
            type(index).__name__,
        )
        return None
    return index


def persist_index(index: VectorStoreIndex, cache_dir: str, manifest: CacheManifest) -> bool:
    """Snapshot ``index`` and commit it with ``manifest``; never raises.

    Called immediately after the embedding pass — the caller persists before it
    does anything else with the built index, so a crash after startup finishes
    cannot cost the corpus embedding work again.

    Order matters: the manifest is removed before the snapshot is written and
    rewritten last, so an interrupted write cannot leave a manifest pointing
    at inconsistent files.

    Returns:
        True when the snapshot is committed (manifest on disk), False when the
        write failed and the run continues cacheless.
    """
    try:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        remove_manifest(cache_dir)
        index.storage_context.persist(persist_dir=cache_dir)
        _write_manifest(cache_dir, manifest)
    except Exception as exc:  # noqa: BLE001 — caching is best-effort by contract
        logger.warning("Embedding index cache write failed (%s); cache disabled this run", exc)
        try:
            remove_manifest(cache_dir)
        except OSError as cleanup_error:
            logger.debug("Could not clear the embedding index manifest at %s (%s)", cache_dir, cleanup_error)
        return False
    return True
