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
verify/fizz/README.md ledger and nagini-verification-plan.md §3.6), plus the
E5 reasoning-client timeout/retry oracle (testing-strategies §3.3).

Direction of the implication (testing-strategies §3.3): these oracles SAMPLE
what the Nagini twin proves (forall inputs) and what the .fizz model checks
exhaustively up to bounds.

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
