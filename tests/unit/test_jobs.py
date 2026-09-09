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
Tests for JobsStore job lifecycle.

The ``jobs_store`` autouse fixture (conftest.py) isolates each test to its own
temporary SQLite database so jobs from one test never bleed into another.

The ``TestGuardedTransitions`` class covers the Week-0 W0-1 bug fix (guarded
transition setters, properties J-1/J-2 of the verification program docs) and
``TestInjectableLock`` covers W0-2 (E6).
"""

import asyncio

import pytest

from src.errors import JobStateError
from src.tools.jobs import JobStatus, JobsStore


async def _reach_status(store: JobsStore, status: str) -> str:
    """Create a job and drive it to the requested status via legitimate transitions."""
    job_id = await store.create_job(requirements="req", domain="dom")
    if status == JobStatus.PENDING:
        return job_id
    await store.set_running(job_id)
    if status == JobStatus.RUNNING:
        return job_id
    if status == JobStatus.COMPLETED:
        await store.set_completed(job_id, '{"ok": true}')
    elif status == JobStatus.FAILED:
        await store.set_failed(job_id, "boom")
    elif status == JobStatus.CANCELLED:
        await store.set_cancelled(job_id)
    return job_id


class TestJobsStoreLifecycle:
    """Happy-path job lifecycle tests."""

    @pytest.mark.asyncio
    async def test_create_job_returns_uuid(self, jobs_store: JobsStore):
        """create_job returns a non-empty string job ID."""
        job_id = await jobs_store.create_job(
            requirements="Build a scalable ETL pipeline",
            domain="data engineering",
        )
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    @pytest.mark.asyncio
    async def test_get_job_returns_pending_job(self, jobs_store: JobsStore):
        """get_job returns the created job with PENDING status."""
        job_id = await jobs_store.create_job(
            requirements="Build a scalable ETL pipeline",
            domain="data engineering",
        )
        job = await jobs_store.get_job(job_id)
        assert job is not None
        assert job["id"] == job_id
        assert job["status"] == JobStatus.PENDING
        assert job["requirements"] == "Build a scalable ETL pipeline"
        assert job["domain"] == "data engineering"
        assert job["override_style"] is None

    @pytest.mark.asyncio
    async def test_get_job_returns_none_for_unknown_id(self, jobs_store: JobsStore):
        """get_job returns None when the job does not exist."""
        job = await jobs_store.get_job("does-not-exist")
        assert job is None

    @pytest.mark.asyncio
    async def test_set_running(self, jobs_store: JobsStore):
        """set_running transitions the job to RUNNING."""
        job_id = await jobs_store.create_job(requirements="req", domain="dom")
        await jobs_store.set_running(job_id)
        job = await jobs_store.get_job(job_id)
        assert job["status"] == JobStatus.RUNNING

    @pytest.mark.asyncio
    async def test_set_completed(self, jobs_store: JobsStore):
        """set_completed transitions the job RUNNING -> COMPLETED with a result.

        Updated under the Week-0 W0-1 deliberate exemption (nagini plan §3.9):
        this test previously encoded the old unconditional-overwrite behaviour
        (set_completed directly from PENDING); transitions are now guarded.
        """
        job_id = await jobs_store.create_job(requirements="req", domain="dom")
        await jobs_store.set_running(job_id)
        await jobs_store.set_completed(job_id, '{"design": {"name": "test"}}')
        job = await jobs_store.get_job(job_id)
        assert job["status"] == JobStatus.COMPLETED
        assert job["result"] == '{"design": {"name": "test"}}'

    @pytest.mark.asyncio
    async def test_set_failed(self, jobs_store: JobsStore):
        """set_failed transitions the job RUNNING -> FAILED with an error message.

        Updated under the Week-0 W0-1 deliberate exemption (guarded transitions).
        """
        job_id = await jobs_store.create_job(requirements="req", domain="dom")
        await jobs_store.set_running(job_id)
        await jobs_store.set_failed(job_id, "ERR_999: something went wrong")
        job = await jobs_store.get_job(job_id)
        assert job["status"] == JobStatus.FAILED
        assert job["error"] == "ERR_999: something went wrong"

    @pytest.mark.asyncio
    async def test_set_cancelled(self, jobs_store: JobsStore):
        """set_cancelled transitions the job to CANCELLED."""
        job_id = await jobs_store.create_job(requirements="req", domain="dom")
        await jobs_store.set_cancelled(job_id)
        job = await jobs_store.get_job(job_id)
        assert job["status"] == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_is_cancelled_returns_true_after_cancel(self, jobs_store: JobsStore):
        """is_cancelled returns True for a cancelled job."""
        job_id = await jobs_store.create_job(requirements="req", domain="dom")
        await jobs_store.set_cancelled(job_id)
        assert await jobs_store.is_cancelled(job_id) is True

    @pytest.mark.asyncio
    async def test_is_cancelled_returns_false_for_pending(self, jobs_store: JobsStore):
        """is_cancelled returns False for a PENDING (not yet cancelled) job."""
        job_id = await jobs_store.create_job(requirements="req", domain="dom")
        assert await jobs_store.is_cancelled(job_id) is False

    @pytest.mark.asyncio
    async def test_is_cancelled_returns_false_for_completed(self, jobs_store: JobsStore):
        """is_cancelled returns False for a COMPLETED job (already terminal).

        Updated under the Week-0 W0-1 deliberate exemption (guarded transitions).
        """
        job_id = await jobs_store.create_job(requirements="req", domain="dom")
        await jobs_store.set_running(job_id)
        await jobs_store.set_completed(job_id, '{}')
        assert await jobs_store.is_cancelled(job_id) is False

    @pytest.mark.asyncio
    async def test_reset_for_test_creates_fresh_db(self, tmp_path, monkeypatch):
        """reset_for_test deletes the old DB file and opens a fresh one at the new path."""
        import os
        db = tmp_path / "fresh.db"
        monkeypatch.setenv("ARCHITECTURE_PATTERN_JOBS_DB", str(db))
        await JobsStore.reset_for_test()
        new_store = await JobsStore.get_instance()
        job_id = await new_store.create_job(requirements="x", domain="y")
        assert (await new_store.get_job(job_id)) is not None
        assert os.path.exists(db)
        await JobsStore.reset_for_test()
        assert not os.path.exists(db), "DB file should be deleted after reset_for_test"


class TestGuardedTransitions:
    """W0-1: guarded transition setters (J-1 terminal immutability, J-2 cancel scope).

    The transition matrix is exhaustive: 4 setters x 5 source statuses. Each
    setter succeeds exactly from its guard set and raises JobStateError with
    the status left unchanged otherwise.
    """

    GUARDS: dict[str, set[str]] = {
        "set_running": {JobStatus.PENDING},
        "set_completed": {JobStatus.RUNNING},
        "set_failed": {JobStatus.RUNNING},
        "set_cancelled": {JobStatus.PENDING, JobStatus.RUNNING},
    }
    SETTER_ARGS: dict[str, tuple[str, ...]] = {
        "set_running": (),
        "set_completed": ('{"ok": true}',),
        "set_failed": ("boom",),
        "set_cancelled": (),
    }
    TARGET_STATUS: dict[str, str] = {
        "set_running": JobStatus.RUNNING,
        "set_completed": JobStatus.COMPLETED,
        "set_failed": JobStatus.FAILED,
        "set_cancelled": JobStatus.CANCELLED,
    }
    ALL_STATUSES = [
        JobStatus.PENDING,
        JobStatus.RUNNING,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("source_status", ALL_STATUSES)
    @pytest.mark.parametrize("setter_name", list(GUARDS))
    async def test_transition_matrix(
        self, jobs_store: JobsStore, setter_name: str, source_status: str
    ):
        job_id = await _reach_status(jobs_store, source_status)
        setter = getattr(jobs_store, setter_name)
        if source_status in self.GUARDS[setter_name]:
            await setter(job_id, *self.SETTER_ARGS[setter_name])
            job = await jobs_store.get_job(job_id)
            assert job["status"] == self.TARGET_STATUS[setter_name]
        else:
            with pytest.raises(JobStateError):
                await setter(job_id, *self.SETTER_ARGS[setter_name])
            job = await jobs_store.get_job(job_id)
            assert job["status"] == source_status

    @pytest.mark.asyncio
    async def test_terminal_immutability_rejects_every_setter(self, jobs_store: JobsStore):
        """J-1: no setter moves a job out of COMPLETED/FAILED/CANCELLED."""
        for terminal in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            job_id = await _reach_status(jobs_store, terminal)
            for setter_name in self.GUARDS:
                with pytest.raises(JobStateError):
                    await getattr(jobs_store, setter_name)(job_id, *self.SETTER_ARGS[setter_name])
                job = await jobs_store.get_job(job_id)
                assert job["status"] == terminal

    @pytest.mark.asyncio
    async def test_cancel_races_completion_frozen_trace(self, jobs_store: JobsStore):
        """Frozen W0-1 race trace (future FizzBee F0 flip anchor): a cancel
        racing a completion can no longer move the job out of COMPLETED."""
        job_id = await _reach_status(jobs_store, JobStatus.RUNNING)
        await jobs_store.set_completed(job_id, '{"ok": true}')
        with pytest.raises(JobStateError) as exc_info:
            await jobs_store.set_cancelled(job_id)
        assert exc_info.value.job_id == job_id
        assert exc_info.value.current_status == JobStatus.COMPLETED
        job = await jobs_store.get_job(job_id)
        assert job["status"] == JobStatus.COMPLETED
        assert job["result"] == '{"ok": true}'
        assert await jobs_store.is_cancelled(job_id) is False

    @pytest.mark.asyncio
    async def test_setter_on_unknown_job_raises(self, jobs_store: JobsStore):
        """A guarded setter on a nonexistent job raises instead of silently no-oping."""
        with pytest.raises(JobStateError):
            await jobs_store.set_running("does-not-exist")


class TestInjectableLock:
    """W0-2 (E6): constructor-injectable lock; default singleton path unchanged."""

    @pytest.mark.asyncio
    async def test_default_singleton_shares_class_lock(self, jobs_store: JobsStore):
        assert JobsStore() is jobs_store
        assert await JobsStore.get_instance() is jobs_store
        assert jobs_store._init_lock is JobsStore._lock

    @pytest.mark.asyncio
    async def test_independent_locks_allow_parallel_stores(self, tmp_path, monkeypatch):
        """Two stores with independent locks operate concurrently without deadlock."""
        lock_a, lock_b = asyncio.Lock(), asyncio.Lock()
        monkeypatch.setattr(JobsStore, "_instance", None)
        monkeypatch.setenv("ARCHITECTURE_PATTERN_JOBS_DB", str(tmp_path / "a.db"))
        store_a = JobsStore(lock=lock_a)
        await store_a._init()
        monkeypatch.setattr(JobsStore, "_instance", None)
        monkeypatch.setenv("ARCHITECTURE_PATTERN_JOBS_DB", str(tmp_path / "b.db"))
        store_b = JobsStore(lock=lock_b)
        await store_b._init()
        assert store_a is not store_b
        assert store_a._init_lock is lock_a
        assert store_b._init_lock is lock_b

        id_a = await store_a.create_job(requirements="req", domain="dom")
        id_b = await store_b.create_job(requirements="req", domain="dom")

        async def lifecycle_a():
            await store_a.set_running(id_a)
            await store_a.set_completed(id_a, '{"store": "a"}')

        async def lifecycle_b():
            await store_b.set_running(id_b)
            await store_b.set_cancelled(id_b)

        await asyncio.wait_for(asyncio.gather(lifecycle_a(), lifecycle_b()), timeout=10)

        job_a = await store_a.get_job(id_a)
        job_b = await store_b.get_job(id_b)
        assert job_a["status"] == JobStatus.COMPLETED
        assert job_b["status"] == JobStatus.CANCELLED

        await store_a.close()
        await store_b.close()
