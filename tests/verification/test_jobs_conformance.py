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
L5 conformance suite: twin <-> implementation (nagini plan §3.6).

Drives the synchronous twin (verify/twin/jobs_state_twin.py) and the REAL
JobsStore through identical Hypothesis-generated interleavings of
create/start/complete/fail/cancel and asserts identical status outcomes after
every step. Mechanism: hypothesis.stateful.RuleBasedStateMachine with a
per-test sync facade (a dedicated event loop each coroutine runs on, since
aiosqlite binds its connection to the creating loop; W0-2's injectable lock
keeps the singleton path untouched).

The twin remains a model subject to the same vacuity discipline as contracts:
it is checked against the garden mutant IDs via the shared property set
(J-1..J-4) and its invariants are executable (check_invariants after every
rule).
"""

import asyncio
import os
import tempfile
import unicodedata
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, initialize, rule, invariant

from src.errors import JobStateError
from src.tools.jobs import JobStatus, JobsStore
from verify.twin.jobs_state_twin import (
    GUARDS,
    JobsStateTwin,
    TransitionRejected,
)

OPERATIONS = ("start", "complete", "fail", "cancel")
OP_TO_STATUS: dict[str, str] = {
    "start": JobStatus.RUNNING,
    "complete": JobStatus.COMPLETED,
    "fail": JobStatus.FAILED,
    "cancel": JobStatus.CANCELLED,
}
OP_TO_SETTER: dict[str, str] = {
    "start": "set_running",
    "complete": "set_completed",
    "fail": "set_failed",
    "cancel": "set_cancelled",
}


class _SyncStoreFacade:
    """Runs each store coroutine to completion on one dedicated event loop."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()

    def call(self, coro: object) -> object:
        return self._loop.run_until_complete(coro)  # type: ignore[arg-type]

    def close(self) -> None:
        self._loop.close()


class JobsConformanceMachine(RuleBasedStateMachine):
    jobs = Bundle("jobs")

    def __init__(self) -> None:
        super().__init__()
        self._facade = _SyncStoreFacade()
        self._tmpdir = tempfile.mkdtemp(prefix="conformance-jobs-")
        self._saved_db_env = os.environ.get("ARCHITECTURE_PATTERN_JOBS_DB")
        os.environ["ARCHITECTURE_PATTERN_JOBS_DB"] = os.path.join(self._tmpdir, "jobs.db")
        # Fresh store bypassing the singleton (W0-2 injectable construction);
        # drop the singleton first so __new__ yields an unbound instance.
        JobsStore._instance = None
        self._store = JobsStore(lock=asyncio.Lock())
        self._facade.call(self._store._init())
        self._twin = JobsStateTwin()
        self._counter = 0

    def teardown(self) -> None:
        self._facade.call(self._store.close())
        self._facade.close()
        if self._saved_db_env is None:
            os.environ.pop("ARCHITECTURE_PATTERN_JOBS_DB", None)
        else:
            os.environ["ARCHITECTURE_PATTERN_JOBS_DB"] = self._saved_db_env

    @initialize(target=jobs)
    def create_initial_job(self) -> str:
        return self._create_job()

    @rule(target=jobs)
    def create_job(self) -> str:
        return self._create_job()

    def _create_job(self) -> str:
        self._counter += 1
        # The STORE generates the id (uuid); the twin models the same id so
        # both sides address identical jobs.
        job_id = self._facade.call(
            self._store.create_job(requirements="req", domain="dom")
        )
        self._twin.create(job_id)
        return job_id

    @rule(jid=jobs, op=st.sampled_from(OPERATIONS))
    def apply_operation(self, jid: str, op: str) -> None:
        new_status = OP_TO_STATUS[op]
        twin_rejected = False
        store_rejected = False
        try:
            self._twin.transition(jid, new_status)
        except TransitionRejected:
            twin_rejected = True

        setter = getattr(self._store, OP_TO_SETTER[op])
        extra: tuple[object, ...] = ()
        if op == "complete":
            extra = ('{"conformance": true}',)
        elif op == "fail":
            extra = ("conformance failure",)
        try:
            self._facade.call(setter(jid, *extra))
        except JobStateError:
            store_rejected = True

        assert twin_rejected == store_rejected, f"acceptance mismatch for {op} on {jid}"
        job = self._facade.call(self._store.get_job(jid))
        assert job["status"] == self._twin.status(jid), "twin/store status drift"
        assert job["created_at"] <= job["updated_at"], "J-3 broken on the store"

    @invariant()
    def twin_invariants_hold(self) -> None:
        self._twin.check_invariants()
        assert set(GUARDS) == {
            JobStatus.RUNNING,
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }


JobsConformanceMachine.TestCase.settings = settings(
    max_examples=15, stateful_step_count=20, deadline=None
)
TestJobsConformance = JobsConformanceMachine.TestCase


class TestStubConformance:
    """Stub-conformance spot-checks (nagini plan §3.5): the oracle assumptions
    the proofs rest on must themselves hold."""

    def test_unicodedata_category_returns_two_letter_category(self) -> None:
        for codepoint in range(0x110000):
            ch = chr(codepoint)
            cat = unicodedata.category(ch)
            assert len(cat) == 2 and cat.isalpha(), (hex(codepoint), cat)

    def test_twin_guard_matrix_matches_store_guards(self) -> None:
        from tests.unit.test_jobs import TestGuardedTransitions

        for setter_name, allowed in TestGuardedTransitions.GUARDS.items():
            target = TestGuardedTransitions.TARGET_STATUS[setter_name]
            assert set(allowed) == set(GUARDS[target]), setter_name
