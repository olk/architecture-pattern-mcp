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

"""DomainVectorIndex - FAISS vector index via llama-index-vector-stores-faiss.

FR-200: The system SHALL depend on llama-index-vector-stores-faiss and LiteLLMEmbedding.
FR-201: The system SHALL provide a DomainVectorIndex class for fast domain similarity search.

Architecture:
- Embedder: LiteLLMEmbedding (from llama-index-embeddings-litellm), optionally wrapped
  in InstructionAwareEmbedding when query/text instructions are set.
- Vector store: FaissVectorStore wrapping a faiss.IndexFlatIP.
- Both backends produce L2-normalised vectors so IndexFlatIP == cosine similarity.

Error Handling:
- E-6 (ERR_006): Failed to initialise LiteLLMEmbedding (http_status: 500, severity: critical)
- E-7 (ERR_007): Failed to embed via TEI (http_status: 500, severity: critical)
"""
from __future__ import annotations

import logging

import faiss
import numpy as np
from llama_index.vector_stores.faiss import FaissVectorStore

from src.config import EmbedderConfig
from src.patterns.embedder import build_embedder

logger = logging.getLogger(__name__)


class DomainVectorIndex:
    """FAISS vector index for domain slug similarity search using dense embeddings.

    Initialise via the keyword arguments directly, or use
    DomainVectorIndex.from_embedder_config(embedder_config) to build from
    the application config Pydantic model.

    Attributes:
        _embedder:     LiteLLMEmbedding (or InstructionAwareEmbedding) instance.
        _domains:      List of domain strings indexed.
        _faiss_index:  faiss.IndexFlatIP instance.
        _vector_store: FaissVectorStore wrapping _faiss_index.
    """

    def __init__(  # noqa: PLR0913
        self,
        base_url: str,
        model: str,
        api_key: str | None,
        embedding_dim: int,  # noqa: ARG002  # retained for API signature compat
        max_tokens: int,  # noqa: ARG002  # retained for API signature compat
        embed_batch_size: int,
        query_instruction: str,
        text_instruction: str,
        provider: str,
    ) -> None:
        """Initialise DomainVectorIndex.

        Args:
            base_url:          Embedder base URL, e.g. "http://localhost:8080".
            model:             Model name for the embedder.
            api_key:           Optional Bearer token / API key for the embedder.
            embedding_dim:      Expected embedding dimension (e.g. 1024 for Qwen3).
            max_tokens:        Max sequence length for the embedder.
            embed_batch_size:  Batch size for embedding calls (issue #9: now used).
            query_instruction:  Instruction prefix prepended to query text.
            text_instruction:  Instruction prefix prepended to indexed text.
            provider:          Embedder provider: "tei", "openai", "ollama", "vllm".
        """
        if not provider:
            raise ValueError("provider is required (e.g. 'tei', 'openai', 'ollama', 'vllm')")

        self._embed_batch_size = max(1, int(embed_batch_size))
        self._embedder = build_embedder(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            query_instruction=query_instruction,
            text_instruction=text_instruction,
            embed_batch_size=self._embed_batch_size,
        )

        self._domains: list[str] = []
        self._faiss_index: faiss.IndexFlatIP | None = None
        self._vector_store: FaissVectorStore | None = None

    @classmethod
    def from_embedder_config(cls, embedder_config: EmbedderConfig) -> DomainVectorIndex:
        """Build a DomainVectorIndex from an EmbedderConfig Pydantic model."""
        cfg = embedder_config.config
        return cls(
            provider=embedder_config.provider,
            model=cfg.model,
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            embed_batch_size=cfg.embed_batch_size,
            query_instruction=cfg.query_instruction,
            text_instruction=cfg.text_instruction,
            embedding_dim=cfg.embedding_dim,
            max_tokens=cfg.max_embedder_tokens,
        )

    @property
    def model_name(self) -> str:
        return self._embedder.model_name

    @property
    def is_built(self) -> bool:
        return self._vector_store is not None and len(self._domains) > 0

    def _embed(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        """Embed a batch of texts via LiteLLMEmbedding.

        Issue #9: for non-query batches, send ``embed_batch_size`` texts per
        HTTP call instead of one call per text. Query path remains single
        (one embedding per ``DomainVectorIndex.search`` call).

        Args:
            texts:     List of text strings to embed.
            is_query:  If True apply query_instruction prefix, else text_instruction prefix.

        Returns:
            L2-normalised embedding vectors as numpy array (float32).
        """
        if is_query:
            vecs = [self._embedder._get_query_embedding(t) for t in texts]
        else:
            batch = self._embed_batch_size
            vecs = []
            for i in range(0, len(texts), batch):
                chunk = texts[i : i + batch]
                vecs.extend(self._embedder._get_text_embeddings(chunk))
        arr = np.asarray(vecs, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return arr / norms

    def build_index(self, domains: list[str]) -> None:
        """Build FAISS index with L2-normalised domain-slug embeddings.

        Args:
            domains: List of domain slug strings to index.
        """
        if not domains:
            logger.warning("build_index called with empty domains list")
            self._domains = []
            self._faiss_index = None
            self._vector_store = None
            return

        self._domains = list(domains)
        embs = self._embed(domains, is_query=False)

        idx = faiss.IndexFlatIP(embs.shape[1])
        idx.add(embs.astype(np.float32))
        self._faiss_index = idx
        self._vector_store = FaissVectorStore(faiss_index=idx)

        logger.info(
            f"FAISS index built with {idx.ntotal} vectors",
            extra={"domain_count": len(self._domains)},
        )

    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        """Search for most similar domains to query.

        Args:
            query: Query string to find similar domains for.
            k:     Number of top results to return. ``k <= 0`` means
                   "full corpus" (lossless recall): the full indexed domain
                   list is returned, ordered by similarity.

        Returns:
            List of (domain, similarity_score) tuples, sorted by score descending.
        """
        if not self.is_built:
            logger.warning("search called on unbuilt index, returning empty results")
            return []

        assert self._faiss_index is not None, "faiss_index must be set when is_built is True"
        if k <= 0:
            k = len(self._domains)  # 0 = full corpus
        k = min(k, len(self._domains))
        q = self._embed([query], is_query=True)
        scores, indices = self._faiss_index.search(q.astype(np.float32), k)

        results: list[tuple[str, float]] = []
        for idx, score in zip(indices[0], scores[0], strict=True):
            if int(idx) >= 0:
                results.append((self._domains[int(idx)], float(score)))

        return results

    def rebuild_index(self, domains: list[str]) -> None:
        """Rebuild the FAISS index with new domains."""
        self._faiss_index = None
        self._vector_store = None
        self._domains = []
        self.build_index(domains)

    @property
    def domains(self) -> list[str]:
        """Return a copy of the indexed domain slug list."""
        return list(self._domains)

    @property
    def vector_store(self) -> FaissVectorStore | None:
        """Expose FaissVectorStore for advanced callers that need it."""
        return self._vector_store
