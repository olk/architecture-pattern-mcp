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
Tests for the dense retrieval leg built via the upstream LlamaIndex stack
(VectorStoreIndex over FaissVectorStore) and the InstructionAwareEmbedding
normalisation / batching contract.

Uses a deterministic hash embedder so the gates run fully offline:
- factory behaviour (top_k resolution, full-corpus semantics)
- result shape (NodeWithScore, slug metadata, float scores)
- self-recall (identical texts embed identically → top-1)
- cross-leg node-hash equality (dense + BM25 share one node set)
- mutation isolation (leg results are independent object graphs)
- embedder L2-normalisation on every embedding path
- batching: get_text_embedding_batch chunks by embed_batch_size (issue #9
  HTTP-call shape) and accepts the show_progress kwarg (S1)
"""

import math
from typing import Any
from unittest.mock import MagicMock

import pytest
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.schema import QueryBundle
from llama_index.embeddings.litellm import LiteLLMEmbedding

from src.patterns.embedder import InstructionAwareEmbedding
from src.patterns.nodes import (
    build_bm25_retriever,
    build_domain_nodes,
    build_vector_index,
)

DOMAINS = [
    "event-driven",
    "cloud-native",
    "microservices",
    "real-time-processing",
    "high-traffic",
]


class _HashEmbedding(BaseEmbedding):
    """Deterministic offline embedder: identical texts → identical vectors."""

    embed_dim: int

    def __init__(self, embed_dim: int = 8, **kwargs: Any) -> None:
        super().__init__(embed_dim=embed_dim, **kwargs)

    @staticmethod
    def _vectorize(text: str, dim: int) -> list[float]:
        vec = [0.0] * dim
        for i, ch in enumerate(text):
            bucket = ord(ch) % dim
            vec[bucket] += ((ord(ch) + i) % 7 + 1) / 8.0
        # L2-normalise: IndexFlatIP ranks by inner product, which equals
        # cosine only for unit vectors — the same contract the production
        # embedder enforces.
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def _get_query_embedding(self, text: str) -> list[float]:
        return self._vectorize(text, self.embed_dim)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._vectorize(text, self.embed_dim)

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [self._vectorize(t, self.embed_dim) for t in texts]

    async def _aget_query_embedding(self, text: str) -> list[float]:
        return self._vectorize(text, self.embed_dim)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._vectorize(text, self.embed_dim)


def _make_embedder(dim: int = 8) -> _HashEmbedding:
    return _HashEmbedding(embed_dim=dim)


@pytest.fixture
def nodes() -> list:
    return build_domain_nodes(DOMAINS)


@pytest.fixture
def dense_retriever(nodes) -> object:
    return build_vector_index(nodes, _make_embedder()).as_retriever(
        similarity_top_k=3
    )


def _slugs(result) -> list[str]:
    return [n.node.metadata["slug"] for n in result]


class TestBuildVectorIndex:
    def test_returns_nodes_with_score(self, dense_retriever) -> None:
        result = dense_retriever.retrieve(QueryBundle(query_str="cloud-native"))
        assert len(result) > 0
        for nws in result:
            assert nws.score is not None
            assert isinstance(nws.score, float)

    def test_node_metadata_contains_slug(self, dense_retriever) -> None:
        result = dense_retriever.retrieve(QueryBundle(query_str="microservices"))
        assert "microservices" in _slugs(result)

    def test_respects_similarity_top_k(self, dense_retriever) -> None:
        result = dense_retriever.retrieve(QueryBundle(query_str="processing"))
        assert len(result) <= 3

    def test_full_corpus_top_k(self, nodes) -> None:
        retriever = build_vector_index(nodes, _make_embedder()).as_retriever(
            similarity_top_k=len(nodes)
        )
        result = retriever.retrieve(QueryBundle(query_str="processing"))
        assert len(result) == len(DOMAINS)

    def test_scores_sorted_descending(self, dense_retriever) -> None:
        result = dense_retriever.retrieve(QueryBundle(query_str="real time processing"))
        scores = [n.score for n in result]
        assert scores == sorted(scores, reverse=True)

    def test_in_memory_no_persist(self, nodes, monkeypatch: pytest.MonkeyPatch) -> None:
        """In-memory-only contract: neither the vector store nor the storage
        context may be persisted during build."""
        from llama_index.vector_stores.faiss import FaissVectorStore

        persist_spy = MagicMock()
        monkeypatch.setattr(FaissVectorStore, "persist", persist_spy)
        build_vector_index(nodes, _make_embedder())
        persist_spy.assert_not_called()


class TestDenseSelfRecall:
    """Identical texts embed identically, so a slug queried with its own
    text must be top-1 with the maximum score."""

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_slug_self_recall_top1(self, nodes, domain) -> None:
        retriever = build_vector_index(nodes, _make_embedder()).as_retriever(
            similarity_top_k=len(nodes)
        )
        result = retriever.retrieve(QueryBundle(query_str=domain))
        assert _slugs(result)[0] == domain


class TestCrossLegParity:
    """Both legs consume the same node set: hashes must match per slug."""

    def test_dense_and_bm25_node_hash_equal(self, nodes) -> None:
        dense = build_vector_index(nodes, _make_embedder()).as_retriever(
            similarity_top_k=len(nodes)
        )
        bm25 = build_bm25_retriever(nodes, top_k=len(nodes))
        dense_result = dense.retrieve(QueryBundle(query_str="microservices"))
        bm25_result = bm25.retrieve(QueryBundle(query_str="microservices"))
        dense_hashes = {n.node.metadata["slug"]: n.node.hash for n in dense_result}
        for nws in bm25_result:
            slug = nws.node.metadata["slug"]
            assert dense_hashes[slug] == nws.node.hash


class TestMutationIsolation:
    """Two retrievals must not share mutable node objects (S2): metadata
    stamped on one retrieval's nodes must not appear in the other."""

    def test_dense_nodes_isolated_between_retrievals(self, nodes) -> None:
        retriever = build_vector_index(nodes, _make_embedder()).as_retriever(
            similarity_top_k=len(nodes)
        )
        first = retriever.retrieve(QueryBundle(query_str="microservices"))
        first[0].node.metadata["rerank_logit"] = 42.0
        second = retriever.retrieve(QueryBundle(query_str="microservices"))
        assert all("rerank_logit" not in n.node.metadata for n in second)


def _fake_vec(text: str) -> list[float]:
    base = float(sum(ord(c) for c in text) % 97 + 1)
    return [base, base * 2.0, base * 3.0, base * 4.0]


async def _afake_query(self, q: str) -> list[float]:
    return _fake_vec(q)


async def _afake_text(self, t: str) -> list[float]:
    return _fake_vec(t)


class TestEmbedderNormalisation:
    """Every InstructionAwareEmbedding path emits unit-length vectors."""

    @staticmethod
    def _embedder() -> InstructionAwareEmbedding:
        return InstructionAwareEmbedding(
            model_name="test-model",
            api_base="http://localhost:1234",
            api_key="test-key",
            query_instruction="query: ",
            text_instruction="passage: ",
        )

    @pytest.fixture(autouse=True)
    def _patch_litellm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            LiteLLMEmbedding, "_get_query_embedding", lambda self, q: _fake_vec(q)
        )
        monkeypatch.setattr(
            LiteLLMEmbedding, "_get_text_embedding", lambda self, t: _fake_vec(t)
        )
        monkeypatch.setattr(
            LiteLLMEmbedding,
            "_get_text_embeddings",
            lambda self, ts: [_fake_vec(t) for t in ts],
        )
        monkeypatch.setattr(LiteLLMEmbedding, "_aget_query_embedding", _afake_query)
        monkeypatch.setattr(LiteLLMEmbedding, "_aget_text_embedding", _afake_text)

    def test_query_embedding_unit_norm(self) -> None:
        vec = self._embedder()._get_query_embedding("microservices")
        assert math.isclose(sum(x * x for x in vec) ** 0.5, 1.0, rel_tol=1e-5)

    def test_text_embedding_unit_norm(self) -> None:
        vec = self._embedder()._get_text_embedding("microservices")
        assert math.isclose(sum(x * x for x in vec) ** 0.5, 1.0, rel_tol=1e-5)

    def test_batch_embeddings_unit_norm(self) -> None:
        vecs = self._embedder().get_text_embedding_batch(DOMAINS)
        for vec in vecs:
            assert math.isclose(sum(x * x for x in vec) ** 0.5, 1.0, rel_tol=1e-5)

    @pytest.mark.asyncio
    async def test_async_embeddings_unit_norm(self) -> None:
        embedder = self._embedder()
        qvec = await embedder._aget_query_embedding("microservices")
        tvec = await embedder._aget_text_embedding("microservices")
        for vec in (qvec, tvec):
            assert math.isclose(sum(x * x for x in vec) ** 0.5, 1.0, rel_tol=1e-5)

    def test_instructions_still_prepended(self) -> None:
        embedder = self._embedder()
        assert embedder._format_query("x") == "query: x"
        assert embedder._format_text("x") == "passage: x"

    def test_batch_accepts_show_progress_kwarg(self) -> None:
        embedder = self._embedder()
        vecs = embedder.get_text_embedding_batch(DOMAINS, show_progress=True)
        assert len(vecs) == len(DOMAINS)


class TestEmbedderBatching:
    """Issue #9 HTTP-call shape: ceil(n / embed_batch_size) calls."""

    def test_batch_chunks_by_embed_batch_size(self, monkeypatch: pytest.MonkeyPatch) -> None:
        embedder = InstructionAwareEmbedding(
            model_name="test-model",
            api_base="http://localhost:1234",
            api_key="test-key",
            embed_batch_size=16,
        )
        calls: list[int] = []

        def fake_batch(self, texts: list[str]) -> list[list[float]]:
            calls.append(len(texts))
            return [[1.0, 0.0] for _ in texts]

        monkeypatch.setattr(LiteLLMEmbedding, "_get_text_embeddings", fake_batch)
        texts = [f"domain-{i}" for i in range(213)]
        result = embedder.get_text_embedding_batch(texts)
        assert len(result) == 213
        assert len(calls) == math.ceil(213 / 16)
        assert max(calls) <= 16
