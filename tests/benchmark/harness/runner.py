"""Run one benchmark arm end to end: scenarios → records → summary → report.

Port of design-pattern-mcp-local ``tests/benchmark/harness/runner.py`` (commit
25cbfba), retargeted to this repository's pipeline: ``ArchitecturePipeline``
exposes ``analyze(requirements=..., domain=...)`` + ``design_loop(...)`` instead
of A's single ``run_design``; the two are called explicitly (B has no combined
method). Stage attribution, record shape, aggregation and report layout follow A
with B's observables (see :mod:`.scoring` / :mod:`.probes` docstrings for the
dropped/renamed metrics). Failure semantics diverge from the ported plan: a
scenario failure is *recorded* (``_failed_record``, ``provenance.error`` set) and
the arm completes; ``--fail-fast`` restores abort-on-first-failure
(``aborted.json``). ``compare`` refuses arms that contain failed runs.

The runner owns the *run*: it loads the corpus, builds the mode's seam wiring
(offline scripts or the live in-process pipeline), times each scenario at the
analyze+design_loop boundary, computes the quality block from the real
``AnalysisResult``/``PipelineResult``, and writes the run directory
(``manifest.json``, ``scenarios/<id>.json``, ``summary.json``, ``report.md``).
"""

from __future__ import annotations

import asyncio
import platform
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from llama_index.core.retrievers import BaseRetriever

from src.agent import SoftwareArchitectAgent
from src.config import ServerConfig
from src.patterns.loader import PatternLoader
from src.pipeline import AnalysisResult as PipelineAnalysisResult
from src.pipeline import ArchitecturePipeline
from src.reasoning.client import ReasoningClient
from src.schemas.evaluation import PipelineResult

from . import config as cfg
from . import scoring
from .offline import build_pipeline as build_offline_pipeline
from .offline import build_script
from .probes import (
    REQUEST_STAGES,
    AgentTimingProxy,
    ReasoningTimingProxy,
    StageRecord,
    StageRecorder,
    SyncLegTimingProxy,
    percentile_fields,
    residual_ms,
    stage_table,
)

HARNESS_VERSION = cfg.HARNESS_VERSION


@dataclass
class RunOptions:
    """One benchmark arm invocation (CLI surface of :mod:`.main`)."""

    mode: str
    scenarios_path: Path = cfg.DEFAULT_SCENARIOS
    out_dir: Path | None = None
    split: str = "all"
    limit: int | None = None
    repeats: int = 1
    flips: tuple[str, ...] = ()
    warmup: bool = True
    run_id: str | None = None
    #: Scenario-failure policy. True (default) = one scenario failure aborts the whole arm:
    #: the plan's "live attribution must not average over failures" stance, and the CLI
    #: exposes it as ``--fail-fast``. False = the failed scenario is recorded with
    #: ``provenance.error`` set and the run completes — the summary/report count the
    #: failure loudly and ``compare`` refuses arms containing errors (paired keys mismatch
    #: otherwise). Rationale for tolerating failures by default: provider JSON faults (e.g.
    #: MiniMax malformed JSON) are stochastic and a 16-scenario live arm holds ~50 generation
    #: calls, so one glitch burning ~50 min of the arm costs more than it protects.
    abort_on_scenario_error: bool = True


class ScenarioExecutor(Protocol):
    """Runs one scenario against one seam wiring and returns the pipeline observables."""

    name: str
    recorder: StageRecorder

    def describe(self) -> dict[str, Any]:
        """Mode-specific provenance block for the manifest."""
        ...

    async def run(
        self, scenario: cfg.Scenario
    ) -> tuple[PipelineAnalysisResult, PipelineResult, list[StageRecord], dict[str, Any]]:
        """Execute ``scenario``; return (analysis, pipeline result, stage slice, provenance)."""
        ...


class OfflineExecutor:
    """Scripted retrieval legs + scripted LLM over the real catalog (deterministic, no network)."""

    name = "offline"

    def __init__(
        self,
        *,
        config: ServerConfig,
        catalog: PatternLoader,
        recorder: StageRecorder,
        flips: frozenset[str],
    ) -> None:
        self._config = config
        self._catalog = catalog
        self._flips = flips
        self.recorder = recorder

    def describe(self) -> dict[str, Any]:
        """Seam provenance: the two doubles and the disabled reasoning client."""
        return {
            "seams": {
                "legs": "offline._StubLeg (scripted domain-slug pool, stages retrieval.dense/bm25)",
                "llm": "offline._ScriptedAgent (seed weights, prompt-parsed style, 85.0 evaluation)",
                "reasoning": "disabled (reasoning_client=None)",
            },
            "flips": sorted(self._flips),
            "note": (
                "offline stage attribution covers the two scripted retrieval legs plus "
                "llm.* stages; embed/rerank are exercised by live mode"
            ),
        }

    async def run(
        self, scenario: cfg.Scenario
    ) -> tuple[PipelineAnalysisResult, PipelineResult, list[StageRecord], dict[str, Any]]:
        """Run one scenario through the real pipeline over the scenario's scripted pool."""
        script = build_script(
            scenario, self._catalog, flip=scenario.scenario_id in self._flips
        )
        pipeline = build_offline_pipeline(
            script, scenario, config=self._config, catalog=self._catalog, recorder=self.recorder
        )
        analysis, result, slice_records = await _execute_pipeline(pipeline, scenario, self.recorder)
        return analysis, result, slice_records, {"script": script.describe()}


class LiveExecutor:
    """Real seams in-process: TEI embedder/reranker, LiteLLM generator, optional reasoning."""

    name = "live"

    def __init__(
        self,
        *,
        config: ServerConfig,
        catalog: PatternLoader,
        recorder: StageRecorder,
        pipeline: ArchitecturePipeline,
        reasoning_health: dict[str, str] | None,
    ) -> None:
        self._config = config
        self._catalog = catalog
        self._pipeline = pipeline
        self._reasoning_health = reasoning_health
        self.recorder = recorder

    @classmethod
    async def create(
        cls, *, config: ServerConfig, catalog: PatternLoader, recorder: StageRecorder
    ) -> LiveExecutor:
        """Build the live wiring exactly like the server does, then wrap the timing seams.

        ``warmup_indexes()`` builds both retrieval legs through the real TEI embedder
        (recorded under ``build.embed``); the built legs are then swapped for sync timing
        proxies so every request-side retrieval lands in ``retrieval.dense`` /
        ``retrieval.bm25``. Rerank time stays in the residual (see :mod:`.probes`).
        """
        agent_inner = SoftwareArchitectAgent(config)
        pipeline = ArchitecturePipeline(
            agent=agent_inner,
            pattern_loader=catalog,
            embedder_config=config.embedder,
            retrieval_config=config.retrieval,
            reranker_config=config.reranker,
        )
        await asyncio.to_thread(pipeline.warmup_indexes)
        if pipeline._dense_retriever is None or pipeline._bm25_retriever is None:
            raise RuntimeError("warmup_indexes left a retrieval leg unbuilt; cannot instrument")

        # Swap the built legs for timing proxies (sync retrieve timed via perf_counter_ns).
        # The pipeline stores raw retrievers/agent; the proxies duck-type the seams they wrap.
        pipeline._dense_retriever = cast(
            "BaseRetriever",
            SyncLegTimingProxy(pipeline._dense_retriever, recorder, stage="retrieval.dense"),
        )
        pipeline._bm25_retriever = cast(
            "BaseRetriever",
            SyncLegTimingProxy(pipeline._bm25_retriever, recorder, stage="retrieval.bm25"),
        )
        pipeline._agent = cast(
            "SoftwareArchitectAgent", AgentTimingProxy(pipeline._agent, recorder)
        )

        reasoning_inner: ReasoningClient | None = None
        reasoning_health: dict[str, str] | None = None
        if config.reasoning.enabled:
            reasoning_inner = ReasoningClient(config.reasoning, agent_inner)
            reasoning_health = await reasoning_inner.health_check()
            pipeline._reasoning = cast(
                "ReasoningClient | None", ReasoningTimingProxy(reasoning_inner, recorder)
            )

        return cls(
            config=config,
            catalog=catalog,
            recorder=recorder,
            pipeline=pipeline,
            reasoning_health=reasoning_health,
        )

    def describe(self) -> dict[str, Any]:
        """Seam provenance: real objects behind timing proxies plus the reasoning health map."""
        return {
            "seams": {
                "legs": "warmup_indexes() TEI-backed legs behind SyncLegTimingProxy",
                "llm": (
                    f"{type(self._pipeline._agent).__name__} over "
                    f"{self._config.generator.provider}:{self._config.generator.config.model}"
                ),
                "reasoning": (
                    "ReasoningClient (enabled)"
                    if self._config.reasoning.enabled
                    else "disabled via REASONING_ENABLED=false"
                ),
            },
            "reasoning_health": self._reasoning_health,
        }

    async def run(
        self, scenario: cfg.Scenario
    ) -> tuple[PipelineAnalysisResult, PipelineResult, list[StageRecord], dict[str, Any]]:
        """Run one scenario in-process; failures propagate to the runner's failure policy."""
        analysis, result, slice_records = await _execute_pipeline(
            self._pipeline, scenario, self.recorder
        )
        return analysis, result, slice_records, {}


async def _execute_pipeline(
    pipeline: ArchitecturePipeline, scenario: cfg.Scenario, recorder: StageRecorder
) -> tuple[PipelineAnalysisResult, PipelineResult, list[StageRecord]]:
    """B's two pipeline phases called explicitly, plus the stage slice they produced.

    B has no combined run method: ``analyze`` derives the requirement weights and the
    recommended style; ``design_loop`` consumes both (plus the analysis result for
    alternative styles). The requirements text is the scenario description. The domain is
    the scenario's authored ``domain`` — analyze keys *both* retrieval legs on it (the
    indexed documents are catalogue domain slugs), so a fabricated domain would measure
    slug-matching noise instead of the pipeline's requirements-weighted ranking; the corpus
    pins it to a ``suitable_domains`` value of the primary label (loader-enforced). The
    offline stub legs ignore the query, but the run record still carries the same domain.
    """
    offset = len(recorder)
    requirements = scenario.description
    domain = scenario.domain
    analysis = await pipeline.analyze(requirements=requirements, domain=domain)
    result = await pipeline.design_loop(
        requirements=requirements,
        domain=domain,
        style=analysis.recommended_style,
        selected_patterns=analysis.selected_patterns,
        criteria="quality",
        analysis_result=analysis,
        max_tries=3,
        min_quality_score=50.0,
    )
    return analysis, result, recorder.snapshot()[offset:]


async def run_benchmark(options: RunOptions) -> dict[str, Any]:
    """Execute one arm and write its run directory; return the run id/paths for the CLI.

    Failure policy (``RunOptions.abort_on_scenario_error``): tolerant mode (the default in
    :mod:`.main`) records a failed scenario via ``_failed_record`` and completes the arm;
    ``--fail-fast`` aborts on the first failure instead — an ``aborted.json`` marker records
    how far the arm got, the original error is re-raised, and ``compare`` refuses such
    directories (manifest.json/summary.json are missing). ``compare`` also refuses
    *completed* arms that contain recorded failures unless ``--allow-mismatch``.
    """
    try:
        return await _run_benchmark(options)
    except BaseException as exc:
        _write_abort_marker(options, exc)
        raise


def _write_abort_marker(options: RunOptions, exc: BaseException) -> None:
    """Best-effort ``aborted.json`` in the run directory (never masks the original error)."""
    marker = {
        "aborted": True,
        "mode": options.mode,
        "error": f"{type(exc).__name__}: {exc}",
        "reason": (
            "failures propagate (no silent degradation); discard this run directory — "
            "compare refuses it because manifest.json/summary.json are missing"
        ),
        "at": cfg.utc_now_iso(),
    }
    try:
        out_dir = options.out_dir or (
            cfg.DEFAULT_OUT_DIR / (options.run_id or cfg.default_run_id(options.mode))
        )
        cfg.write_json(cfg.RunPaths.for_run(out_dir).root / "aborted.json", marker)
    except OSError:
        pass


async def _run_scenarios(
    executor: ScenarioExecutor,
    selected: Sequence[cfg.Scenario],
    *,
    repeats: int,
    options: RunOptions,
    paths: cfg.RunPaths,
) -> tuple[list[dict[str, Any]], list[StageRecord], list[dict[str, str]]]:
    """Execute every (repeat, scenario) pair, honoring the failure policy.

    ``abort_on_scenario_error`` (CLI ``--fail-fast``) re-raises the first scenario failure;
    otherwise the failure is recorded (``_failed_record``) and the arm completes. Failed
    scenario JSON still lands in ``scenarios/`` so the run directory stays self-describing.
    """
    records: list[dict[str, Any]] = []
    stage_records: list[StageRecord] = []
    failures: list[dict[str, str]] = []
    for repeat in range(1, repeats + 1):
        for scenario in selected:
            try:
                record, slice_records = await _execute(executor, scenario, repeat=repeat, warmup=False)
            except Exception as exc:  # noqa: BLE001 - the failure policy below decides severity
                if options.abort_on_scenario_error:
                    raise
                failures.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "repeat": str(repeat),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                record = _failed_record(executor, scenario, repeat=repeat, exc=exc)
                slice_records = []
            records.append(record)
            stage_records.extend(slice_records)
            cfg.write_json(paths.scenarios_dir / f"{scenario.scenario_id}-r{repeat}.json", record)
    return records, stage_records, failures


async def _run_benchmark(options: RunOptions) -> dict[str, Any]:
    """Execute one arm and write its run directory; return the run id/paths for the CLI."""
    config = cfg.load_server_config(options.mode)
    catalog = cfg.load_repo_catalog(config)
    corpus = cfg.load_scenarios(options.scenarios_path, catalog)
    selected = cfg.select_scenarios(corpus, split=options.split, limit=options.limit)
    if not selected:
        raise ValueError(f"no scenarios selected (split={options.split!r}, limit={options.limit})")
    known = {scenario.scenario_id for scenario in corpus}
    unknown_flips = sorted(set(options.flips) - known)
    if unknown_flips:
        raise ValueError(f"--flip ids not in {options.scenarios_path}: {unknown_flips}")
    if options.flips and options.mode != "offline":
        raise ValueError("--flip is an offline-only debug hook (compare dry run)")

    started_at = cfg.utc_now_iso()
    recorder = StageRecorder()
    executor: ScenarioExecutor
    if options.mode == "offline":
        executor = OfflineExecutor(
            config=config, catalog=catalog, recorder=recorder, flips=frozenset(options.flips)
        )
    elif options.mode == "live":
        executor = await LiveExecutor.create(config=config, catalog=catalog, recorder=recorder)
    else:
        raise ValueError(f"mode {options.mode!r} runs through e2e.py (black-box, no stages)")

    run_id = options.run_id or cfg.default_run_id(options.mode)
    out_dir = options.out_dir or (cfg.DEFAULT_OUT_DIR / run_id)
    paths = cfg.RunPaths.for_run(out_dir)

    warmup_record: dict[str, Any] | None = None
    if options.warmup:
        warmup_record, _warmup_stages = await _execute(
            executor, selected[0], repeat=0, warmup=True
        )
        cfg.write_json(paths.root / "warmup.json", warmup_record)

    records, stage_records, failures = await _run_scenarios(
        executor, selected, repeats=options.repeats, options=options, paths=paths
    )

    notes = _fixture_notes(options, records)
    if failures:
        failed_keys = ", ".join(f"{item['scenario_id']}#r{item['repeat']}" for item in failures)
        notes.append(
            f"{len(failures)} of {len(records)} scenario runs failed and are recorded as errors "
            f"(hit=false by definition; excluded from nothing — they count as misses): {failed_keys}"
        )
    summary = summarise(
        records,
        stage_records=stage_records,
        warmup_record=warmup_record,
        options=options,
        config=config,
        catalog=catalog,
        executor=executor,
        paths=paths,
        run_id=run_id,
        started_at=started_at,
        notes=notes,
    )
    summary["failures"] = failures
    manifest = _manifest(
        options=options,
        config=config,
        catalog=catalog,
        executor=executor,
        records=records,
        warmup_record=warmup_record,
        run_id=run_id,
        started_at=started_at,
        notes=notes,
    )
    cfg.write_json(paths.manifest, manifest)
    cfg.write_json(paths.summary, summary)
    paths.report.write_text(render_report(summary, manifest), encoding="utf-8")
    return {
        "run_id": run_id,
        "run_dir": str(paths.root),
        "records": len(records),
        "summary": summary,
        "manifest": manifest,
    }


async def _execute(
    executor: ScenarioExecutor, scenario: cfg.Scenario, *, repeat: int, warmup: bool
) -> tuple[dict[str, Any], list[StageRecord]]:
    """Run one scenario, time it at the run boundary and assemble its record."""
    started_ns = executor.recorder.now_ns()
    analysis, result, slice_records, extra = await executor.run(scenario)
    e2e_ms = round((executor.recorder.now_ns() - started_ns) / 1_000_000.0, 3)
    table = stage_table(slice_records)
    quality = _quality_block(analysis, result, scenario)
    stage_total = round(sum(float(entry["total_ms"]) for entry in table.values()), 3)
    residual = residual_ms(e2e_ms, table)
    record: dict[str, Any] = {
        "harness_version": HARNESS_VERSION,
        "mode": executor.name,
        "scenario": scenario.record_identity(),
        "repeat": repeat,
        "warmup": warmup,
        "e2e_ms": e2e_ms,
        "stages": table,
        "stage_total_ms": stage_total,
        "residual_ms": residual,
        "residual_note": _residual_note(residual),
        "quality": quality,
        "pipeline": _pipeline_block(result),
        "selection": _selection_block(analysis),
        "provenance": extra,
    }
    return record, slice_records


def _failed_record(
    executor: ScenarioExecutor, scenario: cfg.Scenario, *, repeat: int, exc: Exception
) -> dict[str, Any]:
    """Record shape for a tolerated scenario failure (mirrors ``_execute``'s keys).

    ``quality`` keeps every key with ``None``/miss values so downstream consumers
    (``scoring.aggregate_quality``, ``compare._dig``) see the same structure as a successful
    record — the failure is visible in ``provenance.error``, never as a missing key. A failed
    run contributes a miss to every rate (``hit`` is ``False``), which is the conservative
    reading of "the pipeline produced no acceptable answer".
    """
    _ = executor  # tap point for future stage-slice salvage; currently nothing to salvage
    identity = scenario.record_identity()
    return {
        "harness_version": HARNESS_VERSION,
        "mode": executor.name,
        "scenario": identity,
        "repeat": repeat,
        "warmup": False,
        "e2e_ms": None,
        "stages": {},
        "stage_total_ms": 0.0,
        "residual_ms": None,
        "residual_note": "scenario failed before completion; no timing is attributable",
        "quality": {
            "hit": False,
            "fallback": None,
            "final_pattern": None,
            "expected_primary": scenario.primary,
            "acceptable_primary": list(scenario.acceptable_primary),
            "selected": [],
            "selected_true_positives": [],
            "recall_at_3": None,
            "recall_at_5": None,
            "acceptable_primary_f1": scoring.acceptable_primary_f1(False, scenario.acceptable_primary),
            "score": None,
            "score_scaled": None,
            "reliability_bin": None,
            "brier": None,
            "calibration_eligible": scenario.split == "train",
        },
        "pipeline": None,
        "selection": None,
        "provenance": {"error": f"{type(exc).__name__}: {exc}"},
    }


def _residual_note(residual: float) -> str | None:
    """Explain a negative residual: overlapping stages break the sum-is-wall-clock identity.

    B's GENERATE phase fans component generation out with bounded concurrency, so per-call
    durations of parallel batches overlap; the stage *sum* then exceeds the measured wall
    clock. The residual stays a diagnostic of time spent outside the wrapped seams — never a
    hard accounting identity.
    """
    if residual >= 0.0:
        return None
    return (
        "negative: per-call stage durations overlap (concurrent generate batches), so the "
        "stage sum exceeds the measured wall clock; use the per-stage table, not this residual"
    )


def _quality_block(
    analysis: PipelineAnalysisResult, result: PipelineResult, scenario: cfg.Scenario
) -> dict[str, Any]:
    """Every quality metric for one scenario (plan §4)."""
    fallback = scoring.is_fallback(analysis, result)
    final_style = scoring.final_pattern_of(analysis, result)
    hit = (not fallback) and final_style is not None and final_style in set(scenario.acceptable_primary)
    selected = scoring.selected_ordered(analysis)
    score = scoring.calibration_score(result)
    return {
        "hit": hit,
        "fallback": fallback,
        "final_pattern": final_style,
        "expected_primary": scenario.primary,
        "acceptable_primary": list(scenario.acceptable_primary),
        "selected": selected,
        "selected_true_positives": sorted(set(selected) & set(scenario.acceptable)),
        "recall_at_3": round(scoring.recall_at_k(selected, scenario.acceptable, 3), 6),
        "recall_at_5": round(scoring.recall_at_k(selected, scenario.acceptable, 5), 6),
        "acceptable_primary_f1": scoring.acceptable_primary_f1(hit, scenario.acceptable_primary),
        "score": score,
        "score_scaled": round(score * 100.0, 3),
        "reliability_bin": scoring.reliability_bin(score),
        "brier": round((score - (1.0 if hit else 0.0)) ** 2, 6),
        "calibration_eligible": scenario.split == "train",
    }


def _pipeline_block(result: PipelineResult) -> dict[str, Any]:
    """Run-level observables of the generate–evaluate loop (compact, replay-relevant)."""
    return {
        "attempts": result.attempts,
        "final_pattern": result.final_style,
        "final_quality_score": result.final_quality_score,
        "evaluation_score": result.evaluation.summary.overall_score,
        "is_fallback": result.is_fallback,
        "alternative_patterns": [c.name for c in result.alternative_styles],
    }


def _selection_block(analysis: PipelineAnalysisResult) -> list[dict[str, Any]]:
    """Per-pattern selection observables: the hand-audit view of one run.

    The pipeline's ``AnalysisResult.selected_patterns`` carries dict-shaped entries
    (LLM-JSON compatible); scores are optional and audited as ``null`` when absent.
    """
    block: list[dict[str, Any]] = []
    for pattern in analysis.selected_patterns:
        entry: dict[str, Any] = dict(pattern) if isinstance(pattern, dict) else {"name": pattern}
        block.append(
            {
                "name": entry.get("name"),
                "category": entry.get("category"),
                "analysis_score": _round_or_none(entry.get("analysis_score")),
                "fusion_score_normalized": _round_or_none(entry.get("fusion_score_normalized")),
                "blended_score": _round_or_none(entry.get("blended_score")),
            }
        )
    return block


def _round_or_none(value: float | None) -> float | None:
    """Round an optional score to 4 decimals (``None`` passes through)."""
    return None if value is None else round(float(value), 4)


def _fixture_notes(options: RunOptions, records: Sequence[dict[str, Any]]) -> list[str]:
    """Offline fixture integrity: a non-flipped scenario must hit, a flipped one must miss.

    Offline hits are scripted, so a deviation means the corpus script and the pipeline disagree
    (e.g. a decoy slug that resolves to an acceptable pattern) — loud, not silently averaged away.
    Failed scenario runs (tolerated via the live failure policy) carry no verdict here: their
    integrity is expressed by ``summary.failures``, not by the hit gate.
    """
    notes: list[str] = []
    if options.mode != "offline":
        return notes
    flips = set(options.flips)
    violations: list[str] = []
    for record in records:
        if record.get("provenance", {}).get("error"):
            continue
        scenario_id = record["scenario"]["scenario_id"]
        hit = bool(record["quality"]["hit"])
        if scenario_id in flips and hit:
            violations.append(
                f"{scenario_id}: flipped scenario still hit ({record['quality']['final_pattern']})"
            )
        if scenario_id not in flips and not hit:
            violations.append(
                f"{scenario_id}: scripted slug pool missed (final={record['quality']['final_pattern']}, "
                f"fallback={record['quality']['fallback']})"
            )
    if violations:
        raise ValueError("offline fixture integrity failed:\n  " + "\n  ".join(violations))
    notes.append(
        "offline fixture integrity verified: every non-flipped scenario hit, every flipped scenario missed"
    )
    return notes


# --------------------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------------------


def summarise(
    records: Sequence[dict[str, Any]],
    *,
    stage_records: Sequence[StageRecord],
    warmup_record: dict[str, Any] | None,
    options: RunOptions,
    config: ServerConfig,
    catalog: PatternLoader,
    executor: ScenarioExecutor,
    paths: cfg.RunPaths,
    run_id: str,
    started_at: str,
    notes: Sequence[str],
) -> dict[str, Any]:
    """Aggregate the run: quality by split, stage latencies, calibration, risk-coverage."""
    del config  # effective-config echo lives in the manifest; kept for signature parity with A
    train = [record for record in records if record["scenario"]["split"] == "train"]
    holdout = [record for record in records if record["scenario"]["split"] == "holdout"]
    warmup_e2e = warmup_record["e2e_ms"] if warmup_record is not None else None
    return {
        "harness_version": HARNESS_VERSION,
        "run_id": run_id,
        "mode": executor.name,
        "started_at": started_at,
        "finished_at": cfg.utc_now_iso(),
        "scenario_file": {
            "path": str(options.scenarios_path),
            "sha256": cfg.file_sha256(options.scenarios_path),
        },
        "selection": {
            "split": options.split,
            "limit": options.limit,
            "repeats": options.repeats,
            "warmup": options.warmup,
            "flips": sorted(options.flips),
            "scenario_ids": [record["scenario"]["scenario_id"] for record in records],
        },
        "run_dir": str(paths.root),
        "catalog": {"records": len(catalog.load_all())},
        "quality": {
            "overall": _quality_aggregate(records),
            "train": _quality_aggregate(train),
            "holdout": _quality_aggregate(holdout),
        },
        "latency": {
            "e2e_ms": percentile_fields(
                [
                    float(record["e2e_ms"])
                    for record in records
                    if record["e2e_ms"] is not None
                ]
            ),
            "warmup_e2e_ms": warmup_e2e,
            "stages": stage_table(stage_records),
            "negative_residual_scenarios": sum(
                1
                for record in records
                if record["residual_ms"] is not None and float(record["residual_ms"]) < 0.0
            ),
            "residual_note": (
                "stage sums double-count wall clock when generate batches run concurrently; "
                "a negative residual means overlap, not missing time"
                if any(
                    record["residual_ms"] is not None and float(record["residual_ms"]) < 0.0
                    for record in records
                )
                else None
            ),
            "per_scenario_e2e_ms": {
                f"{record['scenario']['scenario_id']}#{record['repeat']}": record["e2e_ms"]
                for record in records
            },
        },
        "calibration": scoring.calibration(
            [
                (float(record["quality"]["score"]), bool(record["quality"]["hit"]))
                for record in train
                if record["quality"]["score"] is not None
            ]
        ),
        "risk_coverage": {
            "holdout": scoring.risk_coverage(
                [
                    (float(record["quality"]["score"]), bool(record["quality"]["hit"]))
                    for record in holdout
                    if record["quality"]["score"] is not None
                ]
            ),
            "train": scoring.risk_coverage(
                [
                    (float(record["quality"]["score"]), bool(record["quality"]["hit"]))
                    for record in train
                    if record["quality"]["score"] is not None
                ]
            ),
        },
        "per_scenario": [
            {
                "scenario_id": record["scenario"]["scenario_id"],
                "repeat": record["repeat"],
                "family": record["scenario"]["family"],
                "category": record["scenario"]["category"],
                "split": record["scenario"]["split"],
                "hit": record["quality"]["hit"],
                "fallback": record["quality"]["fallback"],
                "final_pattern": record["quality"]["final_pattern"],
                "expected_primary": record["quality"]["expected_primary"],
                "score": record["quality"]["score"],
                "recall_at_3": record["quality"]["recall_at_3"],
                "recall_at_5": record["quality"]["recall_at_5"],
                "acceptable_primary_f1": record["quality"]["acceptable_primary_f1"]["f1"],
                "e2e_ms": record["e2e_ms"],
                "residual_ms": record["residual_ms"],
            }
            for record in records
        ],
        "notes": list(notes),
    }


def _quality_aggregate(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Hit rate (+ Wilson CI) and mean/median metric summaries over ``records``."""
    return scoring.aggregate_quality(records)


# --------------------------------------------------------------------------------------
# Artifacts
# --------------------------------------------------------------------------------------


def _manifest(
    *,
    options: RunOptions,
    config: ServerConfig,
    catalog: PatternLoader,
    executor: ScenarioExecutor,
    records: Sequence[dict[str, Any]],
    warmup_record: dict[str, Any] | None,
    run_id: str,
    started_at: str,
    notes: Sequence[str],
) -> dict[str, Any]:
    """Run provenance: git, environment, effective config, corpus hash, executor seams."""
    return {
        "harness_version": HARNESS_VERSION,
        "run_id": run_id,
        "mode": options.mode,
        "started_at": started_at,
        "finished_at": cfg.utc_now_iso(),
        "scenario_file": {
            "path": str(options.scenarios_path),
            "sha256": cfg.file_sha256(options.scenarios_path),
        },
        "selection": {
            "split": options.split,
            "limit": options.limit,
            "repeats": options.repeats,
            "warmup": options.warmup,
            "flips": sorted(options.flips),
        },
        "scenario_ids": [record["scenario"]["scenario_id"] for record in records],
        "warmup": {
            "enabled": options.warmup,
            "scenario_id": warmup_record["scenario"]["scenario_id"] if warmup_record else None,
            "e2e_ms": warmup_record["e2e_ms"] if warmup_record else None,
        },
        "git": cfg.git_snapshot(),
        "env": cfg.masked_env_snapshot(),
        "server_config": cfg.mask_secrets(config.model_dump()),
        "catalog": {"records": len(catalog.load_all())},
        "executor": executor.describe(),
        "runtime": {"python": sys.version.split()[0], "platform": platform.platform()},
        "counts": {
            "records": len(records),
            "train": sum(1 for record in records if record["scenario"]["split"] == "train"),
            "holdout": sum(1 for record in records if record["scenario"]["split"] == "holdout"),
        },
        "notes": list(notes),
    }


def render_report(summary: dict[str, Any], manifest: dict[str, Any]) -> str:
    """Markdown report for one arm run."""
    quality = summary["quality"]
    latency = summary["latency"]
    lines: list[str] = [f"# Benchmark run {summary['run_id']}", ""]
    lines.append(
        f"- mode: `{summary['mode']}` · split `{summary['selection']['split']}` · "
        f"limit `{summary['selection']['limit']}` · repeats `{summary['selection']['repeats']}`"
    )
    lines.append(
        f"- scenarios: {manifest['counts']['records']} records "
        f"(train {manifest['counts']['train']} / holdout {manifest['counts']['holdout']})"
    )
    lines += [
        f"- corpus: `{summary['scenario_file']['path']}` sha256 `{summary['scenario_file']['sha256'][:16]}…`",
        f"- git: `{(manifest['git']['head'] or 'unknown')[:12]}` dirty={manifest['git']['dirty']}",
        f"- catalog: {summary['catalog']['records']} records",
        "",
        "## Quality (per split)",
        "",
        "| split | n | hit rate | Wilson 95% | fallbacks | recall@3 | recall@5 | primary F1 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name in ("overall", "train", "holdout"):
        block = quality[name]
        wilson = block["hit_rate_wilson"]
        wilson_text = (
            f"[{wilson['low']:.3f}, {wilson['high']:.3f}]" if wilson["low"] is not None else "null"
        )
        lines.append(
            f"| {name} | {block['scenarios']} | {_pct(block['hit_rate'])} | {wilson_text} | "
            f"{_int_or_null(block['fallbacks'])} | {_num(block['recall_at_3']['mean'])} | "
            f"{_num(block['recall_at_5']['mean'])} | {_num(block['acceptable_primary_f1']['mean'])} |"
        )
    lines += ["", "## Latency", ""]
    e2e = latency["e2e_ms"]
    lines.append(
        f"- e2e: n={e2e['samples']} p50={_ms(e2e['p50_ms'])} p95={_ms(e2e['p95_ms'])}"
        + (
            f" (warmup {_ms(latency['warmup_e2e_ms'])})"
            if latency["warmup_e2e_ms"] is not None
            else ""
        )
        + (f" — {e2e['note']}" if e2e["note"] else "")
    )
    if latency.get("residual_note"):
        lines.append(f"- residual: {latency['residual_note']}")
    lines += [
        "",
        "| stage | calls | failures | total ms | p50 ms | p95 ms | ops |",
        "|---|---|---|---|---|---|---|",
    ]
    for stage, entry in sorted(
        latency["stages"].items(), key=lambda item: _stage_order(item[0], item[1])
    ):
        lines.append(
            f"| `{stage}` | {entry['count']} | {entry['failures']} | {entry['total_ms']:.1f} | "
            f"{_ms(entry['p50_ms'])} | {_ms(entry['p95_ms'])} | "
            f"{', '.join(f'{op} x{count}' for op, count in sorted(entry['ops'].items()))} |"
        )
    lines += ["", "## Calibration (train split, monitoring only)", ""]
    calibration = summary["calibration"]
    lines.append(f"- Brier: {_num(calibration['brier'])} · ECE (10 bins): {_num(calibration['ece'])}")
    lines += ["", "| bin | range | n | avg score | accuracy | gap |", "|---|---|---|---|---|---|"]
    for entry in calibration["bins"]:
        if not entry["count"]:
            continue
        lines.append(
            f"| {entry['bin']} | [{entry['low']}, {entry['high']}) | {entry['count']} | "
            f"{_num(entry['avg_score'])} | {_num(entry['accuracy'])} | {_num(entry['gap'])} |"
        )
    lines += ["", "## Risk-coverage", ""]
    for split, block in summary["risk_coverage"].items():
        lines.append(
            f"- {split}: n={block['samples']} risk@80={_num(block['risk_at_80'])} "
            f"risk@90={_num(block['risk_at_90'])} risk@100={_num(block['risk_at_100'])} "
            f"AURC={_num(block['aurc'])}"
        )
    lines += [
        "",
        "## Per scenario",
        "",
        "| scenario | split | category | hit | final | expected | score | e2e ms | residual ms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for record in summary["per_scenario"]:
        e2e_value = record["e2e_ms"]
        residual_value = record["residual_ms"]
        lines.append(
            f"| `{record['scenario_id']}` | {record['split']} | {record['category']} | "
            f"{'✔' if record['hit'] else '✘'} | `{record['final_pattern']}` | "
            f"`{record['expected_primary']}` | {_num(record['score'])} | "
            f"{_ms(e2e_value)} | {_ms(residual_value)} |"
        )
    if summary.get("failures"):
        lines += ["", "## Failed scenario runs", "", "| key | error |", "|---|---|"]
        for failure in summary["failures"]:
            lines.append(f"| `{failure['scenario_id']}#r{failure['repeat']}` | {failure['error']} |")
    if summary["notes"]:
        lines += ["", "## Notes", ""] + [f"- {note}" for note in summary["notes"]]
    lines.append("")
    return "\n".join(lines)


def _stage_order(stage: str, entry: dict[str, Any]) -> tuple[int, float]:
    """Report order: documented request buckets first (probes.REQUEST_STAGES), then by total ms."""
    if stage in REQUEST_STAGES:
        return REQUEST_STAGES.index(stage), -float(entry["total_ms"])
    return len(REQUEST_STAGES) + 1, -float(entry["total_ms"])


def _num(value: Any) -> str:
    """Format an optional float for the report."""
    return "null" if value is None else f"{float(value):.3f}"


def _ms(value: Any) -> str:
    """Format an optional millisecond value for the report."""
    return "null" if value is None else f"{float(value):.1f}"


def _pct(value: Any) -> str:
    """Format an optional rate as a percentage."""
    return "null" if value is None else f"{100.0 * float(value):.1f}%"


def _int_or_null(value: Any) -> str:
    """Format an optional count (``null`` when a mode cannot observe it)."""
    return "null" if value is None else str(int(value))
