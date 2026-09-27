"""Stage-attribution probes: seam wrappers that time every injected dependency call.

Port of design-pattern-mcp-local ``tests/benchmark/harness/probes.py`` (commit 25cbfba),
retargeted to this repository's seams:

- ``build.embed`` — warmup index build over the corpus (once per run, never per request).
- ``retrieval.dense`` / ``retrieval.bm25`` — the two fusion legs. Both run inside
  ``asyncio.to_thread`` in production, so the harness wraps the *sync* ``retrieve`` method
  with ``time.perf_counter_ns()`` timing; the wrapper class is async and delegates through
  ``asyncio.to_thread`` exactly as the pipeline would.
- ``llm.weights`` / ``llm.generate`` / ``llm.evaluate`` — the agent's structured-generation
  kinds, dispatched by ``response_schema``.
- ``reasoning.<phase>`` — ``ReasoningClient.run_pre_llm(phase, task_inputs)``.
- ``e2e.total`` — the per-request wall clock recorded by the runner (not a proxy).

Rerank latency is NOT separately attributed: the production reranker is constructed inside
``HybridPatternRetriever._ensure_reranker`` (not injected), so its time lands in the request
residual. This is a documented deviation from A, where the reranker is injectable.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Awaitable

#: Index-build stages: recorded, but never part of a per-request aggregate.
BUILD_STAGES: tuple[str, ...] = ("build.embed",)
STAGE_BUILD_EMBED = BUILD_STAGES[0]

STAGE_RETRIEVAL_DENSE = "retrieval.dense"
STAGE_RETRIEVAL_BM25 = "retrieval.bm25"
STAGE_LLM_WEIGHTS = "llm.weights"
STAGE_LLM_GENERATE = "llm.generate"
STAGE_LLM_EVALUATE = "llm.evaluate"
STAGE_DRAFT = "llm.draft"

#: Per-request stage buckets in report order (build stages deliberately absent).
REQUEST_STAGES: tuple[str, ...] = (
    STAGE_RETRIEVAL_DENSE,
    STAGE_RETRIEVAL_BM25,
    STAGE_LLM_WEIGHTS,
    STAGE_LLM_GENERATE,
    STAGE_LLM_EVALUATE,
)

#: Below this many samples a percentile is reported as ``null`` with a note (never NaN).
MIN_PERCENTILE_SAMPLES = 4

#: ``statistics.quantiles(n=20, method="inclusive")`` cut-point indices: p50 = 10/20, p95 = 19/20.
_QUANTILE_INDEX_P50 = 9
_QUANTILE_INDEX_P95 = 18


def reasoning_stage(phase: str) -> str:
    """Stage bucket for one reasoning phase (``analyze``/``generate``/``evaluate``/``retry``)."""
    return f"reasoning.{phase}"


@dataclass(frozen=True)
class StageRecord:
    """One timed seam call."""

    stage: str
    op: str
    started_ns: int
    duration_ms: float
    ok: bool
    meta: dict[str, Any] = field(default_factory=dict)


class StageRecorder:
    """Append-only timing sink shared by every proxy of one run."""

    def __init__(self) -> None:
        self._records: list[StageRecord] = []

    def __len__(self) -> int:
        return len(self._records)

    @property
    def records(self) -> list[StageRecord]:
        """All records in call order (live view; use :meth:`snapshot` to freeze a slice)."""
        return self._records

    def now_ns(self) -> int:
        """Monotonic clock reading for a caller that wants to time its own boundary."""
        return time.perf_counter_ns()

    def mark(
        self,
        *,
        stage: str,
        op: str,
        started_ns: int,
        ok: bool,
        meta: dict[str, Any] | None = None,
    ) -> StageRecord:
        """Record one finished call; ``duration_ms`` is derived from the caller's start stamp."""
        record = StageRecord(
            stage=stage,
            op=op,
            started_ns=started_ns,
            duration_ms=(time.perf_counter_ns() - started_ns) / 1_000_000.0,
            ok=ok,
            meta=dict(meta or {}),
        )
        self._records.append(record)
        return record

    def snapshot(self) -> list[StageRecord]:
        """A copy of every record so far (caller keeps this as a per-request slice)."""
        return list(self._records)


async def _timed(
    recorder: StageRecorder,
    *,
    stage: str,
    op: str,
    meta: dict[str, Any],
    call: Callable[[], Awaitable[Any]],
) -> Any:
    """Await ``call()``, recording its duration and outcome even on failure."""
    started_ns = recorder.now_ns()
    try:
        result = await call()
    except BaseException as exc:  # noqa: BLE001 - attribution must survive any seam failure
        recorder.mark(
            stage=stage,
            op=op,
            started_ns=started_ns,
            ok=False,
            meta={**meta, "error": f"{type(exc).__name__}: {exc}"},
        )
        raise
    recorder.mark(stage=stage, op=op, started_ns=started_ns, ok=True, meta=meta)
    return result


class SyncLegTimingProxy:
    """Timing wrapper for one *sync* retrieval leg (dense vector index or BM25 index).

    Production runs each leg inside ``asyncio.to_thread`` (the llama-index retriever API is
    synchronous), so the proxy mirrors that: a synchronous ``retrieve`` timed with the
    monotonic clock, exposed to async callers through ``retrieve_async``. The recorder is
    shared with the run's other proxies; the stage name distinguishes the legs.
    """

    def __init__(self, inner: Any, recorder: StageRecorder, *, stage: str) -> None:
        self._inner = inner
        self._recorder = recorder
        self._stage = stage

    @property
    def inner(self) -> Any:
        """The wrapped leg retriever (never unwrap for the pipeline)."""
        return self._inner

    def retrieve(self, query_bundle: Any) -> list[Any]:
        """One synchronous leg retrieval, timed (the production call runs in a worker thread)."""
        started_ns = self._recorder.now_ns()
        try:
            result = list(self._inner.retrieve(query_bundle))
        except BaseException as exc:  # noqa: BLE001 - attribution must survive any seam failure
            self._recorder.mark(
                stage=self._stage,
                op="retrieve",
                started_ns=started_ns,
                ok=False,
                meta={"error": f"{type(exc).__name__}: {exc}"},
            )
            raise
        self._recorder.mark(
            stage=self._stage,
            op="retrieve",
            started_ns=started_ns,
            ok=True,
            meta={"nodes": len(result)},
        )
        return result

    async def aretrieve(self, query_bundle: Any) -> list[Any]:
        """Async passthrough that keeps the timing in the sync path (thread offload)."""
        return await asyncio.to_thread(self.retrieve, query_bundle)


class AgentTimingProxy:
    """Timing wrapper for the agent's ``generate_structured`` seam, dispatched by schema.

    The schema type determines the stage bucket:
    ``RequirementWeights`` → ``llm.weights``, ``ArchitectureDesignResponse`` (or the lean
    ``...Wire`` variant) → ``llm.generate``, ``ArchitectureEvaluation`` → ``llm.evaluate``,
    ``DraftScenarioList`` → ``llm.draft``.
    """

    def __init__(self, inner: Any, recorder: StageRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    def _stage_for(self, response_schema: Any) -> str:
        name = getattr(response_schema, "__name__", "")
        if name == "RequirementWeights":
            return STAGE_LLM_WEIGHTS
        if name in ("ArchitectureDesignResponse", "ArchitectureDesignResponseWire"):
            return STAGE_LLM_GENERATE
        if name == "ArchitectureEvaluation":
            return STAGE_LLM_EVALUATE
        if name in ("DraftScenarioList", "DraftScenarioListWire"):
            return STAGE_DRAFT
        return STAGE_LLM_GENERATE

    async def generate_structured(
        self, system_prompt: str, user_prompt: str, response_schema: Any
    ) -> Any:
        """One structured-generation call, attributed by the requested response schema."""
        stage = self._stage_for(response_schema)
        return await _timed(
            self._recorder,
            stage=stage,
            op="generate_structured",
            meta={
                "schema": getattr(response_schema, "__name__", str(response_schema)),
                "user_prompt_chars": len(user_prompt),
                "system_prompt_chars": len(system_prompt),
            },
            call=lambda: self._inner.generate_structured(system_prompt, user_prompt, response_schema),
        )

    def __getattr__(self, item: str) -> Any:
        """Delegate anything else (health probes, provider handles) to the wrapped agent."""
        return getattr(self._inner, item)


class ReasoningTimingProxy:
    """Timing wrapper for ``ReasoningClient``'s two pipeline-visible members.

    The pipeline reads ``.enabled`` and calls ``run_pre_llm(phase, task_inputs)`` — nothing
    else, so the proxy exposes exactly those and delegates the rest.
    """

    def __init__(self, inner: Any, recorder: StageRecorder) -> None:
        self._inner = inner
        self._recorder = recorder

    @property
    def enabled(self) -> bool:
        """Master switch, mirrored from the wrapped client."""
        return bool(self._inner.enabled)

    async def run_pre_llm(self, phase: str, task_inputs: dict[str, str]) -> Any:
        """One pre-LLM reasoning loop for ``phase`` (internal drafts count toward this stage)."""
        return await _timed(
            self._recorder,
            stage=reasoning_stage(phase),
            op="run_pre_llm",
            meta={"task_input_keys": sorted(task_inputs)},
            call=lambda: self._inner.run_pre_llm(phase, task_inputs),
        )

    def __getattr__(self, item: str) -> Any:
        """Delegate anything else (``health_check``, ``close``) to the wrapped client."""
        return getattr(self._inner, item)


def percentile_fields(values: Sequence[float]) -> dict[str, Any]:
    """p50/p95 of ``values`` via the stdlib inclusive quantiles, or ``null`` fields when sparse.

    ``statistics.quantiles(n=20, method="inclusive")`` yields the 19 cut points at ``i/20``;
    p50 is index 9 and p95 index 18. Fewer than :data:`MIN_PERCENTILE_SAMPLES` samples report
    ``None`` plus an explanatory note — never NaN.
    """
    samples = len(values)
    if samples < MIN_PERCENTILE_SAMPLES:
        return {
            "samples": samples,
            "p50_ms": None,
            "p95_ms": None,
            "note": f"{samples} sample(s): p50/p95 need at least {MIN_PERCENTILE_SAMPLES}",
        }
    cuts = statistics.quantiles(list(values), n=20, method="inclusive")
    return {
        "samples": samples,
        "p50_ms": round(cuts[_QUANTILE_INDEX_P50], 3),
        "p95_ms": round(cuts[_QUANTILE_INDEX_P95], 3),
        "note": None,
    }


def stage_table(records: Sequence[StageRecord]) -> dict[str, dict[str, Any]]:
    """Group ``records`` by stage: call count, failures, total ms, per-call p50/p95 and ops."""
    table: dict[str, dict[str, Any]] = {}
    for record in records:
        entry = table.setdefault(
            record.stage,
            {"count": 0, "failures": 0, "total_ms": 0.0, "ops": {}, "durations": []},
        )
        entry["count"] += 1
        if not record.ok:
            entry["failures"] += 1
        entry["total_ms"] = round(entry["total_ms"] + record.duration_ms, 3)
        entry["ops"][record.op] = entry["ops"].get(record.op, 0) + 1
        entry["durations"].append(record.duration_ms)
    for entry in table.values():
        entry.update(percentile_fields(entry.pop("durations")))
    return table


def request_stage_total_ms(table: dict[str, dict[str, Any]]) -> float:
    """Σ total_ms over every non-build stage (index build excluded)."""
    return round(
        sum(float(entry["total_ms"]) for stage, entry in table.items() if stage not in BUILD_STAGES),
        3,
    )


def residual_ms(e2e_ms: float, table: dict[str, dict[str, Any]]) -> float:
    """``pipeline-residual = e2e − Σ(request stages)``: harness/loop overhead outside the seams."""
    return round(e2e_ms - request_stage_total_ms(table), 3)
