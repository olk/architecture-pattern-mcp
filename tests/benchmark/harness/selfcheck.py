"""Metric-math selfcheck: hand-computed anchors for every formula the harness reports.

Port of design-pattern-mcp-local ``tests/benchmark/harness/selfcheck.py`` (commit 25cbfba).
B drops A's veto-conflict and seed-name checks (no veto ledger, no alternatives prose in this
repository) and retargets the fixtures to ``AnalysisResult``/``PipelineResult``.

Run: ``uv run python -m tests.benchmark.harness.selfcheck`` — exit 0 with one PASS line per
check means every reported number is grounded.
"""

from __future__ import annotations

import asyncio
import math
import sys
from collections.abc import Sequence
from typing import Any

from src.schemas.analysis import AnalysisResult
from src.schemas.components import Component
from src.schemas.design import ArchitectureDesign
from src.schemas.design import ArchitectureOverview
from src.schemas.enums import ArchitectureStyle, PatternCategory
from src.schemas.evaluation import ArchitectureEvaluation, EvaluationSummary, PipelineResult
from src.schemas.patterns import ScoredPattern

from . import scoring
from .probes import (
    AgentTimingProxy,
    StageRecorder,
    STAGE_LLM_GENERATE,
    STAGE_LLM_WEIGHTS,
    percentile_fields,
    request_stage_total_ms,
    residual_ms,
    stage_table,
)


class CheckFailure(AssertionError):
    """A named selfcheck failure (kept distinct so the CLI can report all of them)."""


def _assert(condition: bool, message: str) -> None:
    """Raise :class:`CheckFailure` with ``message`` when ``condition`` is false."""
    if not condition:
        raise CheckFailure(message)


def _approx(actual: Any, expected: Any, *, label: str, tolerance: float = 1e-9) -> None:
    """Assert ``actual`` equals ``expected`` within ``tolerance`` (or both are ``None``)."""
    if expected is None:
        _assert(actual is None, f"{label}: expected null, got {actual!r}")
        return
    _assert(actual is not None, f"{label}: expected {expected!r}, got null")
    _assert(
        abs(float(actual) - float(expected)) <= tolerance,
        f"{label}: expected {expected!r}, got {actual!r}",
    )


# --------------------------------------------------------------------------------------
# Fixtures: the smallest pydantic objects the metrics read
# --------------------------------------------------------------------------------------


def _pattern(name: str, category: PatternCategory = PatternCategory.MESSAGING) -> ScoredPattern:
    return ScoredPattern(
        name=name,
        context="ctx",
        category=category,
        quality_attributes={},
        suitable_domains=[],
        unsuitable_domains=[],
        use_cases=[],
        avoid_when=[],
        component_types=[],
        technology_stack=[],
        anti_patterns=[],
    )


def _analysis(
    selected: Sequence[str],
    *,
    recommended: str = "saga",
    is_fallback: bool = False,
    analysis_scores: Sequence[float] | None = None,
) -> AnalysisResult:
    patterns: list[ScoredPattern] = []
    for index, name in enumerate(selected):
        pattern = _pattern(name)
        if analysis_scores is not None:
            pattern.analysis_score = analysis_scores[index]
        patterns.append(pattern)
    return AnalysisResult(
        recommended_style=recommended,
        selected_patterns=patterns,
        is_fallback=is_fallback,
    )


def _result(
    final_style: str | None,
    *,
    is_fallback: bool = False,
    score: float = 85.0,
) -> PipelineResult:
    overview = ArchitectureOverview(
        reasoning="r",
        style=ArchitectureStyle.SAGA,
        category=PatternCategory.COORDINATION,
        principles=["p"],
        constraints=["c"],
    )
    design = ArchitectureDesign(
        overview=overview,
        components=[
            Component(
                id="core",
                name="Core",
                type="service",
                description="core component",
                responsibilities=["r"],
            )
        ],
        relationships=[],
        quality_attributes={},
        api_contracts=[],
        shared_data_models=[],
        event_contracts=[],
    )
    return PipelineResult(
        design=design,
        evaluation=ArchitectureEvaluation(
            summary=EvaluationSummary(overall_score=score),
            metrics=[],
            recommendations={},
        ),
        attempts=1,
        final_style=final_style or "saga",
        final_quality_score=score,
        is_fallback=is_fallback,
    )


# --------------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------------


def check_percentiles() -> None:
    """Inclusive 20-quantile cut points; null p50/p95 below four samples (never NaN)."""
    sparse = percentile_fields([1.0, 2.0])
    _assert(sparse["p50_ms"] is None and sparse["p95_ms"] is None, f"2 samples must be null: {sparse}")
    _assert("at least 4" in str(sparse["note"]), f"missing explanatory note: {sparse}")
    empty = percentile_fields([])
    _assert(empty["samples"] == 0 and empty["p50_ms"] is None, f"empty input: {empty}")
    # [1, 2, 3, 4]: p50 = 2 + 0.5*(3-2) = 2.5; p95 = 3 + 0.85*(4-3) = 3.85
    dense = percentile_fields([1.0, 2.0, 3.0, 4.0])
    _approx(dense["p50_ms"], 2.5, label="p50 of [1,2,3,4]")
    _approx(dense["p95_ms"], 3.85, label="p95 of [1,2,3,4]")
    _assert(not math.isnan(float(dense["p50_ms"])), "p50 must never be NaN")


def check_stage_table() -> None:
    """Stage grouping: counts, totals, failures, residual and per-call percentiles."""
    recorder = StageRecorder()
    started = recorder.now_ns()
    recorder.mark(stage=STAGE_LLM_WEIGHTS, op="generate_structured", started_ns=started, ok=True)
    recorder.mark(stage=STAGE_LLM_WEIGHTS, op="generate_structured", started_ns=started, ok=False, meta={"error": "x"})
    recorder.mark(stage=STAGE_LLM_GENERATE, op="generate_structured", started_ns=started, ok=True)
    table = stage_table(recorder.snapshot())
    _assert(table[STAGE_LLM_WEIGHTS]["count"] == 2, f"count: {table}")
    _assert(table[STAGE_LLM_WEIGHTS]["failures"] == 1, f"failures: {table}")
    _assert(table[STAGE_LLM_WEIGHTS]["ops"] == {"generate_structured": 2}, f"ops: {table}")
    _assert(table[STAGE_LLM_WEIGHTS]["p50_ms"] is None, f"2 samples must be null: {table}")
    _assert(table[STAGE_LLM_WEIGHTS]["total_ms"] >= 0.0, "totals must be non-negative")
    request_total = request_stage_total_ms(table)
    _assert(request_total >= table[STAGE_LLM_WEIGHTS]["total_ms"], "request total must include the stage")
    _approx(residual_ms(1000.0, table), round(1000.0 - request_total, 3), label="residual")
    _assert(residual_ms(1000.0, {}) == 1000.0, "empty table leaves the full residual")


def check_wilson() -> None:
    """Wilson intervals against the standard closed form (k=5,n=10 etc.)."""
    _approx(scoring.wilson_interval(5, 10)["low"], 0.236593, label="wilson(5,10).low")
    _approx(scoring.wilson_interval(5, 10)["high"], 0.763407, label="wilson(5,10).high")
    _approx(scoring.wilson_interval(0, 10)["low"], 0.0, label="wilson(0,10).low")
    _approx(scoring.wilson_interval(0, 10)["high"], 0.277533, label="wilson(0,10).high")
    _approx(scoring.wilson_interval(10, 10)["low"], 0.722467, label="wilson(10,10).low")
    _approx(scoring.wilson_interval(10, 10)["high"], 1.0, label="wilson(10,10).high")
    empty = scoring.wilson_interval(0, 0)
    _assert(empty["low"] is None and empty["high"] is None, f"no samples: {empty}")
    _assert(scoring.wilson_interval(5, 10)["p_hat"] == 0.5, "p_hat must equal k/n")


def check_sign_test() -> None:
    """Exact two-sided binomial sign test (zeros dropped, p capped at 1.0)."""
    _approx(scoring.sign_test([1.0] * 10)["p_two_sided"], 0.001953, label="10/10 positives")
    _approx(scoring.sign_test([1.0] * 9 + [-1.0])["p_two_sided"], 0.021484, label="9/10 positives")
    _approx(scoring.sign_test([1.0] * 8 + [-1.0] * 2)["p_two_sided"], 0.109375, label="8/10 positives")
    _approx(scoring.sign_test([1.0] * 5 + [-1.0] * 5)["p_two_sided"], 1.0, label="5/10 positives")
    zeros = scoring.sign_test([0.0, 0.0])
    _assert(zeros["n"] == 0 and zeros["p_two_sided"] == 1.0, f"all-zero deltas: {zeros}")
    _assert(zeros["n_dropped"] == 2, f"all-zero deltas drop every pair: {zeros}")
    mixed = scoring.sign_test([0.0, 2.0, 3.0])
    _assert(mixed["n"] == 2 and mixed["positive"] == 2, f"zeros dropped: {mixed}")
    _assert(mixed["n_dropped"] == 1, f"mixed deltas drop exactly the zero: {mixed}")


def check_newcombe() -> None:
    """Newcombe's Wilson-based difference CI (unrounded bounds inside the formula)."""
    unequal = scoring.newcombe_difference_ci(6, 10, 4, 10)
    _approx(unequal["difference"], 0.2, label="difference(6/10, 4/10)")
    _approx(unequal["low"], -0.206341, label="newcombe low")
    _approx(unequal["high"], 0.527843, label="newcombe high")
    equal = scoring.newcombe_difference_ci(5, 10, 5, 10)
    _approx(equal["difference"], 0.0, label="equal proportions difference")
    _approx(equal["low"], -0.372514, label="equal proportions low")
    _approx(equal["high"], 0.372514, label="equal proportions high")
    _assert(scoring.newcombe_difference_ci(0, 0, 1, 2)["difference"] is None, "no samples must be null")


def check_recall_and_f1() -> None:
    """recall@K over the ordered selected set and the acceptable-primary F1 direction."""
    _approx(scoring.recall_at_k(["a", "b", "z", "q"], ["a", "b", "c"], 3), 2 / 3, label="recall@3")
    _approx(scoring.recall_at_k(["a", "b", "z", "q"], ["a", "b", "c"], 4), 2 / 3, label="recall@4")
    _approx(scoring.recall_at_k(["a", "b", "c"], ["a", "b", "c"], 3), 1.0, label="full recall@3")
    _approx(scoring.recall_at_k(["a"], ["a", "b"], 5), 0.5, label="partial recall@5")
    _approx(scoring.recall_at_k(["a"], [], 5), 0.0, label="empty acceptable set")

    ordered = scoring.selected_ordered(_analysis(["saga", "pipe-and-filter", "blockchain-based"]))
    _assert(ordered == ["saga", "pipe-and-filter", "blockchain-based"], f"ordered selection: {ordered}")
    _assert(scoring.selected_ordered(None) == [], "no analysis: empty selection")
    _approx(scoring.recall_at_k(ordered, ["saga", "blockchain-based"], 5), 1.0, label="recall over siblings")
    _approx(scoring.recall_at_k(ordered[:1], ["saga", "blockchain-based"], 3), 0.5, label="top-1 recall")

    hit = scoring.acceptable_primary_f1(True, ["a", "b", "c", "d"])
    _approx(hit["precision"], 1.0, label="primary F1 precision on a hit")
    _approx(hit["recall"], 0.25, label="primary F1 recall on a hit")
    _approx(hit["f1"], 0.4, label="primary F1 on a hit")
    miss = scoring.acceptable_primary_f1(False, ["a", "b"])
    _assert(miss["f1"] == 0.0, f"a miss scores 0: {miss}")


def check_hit_and_score() -> None:
    """Hit/fallback semantics and the calibrated score source (final_quality_score / 100)."""
    analysis = _analysis(["saga", "blockchain-based"], recommended="saga")
    result = _result("saga", score=85.0)
    _assert(scoring.is_fallback(analysis, result) is False, "clean run is not a fallback")
    _assert(scoring.final_pattern_of(analysis, result) == "saga", "final pattern is the loop's style")
    _approx(scoring.calibration_score(result), 0.85, label="calibration score scales to [0, 1]")

    # Analyze-only run: final pattern falls back to recommended_style.
    _assert(scoring.final_pattern_of(analysis, None) == "saga", "analyze-only uses recommended_style")
    _assert(scoring.is_fallback(analysis, None) is False, "clean analysis is not a fallback")
    _approx(scoring.calibration_score(None), 0.0, label="no result: zero calibration score")

    fallback_analysis = _analysis([], recommended="layered-monolith", is_fallback=True)
    fallback_result = _result("layered-monolith", is_fallback=True)
    _assert(scoring.is_fallback(fallback_analysis, fallback_result) is True, "result fallback propagates")
    _assert(scoring.is_fallback(fallback_analysis, None) is True, "analysis fallback propagates")

    hit = _result("saga")
    _assert(scoring.final_pattern_of(None, hit) in ("saga", "blockchain-based"), "hit membership is caller-checked")


def check_calibration() -> None:
    """Brier, 10-bin equal-width ECE and the reliability table."""
    entries = [(0.8, True), (0.2, False)]
    block = scoring.calibration(entries)
    _approx(block["brier"], 0.04, label="Brier of [(0.8, hit), (0.2, miss)]")
    _approx(block["ece"], 0.2, label="ECE of [(0.8, hit), (0.2, miss)]")
    bins = {entry["bin"]: entry for entry in block["bins"]}
    _assert(bins[8]["count"] == 1 and bins[2]["count"] == 1, f"bin assignment: {bins}")
    _approx(bins[8]["gap"], 0.2, label="gap of bin 8")
    _approx(bins[2]["gap"], 0.2, label="gap of bin 2")
    _approx(scoring.brier([(1.0, True), (0.0, False)]), 0.0, label="perfect calibration Brier")
    _approx(scoring.brier([(1.0, False), (0.0, True)]), 1.0, label="worst calibration Brier")
    _assert(scoring.reliability_bin(1.0) == 9 and scoring.reliability_bin(0.0) == 0, "bin edges")
    _assert(scoring.reliability_bin(0.85) == 8, "0.85 belongs to bin 8")
    _assert(scoring.calibration([])["brier"] is None, "no entries: null Brier")
    _approx(scoring.clip01(1.5), 1.0, label="clip01 upper")
    _approx(scoring.clip01(-0.5), 0.0, label="clip01 lower")


def check_risk_coverage() -> None:
    """Risk at 80/90/100% coverage and the trapezoidal risk-coverage AUC."""
    block = scoring.risk_coverage([(0.9, True), (0.8, False), (0.7, True), (0.6, False), (0.5, True)])
    _assert(block["samples"] == 5, f"samples: {block}")
    _approx(block["risk_at_80"], 0.5, label="risk at 80% coverage (k=4)")
    _approx(block["risk_at_90"], 0.4, label="risk at 90% coverage (k=5)")
    _approx(block["risk_at_100"], 0.4, label="risk at 100% coverage")
    # trapezoid: 0.2*0 + 0.2*(0.5)/2 + 0.2*(0.5+1/3)/2 + 0.2*(1/3+0.5)/2 + 0.2*(0.5+0.4)/2
    _approx(block["aurc"], 0.306667, label="AURC")
    ordered = scoring.risk_coverage([(0.1, True), (0.9, False)])
    _assert(ordered["risk_at_100"] == 0.5, f"ordering by score desc: {ordered}")
    _assert(scoring.risk_coverage([])["aurc"] is None, "no samples: null AUC")


class _ScriptedAgent:
    """Minimal scripted agent for the proxy checks."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate_structured(self, system_prompt: str, user_prompt: str, response_schema: Any) -> Any:
        self.calls += 1
        await asyncio.sleep(0)
        return {"ok": True}


class _RaisingAgent:
    """Minimal failing agent double for the proxy failure-path check."""

    async def generate_structured(self, system_prompt: str, user_prompt: str, response_schema: Any) -> Any:
        raise RuntimeError("provider exploded")

    def health_probe(self) -> str:
        return "healthy"


def check_proxies() -> None:
    """Proxies record stage, op, outcome and re-raise; failures keep their attribution."""
    from src.schemas.analysis import RequirementWeights
    from src.schemas.evaluation import ArchitectureEvaluation

    async def _exercise() -> None:
        recorder = StageRecorder()
        agent = AgentTimingProxy(_ScriptedAgent(), recorder)
        schema = RequirementWeights
        result = await agent.generate_structured("sys", "user", schema)
        _assert(result == {"ok": True}, "proxy must return the wrapped result")
        _assert(len(recorder.records) == 1, f"one record per call: {recorder.records}")
        record = recorder.records[0]
        _assert(record.stage == STAGE_LLM_WEIGHTS and record.ok, f"stage/ok: {record}")
        _assert(record.meta["schema"] == "RequirementWeights", f"meta schema: {record.meta}")
        _assert(record.duration_ms >= 0.0, "duration must be non-negative")

        # Schema dispatch: design/evaluation/draft route to their own stages.
        design_stage = agent._stage_for(type("_ArchitectureDesignResponse", (), {}))
        _assert(design_stage == STAGE_LLM_GENERATE, f"design schema routes to generate: {design_stage}")
        evaluation_stage = agent._stage_for(ArchitectureEvaluation)
        _assert(evaluation_stage == "llm.evaluate", f"evaluation schema routes: {evaluation_stage}")

        failing = AgentTimingProxy(_RaisingAgent(), recorder)
        raised = False
        try:
            await failing.generate_structured("sys", "user", RequirementWeights)
        except RuntimeError:
            raised = True
        _assert(raised, "proxy must re-raise the seam failure")
        failed = recorder.records[-1]
        _assert(not failed.ok and "provider exploded" in failed.meta["error"], f"failure attribution: {failed}")
        # __getattr__ delegation reaches non-seam members of the wrapped agent.
        _assert(failing.health_probe() == "healthy", "attribute delegation")

    asyncio.run(_exercise())


CHECKS: tuple[tuple[str, Any], ...] = (
    ("percentiles", check_percentiles),
    ("stage table + residual", check_stage_table),
    ("Wilson intervals", check_wilson),
    ("sign test", check_sign_test),
    ("Newcombe difference CI", check_newcombe),
    ("recall@K + F1s", check_recall_and_f1),
    ("hit/fallback + score source", check_hit_and_score),
    ("Brier + ECE", check_calibration),
    ("risk-coverage", check_risk_coverage),
    ("timing proxies", check_proxies),
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run every check; print one PASS line per check; exit 1 on the first failure."""
    del argv
    failures: list[str] = []
    for name, check in CHECKS:
        try:
            check()
        except CheckFailure as exc:
            failures.append(f"{name}: {exc}")
            print(f"FAIL {name}: {exc}", file=sys.stderr)
        else:
            print(f"PASS {name}")
    if failures:
        print(f"\n{len(failures)} of {len(CHECKS)} checks failed", file=sys.stderr)
        return 1
    print(f"\nall {len(CHECKS)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
