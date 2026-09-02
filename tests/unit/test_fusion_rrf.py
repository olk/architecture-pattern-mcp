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
RRF fusion regression tests (via the upstream QueryFusionRetriever).

The fusion formula is part of the system's behavioural contract:
``min_fusion_score`` thresholds stored in operator configs are calibrated
against these exact score values, so the arithmetic must not drift
silently.  If a test here fails after a dependency bump, the upstream
fusion ranking changed — require an explicit migration note, never a
silent threshold shift.

Locked-in properties (issue numbers refer to the original fixes):
- RRF score per node = sum over legs of 1/(rank + k - 1), k=60 (#23:
  rank starts at 1, so rank 1 contributes exactly 1/60 — NOT 1/61;
  numerically identical to upstream's 1/(rank0 + k) with rank0 = rank - 1)
- fusion runs on retriever-specific ranks (not upstream's
  fusion_rank/retriever_idx collision)
- the underlying TextNode objects (hash + metadata) are never mutated (#24)
- consensus slugs (retrieved by both legs) outrank single-leg slugs
- the legacy "simple" rank-union mode is removed from configuration and
  from HybridPatternRetriever
"""

from unittest.mock import MagicMock

import pytest
from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.llms.mock import MockLLM
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from src.config import FusionMode
from src.patterns.retriever import (
    RRF_K,
    HybridPatternRetriever,
    reciprocal_rank_score,
)

SLUGS = ["slug-a", "slug-b", "slug-c", "slug-d", "slug-e"]

# Distinct orderings per leg so every node has a unique (dense_rank, bm25_rank)
# combination: dense prefers a>b>c>d>e, BM25 prefers c>a>e>b>d.
DENSE_ORDER = SLUGS
BM25_ORDER = ["slug-c", "slug-a", "slug-e", "slug-b", "slug-d"]


def _nodes(order: list[str]) -> list[NodeWithScore]:
    return [
        NodeWithScore(
            node=TextNode(text=slug, metadata={"slug": slug, "domain": slug}, id_=slug),
            score=1.0 - 0.1 * rank,
        )
        for rank, slug in enumerate(order)
    ]


class _StubRetriever(BaseRetriever):
    """Retriever leg that always returns a fixed node list."""

    def __init__(self, nodes: list[NodeWithScore]) -> None:
        super().__init__()
        self._nodes = nodes

    def _retrieve(self, _query_bundle: QueryBundle) -> list[NodeWithScore]:
        return list(self._nodes)


def _fuse(dense: list[NodeWithScore], bm25: list[NodeWithScore]) -> list[NodeWithScore]:
    fusion = QueryFusionRetriever(
        retrievers=[_StubRetriever(dense), _StubRetriever(bm25)],
        llm=MockLLM(),  # num_queries=1 never calls it; avoids Settings.llm auto-construction
        mode=FUSION_MODES.RECIPROCAL_RANK,
        num_queries=1,
        use_async=False,
        similarity_top_k=len(SLUGS) * 2,  # lossless: union of both legs
    )
    # Same split-query shape HybridPatternRetriever.retrieve uses.
    return fusion.retrieve(
        QueryBundle(query_str="normalized", custom_embedding_strs=["raw"])
    )


@pytest.fixture
def dense_nodes() -> list[NodeWithScore]:
    return _nodes(DENSE_ORDER)


@pytest.fixture
def bm25_nodes() -> list[NodeWithScore]:
    return _nodes(BM25_ORDER)


def _expected_rrf(slug: str) -> float:
    dense_rank = DENSE_ORDER.index(slug) + 1
    bm25_rank = BM25_ORDER.index(slug) + 1
    return 1.0 / (dense_rank + RRF_K - 1) + 1.0 / (bm25_rank + RRF_K - 1)


class TestRRFContract:
    def test_rrf_k_is_60(self) -> None:
        assert RRF_K == 60.0

    def test_rank_one_contributes_exactly_one_over_k(self) -> None:
        # Issue #23 off-by-one fix: rank=1 → 1/60, NOT 1/61.
        assert reciprocal_rank_score(1) == pytest.approx(1.0 / 60.0)

    def test_formula(self) -> None:
        assert reciprocal_rank_score(3) == pytest.approx(1.0 / 62.0)
        assert reciprocal_rank_score(60) == pytest.approx(1.0 / 119.0)


class TestQueryFusionRRF:
    def test_every_node_score_matches_hand_computed_rrf(
        self, dense_nodes, bm25_nodes
    ) -> None:
        fused = _fuse(dense_nodes, bm25_nodes)
        fused_by_slug = {n.node.metadata["slug"]: n for n in fused}
        assert set(fused_by_slug) == set(SLUGS)
        for slug in SLUGS:
            assert fused_by_slug[slug].score == pytest.approx(_expected_rrf(slug))

    def test_consensus_slug_wins(self, dense_nodes, bm25_nodes) -> None:
        # slug-a holds dense rank 1 + BM25 rank 2 → RRF 1/60 + 1/61 ≈ 0.03306,
        # the highest consensus score and must outrank every other slug
        # (runner-up slug-c: 1/62 + 1/60 ≈ 0.03280).
        fused = _fuse(dense_nodes, bm25_nodes)
        assert fused[0].node.metadata["slug"] == "slug-a"

    def test_ranking_matches_expected_rrf_order(
        self, dense_nodes, bm25_nodes
    ) -> None:
        fused = _fuse(dense_nodes, bm25_nodes)
        expected = sorted(SLUGS, key=_expected_rrf, reverse=True)
        assert [n.node.metadata["slug"] for n in fused] == expected

    def test_nodes_never_mutated(self, dense_nodes, bm25_nodes) -> None:
        # Issue #24: fusion must not touch the input TextNode objects
        # (hash = sha256(text + metadata), id_ not included).  Upstream may
        # overwrite the NodeWithScore wrapper's .score with the fused value;
        # the node identity must stay intact.
        dense_before = [(n.node.hash, n.node.metadata) for n in dense_nodes]
        bm25_before = [(n.node.hash, n.node.metadata) for n in bm25_nodes]
        _fuse(dense_nodes, bm25_nodes)
        assert [(n.node.hash, n.node.metadata) for n in dense_nodes] == dense_before
        assert [(n.node.hash, n.node.metadata) for n in bm25_nodes] == bm25_before

    def test_cross_leg_dedup_by_node_hash(self, dense_nodes, bm25_nodes) -> None:
        # The same slug retrieved by both legs must merge into ONE fused
        # entry (TextNode.hash = sha256(text + metadata), id_ not included).
        fused = _fuse(dense_nodes, bm25_nodes)
        assert len(fused) == len(SLUGS)

    def test_split_query_reaches_legs(self, dense_nodes, bm25_nodes) -> None:
        # The dense leg must receive the raw embedding string and the BM25
        # leg the normalized query_str — the QueryBundle split contract.
        seen: list[str] = []

        class _RecordingRetriever(_StubRetriever):
            def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
                seen.append(query_bundle.query_str)
                return list(self._nodes)

        fusion = QueryFusionRetriever(
            retrievers=[
                _RecordingRetriever(dense_nodes),
                _RecordingRetriever(bm25_nodes),
            ],
            llm=MockLLM(),
            mode=FUSION_MODES.RECIPROCAL_RANK,
            num_queries=1,
            use_async=False,
            similarity_top_k=100,
        )
        bundle = QueryBundle(query_str="normalized", custom_embedding_strs=["raw"])
        fusion.retrieve(bundle)
        assert bundle.embedding_strs == ["raw"]
        assert seen.count("normalized") == 2


class TestSimpleModeRemoved:
    """The legacy "simple" rank-union mode is gone: not a config literal and
    not accepted by HybridPatternRetriever (upstream FUSION_MODES.SIMPLE has
    different max-raw-score semantics and must stay unreachable)."""

    def test_simple_mode_not_in_fusion_mode(self) -> None:
        assert "simple" not in FusionMode.__args__  # type: ignore[attr-defined]
        assert "reciprocal_rerank" in FusionMode.__args__  # type: ignore[attr-defined]
        assert "relative_score" in FusionMode.__args__  # type: ignore[attr-defined]
        assert "dist_based_score" in FusionMode.__args__  # type: ignore[attr-defined]

    def test_simple_mode_rejected_by_retriever(self) -> None:
        with pytest.raises(ValueError, match="Unsupported fusion mode"):
            HybridPatternRetriever(
                dense_retriever=MagicMock(),
                bm25_retriever=MagicMock(),
                pattern_loader=MagicMock(),
                mode="simple",  # type: ignore[arg-type]
            )

    def test_unknown_mode_rejected_by_retriever(self) -> None:
        with pytest.raises(ValueError, match="Unsupported fusion mode"):
            HybridPatternRetriever(
                dense_retriever=MagicMock(),
                bm25_retriever=MagicMock(),
                pattern_loader=MagicMock(),
                mode="bogus",  # type: ignore[arg-type]
            )
