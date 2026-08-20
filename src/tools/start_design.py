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
start_design_architecture tool — Fix 4: manual async job pattern.

Creates a pending job and returns immediately with a job_id.
The actual pipeline runs in a background asyncio task; poll get_design_status
to observe progress, and cancel_design to abort.

This tool is the only Fix-4 primitive that requires no special client support —
every MCP client can call it and read the job_id from the response.
"""

import asyncio
import logging
from typing import Annotated, Any

from pydantic import Field

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from fastmcp.tools.base import ToolAnnotations

from src.agent import ERROR_LLM_PROVIDER, LLMError, SoftwareArchitectAgent
from src.pipeline import ArchitecturePipeline
from src.tools.jobs import JobStatus, JobsStore

logger = logging.getLogger(__name__)


class StartDesignArchitectureTool:
    def __init__(
        self,
        agent: SoftwareArchitectAgent,
        pipeline: ArchitecturePipeline,
    ) -> None:
        self._agent = agent
        self._pipeline = pipeline
        self._running_tasks: set[asyncio.Task[None]] = set()

    @tool(
        name="start_design_architecture",
        description=(
            "Start a background design_architecture job and return a job_id immediately. "
            "Poll get_design_status(job_id) until status is 'completed', 'failed', or 'cancelled'. "
            "Long-running (minutes); returns in <100 ms regardless of job duration."
        ),
        tags={"architecture", "design"},
        annotations=ToolAnnotations(
            title="Start Design Architecture (async)",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def start_design(
        self,
        requirements: Annotated[str, Field(description="Architecture requirements description", min_length=1)],
        domain: Annotated[str, Field(description="Target architecture domain", min_length=1)],
        override_style: Annotated[str | None, Field(description="Override the derived architecture style")] = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        if ctx is not None:
            await ctx.info(f"start_design_architecture: domain={domain}, req_len={len(requirements)}")

        if not requirements or not requirements.strip():
            raise ToolError("ERR_001: Requirements validation fails")
        if not domain or not domain.strip():
            raise ToolError("ERR_001: Requirements validation fails")

        store = await JobsStore.get_instance()
        job_id = await store.create_job(
            requirements=requirements,
            domain=domain,
            override_style=override_style,
        )

        task = asyncio.create_task(
            self._run_job(job_id, requirements, domain, override_style),
            name=f"design-job-{job_id}",
        )
        self._running_tasks.add(task)
        task.add_done_callback(self._running_tasks.discard)

        return {
            "job_id": job_id,
            "status": JobStatus.PENDING,
            "message": (
                f"Job {job_id} created. Poll get_design_status('{job_id}') "
                "until status is 'completed', 'failed', or 'cancelled'."
            ),
        }

    async def _run_job(
        self,
        job_id: str,
        requirements: str,
        domain: str,
        override_style: str | None,
    ) -> None:
        """Background task: run the pipeline and update job state."""
        store = await JobsStore.get_instance()

        try:
            await store.set_running(job_id)

            if await store.is_cancelled(job_id):
                return

            from src.tools._adapters import design_to_pydantic

            refined = await self._pipeline.run_design(
                requirements=requirements,
                domain=domain,
                style=override_style,
            )

            if await store.is_cancelled(job_id):
                return

            output = {
                "design": design_to_pydantic(refined.design).model_dump(),
                "evaluation": (
                    refined.evaluation.model_dump()
                    if hasattr(refined.evaluation, "model_dump")
                    else dict(refined.evaluation)
                ),
                "attempts": refined.attempts,
                "final_style": refined.final_style,
                "quality_metrics": (
                    refined.quality_metrics.model_dump()
                    if refined.quality_metrics else None
                ),
                "final_quality_score": refined.final_quality_score,
            }

            import json
            await store.set_completed(job_id, json.dumps(output))
            logger.info("Job completed", extra={"job_id": job_id})

        except Exception as e:
            error_text = str(e)
            if isinstance(e, LLMError):
                error_text = f"{ERROR_LLM_PROVIDER}: {error_text}"
            elif not isinstance(e, ToolError):
                error_text = f"ERR_999: {error_text}"
            await store.set_failed(job_id, error_text)
            logger.error("Job failed", extra={"job_id": job_id, "error": error_text})


def start_design_architecture_tool(
    agent: SoftwareArchitectAgent,
    pipeline: ArchitecturePipeline,
) -> StartDesignArchitectureTool:
    return StartDesignArchitectureTool(agent=agent, pipeline=pipeline)
