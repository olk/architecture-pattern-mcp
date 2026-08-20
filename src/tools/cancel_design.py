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
cancel_design tool — Fix 4: cancel a running start_design_architecture job.

Sets the job status to 'cancelled'. The background asyncio task checks
is_cancelled() before each stage and exits promptly when it sees the flag.
"""

import logging
from typing import Annotated

from pydantic import Field

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from fastmcp.tools.base import ToolAnnotations

from src.tools.jobs import JobStatus, JobsStore

logger = logging.getLogger(__name__)


class CancelDesignTool:
    def __init__(self) -> None:
        pass

    @tool(
        name="cancel_design",
        description=(
            "Cancel a running start_design_architecture job. "
            "The background pipeline task checks the cancellation flag between stages "
            "and exits promptly. A job that has already completed cannot be cancelled."
        ),
        tags={"architecture", "design"},
        annotations=ToolAnnotations(
            title="Cancel Design Job",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def cancel(
        self,
        job_id: Annotated[str, Field(description="Job ID returned by start_design_architecture")],
        ctx: Context | None = None,
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

        await store.set_cancelled(job_id)
        logger.info("Job cancelled", extra={"job_id": job_id})

        return {
            "job_id": job_id,
            "status": JobStatus.CANCELLED,
            "cancelled": True,
            "message": f"Job {job_id} marked as cancelled. "
                      "The background task will exit at its next cancellation checkpoint.",
        }


def cancel_design_tool() -> CancelDesignTool:
    return CancelDesignTool()
