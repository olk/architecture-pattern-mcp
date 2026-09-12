# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
L2 oracles for the retrieval resolution/floor/fallback tail
(src/patterns/retriever.py::HybridPatternRetriever.retrieve; ledger rows
FUS-1/2/3, garden mutants FG-25/26/27).

  FUS-1  a REAL outcome always carries ≥ 1 resolved pattern (empty recall
         must fall back, never return an empty REAL result).
  FUS-2  a REAL outcome always passed the min_fusion_score gate: the best
         reported score is ≥ the configured floor.
  FUS-3  every fallback outcome carries the is_fallback sentinel on the
         pattern dict and the 0.0 score — it can never outrank a real
         match.

Mechanics: both retriever legs are deterministic stubs over generated slug
orderings (the tests/unit/test_fusion_rrf.py stub pattern); the TEI
reranker is a deterministic fake injected into the private ``_reranker``
slot so ``_ensure_reranker`` no-ops and the production rank_fusion blend
runs without a sidecar. Branch reachability is steered with ``target()``
(fallback vs REAL must BOTH be sampled or the oracle would be vacuous —
asserted via a flag counter per run, not by hope).

Direction of the implication: retrieval_fusion.fizz checks FUS-1..3
exhaustively over the abstracted resolve/floor/tag machine; this oracle
samples the real code's decision tail over generated leg orderings and
floors.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

from hypothesis import given, settings, target
from hypothesis import strategies as st
from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from src.patterns.loader import PatternLoader
from src.patterns.retriever import (
    DEFAULT_FALLBACK_PATTERN_NAME,
    HybridPatternRetriever,
    RetrievalOutcome,
)

SLUG_POOL = ["slug-alpha", "slug-beta", "slug-gamma", "slug-delta"]
CATEGORY = "structural"


class _StubRetriever(BaseRetriever):
    """Retriever leg returning a fixed node list (fixture pattern from L1)."""

    def __init__(self, nodes: list[NodeWithScore]) -> None:
        super().__init__()
        self._nodes = nodes

    def _retrieve(self, _query_bundle: QueryBundle) -> list[NodeWithScore]:
        return list(self._nodes)


class _FakeReranker:
    """Deterministic stand-in for SafeTEIReranker: reverses leg order.

    Injected into ``_reranker`` so the production blend
    RR(fused_rank) + RR(ce_rank) executes without a TEI sidecar.
    """

    def postprocess_nodes(
        self, nodes: list[NodeWithScore], query_bundle: QueryBundle | None = None
    ) -> list[NodeWithScore]:
        reordered = list(reversed(nodes))
        return [
            NodeWithScore(node=n.node.model_copy(deep=True), score=1.0 - 0.01 * rank)
            for rank, n in enumerate(reordered)
        ]


def _nodes(order: list[str]) -> list[NodeWithScore]:
    return [
        NodeWithScore(
            node=TextNode(text=slug, metadata={"slug": slug, "domain": slug}, id_=slug),
            score=1.0 - 0.1 * rank,
        )
        for rank, slug in enumerate(order)
    ]


def _make_loader() -> MagicMock:
    loader = MagicMock(spec=PatternLoader)
    loader.filter_by_domain.side_effect = lambda slug: [
        {"name": slug, "context": f"ctx for {slug}", "category": CATEGORY}
    ]
    loader.get_by_name.return_value = {
        "name": DEFAULT_FALLBACK_PATTERN_NAME,
        "context": "fallback context",
        "category": CATEGORY,
    }
    return loader


def _make_retriever(
    dense_order: list[str],
    bm25_order: list[str],
    min_fusion_score: float,
    rerank_top_n: int,
) -> HybridPatternRetriever:
    retriever = HybridPatternRetriever(
        dense_retriever=_StubRetriever(_nodes(dense_order)),
        bm25_retriever=_StubRetriever(_nodes(bm25_order)),
        pattern_loader=_make_loader(),
        min_fusion_score=min_fusion_score,
        rerank_top_n=rerank_top_n,
    )
    # Injection seam: _ensure_reranker no-ops when _reranker is not None,
    # so the production blend runs without a TEI sidecar.
    cast("Any", retriever)._reranker = _FakeReranker()
    return retriever


_slug_set = st.lists(
    st.sampled_from(SLUG_POOL), min_size=1, max_size=3, unique=True
)

# Mix a coarse and a fine floor distribution: blend scores live in
# (0, 2/60]; the fine branch keeps the REAL branch reachable while the
# coarse branch exercises the fallback branch.
_floor = st.one_of(
    st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0, max_value=0.05, allow_nan=False, allow_infinity=False),
)


def _is_fallback(outcome: RetrievalOutcome) -> bool:
    return bool(outcome.patterns) and bool(
        outcome.patterns[0][0].get("is_fallback")
    )


class TestFusionDecisionLaws:
    @given(
        dense_order=_slug_set,
        bm25_order=_slug_set,
        min_fusion_score=_floor,
        rerank_top_n=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=40)
    def test_fus_1_2_3_hold_over_generated_tail(
        self,
        dense_order: list[str],
        bm25_order: list[str],
        min_fusion_score: float,
        rerank_top_n: int,
    ) -> None:
        retriever = _make_retriever(dense_order, bm25_order, min_fusion_score, rerank_top_n)
        outcome = retriever.retrieve("raw domain", "normalized domain")

        fell_back = _is_fallback(outcome)
        target(0.0 if fell_back else 1.0, label="REAL=1 sampled / fallback=0 sampled")

        if fell_back:
            # FUS-3: the sentinel and the 0.0 score are mandatory.
            pattern_dict, score = outcome.patterns[0]
            assert pattern_dict.get("is_fallback") is True
            assert score == 0.0
            return

        # FUS-1: a REAL outcome is never empty.
        assert len(outcome.patterns) >= 1
        # FUS-2: the gate ran — best score ≥ floor.
        best_score = outcome.patterns[0][1]
        assert best_score >= min_fusion_score, (
            f"REAL outcome below floor: best={best_score}, floor={min_fusion_score}"
        )
        # FUS-3 (inverse direction): no REAL pattern carries the sentinel.
        assert all(not p[0].get("is_fallback") for p in outcome.patterns)

    def test_fus_1_empty_recall_falls_back(self) -> None:
        """No leg returns anything → fallback (never an empty REAL result)."""
        retriever = _make_retriever([], [], min_fusion_score=0.0, rerank_top_n=3)
        outcome = retriever.retrieve("raw", "normalized")
        assert _is_fallback(outcome)

    def test_fus_3_fallback_sentinel_shape(self) -> None:
        retriever = _make_retriever([], [], min_fusion_score=0.0, rerank_top_n=3)
        outcome = retriever.retrieve("raw", "normalized")
        pattern_dict, score = outcome.patterns[0]
        assert pattern_dict["name"] == DEFAULT_FALLBACK_PATTERN_NAME
        assert pattern_dict["is_fallback"] is True
        assert score == 0.0
        assert outcome.matched_domains == []

    def test_both_branches_reachable_for_floor_sweep(self) -> None:
        """Direct evidence the floor gate discriminates (vacuity pin).

        Same generated input, floor below vs above the best blend —
        exactly one of the two outcomes must flip.
        """
        retriever_low = _make_retriever(
            ["slug-alpha", "slug-beta"], ["slug-beta"], 0.0, 3
        )
        real = retriever_low.retrieve("raw", "normalized")
        assert not _is_fallback(real)
        retriever_high = _make_retriever(
            ["slug-alpha", "slug-beta"], ["slug-beta"], 1.0, 3
        )
        fallback = retriever_high.retrieve("raw", "normalized")
        assert _is_fallback(fallback)
