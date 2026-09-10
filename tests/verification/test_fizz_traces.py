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
L4 trace-replay regression tests (fizzbee plan §5.1).

Every real FizzBee counterexample — a trace exposing a genuine
design/implementation violation — is frozen as a deterministic pytest case
here and replays the traced interleaving against the REAL implementation.
These tests run in every `make test-oracles` pass, independent
of `fizz` tool availability.

Frozen traces:
  test_cancel_races_completion   J-1 anchor; source: jobs_protocol.fizz
                                 GUARDED=False flip (exhaustive run, 2026-09).
                                 Repair: Week-0 guarded UPDATEs (W0-1).
  test_cancel_wins_over_completion  J-2 anchor; symmetric interleaving — the
                                 completed write must lose to cancel.
"""

import pytest

from src.errors import JobStateError
from src.tools.jobs import JobStatus, JobsStore


class TestFrozenFizzTraces:
    @pytest.mark.asyncio
    async def test_cancel_races_completion(self, jobs_store: JobsStore):
        """Frozen FizzBee counterexample for J-1 (specs/fizz/README.md ledger).

        Trace: A: Trans(j0, COMPLETED) -> B: Trans(j0, CANCELLED) mid-flight
        -> j0 left COMPLETED. Source: fizz specs/fizz/jobs_protocol.fizz
        (exhaustive, GUARDED=False flip). Repair: Week-0 guarded UPDATEs
        (nagini plan §3.6, fourth amendment).
        """
        job_id = await jobs_store.create_job(requirements="req", domain="dom")
        await jobs_store.set_running(job_id)
        await jobs_store.set_completed(job_id, '{"ok": true}')

        with pytest.raises(JobStateError):
            await jobs_store.set_cancelled(job_id)

        job = await jobs_store.get_job(job_id)
        assert job["status"] == JobStatus.COMPLETED, "J-1 violated: job left COMPLETED"
        assert job["result"] == '{"ok": true}'
        assert await jobs_store.is_cancelled(job_id) is False

    @pytest.mark.asyncio
    async def test_cancel_wins_over_completion(self, jobs_store: JobsStore):
        """Frozen FizzBee counterexample for J-2 (symmetric interleaving):
        B: Trans(j0, CANCELLED) lands before A: Trans(j0, COMPLETED) — the
        completion write must be rejected, the result never persisted."""
        job_id = await jobs_store.create_job(requirements="req", domain="dom")
        await jobs_store.set_running(job_id)
        await jobs_store.set_cancelled(job_id)

        with pytest.raises(JobStateError):
            await jobs_store.set_completed(job_id, '{"late": true}')

        job = await jobs_store.get_job(job_id)
        assert job["status"] == JobStatus.CANCELLED, "J-2 violated: cancel overwritten"
        assert job["result"] is None, "late result must not be persisted"
