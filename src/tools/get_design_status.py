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
get_design_status tool — poll job state.

Returns the current status, progress message, and result/error of a
start_design_architecture job.
"""

import json
import logging
from typing import Annotated, Any

from pydantic import Field

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from fastmcp.tools.base import ToolAnnotations

from src.tools.jobs import JobStatus, JobsStore

logger = logging.getLogger(__name__)

_STATUS_MESSAGES = {
    JobStatus.PENDING: "Job is queued, not yet started.",
    JobStatus.RUNNING: "Job is actively running the design pipeline.",
    JobStatus.COMPLETED: "Job completed successfully.",
    JobStatus.FAILED: "Job failed — see the error field.",
    JobStatus.CANCELLED: "Job was cancelled by a cancel_design call.",
}


class GetDesignStatusTool:
    def __init__(self) -> None:
        pass

    @tool(
        name="get_design_status",
        description=(
            "Poll the status of a submit_design_job background job. "
            "Call repeatedly (every 10-30 s) until status is 'completed', 'failed', or 'cancelled'; "
            "when completed, the result field contains the full design output. "
            "Only use this with a job_id previously returned by submit_design_job — "
            "do not use it to request a new design."
        ),
        tags={"architecture", "design"},
        annotations=ToolAnnotations(
            title="Get Design Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_status(
        self,
        job_id: Annotated[str, Field(description="Job ID returned by submit_design_job")],
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        store = await JobsStore.get_instance()
        job = await store.get_job(job_id)

        if job is None:
            raise ToolError(f"ERR_404: Job {job_id!r} not found.")

        status = job["status"]

        response: dict[str, Any] = {
            "job_id": job_id,
            "status": status,
            "message": _STATUS_MESSAGES.get(status, f"Unknown status: {status}"),
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
        }

        if status == JobStatus.COMPLETED and job.get("result"):
            try:
                response["result"] = json.loads(job["result"])
            except Exception:
                response["result"] = job["result"]

        if status == JobStatus.FAILED and job.get("error"):
            response["error"] = job["error"]

        return response


def get_design_status_tool() -> GetDesignStatusTool:
    return GetDesignStatusTool()
