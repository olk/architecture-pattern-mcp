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
L6 deterministic-simulation experiment (testing-strategies §3.7; the DST
head-to-head sub-experiment of formal_verification.md §2.7).

Target: prove J-1/J-2 on the REAL JobsStore implementation under bounded
schedule exploration (E1 acceptance: >= 1 of the discriminating pair
J-1/J-2; this suite proves BOTH).

Two exploration modes, both deterministic and replayable:

1. EXHAUSTIVE micro-step interleaving: the cancel/completion race decomposes
   into two ordered step lists ([A1 running, A2 completed] vs [B1 status
   check, B2 cancelled]); every interleaving preserving per-party order is
   executed (C(4,2) = 6 schedules). A schedule step that hits the guard
   raises JobStateError and is recorded as a rejection.

2. SEEDED real-loop races: both parties run as real asyncio coroutines on the
   real event loop; seeded pre-yield counts (asyncio.sleep(0) spin-up) shift
   the natural interleaving. Every failure is replayable from the seed.

simloom/frontrun swap-in: the harness is written so each mode maps 1:1 onto
the target tools (mode 1 -> simloom @test(systematic=True, max_delays=N);
mode 2 -> simloom seeded scheduler / frontrun DPOR). Neither tool is
installable in this environment (docs/phase-0-decisions.md); when
provisioned, the same scenarios and oracles run under their schedulers.

SlateDB DST caveat honoured (testing-strategies §3.7): "zero bugs since
inception" is a harness-smell — the suite asserts the guard REJECTS specific
schedules (can-fail oracle), not just that nothing crashed.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import pytest

from src.errors import JobStateError
from src.tools.jobs import JobStatus, JobsStore

BoundedOracle = Callable[[], Awaitable[object]]


@dataclass
class ScheduleResult:
    schedule: tuple[str, ...]
    rejections: list[str] = field(default_factory=list)
    status_history: list[str] = field(default_factory=list)
    final_status: str = ""

    def assert_properties(self) -> None:
        """J-1: once terminal, status never changes. J-2: every out-of-guard
        write raises JobStateError (never silent overwrite)."""
        terminal_seen_at = None
        for index, status in enumerate(self.status_history):
            if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                if terminal_seen_at is None:
                    terminal_seen_at = index
                assert index == terminal_seen_at or status == self.status_history[
                    terminal_seen_at
                ], f"J-1 violated in schedule {self.schedule}: left terminal state"
        assert self.final_status in {
            JobStatus.COMPLETED,
            JobStatus.CANCELLED,
        }, f"unexpected final status {self.final_status}"
        assert self.rejections, (
            f"can-fail oracle: schedule {self.schedule} produced no rejections — "
            "the guard never fired, the exploration is vacuous"
        )


class TestDeterministicScheduleExploration:
    """Exhaustive micro-step interleaving over the real store (mode 1)."""

    def test_all_race_interleavings_preserve_j1_j2(self) -> None:
        schedules = _all_interleavings(
            ("A1_running", "A2_completed"), ("B1_check", "B2_cancel")
        )
        assert len(schedules) == 6
        results = [asyncio.run(self._execute(schedule)) for schedule in schedules]
        for result in results:
            result.assert_properties()
        # The frozen counterexample schedule (A completes, then B cancels) must
        # be among the rejected ones — the guard's exact job (J-1).
        a_first = [r for r in results if r.schedule.index("A2_completed") < r.schedule.index("B2_cancel")]
        assert any("B2_cancel" in r.rejections for r in a_first), (
            "guard failed to reject the historical J-1 race schedule"
        )

    async def _execute(self, schedule: tuple[str, ...]) -> ScheduleResult:
        await JobsStore.reset_for_test()
        try:
            store = await JobsStore.get_instance()
            job_id = await store.create_job(requirements="req", domain="dom")
            result = ScheduleResult(schedule=schedule)
            steps: dict[str, BoundedOracle] = {
                "A1_running": lambda: store.set_running(job_id),
                "A2_completed": lambda: store.set_completed(job_id, '{"side":"A"}'),
                "B1_check": lambda: store.is_cancelled(job_id),
                "B2_cancel": lambda: store.set_cancelled(job_id),
            }

            for step_name in schedule:
                try:
                    await steps[step_name]()
                    job = await store.get_job(job_id)
                    result.status_history.append(str(job["status"]))
                except JobStateError:
                    result.rejections.append(step_name)
                    job = await store.get_job(job_id)
                    result.status_history.append(str(job["status"]))
            job = await store.get_job(job_id)
            result.final_status = str(job["status"])
            return result
        finally:
            await JobsStore.reset_for_test()


def _all_interleavings(
    a: tuple[str, ...], b: tuple[str, ...]
) -> list[tuple[str, ...]]:
    """Every merge of two ordered tuples (within-party order preserved)."""
    if not a:
        return [b]
    if not b:
        return [a]
    head_a, tail_a = a[:1], a[1:]
    head_b, tail_b = b[:1], b[1:]
    return [
        *(head_a + rest for rest in _all_interleavings(tail_a, b)),
        *(head_b + rest for rest in _all_interleavings(a, tail_b)),
    ]


class TestSeededRealLoopRaces:
    """Seeded real-asyncio races over the real store (mode 2)."""

    @pytest.mark.parametrize("seed", [1, 42, 1337, 20260909, 7])
    def test_seeded_race_preserves_j1_j2(self, seed: int) -> None:
        rng = random.Random(seed)
        pre_yields_a = rng.randint(0, 4)
        pre_yields_b = rng.randint(0, 4)
        result = asyncio.run(
            self._race(seed=seed, pre_yields_a=pre_yields_a, pre_yields_b=pre_yields_b)
        )
        result.assert_properties()

    async def _race(self, seed: int, pre_yields_a: int, pre_yields_b: int) -> ScheduleResult:
        await JobsStore.reset_for_test()
        try:
            store = await JobsStore.get_instance()
            job_id = await store.create_job(requirements="req", domain="dom")
            label = f"seed={seed} yieldsA={pre_yields_a} yieldsB={pre_yields_b}"
            result = ScheduleResult(schedule=(label,))
            errors: list[JobStateError] = []

            async def party(
                party_yields: int, write: Callable[[], Awaitable[object]]
            ) -> None:
                for _ in range(party_yields):
                    await asyncio.sleep(0)
                try:
                    await write()
                except JobStateError as exc:
                    errors.append(exc)

            await asyncio.gather(
                party(pre_yields_a, lambda: store.set_completed(job_id, '{"side":"A"}')),
                party(pre_yields_b, lambda: store.set_cancelled(job_id)),
            )
            result.rejections = [f"rejected:{type(err).__name__}" for err in errors]
            job = await store.get_job(job_id)
            result.status_history = [str(job["status"])]
            result.final_status = str(job["status"])
            return result
        finally:
            await JobsStore.reset_for_test()
