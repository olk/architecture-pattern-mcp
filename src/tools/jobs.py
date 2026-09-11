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
Async SQLite job store for the manual submit/get_status/cancel tool trio.

Provides durable job state so that long-running design_architecture calls
can be polled via get_architecture_design_status and cancelled via cancel_architecture_design.

The store is a singleton — a single aiosqlite connection is shared across all calls.
"""

import aiosqlite
import asyncio
import logging
import os
import uuid
from datetime import datetime, UTC
from typing import Any

from src.errors import JobStateError

logger = logging.getLogger(__name__)


def _get_db_path() -> str:
    """Return the effective DB path, re-evaluated on every call for test isolation."""
    return os.environ.get(
        "ARCHITECTURE_PATTERN_JOBS_DB",
        os.path.expanduser("~/.config/architecture-pattern-mcp/jobs.db"),
    )


class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobsStore:
    """Singleton async SQLite store for design_architecture job state.

    W0-1: transition setters are guarded (``WHERE ... AND status IN (...)``) —
    the guard is atomic inside SQLite, which makes J-1 (terminal-state
    immutability) and J-2 (cancel effective only from pending/running) true of
    the implementation. This is the deliberate bug-fix exemption from the
    no-runtime-change rule (formal_verification.md §4.5).
    """

    _instance: "JobsStore | None" = None
    _db: aiosqlite.Connection | None = None
    _lock: asyncio.Lock = asyncio.Lock()
    _init_lock: asyncio.Lock

    def __new__(cls, lock: asyncio.Lock | None = None) -> "JobsStore":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_lock = lock if lock is not None else cls._lock
            cls._instance._db = None
        return cls._instance

    @classmethod
    async def get_instance(cls, lock: asyncio.Lock | None = None) -> "JobsStore":
        """Get or create the singleton instance, initialising the DB on first call."""
        # Read _db off the instance: self._db assignments shadow the class
        # attribute, so cls._db is always None and must not be used here.
        if cls._instance is None or cls._instance._db is None:
            async with (lock if lock is not None else cls._lock):
                if cls._instance is None or cls._instance._db is None:
                    cls._instance = cls(lock=lock)
                    await cls._instance._init()
        return cls._instance

    @classmethod
    async def reset_for_test(cls) -> None:
        """Test helper: close current connection, delete the DB file, and drop singleton.

        Use this with a temporarily overridden ``ARCHITECTURE_PATTERN_JOBS_DB``
        env-var to point at a per-test temporary directory.
        """
        # Close via the instance attribute (see get_instance): cls._db is a
        # shadowed class attribute that stays None. Awaiting close() also
        # joins the aiosqlite worker thread before the caller's event loop
        # closes — otherwise the worker races the loop shutdown and raises
        # "RuntimeError: Event loop is closed".
        instance = cls._instance
        if instance is not None:
            await instance.close()
            cls._instance = None
        cls._db = None
        db_path = _get_db_path()
        if os.path.exists(db_path):
            os.unlink(db_path)

    async def _init(self) -> None:
        db_path = _get_db_path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db = await aiosqlite.connect(db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(
            "CREATE TABLE IF NOT EXISTS jobs ("
            "  id TEXT PRIMARY KEY,"
            "  status TEXT NOT NULL DEFAULT 'pending',"
            "  requirements TEXT NOT NULL,"
            "  domain TEXT NOT NULL,"
            "  override_style TEXT,"
            "  created_at TEXT NOT NULL,"
            "  updated_at TEXT NOT NULL,"
            "  result TEXT,"
            "  error TEXT"
            ")"
        )
        await self._db.commit()
        logger.debug("JobsStore initialised", extra={"db_path": db_path})

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
            JobsStore._instance = None

    def _conn(self) -> aiosqlite.Connection:
        """Initialised DB connection — get_instance() guarantees _db is set."""
        if self._db is None:
            raise RuntimeError("JobsStore not initialised — call JobsStore.get_instance() first")
        return self._db

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    async def create_job(
        self,
        requirements: str,
        domain: str,
        override_style: str | None = None,
    ) -> str:
        """Create a pending job and return its ID."""
        job_id = str(uuid.uuid4())
        now = self._now()
        await self._conn().execute(
            "INSERT INTO jobs (id, status, requirements, domain, override_style, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, JobStatus.PENDING, requirements, domain, override_style, now, now),
        )
        await self._conn().commit()
        logger.debug("Job created", extra={"job_id": job_id})
        return job_id

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Return job dict or None if not found."""
        cursor = await self._conn().execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def _guarded_update(self, job_id: str, sql: str, params: tuple[Any, ...]) -> None:
        """Execute a guarded transition UPDATE and raise JobStateError on rejection.

        W0-1 (J-1/J-2): the ``AND status ...`` clause in ``sql`` is the guard —
        the check-and-set is atomic inside SQLite, so no caller-side
        check-then-act window exists. On rowcount 0 the current status is
        re-read for the error message.
        """
        cursor = await self._conn().execute(sql, params)
        await self._conn().commit()
        if cursor.rowcount == 0:
            job = await self.get_job(job_id)
            current_status: str | None = str(job["status"]) if job is not None else None
            raise JobStateError(job_id=job_id, current_status=current_status)

    async def set_running(self, job_id: str) -> None:
        """Transition pending -> running (guard: pending only)."""
        await self._guarded_update(
            job_id,
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
            (JobStatus.RUNNING, self._now(), job_id, JobStatus.PENDING),
        )

    async def set_completed(self, job_id: str, result: str) -> None:
        """Transition running -> completed (guard: running only)."""
        await self._guarded_update(
            job_id,
            "UPDATE jobs SET status = ?, result = ?, updated_at = ? WHERE id = ? AND status = ?",
            (JobStatus.COMPLETED, result, self._now(), job_id, JobStatus.RUNNING),
        )

    async def set_failed(self, job_id: str, error: str) -> None:
        """Transition running -> failed (guard: running only)."""
        await self._guarded_update(
            job_id,
            "UPDATE jobs SET status = ?, error = ?, updated_at = ? WHERE id = ? AND status = ?",
            (JobStatus.FAILED, error, self._now(), job_id, JobStatus.RUNNING),
        )

    async def set_cancelled(self, job_id: str) -> None:
        """Transition pending/running -> cancelled (J-2: cancel never leaves a terminal state)."""
        await self._guarded_update(
            job_id,
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ? AND status IN (?, ?)",
            (JobStatus.CANCELLED, self._now(), job_id, JobStatus.PENDING, JobStatus.RUNNING),
        )

    async def is_cancelled(self, job_id: str) -> bool:
        cursor = await self._conn().execute(
            "SELECT status FROM jobs WHERE id = ?", (job_id,)
        )
        row = await cursor.fetchone()
        return row is not None and row["status"] == JobStatus.CANCELLED
