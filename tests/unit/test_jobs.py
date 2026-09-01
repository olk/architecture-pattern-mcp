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
"""

import pytest

from src.tools.jobs import JobStatus, JobsStore


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
        """set_completed transitions the job to COMPLETED with a result."""
        job_id = await jobs_store.create_job(requirements="req", domain="dom")
        await jobs_store.set_completed(job_id, '{"design": {"name": "test"}}')
        job = await jobs_store.get_job(job_id)
        assert job["status"] == JobStatus.COMPLETED
        assert job["result"] == '{"design": {"name": "test"}}'

    @pytest.mark.asyncio
    async def test_set_failed(self, jobs_store: JobsStore):
        """set_failed transitions the job to FAILED with an error message."""
        job_id = await jobs_store.create_job(requirements="req", domain="dom")
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
        """is_cancelled returns False for a COMPLETED job (already terminal)."""
        job_id = await jobs_store.create_job(requirements="req", domain="dom")
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
