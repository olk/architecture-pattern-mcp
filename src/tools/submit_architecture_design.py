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
submit_architecture_design_job tool — manual async job pattern.

Creates a pending job and returns immediately with a job_id.
The actual pipeline runs in a background asyncio task; poll get_architecture_design_status
to observe progress, and cancel_architecture_design to abort.

This tool is the Fix-4 primitive for clients with short request timeouts
(Cursor, Claude Desktop, TS-SDK). The blocking design_architecture tool
is the default for all other clients.
"""

import asyncio
import json
import logging
from typing import Annotated, Any

from pydantic import Field

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from fastmcp.tools.base import ToolAnnotations

from src.agent import ERROR_LLM_PROVIDER, LLMError, SoftwareArchitectAgent
from src.errors import ERROR_REQUIREMENTS_VALIDATION
from src.pipeline import ArchitecturePipeline
from src.text_validation import DomainName, PrintableText, ensure_printable_text
from src.tools.design import pipeline_result_to_output
from src.tools.jobs import JobStatus, JobsStore

logger = logging.getLogger(__name__)


class SubmitArchitectureDesignJobTool:
    def __init__(
        self,
        agent: SoftwareArchitectAgent,
        pipeline: ArchitecturePipeline,
    ) -> None:
        self._agent = agent
        self._pipeline = pipeline
        self._running_tasks: set[asyncio.Task[None]] = set()

    @tool(
        name="submit_architecture_design_job",
        description=(
            "Start a background design job and return a job_id immediately (returns in <100 ms; "
            "the job itself takes minutes). ONLY use this when the calling client cannot wait "
            "for a long response — e.g. Cursor, Claude Desktop, or any client with a 60-120 s "
            "request timeout. Do NOT use when the user wants the design itself or explicitly "
            "names a design tool — the blocking design_architecture tool returns the full design "
            "directly. After starting, poll get_architecture_design_status(job_id) every 10-30 s until "
            "status is 'completed', 'failed', or 'cancelled'."
        ),
        tags={"architecture", "design"},
        annotations=ToolAnnotations(
            title="Submit Design Job (async)",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def submit_job(
        self,
        requirements: Annotated[PrintableText, Field(description="Architecture requirements description (1-100000 chars, must contain visible text)")],
        domain: Annotated[DomainName, Field(description="Target architecture domain (1-200 chars, must contain visible text)")],
        override_style: Annotated[PrintableText | None, Field(description="Override the derived architecture style")] = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        if ctx is not None:
            await ctx.info(f"submit_architecture_design_job: domain={domain}, req_len={len(requirements)}")

        try:
            requirements = ensure_printable_text(requirements, field="requirements")
        except ValueError as e:
            raise ToolError(f"{ERROR_REQUIREMENTS_VALIDATION}: {e}") from e

        try:
            domain = ensure_printable_text(domain, field="domain", allow_line_breaks=False)
        except ValueError as e:
            raise ToolError(f"{ERROR_REQUIREMENTS_VALIDATION}: {e}") from e

        store = await JobsStore.get_instance()
        job_id = await store.create_job(
            requirements=requirements,
            domain=domain,
            override_style=override_style,
        )

        task = asyncio.create_task(
            self._run_job(job_id, requirements, domain, override_style, ctx),
            name=f"design-job-{job_id}",
        )
        self._running_tasks.add(task)
        task.add_done_callback(self._running_tasks.discard)

        return {
            "job_id": job_id,
            "status": JobStatus.PENDING,
            "message": (
                f"Job {job_id} created. Poll get_architecture_design_status('{job_id}') "
                "until status is 'completed', 'failed', or 'cancelled'."
            ),
        }

    async def _run_job(
        self,
        job_id: str,
        requirements: str,
        domain: str,
        override_style: str | None,
        ctx: Context | None = None,
    ) -> None:
        """Background task: run the pipeline and update job state."""
        store = await JobsStore.get_instance()

        try:
            await store.set_running(job_id)
            if ctx:
                await ctx.info(f"Job {job_id}: running design pipeline for domain='{domain}'")

            if await store.is_cancelled(job_id):
                if ctx:
                    await ctx.info(f"Job {job_id}: cancelled before pipeline started")
                return

            refined = await self._pipeline.run_design(
                requirements=requirements,
                domain=domain,
                style=override_style,
            )

            if await store.is_cancelled(job_id):
                if ctx:
                    await ctx.info(f"Job {job_id}: cancelled after pipeline, discarding result")
                return

            if ctx:
                await ctx.info(f"Job {job_id}: pipeline finished, storing result (attempts={refined.attempts})")

            output = pipeline_result_to_output(refined).model_dump()
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
            if ctx:
                await ctx.info(f"Job {job_id}: failed — {error_text}")


def submit_architecture_design_job_tool(
    agent: SoftwareArchitectAgent,
    pipeline: ArchitecturePipeline,
) -> SubmitArchitectureDesignJobTool:
    return SubmitArchitectureDesignJobTool(agent=agent, pipeline=pipeline)

