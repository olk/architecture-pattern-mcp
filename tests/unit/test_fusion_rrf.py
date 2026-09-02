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
Fusion regression tests.

Two families live here:

1. TestQueryFusionRRF — upstream RRF arithmetic regression.  The reciprocal
   rank formula is still part of the system's behavioural contract through
   the ``rank_fusion`` CE-blend (``reciprocal_rank_score`` blends the
   stage-1 fused-list rank with the cross-encoder rank), so the arithmetic
   must not drift silently.  If a test here fails after a dependency bump,
   the upstream ranking changed — require an explicit migration note.

2. TestRetrievalFusionModeConstant / TestRelativeScoreWeightedFusion — the
   stage-1 mode is locked to ``FUSION_MODES.RELATIVE_SCORE`` (per-leg
   min-max normalization, dense 0.7 / BM25 0.3 weights).  These tests pin
   the constants and hand-compute the weighted fusion arithmetic.

Locked-in properties (issue numbers refer to the original fixes):
- RRF score per node = sum over legs of 1/(rank + k - 1), k=60 (#23:
  rank starts at 1, so rank 1 contributes exactly 1/60 — NOT 1/61;
  numerically identical to upstream's 1/(rank0 + k) with rank0 = rank - 1)
- fusion runs on retriever-specific ranks (not upstream's
  fusion_rank/retriever_idx collision)
- the underlying TextNode objects (hash + metadata) are never mutated (#24)
- consensus slugs (retrieved by both legs) outrank single-leg slugs
"""

from unittest.mock import MagicMock

import pytest
from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.llms.mock import MockLLM
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from src.patterns.retriever import (
    RETRIEVAL_FUSION_MODE,
    RETRIEVAL_RETRIEVER_WEIGHTS,
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


class TestRetrievalFusionModeConstant:
    """Stage-1 fusion is locked: mode and leg weights are module constants,
    not config-exposable.  relative_score is required because it is the only
    family honoring retriever_weights under the pinned llama-index-core
    (RRF silently ignores them — upstream issue #21444)."""

    def test_runtime_fusion_mode_is_relative_score(self) -> None:
        assert RETRIEVAL_FUSION_MODE is FUSION_MODES.RELATIVE_SCORE

    def test_retriever_weights_favor_dense(self) -> None:
        assert RETRIEVAL_RETRIEVER_WEIGHTS == (0.7, 0.3)

    def test_invalid_weights_rejected(self) -> None:
        with pytest.raises(ValueError, match="retriever_weights"):
            HybridPatternRetriever(
                dense_retriever=MagicMock(),
                bm25_retriever=MagicMock(),
                pattern_loader=MagicMock(),
                retriever_weights=(0.7,),
            )
        with pytest.raises(ValueError, match="retriever_weights"):
            HybridPatternRetriever(
                dense_retriever=MagicMock(),
                bm25_retriever=MagicMock(),
                pattern_loader=MagicMock(),
                retriever_weights=(0.7, -0.1),
            )


class TestRelativeScoreWeightedFusion:
    """Hand-computed relative_score arithmetic with the production weights
    (0.7 dense, 0.3 BM25, num_queries=1).

    Per leg: min-max normalize raw scores to [0, 1], multiply by the leg
    weight, then sum across legs for nodes retrieved by both.  With these
    fixtures the best consensus score is 1.0 and a dense-only hit caps at
    0.7 — the scale the min_fusion_score floor (0.25) operates on.
    """

    def _fuse_weighted(
        self,
        dense: list[NodeWithScore],
        bm25: list[NodeWithScore],
        weights: tuple[float, float] = (0.7, 0.3),
    ) -> list[NodeWithScore]:
        fusion = QueryFusionRetriever(
            retrievers=[_StubRetriever(dense), _StubRetriever(bm25)],
            llm=MockLLM(),
            mode=FUSION_MODES.RELATIVE_SCORE,
            retriever_weights=list(weights),
            num_queries=1,
            use_async=False,
            similarity_top_k=len(SLUGS) * 2,  # lossless: union of both legs
        )
        return fusion.retrieve(
            QueryBundle(query_str="normalized", custom_embedding_strs=["raw"])
        )

    def test_hand_computed_weighted_scores(self, dense_nodes, bm25_nodes) -> None:
        fused = self._fuse_weighted(dense_nodes, bm25_nodes)
        fused_by_slug = {n.node.metadata["slug"]: n for n in fused}
        expected = {
            # dense mm, bm25 mm → 0.7·dense + 0.3·bm25
            "slug-a": 0.7 * 1.0 + 0.3 * 0.75,   # 0.925 — consensus winner
            "slug-b": 0.7 * 0.75 + 0.3 * 0.25,  # 0.6
            "slug-c": 0.7 * 0.5 + 0.3 * 1.0,    # 0.65
            "slug-d": 0.7 * 0.25 + 0.3 * 0.0,   # 0.175
            "slug-e": 0.7 * 0.0 + 0.3 * 0.5,    # 0.15
        }
        for slug, score in expected.items():
            assert fused_by_slug[slug].score == pytest.approx(score)

    def test_weighted_ordering_dense_consensus_wins(
        self, dense_nodes, bm25_nodes
    ) -> None:
        fused = self._fuse_weighted(dense_nodes, bm25_nodes)
        order = [n.node.metadata["slug"] for n in fused]
        assert order == ["slug-a", "slug-c", "slug-b", "slug-d", "slug-e"]

    def test_single_leg_scores_capped_by_leg_weight(self) -> None:
        # A dense-only hit normalizes to 1.0 → exactly 0.7; a BM25-only hit
        # → 0.3 — regardless of raw score magnitude (10.0 vs 0.9).
        dense = [NodeWithScore(node=TextNode(text="a", metadata={"slug": "a"}), score=0.9)]
        bm25 = [NodeWithScore(node=TextNode(text="b", metadata={"slug": "b"}), score=10.0)]
        fused = self._fuse_weighted(dense, bm25)
        fused_by_slug = {n.node.metadata["slug"]: n for n in fused}
        assert fused_by_slug["a"].score == pytest.approx(0.7)
        assert fused_by_slug["b"].score == pytest.approx(0.3)
        assert fused[0].node.metadata["slug"] == "a"
