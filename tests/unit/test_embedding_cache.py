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

"""
Tests for the embedding-index snapshot cache (src/patterns/embedding_cache.py
plus its single integration seam, ``ArchitecturePipeline._build_retrievers``).

Contract under test:
- the cache directory comes from the environment, with an off switch;
- the fingerprint covers every input that changes the vector space, and only
  those;
- a valid snapshot loads with ZERO text-embedding calls, an invalid one is a
  miss (manifest, fingerprint, corpus, probe vector, unreadable files);
- a cold build persists; a warm start reuses it;
- every failure degrades to the embed-from-scratch path.

All tests are offline: the embedder is the deterministic hash fake from
test_vector_retriever, extended with call counters.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.schema import QueryBundle

from src.config import EmbedderConfig, EmbedderInnerConfig
from src.patterns import embedding_cache
from src.patterns.embedder import TEI_EMBEDDER_MODEL, resolve_model_name
from src.patterns.embedding_cache import (
    CACHE_FORMAT_VERSION,
    DEFAULT_CACHE_DIR,
    ENV_CACHE_DIR,
    PROBE_TEXT,
    CacheManifest,
    compute_fingerprint,
    corpus_fingerprint,
    load_cached_index,
    load_manifest,
    persist_index,
    probe_matches,
    remove_manifest,
    resolve_cache_dir,
)
from src.patterns.nodes import build_domain_nodes, build_vector_index
from src.pipeline import ArchitecturePipeline
from tests.unit.test_vector_retriever import _HashEmbedding

DOMAINS = [
    "event-driven",
    "cloud-native",
    "microservices",
    "real-time-processing",
    "high-traffic",
]
EMBED_DIM = 8
BASE_URL = "http://pattern-tei-embed:8080"
QUERY_INSTRUCTION = "Instruct: Given a software architecture pattern domain tag\nQuery: "
FINGERPRINT_FIELDS = ["provider", "base_url", "model_name", "query_instruction", "text_instruction"]


class _CountingEmbedding(_HashEmbedding):
    """Deterministic hash embedder that counts text/multi-text/query calls."""

    text_calls: int = 0
    query_calls: int = 0

    def reset_counters(self) -> None:
        self.text_calls = 0
        self.query_calls = 0

    def _get_query_embedding(self, text: str) -> list[float]:
        self.query_calls += 1
        return list(super()._get_query_embedding(text))

    def _get_text_embedding(self, text: str) -> list[float]:
        self.text_calls += 1
        return list(super()._get_text_embedding(text))

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        self.text_calls += len(texts)
        return [list(vector) for vector in super()._get_text_embeddings(texts)]


def _make_embedder() -> _CountingEmbedding:
    return _CountingEmbedding(embed_dim=EMBED_DIM)


def _manifest_for(embedder: _CountingEmbedding, domains: list[str], *, provider: str = "tei") -> CacheManifest:
    probe = embedder.get_query_embedding(PROBE_TEXT)
    return CacheManifest(
        format_version=CACHE_FORMAT_VERSION,
        fingerprint=compute_fingerprint(provider, BASE_URL, "openai//data/qwen3-embedding-0.6b", QUERY_INSTRUCTION, ""),
        corpus_sha256=corpus_fingerprint(domains),
        dim=len(probe),
        probe_vector=probe,
    )


def _persist_demo(cache_dir: str, domains: list[str]) -> VectorStoreIndex:
    """Cold build over ``domains`` and persist it into ``cache_dir``."""
    embedder = _make_embedder()
    index = build_vector_index(build_domain_nodes(domains), embedder)
    persist_index(index, cache_dir, _manifest_for(embedder, domains))
    return index


def _slugs(result: object) -> list[str]:
    return [node_with_score.node.metadata["slug"] for node_with_score in result]  # type: ignore[attr-defined]


def _embedder_config(provider: str = "tei") -> EmbedderConfig:
    return EmbedderConfig(
        provider=provider,
        config=EmbedderInnerConfig(
            base_url=BASE_URL,
            api_key=None,
            embed_batch_size=16,
            query_instruction=QUERY_INSTRUCTION,
            text_instruction="",
        ),
    )


def _make_pipeline(domains: list[str], provider: str = "tei") -> ArchitecturePipeline:
    """Pipeline with a loader stub whose catalogue emits ``domains``."""
    stub_loader = MagicMock()
    stub_loader.is_loaded = True
    stub_loader.load_all.return_value = [{"suitable_domains": [domain]} for domain in domains]
    return ArchitecturePipeline(
        agent=MagicMock(),
        pattern_loader=stub_loader,
        embedder_config=_embedder_config(provider),
    )


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point the cache at a per-test directory (never the developer's ~/.config)."""
    directory = tmp_path / "embedding-index"
    monkeypatch.setenv(ENV_CACHE_DIR, str(directory))
    return str(directory)


@pytest.fixture
def embedder(monkeypatch: pytest.MonkeyPatch) -> _CountingEmbedding:
    """Replace the embedder factory with one shared counting fake."""
    fake = _make_embedder()
    monkeypatch.setattr("src.patterns.embedder.build_embedder", lambda *args, **kwargs: fake)
    return fake


class TestResolveCacheDir:
    def test_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(ENV_CACHE_DIR, raising=False)
        assert resolve_cache_dir() == str(Path(DEFAULT_CACHE_DIR).expanduser())

    @pytest.mark.parametrize("value", ["", "0", "false", "off", "no", " FALSE ", "Off"])
    def test_disable_values(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(ENV_CACHE_DIR, value)
        assert resolve_cache_dir() is None

    def test_expands_user_and_variables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APM_CACHE_ROOT", "/srv/cache")
        monkeypatch.setenv(ENV_CACHE_DIR, "$APM_CACHE_ROOT/embedding-index")
        assert resolve_cache_dir() == "/srv/cache/embedding-index"

    def test_expands_tilde(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_CACHE_DIR, "~/apm-cache")
        assert resolve_cache_dir() == str(Path("~/apm-cache").expanduser())


class TestFingerprint:
    def test_stable_for_equal_inputs(self) -> None:
        first = compute_fingerprint("tei", BASE_URL, "model", "q", "t")
        second = compute_fingerprint("tei", BASE_URL, "model", "q", "t")
        assert first == second

    @pytest.mark.parametrize("field", FINGERPRINT_FIELDS)
    def test_changed_field_changes_fingerprint(self, field: str) -> None:
        baseline: dict[str, str] = {
            "provider": "tei",
            "base_url": BASE_URL,
            "model_name": "model",
            "query_instruction": "q",
            "text_instruction": "t",
        }
        mutated = dict(baseline)
        mutated[field] = baseline[field] + "-changed"
        assert compute_fingerprint(**baseline) != compute_fingerprint(**mutated)

    def test_field_boundaries_are_not_ambiguous(self) -> None:
        """Length prefixes: shifting characters between fields must not collide."""
        assert compute_fingerprint("tei", "ab", "c", "q", "t") != compute_fingerprint("tei", "a", "bc", "q", "t")

    def test_corpus_fingerprint_tracks_slugs_and_order(self) -> None:
        assert corpus_fingerprint(DOMAINS) == corpus_fingerprint(list(DOMAINS))
        assert corpus_fingerprint(DOMAINS) != corpus_fingerprint([*DOMAINS, "extra"])
        assert corpus_fingerprint(DOMAINS) != corpus_fingerprint(list(reversed(DOMAINS)))


class TestResolveModelName:
    """The fingerprint's model name must be the name the embedder actually uses."""

    def test_tei_is_the_fixed_local_model(self) -> None:
        assert resolve_model_name("tei") == TEI_EMBEDDER_MODEL

    def test_provider_match_is_case_insensitive(self) -> None:
        assert resolve_model_name("TEI") == TEI_EMBEDDER_MODEL

    @pytest.mark.parametrize("provider", ["openai", "ollama", "vllm", "hosted_vllm"])
    def test_other_providers_resolve_their_model_elsewhere(self, provider: str) -> None:
        assert resolve_model_name(provider) == ""


class TestManifest:
    def test_round_trip(self, tmp_path: Path) -> None:
        embedder = _make_embedder()
        manifest = _manifest_for(embedder, DOMAINS)
        (tmp_path / "manifest.json").write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
        loaded = load_manifest(str(tmp_path))
        assert loaded == manifest

    def test_missing_manifest_is_a_miss(self, tmp_path: Path) -> None:
        assert load_manifest(str(tmp_path)) is None

    def test_corrupt_json_is_a_miss(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.json").write_text('{"format_version": 1, "fingerprint": ', encoding="utf-8")
        assert load_manifest(str(tmp_path)) is None

    def test_wrong_format_version_is_a_miss(self, tmp_path: Path) -> None:
        manifest = _manifest_for(_make_embedder(), DOMAINS)
        document = manifest.to_dict()
        document["format_version"] = CACHE_FORMAT_VERSION + 1
        (tmp_path / "manifest.json").write_text(json.dumps(document), encoding="utf-8")
        assert load_manifest(str(tmp_path)) is None

    def test_probe_length_mismatch_is_a_miss(self, tmp_path: Path) -> None:
        manifest = _manifest_for(_make_embedder(), DOMAINS)
        document = manifest.to_dict()
        document["dim"] = manifest.dim + 1
        (tmp_path / "manifest.json").write_text(json.dumps(document), encoding="utf-8")
        assert load_manifest(str(tmp_path)) is None

    @pytest.mark.parametrize(
        "field_mutation",
        [
            pytest.param({"format_version": True}, id="bool-format-version"),
            pytest.param({"dim": True}, id="bool-dim"),
            pytest.param({"probe_vector": ["0.1", "0.2"]}, id="string-vector-entry"),
            pytest.param({"probe_vector": "0.1, 0.2"}, id="string-vector"),
            pytest.param({"fingerprint": 7}, id="int-fingerprint"),
        ],
    )
    def test_wrongly_typed_field_is_a_miss(self, tmp_path: Path, field_mutation: dict[str, object]) -> None:
        """A hand-edited manifest must never be trusted (json truthiness trap:
        True == 1, so the bool guards are what reject it)."""
        document = _manifest_for(_make_embedder(), DOMAINS).to_dict()
        document.update(field_mutation)
        (tmp_path / "manifest.json").write_text(json.dumps(document), encoding="utf-8")
        assert load_manifest(str(tmp_path)) is None

    def test_length_prefix_encoding_is_unambiguous(self) -> None:
        """The fingerprint contract: byte length, colon, UTF-8 payload."""
        assert embedding_cache._length_prefixed("ab") == b"2:ab"
        assert embedding_cache._length_prefixed("ä") == b"2:\xc3\xa4"
        assert embedding_cache._length_prefixed("") == b"0:"

    def test_remove_manifest_is_idempotent(self, tmp_path: Path) -> None:
        remove_manifest(str(tmp_path))
        manifest = _manifest_for(_make_embedder(), DOMAINS)
        (tmp_path / "manifest.json").write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
        remove_manifest(str(tmp_path))
        assert load_manifest(str(tmp_path)) is None


class TestProbeMatches:
    def test_identical_vector_matches(self) -> None:
        embedder = _make_embedder()
        manifest = _manifest_for(embedder, DOMAINS)
        assert probe_matches(list(manifest.probe_vector), manifest) is True

    def test_orthogonal_vector_does_not_match(self) -> None:
        manifest = _manifest_for(_make_embedder(), DOMAINS)
        orthogonal = [1.0] + [0.0] * (manifest.dim - 1)
        assert probe_matches(orthogonal, manifest) is False

    def test_dimension_mismatch_does_not_match(self) -> None:
        manifest = _manifest_for(_make_embedder(), DOMAINS)
        assert probe_matches([*manifest.probe_vector, 0.1], manifest) is False

    def test_zero_vector_does_not_match(self) -> None:
        manifest = _manifest_for(_make_embedder(), DOMAINS)
        assert probe_matches([0.0] * manifest.dim, manifest) is False


class TestSnapshotRoundTrip:
    def test_load_reproduces_ranking_and_scores(self, tmp_path: Path) -> None:
        fresh = _persist_demo(str(tmp_path), DOMAINS)
        loaded = load_cached_index(str(tmp_path), _make_embedder())
        assert loaded is not None

        query = QueryBundle(query_str="cloud native")
        fresh_result = fresh.as_retriever(similarity_top_k=len(DOMAINS)).retrieve(query)
        loaded_result = loaded.as_retriever(similarity_top_k=len(DOMAINS)).retrieve(query)

        assert _slugs(loaded_result) == _slugs(fresh_result)
        for loaded_node, fresh_node in zip(loaded_result, fresh_result, strict=True):
            assert loaded_node.score == pytest.approx(fresh_node.score, abs=1e-6)

    def test_load_embeds_nothing(self, tmp_path: Path) -> None:
        _persist_demo(str(tmp_path), DOMAINS)
        embedder = _make_embedder()
        assert load_cached_index(str(tmp_path), embedder) is not None
        assert embedder.text_calls == 0

    def test_loaded_docstore_hashes_match_fresh_nodes(self, tmp_path: Path) -> None:
        """Stage-1 fusion accumulates by node.hash — the snapshot must not alter it."""
        _persist_demo(str(tmp_path), DOMAINS)
        loaded = load_cached_index(str(tmp_path), _make_embedder())
        assert loaded is not None
        stored = {node.metadata["slug"]: node.hash for node in loaded.storage_context.docstore.docs.values()}
        fresh = {node.metadata["slug"]: node.hash for node in build_domain_nodes(DOMAINS)}
        assert stored == fresh

    def test_snapshot_writes_six_files(self, tmp_path: Path) -> None:
        directory = tmp_path / "cache"
        _persist_demo(str(directory), DOMAINS)
        assert sorted(entry.name for entry in directory.iterdir()) == [
            "default__vector_store.json",
            "docstore.json",
            "graph_store.json",
            "image__vector_store.json",
            "index_store.json",
            "manifest.json",
        ]

    def test_persist_failure_leaves_no_manifest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def exploding_persist(*args: object, **kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(StorageContext, "persist", exploding_persist)
        _persist_demo(str(tmp_path), DOMAINS)
        assert load_manifest(str(tmp_path)) is None

    def test_non_index_payload_is_a_miss(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A snapshot whose index is not a VectorStoreIndex is not adopted."""
        _persist_demo(str(tmp_path), DOMAINS)
        monkeypatch.setattr("src.patterns.embedding_cache.load_index_from_storage",
                            lambda *args, **kwargs: object())
        assert load_cached_index(str(tmp_path), _make_embedder()) is None

    def test_unreadable_snapshot_is_a_miss(self, tmp_path: Path) -> None:
        _persist_demo(str(tmp_path), DOMAINS)
        (tmp_path / "default__vector_store.json").write_text("not a faiss index", encoding="utf-8")
        assert load_cached_index(str(tmp_path), _make_embedder()) is None


class TestWarmStartThroughPipeline:
    """The integration seam: ``_build_retrievers`` reuses a valid snapshot."""

    def test_cold_then_warm_start(
        self, cache_dir: str, embedder: _CountingEmbedding, caplog: pytest.LogCaptureFixture
    ) -> None:
        cold = _make_pipeline(DOMAINS)
        cold._build_retrievers()
        assert embedder.text_calls == len(DOMAINS)
        assert embedder.query_calls == 1

        embedder.reset_counters()
        warm = _make_pipeline(DOMAINS)
        with caplog.at_level("INFO", logger="src.pipeline"):
            warm._build_retrievers()
        assert embedder.text_calls == 0
        assert embedder.query_calls == 1
        assert f"snapshot {cache_dir}" in caplog.text

        assert cold._dense_retriever is not None
        assert warm._dense_retriever is not None
        query = QueryBundle(query_str="microservices")
        cold_result = cold._dense_retriever.retrieve(query)
        warm_result = warm._dense_retriever.retrieve(query)
        assert _slugs(warm_result) == _slugs(cold_result)
        assert warm._retrieval_corpus_size == len(DOMAINS)

    def test_snapshot_hits_disk_within_the_cold_build(
        self, cache_dir: str, embedder: _CountingEmbedding
    ) -> None:
        """Persist happens immediately after the embedding pass, not on shutdown:
        the manifest + files exist the moment _build_retrievers returns."""
        assert load_manifest(cache_dir) is None
        _make_pipeline(DOMAINS)._build_retrievers()
        manifest = load_manifest(cache_dir)
        assert manifest is not None
        assert manifest.corpus_sha256 == corpus_fingerprint(DOMAINS)
        assert sorted(p.name for p in Path(cache_dir).iterdir()) == [
            "default__vector_store.json",
            "docstore.json",
            "graph_store.json",
            "image__vector_store.json",
            "index_store.json",
            "manifest.json",
        ]

    def test_cold_build_logs_the_snapshot_path(
        self, cache_dir: str, embedder: _CountingEmbedding, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("INFO", logger="src.pipeline"):
            _make_pipeline(DOMAINS)._build_retrievers()
        assert "Embedding index cache miss (no/invalid manifest)" in caplog.text
        assert f"Embedding index snapshot written: {len(DOMAINS)} slugs (path {cache_dir})" in caplog.text

    def test_persist_failure_returns_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def exploding_persist(*args: object, **kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(StorageContext, "persist", exploding_persist)
        index = build_vector_index(build_domain_nodes(DOMAINS), _make_embedder())
        assert persist_index(index, str(tmp_path / "cache"),
                             _manifest_for(_make_embedder(), DOMAINS)) is False
        assert load_manifest(str(tmp_path / "cache")) is None

    def test_corpus_change_forces_rebuild(self, cache_dir: str, embedder: _CountingEmbedding) -> None:
        _make_pipeline(DOMAINS)._build_retrievers()
        embedder.reset_counters()
        extended = [*DOMAINS, "edge-computing"]
        _make_pipeline(extended)._build_retrievers()
        assert embedder.text_calls == len(extended)

    def test_provider_change_forces_rebuild(self, cache_dir: str, embedder: _CountingEmbedding) -> None:
        _make_pipeline(DOMAINS)._build_retrievers()
        embedder.reset_counters()
        _make_pipeline(DOMAINS, provider="openai")._build_retrievers()
        assert embedder.text_calls == len(DOMAINS)

    def test_probe_mismatch_forces_rebuild(self, cache_dir: str, embedder: _CountingEmbedding) -> None:
        """A different model behind an unchanged config is caught by the probe."""
        _make_pipeline(DOMAINS)._build_retrievers()
        manifest = load_manifest(cache_dir)
        assert manifest is not None
        document = manifest.to_dict()
        document["probe_vector"] = [1.0] + [0.0] * (manifest.dim - 1)
        (Path(cache_dir) / "manifest.json").write_text(json.dumps(document), encoding="utf-8")

        embedder.reset_counters()
        _make_pipeline(DOMAINS)._build_retrievers()
        assert embedder.text_calls == len(DOMAINS)

    def test_missing_manifest_forces_rebuild(self, cache_dir: str, embedder: _CountingEmbedding) -> None:
        _make_pipeline(DOMAINS)._build_retrievers()
        remove_manifest(cache_dir)
        embedder.reset_counters()
        _make_pipeline(DOMAINS)._build_retrievers()
        assert embedder.text_calls == len(DOMAINS)

    def test_persist_failure_still_builds_retriever(
        self, cache_dir: str, embedder: _CountingEmbedding, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def exploding_persist(*args: object, **kwargs: object) -> None:
            raise OSError("read-only volume")

        monkeypatch.setattr(StorageContext, "persist", exploding_persist)
        pipeline = _make_pipeline(DOMAINS)
        pipeline._build_retrievers()
        assert pipeline._dense_retriever is not None
        assert load_manifest(cache_dir) is None

    def test_disabled_cache_never_touches_disk(
        self,
        tmp_path: Path,
        embedder: _CountingEmbedding,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        sentinel = tmp_path / "disabled-cache"
        monkeypatch.setenv(ENV_CACHE_DIR, "0")
        with caplog.at_level("INFO", logger="src.pipeline"):
            _make_pipeline(DOMAINS)._build_retrievers()
        assert embedder.text_calls == len(DOMAINS)
        assert "Embedding index cache disabled; embedding corpus" in caplog.text
        assert "cache miss" not in caplog.text
        assert not sentinel.exists()
        assert not (tmp_path / "embedding-index").exists()
