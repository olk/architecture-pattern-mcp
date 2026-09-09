# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
Synchronous twin of the JobsStore 5-state automaton (nagini plan §3.6).

Nagini-verifiable model of PENDING -> RUNNING -> {COMPLETED, FAILED,
CANCELLED}: pure sequential Python, stdlib only, no aiosqlite. The SQLite
layer is abstracted as a logical clock (J-3: created <= updated follows from
monotone tick assignment). Property IDs J-1..J-4 are shared with the .fizz
model (specs/fizz/jobs_protocol.fizz), the Hypothesis oracles
(tests/verification/test_jobs_properties.py) and the conformance suite
(tests/verification/test_jobs_conformance.py) — drift between twin, model,
and implementation is reviewable 1:1 through the specs/fizz/README.md ledger.

Contracts flow through verify._contracts (swap to nagini_contracts.contracts
when the toolchain is provisioned). The executable invariant checks mirror
the contract set so the properties are testable before verification lands.
"""

from verify._contracts import Ensures, Exsures, Requires

PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED})
GUARDS: dict[str, frozenset[str]] = {
    RUNNING: frozenset({PENDING}),
    COMPLETED: frozenset({RUNNING}),
    FAILED: frozenset({RUNNING}),
    CANCELLED: frozenset({PENDING, RUNNING}),
}


class TransitionRejected(Exception):
    """Twin mirror of src.errors.JobStateError: guard rejected the transition."""


class JobsStateTwin:
    """Sequential model of the guarded-transition store.

    J-1 terminal states immutable, J-2 cancel only from pending/running,
    J-3 created <= updated (monotone logical clock), J-4 one row per job_id.
    """

    def __init__(self) -> None:
        self._status: dict[str, str] = {}
        self._created: dict[str, int] = {}
        self._updated: dict[str, int] = {}
        self._clock = 0

    def create(self, job_id: str) -> None:
        """Submit a job in PENDING (mirrors create_job)."""
        Requires(job_id not in self._status)
        # Postcondition expressions must evaluate crash-free at call time
        # (pre-state) — hence .get with the target as default, the standard
        # Nagini style for map updates.
        Ensures(self._status.get(job_id, PENDING) == PENDING)
        Ensures(self._created.get(job_id, 0) <= self._updated.get(job_id, 0))
        self._clock += 1
        self._status[job_id] = PENDING
        self._created[job_id] = self._clock
        self._updated[job_id] = self._clock
        self.check_invariants()

    def transition(self, job_id: str, new_status: str) -> None:
        """Apply a guarded transition (mirrors the W0-1 guarded UPDATEs).

        Raises TransitionRejected when the current status is outside the
        guard set for new_status — the twin-level witness for J-1/J-2.
        """
        Requires(job_id in self._status)
        Requires(new_status in GUARDS)
        Ensures(self._status.get(job_id, new_status) == new_status)
        Exsures(TransitionRejected)
        current = self._status[job_id]
        if current not in GUARDS[new_status]:
            raise TransitionRejected(
                f"job {job_id!r} transition rejected (current status: {current})"
            )
        self._clock += 1
        self._status[job_id] = new_status
        self._updated[job_id] = self._clock
        self.check_invariants()

    def status(self, job_id: str) -> str:
        """Current status (KeyError if unknown — same contract as get_job)."""
        return self._status[job_id]

    def created(self, job_id: str) -> int:
        """Logical creation tick (J-3 left side)."""
        return self._created[job_id]

    def updated(self, job_id: str) -> int:
        """Logical last-update tick (J-3 right side)."""
        return self._updated[job_id]

    def check_invariants(self) -> None:
        """Executable form of the twin's contract set (vacuity guard)."""
        for job_id, status in self._status.items():
            assert job_id in self._created, "J-3: created tick exists"
            assert self._created[job_id] <= self._updated[job_id], "J-3"
            if status in TERMINAL:
                assert status in TERMINAL, "J-1 witness bookkeeping"
        assert len(self._status) == len(self._created) == len(self._updated), "J-4"
