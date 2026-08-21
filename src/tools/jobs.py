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
Async SQLite job store for the manual start/get_status/cancel tool trio.

provides durable job state so that long-running design_architecture calls
can be polled via get_design_status and cancelled via cancel_design.

The store is a singleton — a single aiosqlite connection is shared across all calls.
"""

import aiosqlite
import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone, UTC
from typing import Any

logger = logging.getLogger(__name__)

_DB_PATH = os.environ.get(
    "ARCHITECTURE_PATTERN_JOBS_DB",
    os.path.expanduser("~/.config/architecture-pattern-mcp/jobs.db"),
)


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


_TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


class JobsStore:
    """Singleton async SQLite store for design_architecture job state."""

    _instance: "JobsStore | None" = None
    _lock: asyncio.Lock = asyncio.Lock()
    _db: aiosqlite.Connection | None = None

    def __new__(cls) -> "JobsStore":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    async def get_instance(cls) -> "JobsStore":
        """Get or create the singleton instance, initialising the DB on first call."""
        if cls._instance is None or cls._db is None:
            async with cls._lock:
                if cls._instance is None or cls._db is None:
                    cls._instance = super().__new__(cls)
                    await cls._instance._init()
        return cls._instance

    @classmethod
    async def reset_for_test(cls) -> None:
        """Test helper: close current connection, delete the DB file, and drop singleton.

        Use this with a temporarily overridden ``ARCHITECTURE_PATTERN_JOBS_DB``
        env-var to point at a per-test temporary directory.
        """
        if cls._instance is not None and cls._db is not None:
            await cls._db.close()
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
        await self._db.execute(
            "INSERT INTO jobs (id, status, requirements, domain, override_style, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, JobStatus.PENDING, requirements, domain, override_style, now, now),
        )
        await self._db.commit()
        logger.debug("Job created", extra={"job_id": job_id})
        return job_id

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        """Return job dict or None if not found."""
        cursor = await self._db.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def list_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent jobs ordered by created_at desc."""
        cursor = await self._db.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def set_running(self, job_id: str) -> None:
        now = self._now()
        await self._db.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (JobStatus.RUNNING, now, job_id),
        )
        await self._db.commit()

    async def set_completed(self, job_id: str, result: str) -> None:
        now = self._now()
        await self._db.execute(
            "UPDATE jobs SET status = ?, result = ?, updated_at = ? WHERE id = ?",
            (JobStatus.COMPLETED, result, now, job_id),
        )
        await self._db.commit()

    async def set_failed(self, job_id: str, error: str) -> None:
        now = self._now()
        await self._db.execute(
            "UPDATE jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (JobStatus.FAILED, error, now, job_id),
        )
        await self._db.commit()

    async def set_cancelled(self, job_id: str) -> None:
        now = self._now()
        await self._db.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (JobStatus.CANCELLED, now, job_id),
        )
        await self._db.commit()

    async def is_cancelled(self, job_id: str) -> bool:
        cursor = await self._db.execute(
            "SELECT status FROM jobs WHERE id = ?", (job_id,)
        )
        row = await cursor.fetchone()
        return row is not None and row["status"] == JobStatus.CANCELLED
