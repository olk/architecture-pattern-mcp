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
cancel_architecture_design tool — cancel a background architecture-design job
created by submit_architecture_design_job.

Signals cancellation via the CancellationToken and calls task.cancel().
The background task checks the cancellation flag after each design_loop attempt
and exits at the next checkpoint.  Cancellation is best-effort and may
take up to one LLM call to take effect.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from pydantic import Field

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp.types import ToolAnnotations

from src.pipeline import CancellationToken
from src.tools.jobs import JobStatus, JobsStore

logger = logging.getLogger(__name__)


class CancelArchitectureDesignTool:
    def __init__(
        self,
        *,
        job_tasks: dict[str, tuple[asyncio.Task[None], CancellationToken]] | None = None,
    ) -> None:
        self._job_tasks: dict[str, tuple[asyncio.Task[None], CancellationToken]] = (
            job_tasks if job_tasks is not None else {}
        )

    @tool(
        name="cancel_architecture_design",
        description=(
            "Cancel a running background design job started via submit_architecture_design_job. "
            "The background task checks the cancellation flag between pipeline stages "
            "and exits at the next stage boundary. Cancellation is best-effort and may "
            "take up to one LLM call to take effect. Only use with a job_id from "
            "submit_architecture_design_job; jobs already completed, failed, or cancelled "
            "cannot be cancelled again."
        ),
        tags={"architecture", "design"},
        annotations=ToolAnnotations(
            title="Cancel Design Job",
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    async def cancel(
        self,
        job_id: Annotated[str, Field(description="Job ID returned by submit_architecture_design_job")],
        _ctx: Context | None = None,
    ) -> dict:
        store = await JobsStore.get_instance()
        job = await store.get_job(job_id)

        if job is None:
            raise ToolError(f"ERR_404: Job {job_id!r} not found.")

        status = job["status"]
        if status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return {
                "job_id": job_id,
                "status": status,
                "cancelled": False,
                "message": f"Job is already {status}; cannot cancel.",
            }

        entry = self._job_tasks.get(job_id)
        if entry is None:
            await store.set_cancelled(job_id)
            logger.info("Job %s cancelled (no live task found — DB flag set only)", job_id)
            return {
                "job_id": job_id,
                "status": JobStatus.CANCELLED,
                "cancelled": True,
                "task_was_running": False,
                "message": (
                    f"Job {job_id} marked as cancelled. "
                    "No live asyncio.Task found (server restart? DB flag set only.)"
                ),
            }

        task, token = entry
        token.cancel()
        task.cancel()
        await store.set_cancelled(job_id)
        logger.info("Job %s cancelled", job_id)

        return {
            "job_id": job_id,
            "status": JobStatus.CANCELLED,
            "cancelled": True,
            "task_was_running": not task.done(),
            "message": (
                f"Job {job_id} cancelled. "
                "The background task will exit at its next cancellation checkpoint."
            ),
        }


def cancel_architecture_design_tool(
    *,
    job_tasks: dict[str, tuple[asyncio.Task[None], CancellationToken]] | None = None,
) -> CancelArchitectureDesignTool:
    return CancelArchitectureDesignTool(job_tasks=job_tasks)
