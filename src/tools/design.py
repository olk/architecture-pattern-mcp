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
DesignArchitectureTool - High-level wrapper tool delegating to full architecture pipeline.

FR-224: The system SHALL provide a DesignArchitectureTool class
API-1: /tools/design_architecture endpoint (POST)
CF-1: design_architecture function with requirements, domain, optional override_style
DF-1: Full pipeline execute flow

Error Handling:
- E-1: ERR_001 - Requirements validation fails (HTTP 400, severity: warn)
- E-9: ERR_009 - LLM provider returned error (HTTP 502, severity: error)
- E-12: ERR_012 - Malformed architecture overview at I/O boundary (HTTP 400, severity: warn)

Implementation Notes:
- Uses FastMCP @tool decorator for MCP protocol
- Pydantic v2 for input validation
- Delegates to ArchitecturePipeline.run() for complete design generation
- Factory Pattern (DP-4) for consistent tool initialization
- Adapter Pattern (DP-7) for protocol interface adaptation

Architecture:
- ADR-1: Python 3.12+ with FastMCP for MCP Protocol Implementation
- ADR-3: MCP Tool-Based API with Four Core Tools
- DP-1: Pipeline Pattern - delegate to ArchitecturePipeline.run()
- DP-4: Factory Pattern - tool creation with consistent initialization
- DP-5: Dependency Injection - receive dependencies via constructor
- DP-7: Adapter Pattern - adapts FastMCP protocol to internal implementation
"""

import asyncio
import contextlib
import logging
from typing import Annotated, Any

from pydantic import BaseModel, Field

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from fastmcp.tools.base import ToolAnnotations

from src.agent import ERROR_LLM_PROVIDER, LLMError, SoftwareArchitectAgent
from src.config import TasksConfig
from src.errors import ERROR_INVALID_ARCHITECTURE, MalformedArchitectureOverviewError
from src.pipeline import ArchitecturePipeline
from src.schemas.evaluation import PipelineResult

logger = logging.getLogger(__name__)


# Error codes for E-1, E-9, and E-12
# E-1: ERR_001 - Requirements validation fails (HTTP 400, severity: warn)
# E-9: ERR_009 - LLM provider returned error (HTTP 502, severity: error)
ERROR_REQUIREMENTS_VALIDATION = "ERR_001"


class DesignArchitectureOutput(BaseModel):
    """
    Output schema for DesignArchitectureTool.

    FR-224: Returns PipelineResult combining ArchitectureDesign and ArchitectureEvaluation
    ENT-12: ArchitectureDesign with overview, components, relationships, etc.
    ENT-13: ArchitectureEvaluation with summary, metrics, recommendations

    Attributes:
        design: Complete architecture design
        evaluation: Full architecture evaluation with metrics, risks, and recommendations
        attempts: Total generate attempts made (initial + retries)
        final_style: Final architecture style
        quality_metrics: Aggregated quality metrics from analysis
        final_quality_score: Final quality score after best attempt
    """

    design: dict = Field(
        default_factory=dict,
        description="Complete architecture design"
    )

    evaluation: dict = Field(
        default_factory=dict,
        description="Full architecture evaluation with metrics, risks, and recommendations"
    )

    attempts: int = Field(
        default=1,
        ge=1,
        description="Total generate attempts made (initial + retries)"
    )

    final_style: str = Field(
        default="",
        description="Final architecture style"
    )

    quality_metrics: dict | None = Field(
        default=None,
        description="Aggregated quality metrics from analysis"
    )

    final_quality_score: float = Field(
        default=0.0,
        description="Final quality score after best attempt"
    )


class DesignArchitectureTool:
    """
    High-level wrapper tool that delegates to the full architecture pipeline.
    
    FR-224: The system SHALL provide a DesignArchitectureTool class
    AC-224: Verify DesignArchitectureTool class exists and delegates to pipeline.run
    
    This tool provides a simplified interface for complete architecture design generation.
    It accepts requirements and domain, optionally allowing style override, and returns
    a complete architecture design with evaluation.
    
    Attributes:
        _agent: SoftwareArchitectAgent instance for LLM interactions
        _pipeline: ArchitecturePipeline instance for orchestrating the design pipeline
    
    Error Handling:
        E-1 (ERR_001): Requirements validation fails - logged with requirements context
        E-9 (ERR_009): LLM provider returned error - logged with provider context
    
    # DP-4: Factory Pattern - Tool creation with consistent initialization
    # DP-5: Dependency Injection - Constructor injection of dependencies
    # DP-7: Adapter Pattern - Adapts FastMCP protocol to internal implementation
    """

    def __init__(
        self,
        agent: SoftwareArchitectAgent,
        pipeline: ArchitecturePipeline,
        tasks_config: TasksConfig | None = None,
    ) -> None:
        """
        Initialize DesignArchitectureTool.

        DP-5: Dependency Injection - Constructor injection of all dependencies

        AC-224: Verify DesignArchitectureTool class exists, accepts SoftwareArchitectAgent

        Args:
            agent: SoftwareArchitectAgent instance for LLM interactions
            pipeline: ArchitecturePipeline instance for orchestrating design pipeline
            tasks_config: Heartbeat configuration for long-running tool defence
        """
        self._agent = agent
        self._pipeline = pipeline
        self._tasks_config = tasks_config

        logger.debug(
            "DesignArchitectureTool initialized",
            extra={
                "agent_type": type(agent).__name__,
                "pipeline_type": type(pipeline).__name__
            }
        )

    @tool(
        name="design_architecture",
        description=(
            "Default tool for creating an architecture design. Runs the full pipeline "
            "(analyze → generate → evaluate → refine, up to 3 attempts) and returns the complete design, "
            "evaluation, and quality scores in a single response. Takes 5-10 minutes; emits progress "
            "notifications every 30 s so clients stay connected. Use this whenever the user wants an "
            "architecture design, including when they explicitly request design_architecture. "
            "Do NOT use submit_design_job for ordinary design requests — that tool is only for clients "
            "with short request timeouts (Cursor, Claude Desktop) and returns only a job_id."
        ),
        tags={"architecture", "design"},
        annotations=ToolAnnotations(
            title="Design Architecture (default)",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=False,  # non-idempotent: each run creates a new LLM pipeline
            openWorldHint=False,
        ),
    )
    async def design(  # noqa: PLR0912

        self,
        requirements: Annotated[str, Field(description="Architecture requirements description", min_length=1)],
        domain: Annotated[str, Field(description="Target architecture domain", min_length=1)],
        override_style: Annotated[str | None, Field(description="Override the derived architecture style")] = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """
        Generate complete architecture design with evaluation.
        
        FR-224: DesignArchitectureTool class delegates to pipeline.run
        CF-1: design_architecture function with requirements, domain, optional override_style
        API-1: /tools/design_architecture endpoint
        
        DF-1: Flow - MCP Client -> MCPArchitectServer -> DesignArchitectureTool.design()
              -> ArchitecturePipeline.run() -> RefinedArchitecture
        
        This method:
        1. Validates inputs (E-1)
        2. Delegates to ArchitecturePipeline.run()
        3. Maps RefinedArchitecture to output dict
        4. Handles E-9 errors appropriately
        
        Args:
            requirements: Architecture requirements description
            domain: Target architecture domain
            override_style: Optional architecture style override
            ctx: FastMCP context for logging and progress reporting
            
        Returns:
            dict with complete design and evaluation
            
        Error Responses:
            E-1: Requirements validation fails (raised as ToolError)
            E-9: LLM provider returned error (raised as ToolError)
        """
        if ctx is not None:
            await ctx.info(f"design_architecture: domain={domain}, req_len={len(requirements)}, override_style={override_style}")

        try:
            if not requirements or not requirements.strip():
                raise ToolError(f"{ERROR_REQUIREMENTS_VALIDATION}: Requirements validation fails")

            if not domain or not domain.strip():
                raise ToolError(f"{ERROR_REQUIREMENTS_VALIDATION}: Requirements validation fails")

            hb = self._start_heartbeat(ctx, "design_architecture")
            try:
                refined = await self._pipeline.run_design(
                    requirements=requirements,
                    domain=domain,
                    style=override_style
                )
            finally:
                if hb is not None:
                    hb.cancel()

            output = self._map_to_output(refined)

            if ctx is not None:
                await ctx.info(
                    f"design_architecture completed: attempts={output.attempts}, "
                    f"score={output.final_quality_score}, components={len(output.design.get('components', []))}"
                )

            return output.model_dump()

        except ToolError:
            raise

        except MalformedArchitectureOverviewError as exc:
            if ctx is not None:
                await ctx.error(f"Malformed architecture overview: {exc.locator} failed validation")
            raise ToolError(
                f"{ERROR_INVALID_ARCHITECTURE}: {exc.locator} failed validation"
            ) from exc

        except Exception as e:
            error_msg = str(e)

            if self._is_llm_error(e):
                if ctx is not None:
                    await ctx.error(f"LLM provider error during design: {error_msg}")
                raise ToolError(f"{ERROR_LLM_PROVIDER}: LLM provider returned error: {error_msg}") from e

            if ctx is not None:
                await ctx.error(f"Unexpected error during design: {error_msg}")
            raise

    def _start_heartbeat(
        self, ctx: Context | None, label: str
    ) -> asyncio.Task[None] | None:
        """Start a parallel heartbeat that emits progress notifications.

        Keeps client HTTP/stdio idle timers alive during long synchronous calls.
        Cancelled automatically via task.cancel() in the outer finally block.
        Silently no-ops when ctx is None, heartbeat is disabled, or ctx.report_progress
        is not supported by the client transport.
        """
        cfg = self._tasks_config
        if ctx is None or cfg is None or not cfg.heartbeat_enabled:
            return None

        async def _hb() -> None:
            step = 0
            try:
                while True:
                    await asyncio.sleep(cfg.heartbeat_interval_seconds)
                    step += 1
                    with contextlib.suppress(Exception):
                        await ctx.report_progress(
                            progress=step,
                            message=f"{label} in progress",
                        )
            except asyncio.CancelledError:
                pass

        return asyncio.create_task(_hb())

    def _map_to_output(self, refined: PipelineResult) -> DesignArchitectureOutput:
        """
        Map PipelineResult from pipeline to DesignArchitectureOutput.

        Args:
            refined: PipelineResult from ArchitecturePipeline.run_design()

        Returns:
            DesignArchitectureOutput mapped from refined architecture
        """
        from src.tools._adapters import design_to_pydantic
        pd_design = design_to_pydantic(refined.design)
        design_dict = pd_design.model_dump()
        eval_dict = refined.evaluation.model_dump() if hasattr(refined.evaluation, "model_dump") else dict(refined.evaluation)
        qm_dict = refined.quality_metrics.model_dump() if refined.quality_metrics else None
        return DesignArchitectureOutput(
            design=design_dict,
            evaluation=eval_dict,
            attempts=refined.attempts,
            final_style=refined.final_style,
            quality_metrics=qm_dict,
            final_quality_score=refined.final_quality_score,
        )

    def _is_llm_error(self, error: Exception) -> bool:
        """
        Check if error is an LLM provider error.
        
        E-9: ERR_009 - LLM provider returned error
        
        Args:
            error: Exception to check
            
        Returns:
            True if error is LLM-related
        """
        return isinstance(error, LLMError)


# MCP Tool definition function
# ADR-3: MCP Tool-Based API - FastMCP @tool decorator
def design_architecture_tool(
    agent: SoftwareArchitectAgent,
    pipeline: ArchitecturePipeline,
    tasks_config=None,
) -> DesignArchitectureTool:
    """
    Factory function to create DesignArchitectureTool instance.

    DP-4: Factory Pattern - Consistent tool initialization with proper dependencies

    Args:
        agent: SoftwareArchitectAgent instance for LLM interactions
        pipeline: ArchitecturePipeline instance for orchestrating design pipeline
        tasks_config: TasksConfig for heartbeat settings (None = defaults applied)

    Returns:
        DesignArchitectureTool instance ready for MCP tool registration
    """
    return DesignArchitectureTool(agent=agent, pipeline=pipeline, tasks_config=tasks_config)
