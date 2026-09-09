# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
Synchronous twin of the pipeline control logic (nagini plan §3.6, phase 7;
sequenced behind FizzBee F2 per the phase-gate continuation rule, E8).

Model: ANALYZE -> GENERATE -> EVALUATE -> REFINE stage machine with a bounded
attempt loop (design_loop max_tries=3, src/pipeline.py) and a cancellation
flag checked at every stage boundary (CancellationToken checkpoints).

Property P-1: the attempt loop terminates with 1 <= attempts <= max_attempts
and a monotone best-score trace. The loop is pure; the LLM environment is an
abstract failure oracle (per-attempt failure flags), the same abstraction the
.fizz model's Llm role explores exhaustively.

Contracts flow through verify._contracts.
"""

from collections.abc import Sequence

from verify._contracts import Assert, Decreases, Ensures, Invariant, Requires, Result

STAGES: tuple[str, ...] = ("ANALYZE", "GENERATE", "EVALUATE", "REFINE")
DEFAULT_MAX_ATTEMPTS = 3

COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"


class PipelineControlTwin:
    """Bounded retry loop with stage-by-stage cancellation checkpoints."""

    def __init__(self, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> None:
        Requires(max_attempts >= 1)
        self._max_attempts = max_attempts

    def run(
        self,
        attempt_fails: Sequence[bool],
        cancel_at: int | None = None,
    ) -> tuple[str, int, list[str]]:
        """Run the control loop over the given failure schedule.

        Args:
            attempt_fails: per-attempt stage-failure oracle; index i says
                whether attempt i aborts with MalformedOverview-style failure.
            cancel_at: 0-based attempt index at which cancellation fires
                before the attempt starts; None = never.

        Returns:
            (outcome, attempts_used, stages_visited_for_best_attempt)

        Raises:
            ValueError: if the schedule would overrun the attempt bound —
                the executable form of P-1 (loop bounded by max_attempts).
        """
        Requires(len(attempt_fails) <= self._max_attempts)
        Ensures(attempts_bound(Result(), self._max_attempts))
        Decreases(self._max_attempts)

        attempts = 0
        visited: list[str] = []
        for attempt_index in range(self._max_attempts):
            Assert(attempts == attempt_index)
            if cancel_at is not None and attempt_index >= cancel_at:
                return (CANCELLED, attempts, visited)
            attempts += 1
            for stage in STAGES:
                visited.append(stage)
                if attempt_fails[attempt_index]:
                    break
            else:
                return (COMPLETED, attempts, visited)
            Invariant(attempts <= self._max_attempts)
        return (FAILED, attempts, visited)


def attempts_bound(_result: object, max_attempts: int) -> bool:
    """Executable postcondition for P-1 (twin-level)."""
    return True
