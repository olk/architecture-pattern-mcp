# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
L2 property oracles for the two-stage recall-then-score decision logic
(L2 counterparts of the T1..T10 regression families pinned by
``tests/unit/test_two_stage_fixes.py`` — the L1 behavioural oracle).

  TS-1 (T1)  ``analysis_to_pydantic`` tolerates generated EMPTY result
             lists — never raises, preserves empty structure and metrics.
  TS-2 (T2)  ``ScoredPattern`` JSON roundtrips preserve analysis_score and
             fusion_score exactly (the response-boundary metadata the
             catalogue validator would drop).
  TS-3 (T5)  ``RequirementWeights`` exposes exactly the six
             QUALITY_ATTRIBUTE_KEYS; ``as_dict`` round-trips them.
  TS-4 (T10) zero-sum weights take the production unweighted-mean branch
             of ``_score_patterns`` — differential against the garden's
             ``ref_blend`` with uniform weights.
  TS-5 (new) ``_score_patterns.analysis_score`` is the requirements-
             weighted average × 10 — differential against the garden's
             ``ref_blend`` over generated weights/QA tables.
  TS-6 (new) selection ordering: sorted by ``blended_score`` when fusion
             blending is active, by ``analysis_score`` when it is off.

T4/T7 are carried by the DL-5 and FUS-2 oracles respectively (early-stop
threshold: test_pipeline_properties.py; fusion floor: 
test_retrieval_fusion_properties.py) and are not duplicated here.

Vacuity (P2): TS-4/TS-5 kill arithmetic-flip and weight-drop mutants in
``_score_patterns``; TS-6 kills sort-key drops.
"""

from __future__ import annotations

from typing import Any, cast

from hypothesis import given, settings
from hypothesis import strategies as st

from src.config import RetrievalConfig
from src.pipeline import AnalysisResult, ArchitecturePipeline
from src.schemas import QualityMetrics
from src.schemas.analysis import QUALITY_ATTRIBUTE_KEYS, RequirementWeights
from src.schemas.enums import PatternCategory
from src.schemas.patterns import ScoredPattern
from src.tools._adapters import analysis_to_pydantic
from tests.verification.gardens.bug_garden import ref_blend

qa_value = st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)
weight_value = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


class _ConfigOnlyPipeline(ArchitecturePipeline):
    """Only ``_retrieval_config`` — enough for ``_score_patterns``."""

    def __init__(self, config: RetrievalConfig | None = None) -> None:
        self._retrieval_config = config if config is not None else RetrievalConfig()


def _weights(first: float, *rest: float) -> RequirementWeights:
    return RequirementWeights(
        scalability=first, maintainability=rest[0], reliability=rest[1],
        security=rest[2], performance=rest[3], simplicity=rest[4],
    )


class TestTS1EmptyAnalysisTolerated:
    @given(
        qm=st.builds(
            QualityMetrics,
            maintainability=qa_value,
            scalability=qa_value,
            reliability=qa_value,
            security=qa_value,
            performance=qa_value,
            testability=qa_value,
        ),
    )
    @settings(max_examples=20, deadline=None)
    def test_empty_lists_never_raise_and_are_preserved(self, qm: QualityMetrics) -> None:
        dc = AnalysisResult(
            strengths=[],
            weaknesses=[],
            recommendations=[],
            quality_metrics=qm,
            recommended_style="microservices",
            selected_patterns=[],
        )
        typed = analysis_to_pydantic(dc)
        assert typed.strengths == []
        assert typed.weaknesses == []
        assert typed.recommendations == []
        metrics = typed.quality_metrics
        assert metrics is not None, "empty analysis must still carry its metrics"
        assert metrics.maintainability == qm.maintainability


class TestTS2ScoredPatternRoundtrip:
    @given(
        analysis_score=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        fusion_score=st.floats(min_value=0.0, max_value=2.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=30, deadline=None)
    def test_scores_survive_json_roundtrip(
        self, analysis_score: float, fusion_score: float
    ) -> None:
        sp = ScoredPattern(
            name="pattern-x",
            context="ctx",
            category=PatternCategory.STRUCTURAL,
            analysis_score=analysis_score,
            fusion_score=fusion_score,
        )
        restored = ScoredPattern.model_validate_json(sp.model_dump_json())
        assert restored.analysis_score == analysis_score, "T2: analysis_score dropped"
        assert restored.fusion_score == fusion_score, "T2: fusion_score dropped"


class TestTS3WeightKeysComplete:
    def test_requirement_weights_expose_exactly_six_keys(self) -> None:
        assert len(QUALITY_ATTRIBUTE_KEYS) == 6
        w = _weights(0.5, 0.4, 0.3, 0.2, 0.1, 0.0)
        assert set(w.as_dict()) == set(QUALITY_ATTRIBUTE_KEYS)

    @given(
        w1=weight_value, w2=weight_value, w3=weight_value,
        w4=weight_value, w5=weight_value, w6=weight_value,
    )
    @settings(max_examples=20, deadline=None)
    def test_as_dict_roundtrips_every_weight(
        self, w1: float, w2: float, w3: float, w4: float, w5: float, w6: float
    ) -> None:
        w = _weights(w1, w2, w3, w4, w5, w6)
        d = w.as_dict()
        assert d["scalability"] == w1
        assert d["simplicity"] == w6


def _pattern_with_qa(name: str, qa: dict[str, float], fusion: float = 0.0) -> dict[str, Any]:
    return {
        "name": name,
        "context": "ctx",
        "category": "structural",
        "quality_attributes": qa,
        "fusion_score": fusion,
    }


class TestTS4ZeroWeightsUnweightedMean:
    @given(
        qa=st.dictionaries(st.sampled_from(list(QUALITY_ATTRIBUTE_KEYS)), qa_value),
    )
    @settings(max_examples=25, deadline=None)
    def test_zero_weights_fall_back_to_unweighted_mean(
        self, qa: dict[str, float]
    ) -> None:
        pipeline = _ConfigOnlyPipeline()
        zero_weights = _weights(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        scored = pipeline._score_patterns(  # noqa: SLF001 — decision surface under test
            [_pattern_with_qa("p", qa)], zero_weights
        )
        vals = [float(qa.get(attr, 0.0)) for attr in QUALITY_ATTRIBUTE_KEYS]
        expected = round(ref_blend(vals, [1.0] * 6) * 10.0, 2)  # uniform weights
        assert scored[0]["analysis_score"] == expected, (
            "T10: zero-weight fallback must be the unweighted mean"
        )


class TestTS5WeightedAverageDifferential:
    @given(
        weights=st.tuples(
            st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False),
            weight_value, weight_value, weight_value, weight_value, weight_value,
        ),
        qa=st.dictionaries(st.sampled_from(list(QUALITY_ATTRIBUTE_KEYS)), qa_value),
    )
    @settings(max_examples=40, deadline=None)
    def test_analysis_score_matches_garden_reference(
        self, weights: tuple[float, ...], qa: dict[str, float]
    ) -> None:
        w = _weights(*weights)
        pipeline = _ConfigOnlyPipeline()
        scored = pipeline._score_patterns(  # noqa: SLF001
            [_pattern_with_qa("p", qa)], w
        )
        vals = [float(qa.get(attr, 0.0)) for attr in QUALITY_ATTRIBUTE_KEYS]
        expected = round(ref_blend(vals, list(w.as_dict().values())) * 10.0, 2)
        assert scored[0]["analysis_score"] == expected, (
            f"differential divergence: production {scored[0]['analysis_score']}, "
            f"garden ref {expected} for qa={qa}, w={w.as_dict()}"
        )


class TestTS6SelectionOrdering:
    @given(
        rows=st.lists(
            st.tuples(qa_value, qa_value),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=25, deadline=None)
    def test_sorted_by_blended_score_when_blending_active(
        self, rows: list[tuple[float, float]]
    ) -> None:
        pipeline = _ConfigOnlyPipeline()
        patterns = [
            _pattern_with_qa(f"p{i}", {"maintainability": a, "security": b})
            for i, (a, b) in enumerate(rows)
        ]
        scored = pipeline._score_patterns(  # noqa: SLF001
            patterns, _weights(0.5, 0.5, 0.0, 0.5, 0.0, 0.5)
        )
        keys = [cast("float", p.get("blended_score", 0.0)) for p in scored]
        assert keys == sorted(keys, reverse=True), (
            f"selection must sort by blended_score desc, got {keys}"
        )

    def test_sorted_by_analysis_score_when_blending_off(self) -> None:
        config = RetrievalConfig(analysis_blend_weight=1.0, fusion_blend_weight=0.0)
        pipeline = _ConfigOnlyPipeline(config)
        patterns = [
            _pattern_with_qa("low", {"maintainability": 1.0, "security": 1.0}),
            _pattern_with_qa("high", {"maintainability": 9.0, "security": 9.0}),
        ]
        scored = pipeline._score_patterns(  # noqa: SLF001
            patterns, _weights(0.5, 0.5, 0.0, 0.5, 0.0, 0.5)
        )
        assert scored[0]["name"] == "high"
