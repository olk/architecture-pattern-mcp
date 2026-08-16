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
Unit tests for HybridPatternRetriever fallback behaviour.

Test Case IDs: UT-RET-1 through UT-RET-4
Validates Requirements: FR-189 (no-match fallback)

Test Scenarios:
- UT-RET-1: When retrieve() finds no patterns, fallback is returned with score 0.0
- UT-RET-2: When retrieve() finds no patterns and fallback is missing, empty list is returned
- UT-RET-3: When retrieve() finds patterns, fallback is NOT used and real results returned
- UT-RET-4: get_by_name() returns pattern dict or None
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from src.patterns.retriever import (
    DEFAULT_FALLBACK_PATTERN_NAME,
    HybridPatternRetriever,
)

MOCK_FUSION_SCORE = 1 / 60


class MockBM25Index:
    """Minimal mock DomainBM25Index for retriever tests."""

    def __init__(self, built: bool = True) -> None:
        self._built = built

    @property
    def is_built(self) -> bool:
        return self._built

    def as_retriever(self, _top_k: int = 20):
        return _DummyRetriever()


class MockVectorIndex:
    """Minimal mock DomainVectorIndex for retriever tests."""

    def __init__(self, built: bool = True) -> None:
        self._built = built
        self._vector_store = object()

    @property
    def is_built(self) -> bool:
        return self._built

    @property
    def vector_store(self):
        return self._vector_store

    @property
    def _embedder(self):
        return None


class _DummyRetriever:
    """Minimal retriever that returns empty nodes for any query."""

    def retrieve(self, _query_bundle):
        return []


LAYERED_MONOLITH = {
    "name": "layered-monolith",
    "category": "structural",
    "context": "Single deployable application organized into horizontal layers.",
    "benefits": ["Simplicity"],
    "tradeoffs": ["Coupling"],
    "quality_attributes": {
        "maintainability": 6,
        "scalability": 4,
        "reliability": 6,
        "security": 6,
        "performance": 5,
    },
    "suitable_domains": ["traditional-web"],
    "best_practices": [],
}


class MockPatternLoader:
    """Mock PatternLoader with configurable filter_by_domain and get_by_name."""

    def __init__(
        self,
        filter_by_domain_result: list[dict] | None = None,
        get_by_name_result: dict | None = None,
    ) -> None:
        self._filter_result = filter_by_domain_result or []
        self._get_by_name_result = get_by_name_result
        self._loaded = True

    def filter_by_domain(self, _domain: str) -> list[dict]:
        return self._filter_result

    def get_by_name(self, _name: str) -> dict | None:
        return self._get_by_name_result


class TestRetrieveFallbackWhenNoMatch:
    """UT-RET-1: Fallback returned with score 0.0 when no patterns match."""

    def test_retrieve_returns_fallback_when_no_match(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        When QueryFusionRetriever returns no nodes and filter_by_domain
        finds nothing, retrieve() must return the fallback pattern
        with score 0.0 and emit a WARNING log.
        """
        loader = MockPatternLoader(
            filter_by_domain_result=[],
            get_by_name_result=LAYERED_MONOLITH,
        )

        retriever = HybridPatternRetriever(
            bm25_index=MockBM25Index(),
            vector_index=MockVectorIndex(),
            pattern_loader=loader,
        )
        retriever._dense_retriever = MagicMock()
        retriever._bm25_retriever = MagicMock()

        result = retriever.retrieve(
            user_domain="nonexistent-domain",
            normalized_domain="nonexistent-domain",
        )

        assert len(result) == 1
        pattern, score = result[0]
        assert pattern["name"] == "layered-monolith"
        assert score == 0.0
        assert "No pattern matched domain" in caplog.text
        assert "layered-monolith" in caplog.text
        assert any(r.levelno == logging.WARNING for r in caplog.records)


class TestRetrieveFallbackMissing:
    """UT-RET-2: Empty list returned when fallback pattern is also missing."""

    def test_retrieve_returns_empty_when_fallback_missing(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        When QueryFusionRetriever returns no nodes, filter_by_domain
        finds nothing, AND get_by_name returns None,
        retrieve() must return an empty list and emit a WARNING.
        """
        loader = MockPatternLoader(
            filter_by_domain_result=[],
            get_by_name_result=None,
        )

        retriever = HybridPatternRetriever(
            bm25_index=MockBM25Index(),
            vector_index=MockVectorIndex(),
            pattern_loader=loader,
        )
        retriever._dense_retriever = MagicMock()
        retriever._bm25_retriever = MagicMock()
        # Dense returns 2 fake nodes, BM25 returns empty
        retriever._dense_retriever.retrieve.return_value = [
            NodeWithScore(node=TextNode(text="x", metadata={"slug": "slug1"}), score=0.5),
            NodeWithScore(node=TextNode(text="y", metadata={"slug": "slug2"}), score=0.4),
        ]
        retriever._bm25_retriever.retrieve.return_value = []

        result = retriever.retrieve(
            user_domain="nonexistent-domain",
            normalized_domain="nonexistent-domain",
        )

        assert result == []
        assert "fallback" in caplog.text.lower()
        assert "not found" in caplog.text.lower()
        assert any(r.levelno == logging.WARNING for r in caplog.records)


class TestRetrieveRealResults:
    """UT-RET-3: Real results returned when patterns are found."""

    def test_retrieve_returns_real_results_when_available(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        When QueryFusionRetriever returns matching nodes that map to patterns,
        retrieve() must return those real patterns and NOT use the fallback.
        No WARNING should be emitted.
        """
        real_pattern = {
            "name": "microservices",
            "category": "architectural",
            "context": "Distributed system.",
            "benefits": ["Scalability"],
            "tradeoffs": ["Complexity"],
            "quality_attributes": {
                "maintainability": 7,
                "scalability": 9,
                "reliability": 7,
                "security": 6,
                "performance": 8,
            },
            "suitable_domains": ["microservices"],
            "best_practices": [],
        }

        loader = MockPatternLoader(
            filter_by_domain_result=[real_pattern],
            get_by_name_result=LAYERED_MONOLITH,
        )

        retriever = HybridPatternRetriever(
            bm25_index=MockBM25Index(),
            vector_index=MockVectorIndex(),
            pattern_loader=loader,
        )
        retriever._dense_retriever = MagicMock()
        retriever._bm25_retriever = MagicMock()

        fake_fusion_nodes = [
            NodeWithScore(
                node=TextNode(text="microservices", metadata={"slug": "microservices"}),
                score=MOCK_FUSION_SCORE,
            )
        ]
        retriever._dense_retriever.retrieve.return_value = fake_fusion_nodes
        retriever._bm25_retriever.retrieve.return_value = []

        result = retriever.retrieve(user_domain="microservices", normalized_domain="microservices")

        assert len(result) == 1
        pattern, score = result[0]
        assert pattern["name"] == "microservices"
        assert score == MOCK_FUSION_SCORE
        assert "No pattern matched" not in caplog.text
        assert not any(r.levelno == logging.WARNING for r in caplog.records)


class TestDefaultFallbackConstant:
    """UT-RET-4: DEFAULT_FALLBACK_PATTERN_NAME is 'layered-monolith'."""

    def test_default_fallback_pattern_name_is_layered_monolith(self) -> None:
        assert DEFAULT_FALLBACK_PATTERN_NAME == "layered-monolith"


class TestRetrievalLogging:
    """Verify INFO logs are emitted at each stage of the retrieval pipeline."""

    @pytest.fixture
    def retriever_with_mocks(self) -> HybridPatternRetriever:
        """Create a retriever with pre-seeded mock retrievers."""
        pattern = {
            "name": "microservices",
            "category": "architectural",
            "context": "Distributed system.",
            "benefits": ["Scalability"],
            "tradeoffs": ["Complexity"],
            "quality_attributes": {
                "maintainability": 7,
                "scalability": 9,
                "reliability": 7,
                "security": 6,
                "performance": 8,
            },
            "suitable_domains": ["microservices"],
            "best_practices": [],
        }
        loader = MockPatternLoader(
            filter_by_domain_result=[pattern],
            get_by_name_result=LAYERED_MONOLITH,
        )
        retriever = HybridPatternRetriever(
            bm25_index=MockBM25Index(),
            vector_index=MockVectorIndex(),
            pattern_loader=loader,
            bm25_top_k=5,
            dense_top_k=5,
            reranker_config=MagicMock(base_url="http://reranker:8080", timeout=30.0),
        )
        return retriever

    def test_dense_leg_emits_info_log(
        self, retriever_with_mocks: HybridPatternRetriever, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Stage 1: Dense leg emits INFO with slug and score."""
        retriever = retriever_with_mocks
        retriever._dense_retriever = MagicMock()
        retriever._bm25_retriever = MagicMock()
        retriever._dense_retriever.retrieve.return_value = [
            NodeWithScore(node=TextNode(text="x", metadata={"slug": "microservices"}), score=0.9),
            NodeWithScore(node=TextNode(text="y", metadata={"slug": "event-driven"}), score=0.7),
        ]
        retriever._bm25_retriever.retrieve.return_value = []

        with caplog.at_level(logging.INFO, logger="src.patterns.retriever"):
            retriever.retrieve(user_domain="microservices", normalized_domain="microservices")

        dense_logs = [r for r in caplog.records if r.levelno == logging.INFO and getattr(r, "stage", None) == "dense"]
        assert len(dense_logs) >= 1
        assert getattr(dense_logs[0], "summary", {}).get("count") == 2
        assert len(getattr(dense_logs[0], "summary", {}).get("top", [])) == 2

    def test_bm25_leg_emits_info_log(
        self, retriever_with_mocks: HybridPatternRetriever, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Stage 2: BM25 leg emits INFO with slug and score."""
        retriever = retriever_with_mocks
        retriever._dense_retriever = MagicMock()
        retriever._bm25_retriever = MagicMock()
        retriever._dense_retriever.retrieve.return_value = []
        retriever._bm25_retriever.retrieve.return_value = [
            NodeWithScore(node=TextNode(text="x", metadata={"slug": "microservices"}), score=0.85),
            NodeWithScore(node=TextNode(text="y", metadata={"slug": "event-driven"}), score=0.65),
        ]

        with caplog.at_level(logging.INFO, logger="src.patterns.retriever"):
            retriever.retrieve(user_domain="microservices", normalized_domain="microservices")

        bm25_logs = [r for r in caplog.records if r.levelno == logging.INFO and getattr(r, "stage", None) == "bm25"]
        assert len(bm25_logs) >= 1
        assert getattr(bm25_logs[0], "summary", {}).get("count") == 2

    def test_fusion_emits_info_log(
        self, retriever_with_mocks: HybridPatternRetriever, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Stage 3: Fusion emits INFO with fused scores."""
        retriever = retriever_with_mocks
        retriever._dense_retriever = MagicMock()
        retriever._bm25_retriever = MagicMock()
        retriever._dense_retriever.retrieve.return_value = [
            NodeWithScore(node=TextNode(text="x", metadata={"slug": "microservices"}), score=0.9),
        ]
        retriever._bm25_retriever.retrieve.return_value = [
            NodeWithScore(node=TextNode(text="x", metadata={"slug": "microservices"}), score=0.8),
        ]

        with caplog.at_level(logging.INFO, logger="src.patterns.retriever"):
            retriever.retrieve(user_domain="microservices", normalized_domain="microservices")

        fusion_logs = [r for r in caplog.records if r.levelno == logging.INFO and getattr(r, "stage", None) == "fusion"]
        assert len(fusion_logs) >= 1
        assert getattr(fusion_logs[0], "mode", None) == "reciprocal_rerank"

    def test_rerank_emits_info_log_when_enabled(
        self, retriever_with_mocks: HybridPatternRetriever, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Stage 4: Reranking emits INFO when enable_reranking=True."""
        retriever_with_mocks._enable_reranking = True
        retriever = retriever_with_mocks
        retriever._dense_retriever = MagicMock()
        retriever._bm25_retriever = MagicMock()
        retriever._dense_retriever.retrieve.return_value = [
            NodeWithScore(node=TextNode(text="x", metadata={"slug": "microservices"}), score=0.9),
            NodeWithScore(node=TextNode(text="y", metadata={"slug": "event-driven"}), score=0.7),
        ]
        retriever._bm25_retriever.retrieve.return_value = [
            NodeWithScore(node=TextNode(text="y", metadata={"slug": "event-driven"}), score=0.8),
        ]

        with caplog.at_level(logging.INFO, logger="src.patterns.retriever"), \
             patch("src.patterns.retriever.TextEmbeddingInference") as mock_reranker_cls:
            mock_reranker = MagicMock()
            mock_reranker.postprocess_nodes.return_value = retriever._dense_retriever.retrieve.return_value[:1]
            mock_reranker_cls.return_value = mock_reranker
            retriever.retrieve(user_domain="microservices", normalized_domain="microservices")

        rerank_logs = [r for r in caplog.records if r.levelno == logging.INFO and getattr(r, "stage", None) == "rerank"]
        assert len(rerank_logs) >= 1

    def test_final_selection_emits_info_log(
        self, retriever_with_mocks: HybridPatternRetriever, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Stage 5: Recall set emits INFO with pattern names and scores.

        Selection (top_k_patterns truncation) moved downstream to the analyze
        phase, so the retriever now emits a 'recall' stage log (not 'selected')
        carrying the full candidate set.
        """
        retriever = retriever_with_mocks
        retriever._dense_retriever = MagicMock()
        retriever._bm25_retriever = MagicMock()
        retriever._dense_retriever.retrieve.return_value = [
            NodeWithScore(node=TextNode(text="x", metadata={"slug": "microservices"}), score=0.9),
        ]
        retriever._bm25_retriever.retrieve.return_value = []

        with caplog.at_level(logging.INFO, logger="src.patterns.retriever"):
            retriever.retrieve(user_domain="microservices", normalized_domain="microservices")

        selected_logs = [r for r in caplog.records if r.levelno == logging.INFO and getattr(r, "stage", None) == "recall"]
        assert len(selected_logs) >= 1
        assert getattr(selected_logs[0], "domain", None) == "microservices"
        assert getattr(selected_logs[0], "fusion_mode", None) == "reciprocal_rerank"
        patterns = getattr(selected_logs[0], "patterns", [])
        assert len(patterns) == 1
        assert patterns[0]["name"] == "microservices"
