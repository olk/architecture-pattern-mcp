# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
L2 oracles for scoring/blend decisions over generated inputs.

  S-1  reciprocal_rank_score (src/patterns/retriever.py) is strictly
       decreasing in rank at the production k (RRF_K = 60, pinned by
       tests/unit/test_fusion_rrf.py).
  S-2  RRF bounds: every score lies in (0, 1/k], equality only at rank 1;
       the two-leg blend RR(r1) + RR(r2) never exceeds 2/k, equality only
       at r1 = r2 = 1 (the declared fusion_score ceiling, retriever.py
       module docstring: "in [0, 2/60]").
  S-3  Config weight-sum validators (src/config.py RetrievalConfig
       _check_score_blend_weights / _check_leg_weights_sum_to_one) agree
       with the boundary-tolerance reference implementation
       ref_within_tolerance from the L3 garden — differential oracle over
       the 1e-3 tolerance boundary the server refuses to start without.

Vacuity (P2): S-1/S-2 kill arithmetic-flip and boundary mutants of the RRF
formula; S-3 kills boundary-tolerance mutants in the blend-weight validator
(garden class M-27..M-31 mirrors it).
"""

from __future__ import annotations

from itertools import pairwise

from hypothesis import given, settings
from hypothesis import strategies as st

from src.config import RetrievalConfig
from src.patterns.retriever import RRF_K, reciprocal_rank_score
from tests.verification.gardens.bug_garden import ref_within_tolerance

rank_strategy = st.integers(min_value=1, max_value=10_000)


class TestS1RRFMonotone:
    @given(ranks=st.lists(rank_strategy, min_size=2, max_size=20, unique=True))
    @settings(max_examples=50)
    def test_strictly_decreasing_in_rank(self, ranks: list[int]) -> None:
        ordered = sorted(ranks)
        scores = [reciprocal_rank_score(r) for r in ordered]
        assert all(a > b for a, b in pairwise(scores)), (
            f"not strictly decreasing for ranks {ordered}: {scores}"
        )


class TestS2RRFBounds:
    @given(rank=rank_strategy)
    @settings(max_examples=50)
    def test_single_leg_score_bounded_by_one_over_k(self, rank: int) -> None:
        score = reciprocal_rank_score(rank)
        assert score > 0.0
        assert score <= 1.0 / RRF_K
        assert (score == 1.0 / RRF_K) == (rank == 1)

    @given(r1=rank_strategy, r2=rank_strategy)
    @settings(max_examples=50)
    def test_blend_ceiling_two_over_k(self, r1: int, r2: int) -> None:
        blend = reciprocal_rank_score(r1) + reciprocal_rank_score(r2)
        assert blend <= 2.0 / RRF_K
        assert (blend == 2.0 / RRF_K) == (r1 == 1 and r2 == 1)

    @given(r1=rank_strategy, r2=rank_strategy)
    @settings(max_examples=30)
    def test_higher_consensus_never_loses(self, r1: int, r2: int) -> None:
        """Consensus ordering law: (1,1) outranks every other rank pair."""
        if (r1, r2) != (1, 1):
            assert reciprocal_rank_score(1) + reciprocal_rank_score(1) > (
                reciprocal_rank_score(r1) + reciprocal_rank_score(r2)
            )


def _config_rejects(analysis: float, fusion: float) -> bool:
    try:
        RetrievalConfig(analysis_blend_weight=analysis, fusion_blend_weight=fusion)
    except Exception:  # noqa: BLE001 — pydantic ValidationError (a ValueError)
        return True
    return False


class TestS3BlendWeightToleranceDifferential:
    """RetrievalConfig._check_score_blend_weights ⇔ ref_within_tolerance.

    Only exercised inside the Field domain (ge=0, le=1 per weight) so the
    differential compares the tolerance validator, not the Field bounds.
    """

    @given(
        analysis=st.floats(
            min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
        ),
        fusion=st.floats(
            min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=75)
    def test_config_validator_matches_garden_reference(
        self, analysis: float, fusion: float
    ) -> None:
        reference_ok = ref_within_tolerance([analysis, fusion], target=1.0, tol=1e-3)
        config_ok = not _config_rejects(analysis, fusion)
        assert config_ok == reference_ok, (
            f"tolerance divergence: config_ok={config_ok}, "
            f"ref_ok={reference_ok} for ({analysis!r}, {fusion!r})"
        )

    def test_tolerance_boundary_is_exactly_1e_3(self) -> None:
        # Boundary pins. Floating point: sums landing within the tolerance
        # are accepted; the exact ±1e-3 edge falls outside in binary floats —
        # asserted differentially against the garden reference rather than
        # by hand-derived direction.
        assert not _config_rejects(0.3, 0.7 + 0.5e-3)   # inside → accepted
        assert not _config_rejects(0.3, 0.7 - 0.5e-3)
        assert _config_rejects(0.3, 0.7 + 1.5e-3)       # outside → rejected
        assert _config_rejects(0.3, 0.7 - 1.5e-3)
        for fusion in (0.7 + 1e-3, 0.7 - 1e-3):
            edge = not _config_rejects(0.3, fusion)
            reference = ref_within_tolerance([0.3, fusion], target=1.0, tol=1e-3)
            assert edge == reference, f"exact-edge divergence at {fusion!r}"
