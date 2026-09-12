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
L2 Hypothesis oracles keyed by the shared property IDs (J-1..J-4; see
verify/fizz/README.md ledger and formal_verification.md §4.5), plus the
E5 reasoning-client timeout/retry oracle (testing-strategies §3.3).

Direction of the implication (testing-strategies §3.3): these oracles SAMPLE
the property space that the .fizz models check exhaustively up to bounds.

Determinism rule (testing-strategies §3.2): each Hypothesis example drives its
own event loop (``asyncio.run``) and, for the store oracles, resets the
JobsStore singleton, so examples never share state and failures replay.
"""

import asyncio
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from src.agent import LLMError, SoftwareArchitectAgent
from src.config import (
    EmbedderConfig,
    EmbedderInnerConfig,
    GeneratorConfig,
    GeneratorInnerConfig,
    ServerConfig,
    ValidationConfig,
)
from src.errors import JobStateError
from src.tools.jobs import JobStatus, JobsStore

GUARDS: dict[str, set[str]] = {
    "start": {JobStatus.PENDING},
    "complete": {JobStatus.RUNNING},
    "fail": {JobStatus.RUNNING},
    "cancel": {JobStatus.PENDING, JobStatus.RUNNING},
}
TARGET: dict[str, str] = {
    "start": JobStatus.RUNNING,
    "complete": JobStatus.COMPLETED,
    "fail": JobStatus.FAILED,
    "cancel": JobStatus.CANCELLED,
}
SETTER_NAMES: dict[str, str] = {
    "start": "set_running",
    "complete": "set_completed",
    "fail": "set_failed",
    "cancel": "set_cancelled",
}
SETTER_ARGS: dict[str, tuple[str, ...]] = {
    "start": (),
    "complete": ('{"ok": true}',),
    "fail": ("boom",),
    "cancel": (),
}
TERMINAL = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED})


class _Ok(BaseModel):
    field: str = "ok"


class TestJobsLifecycleProperties:
    @given(
        ops=st.lists(
            st.tuples(st.sampled_from(sorted(GUARDS)), st.integers(0, 2)),
            max_size=14,
        )
    )
    @settings(max_examples=50, deadline=None)
    def test_generated_interleavings_match_guarded_automaton(
        self, ops: list[tuple[str, int]]
    ) -> None:
        """Generated operation sequences replayed against the real JobsStore:
        a shadow model of the guarded automaton predicts every accepted or
        rejected transition, and store/shadow agreement is asserted after
        every step (J-1 terminal immutability, J-2 cancel scope, J-3 timestamp
        monotonicity, J-4 one row per job_id)."""
        asyncio.run(self._replay_interleaving(ops))

    async def _replay_interleaving(self, ops: list[tuple[str, int]]) -> None:
        await JobsStore.reset_for_test()
        try:
            store = await JobsStore.get_instance()
            ids = [
                await store.create_job(requirements="req", domain="dom") for _ in range(3)
            ]
            assert len(set(ids)) == 3, "J-4: one row per job_id"
            shadow: dict[str, str] = dict.fromkeys(ids, JobStatus.PENDING)

            for kind, idx in ops:
                jid = ids[idx]
                setter = getattr(store, SETTER_NAMES[kind])
                if shadow[jid] in GUARDS[kind]:
                    await setter(jid, *SETTER_ARGS[kind])
                    shadow[jid] = TARGET[kind]
                else:
                    with pytest.raises(JobStateError):
                        await setter(jid, *SETTER_ARGS[kind])

                job = await store.get_job(jid)
                assert job["status"] == shadow[jid]
                assert job["created_at"] <= job["updated_at"], "J-3"

            for jid in ids:
                job = await store.get_job(jid)
                if job["status"] in TERMINAL:
                    assert job["status"] == shadow[jid], "J-1: terminal states immutable"
        finally:
            await JobsStore.reset_for_test()


class TestReasoningClientTimeoutRetryOracle:
    """E5: the LLM transport boundary (timeout/retry behaviour) gets a
    Hypothesis oracle — timeout/failure schedules must produce a structured
    LLMError/ValidationError mapping, never a hang, and retry counts stay
    within the configured bound (testing-strategies §3.3, second amendment).

    Split into two decorrelated checks:
      1. the self-healing retry loop (src/validation.validate_with_retries)
         directly, over generated failure schedules — structured errors are
         retried, retry counts stay within max_retries + 1, no hang;
      2. the transport error mapping (agent._generate_structured_once):
         raw timeout/provider exceptions must surface as structured LLMError,
         never escape raw and never hang.
    """

    FAILURE_KINDS = ["validation", "llm"]
    ATTEMPT_BUDGET = 3  # initial call + max_retries=2

    @staticmethod
    def _validation_error() -> ValidationError:
        try:
            ServerConfig.model_validate({"generator": object()})
        except ValidationError as exc:
            return exc
        raise AssertionError("expected ValidationError")

    @given(
        failures=st.lists(st.sampled_from(FAILURE_KINDS), max_size=4),
        eventually_ok=st.booleans(),
    )
    @settings(max_examples=40, deadline=None)
    def test_retry_loop_structured_errors_stay_bounded(
        self, failures: list[str], eventually_ok: bool
    ) -> None:
        asyncio.run(self._check_retry_loop(failures, eventually_ok))

    async def _check_retry_loop(self, failures: list[str], eventually_ok: bool) -> None:
        from src.validation import validate_with_retries

        calls: list[str] = []

        async def _caller(kind: str) -> _Ok:
            calls.append(kind)
            if kind == "validation":
                raise self._validation_error()
            if kind == "llm":
                raise LLMError(provider="openai", error="ERR_009", provider_message="pm")
            return _Ok()

        script: list[str] = failures + (["ok"] if eventually_ok else [])

        async def _initial() -> _Ok:
            return await _caller(script[0] if script else "ok")

        async def _repair(_sp: str, _up: str) -> _Ok:
            idx = min(len(calls), len(script) - 1)
            return await _caller(script[idx])

        bounded = asyncio.wait_for(
            validate_with_retries(
                _initial, _repair, _Ok, max_retries=2, system_prompt="s", user_prompt="u"
            ),
            timeout=10,
        )

        if not failures or (eventually_ok and len(failures) < self.ATTEMPT_BUDGET):
            result = await bounded
            assert isinstance(result, _Ok)
            assert calls == [*failures, "ok"], "succeeds exactly after scheduled failures"
        else:
            first = script[0] if script else "ok"
            expected: type[Exception] = (
                ValidationError if first == "validation" else LLMError
            )
            with pytest.raises(expected):
                await bounded
            assert len(calls) == self.ATTEMPT_BUDGET, "persistent failure exhausts budget"
        assert len(calls) <= self.ATTEMPT_BUDGET, "bounded retries (E5)"

    @given(
        raw_failure=st.sampled_from(["timeout", "runtime", "connection"]),
        delay_s=st.floats(min_value=0, max_value=0.05),
    )
    @settings(max_examples=15, deadline=None)
    def test_raw_transport_failures_map_to_structured_llm_error(
        self, raw_failure: str, delay_s: float
    ) -> None:
        """Timeout/failure of the transport must surface as structured
        LLMError (never raw) and never hang — simulated transport delay
        included (E5: timeout -> structured error, bounded, no hang)."""
        asyncio.run(self._check_raw_mapping(raw_failure, delay_s))

    async def _check_raw_mapping(self, raw_failure: str, delay_s: float) -> None:
        agent = SoftwareArchitectAgent(
            ServerConfig(
                generator=GeneratorConfig(
                    provider="openai",
                    config=GeneratorInnerConfig(model="gpt-oracle"),
                ),
                embedder=EmbedderConfig(
                    provider="tei",
                    config=EmbedderInnerConfig(base_url="http://localhost:8080"),
                ),
                validation=ValidationConfig(retry_on_fail=False, max_retries=0),
            )
        )

        async def _failing_achat(messages: list[object]) -> object:
            await asyncio.sleep(delay_s)
            if raw_failure == "timeout":
                raise TimeoutError("simulated transport timeout")
            if raw_failure == "runtime":
                raise RuntimeError("provider exploded")
            raise ConnectionError("connection reset")

        structured = MagicMock()
        structured.achat = _failing_achat
        client = MagicMock()
        client.as_structured_llm = MagicMock(return_value=structured)
        agent._client = client

        bounded = asyncio.wait_for(
            agent.generate_structured("system", "user", _Ok), timeout=10
        )
        with pytest.raises(LLMError) as exc_info:
            await bounded
        assert exc_info.value.provider == "openai"
        assert exc_info.value.error == "ERR_009"
        assert "simulated" in exc_info.value.provider_message or raw_failure != "timeout"


# ─────────────────────────────────────────────────────────────────────────────
# E5F family: reasoning-client loop discipline (ledger rows E5F-2/3/4;
# reasoning_retry.fizz is the exhaustive peer, FG-20..22 the kill mutants).
# The oracles drive the REAL cache/step-loop through a typed test subclass
# over the two async seams — never a re-implementation of either (P2).
# ─────────────────────────────────────────────────────────────────────────────

from collections.abc import Awaitable, Callable  # noqa: E402
from typing import cast  # noqa: E402

from src.reasoning.client import ReasoningClient, _CACHE_MAX_ENTRIES  # noqa: E402
from src.reasoning.config import ReasoningConfig, ReasoningStrategy  # noqa: E402
from src.reasoning.schemas import ReasoningStep, ReasoningTrace, ThoughtDraft  # noqa: E402

Tracer = Callable[[str, dict[str, str]], Awaitable[ReasoningTrace]]


class _SeamStubClient(ReasoningClient):
    """ReasoningClient with the agent/tool seams replaced by test doubles.

    ``tracer=None`` keeps the PRODUCTION ``_generate_trace`` (E5F-2 drives
    the real step loop); otherwise the injected coroutine stands in for it
    (E5F-3/E5F-4 exercise the real cache/single-flight around it).
    """

    def __init__(
        self,
        config: ReasoningConfig,
        tracer: Tracer | None = None,
        agent: object | None = None,
    ) -> None:
        scripted = agent if agent is not None else MagicMock(name="agent")
        super().__init__(config, cast("SoftwareArchitectAgent", scripted))
        self._tracer = tracer

    async def _generate_trace(
        self, phase: str, task_inputs: dict[str, str]
    ) -> ReasoningTrace:
        if self._tracer is None:
            return await ReasoningClient._generate_trace(self, phase, task_inputs)
        return await self._tracer(phase, task_inputs)

    async def _call_tool(self, kind: object, payload: object) -> str:
        return ""


def _cached_trace(phase: str) -> ReasoningTrace:
    """Trace with one step — only stepped traces enter the LRU."""
    return ReasoningTrace(
        phase=phase,
        steps=[
            ReasoningStep(
                tool="shannon",
                step_number=1,
                thought="t",
                tool_response="",
            )
        ],
    )


class TestE5F2StepLoopBound:
    """E5F-2: steps appended ≤ min(pre_llm_thoughts, max_total_steps)."""

    @given(
        pre_llm_thoughts=st.integers(min_value=1, max_value=6),
        max_total_steps=st.integers(min_value=1, max_value=6),
    )
    @settings(max_examples=15, deadline=None)
    def test_uncached_phase_stops_at_the_bound(
        self, pre_llm_thoughts: int, max_total_steps: int
    ) -> None:
        config = ReasoningConfig(
            enabled=True,
            max_total_steps=max_total_steps,
            per_phase={
                "evaluate": ReasoningStrategy(pre_llm_thoughts=pre_llm_thoughts)
            },
        )
        llm_calls: list[int] = []

        async def _draft(**_kwargs: object) -> ThoughtDraft:
            llm_calls.append(1)
            return ThoughtDraft(
                thought="t",
                phase_tag="problem_definition",
                uncertainty=0.3,
                next_needed=True,
            )

        agent = MagicMock(name="agent")
        agent.generate_structured = _draft
        client = _SeamStubClient(config, tracer=None, agent=agent)

        trace = asyncio.run(client.run_pre_llm("evaluate", {"requirements": "r"}))
        bound = min(pre_llm_thoughts, max_total_steps)
        assert len(trace.steps) == bound, f"steps {len(trace.steps)} != bound {bound}"
        assert len(llm_calls) == bound, "one LLM call per recorded step"
        assert trace.aborted_reason is None


class TestE5F3CacheBound:
    """E5F-3: the trace LRU never exceeds _CACHE_MAX_ENTRIES (real eviction)."""

    @given(n_inserts=st.integers(min_value=1, max_value=90))
    @settings(max_examples=10, deadline=None)
    def test_cache_size_never_exceeds_bound(self, n_inserts: int) -> None:
        async def _tracer(
            phase: str, task_inputs: dict[str, str]
        ) -> ReasoningTrace:
            return _cached_trace(phase)

        client = _SeamStubClient(ReasoningConfig(enabled=True), tracer=_tracer)

        async def _run() -> None:
            for i in range(n_inserts):
                await client._run_cached("analyze", {"requirements": f"r{i}"})
                assert len(client._trace_cache) <= _CACHE_MAX_ENTRIES

        asyncio.run(_run())

    def test_lru_recency_is_respected(self) -> None:
        """Re-touching a cached entry must save it from the next eviction."""

        async def _tracer(
            phase: str, task_inputs: dict[str, str]
        ) -> ReasoningTrace:
            return _cached_trace(phase)

        client = _SeamStubClient(ReasoningConfig(enabled=True), tracer=_tracer)

        async def _run() -> None:
            from src.reasoning.client import _cache_key

            for i in range(_CACHE_MAX_ENTRIES + 3):
                await client._run_cached("analyze", {"requirements": f"k{i}"})
            oldest = ("analyze", _cache_key({"requirements": "k0"}))
            assert oldest not in client._trace_cache
            # Re-touch k3 (still cached), then insert one more entry.
            await client._run_cached("analyze", {"requirements": "k3"})
            await client._run_cached("analyze", {"requirements": "k-new"})
            k3 = ("analyze", _cache_key({"requirements": "k3"}))
            assert k3 in client._trace_cache

        asyncio.run(_run())


class TestE5F4SingleFlight:
    """E5F-4: at most one concurrent trace generation per cache key."""

    @given(n_callers=st.integers(min_value=2, max_value=8))
    @settings(max_examples=10, deadline=None)
    def test_concurrent_callers_share_one_generation(self, n_callers: int) -> None:
        generations: list[int] = []

        async def _tracer(
            phase: str, task_inputs: dict[str, str]
        ) -> ReasoningTrace:
            generations.append(1)
            await asyncio.sleep(0.01)
            return _cached_trace(phase)

        client = _SeamStubClient(ReasoningConfig(enabled=True), tracer=_tracer)

        async def _run() -> list[ReasoningTrace]:
            return list(
                await asyncio.gather(
                    *(
                        client._run_cached("analyze", {"requirements": "same"})
                        for _ in range(n_callers)
                    )
                )
            )

        results = asyncio.run(_run())
        assert len(generations) == 1, (
            f"single-flight violated: {len(generations)} generations for one key"
        )
        assert all(r.steps for r in results)

    def test_distinct_keys_generate_distinct_traces(self) -> None:
        generations: list[str] = []

        async def _tracer(
            phase: str, task_inputs: dict[str, str]
        ) -> ReasoningTrace:
            generations.append(task_inputs["requirements"])
            return _cached_trace(phase)

        client = _SeamStubClient(ReasoningConfig(enabled=True), tracer=_tracer)

        async def _run() -> None:
            await asyncio.gather(
                *(
                    client._run_cached("analyze", {"requirements": f"r{i}"})
                    for i in range(3)
                )
            )

        asyncio.run(_run())
        assert sorted(generations) == ["r0", "r1", "r2"]


