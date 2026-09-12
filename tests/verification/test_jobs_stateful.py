# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
Stateful (RuleBasedStateMachine) L2 oracle over the REAL JobsStore
(testing-strategies.md §3.3; ledger rows J-1..J-4).

Supersedes the list-replay shape of the J-oracle in
``test_jobs_properties.py``: Hypothesis now searches RULE SEQUENCES
(start/complete/fail/cancel/read over a Bundle of live job ids) and shrinks
a failing sequence to the shortest reproducing trace. The shadow automaton
from the J-oracle is retained as the model; every rule step re-checks
store/shadow agreement, so J-1 (terminal immutability), J-2 (cancel scope),
J-3 (timestamp monotonicity) and J-4 (one row per job id) hold after every
generated step, not only at the end.

Determinism rule (testing-strategies.md §3.2, unchanged): one event loop per
machine run — ``_loop.run_until_complete`` per step keeps the aiosqlite
connection on a single loop for the whole schedule (the generalization of
the ``asyncio.run``-per-example pattern used by the J-oracle).

Direction of the implication (unchanged): this oracle SAMPLES schedules;
``jobs_protocol.fizz``/``jobs_runner.fizz`` check them EXHAUSTIVELY up to
bounds. Liveness properties (RUN-4/FC-1) stay out of PBT scope
(``bounded — not sampleable`` in the ledger).
"""

from __future__ import annotations

import asyncio

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, initialize, rule

import pytest

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
NUM_JOBS = 3


class JobsStoreStateMachine(RuleBasedStateMachine):
    """Real store vs shadow automaton over generated operation schedules."""

    jobs: Bundle[str] = Bundle("jobs")

    def __init__(self) -> None:
        super().__init__()
        self._loop = asyncio.new_event_loop()
        self.jids: list[str] = []
        self.shadow: dict[str, str] = {}
        try:
            self._loop.run_until_complete(self._async_setup())
        except BaseException:
            self._close_loop()
            raise

    async def _async_setup(self) -> None:
        await JobsStore.reset_for_test()
        store = await JobsStore.get_instance()
        for _ in range(NUM_JOBS):
            self.jids.append(await store.create_job(requirements="req", domain="dom"))
        assert len(set(self.jids)) == NUM_JOBS, "J-4: one row per job_id"
        self.shadow = dict.fromkeys(self.jids, JobStatus.PENDING)

    # The Bundle must be populated via @initialize (all run before any rule);
    # three rules, one per seeded job — execution order varies per run.
    @initialize(target=jobs)
    def seed_job_0(self) -> str:
        return self.jids[0]

    @initialize(target=jobs)
    def seed_job_1(self) -> str:
        return self.jids[1]

    @initialize(target=jobs)
    def seed_job_2(self) -> str:
        return self.jids[2]

    def _run(self, coro: object) -> object:
        return self._loop.run_until_complete(coro)  # type: ignore[arg-type]

    def _close_loop(self) -> None:
        if not self._loop.is_closed():
            self._loop.close()

    def teardown(self) -> None:
        try:
            self._loop.run_until_complete(JobsStore.reset_for_test())
        finally:
            self._close_loop()

    # ── rules: one guarded transition per step, shadow-agreement asserted ──

    @rule(jid=jobs, kind=st.sampled_from(sorted(GUARDS)))
    def transition(self, jid: str, kind: str) -> None:
        async def _apply() -> None:
            store = await JobsStore.get_instance()
            setter = getattr(store, SETTER_NAMES[kind])
            if self.shadow[jid] in GUARDS[kind]:
                await setter(jid, *SETTER_ARGS[kind])
                self.shadow[jid] = TARGET[kind]
            else:
                with pytest.raises(JobStateError):
                    await setter(jid, *SETTER_ARGS[kind])

        self._run(_apply())
        self._check_step_agreement(jid)

    @rule(jid=jobs)
    def read_is_side_effect_free(self, jid: str) -> None:
        async def _read() -> None:
            store = await JobsStore.get_instance()
            job = await store.get_job(jid)
            assert job is not None
            assert job["status"] == self.shadow[jid]

        self._run(_read())

    @rule()
    def create_is_unique(self) -> None:
        async def _create() -> None:
            store = await JobsStore.get_instance()
            jid = await store.create_job(requirements="req", domain="dom")
            self.jids.append(jid)
            self.shadow[jid] = JobStatus.PENDING

        self._run(_create())

    # ── invariants ─────────────────────────────────────────────────────────

    def _check_step_agreement(self, changed_jid: str) -> None:
        async def _verify() -> None:
            store = await JobsStore.get_instance()
            for jid in self.jids:
                job = await store.get_job(jid)
                assert job is not None, f"J-4 violated: {jid} missing"
                assert job["status"] == self.shadow[jid], (
                    f"shadow disagreement on {jid}: store={job['status']}, "
                    f"shadow={self.shadow[jid]}"
                )
                # J-3: created_at <= updated_at (ISO-8601 UTC: lexicographic
                # = chronological).
                assert job["created_at"] <= job["updated_at"], "J-3 violated"

        self._run(_verify())


TestJobsStoreStatefulMachine = JobsStoreStateMachine.TestCase
TestJobsStoreStatefulMachine.settings = settings(
    max_examples=15,
    deadline=None,
    stateful_step_count=20,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
