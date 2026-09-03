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
GenerateArchitectureTool - MCP tool for generating architecture designs based on requirements.

FR-222: The system SHALL provide a GenerateArchitectureTool class
API-3: /tools/generate_architecture endpoint (POST) for generating architecture designs
CF-3: generate_architecture function with requirements, style, domain, and selected_patterns
DF-3: Generate with pattern metadata flow

Error Handling:
- E-3: ERR_003 - Failed to generate architecture design (HTTP 500, severity: error)
- E-9: ERR_009 - LLM provider returned error (HTTP 502, severity: error)
- E-12: ERR_012 - Malformed architecture overview at I/O boundary (HTTP 400, severity: warn)

Implementation Notes:
- Uses FastMCP @tool decorator for MCP protocol
- Pydantic v2 for input validation
- Delegates to ArchitecturePipeline for LLM-based generation
- Factory Pattern (DP-4) for consistent tool initialization
- Builder Pattern (DP-9) for constructing ArchitectureDesign

Architecture:
- ADR-1: Python 3.12+ with FastMCP for MCP Protocol Implementation
- ADR-3: MCP Tool-Based API with Four Core Tools
- DP-7: Adapter Pattern for protocol interface adaptation
"""

import asyncio
import contextlib
import logging
from typing import Annotated, Any

from pydantic import BaseModel, Field

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp.types import ToolAnnotations

from src.agent import ERROR_LLM_PROVIDER, SoftwareArchitectAgent
from src.config import TasksConfig
from src.errors import ERROR_INVALID_ARCHITECTURE, ERROR_REQUIREMENTS_VALIDATION, MalformedArchitectureOverviewError
from src.pipeline import ArchitecturePipeline
from src.schemas.design import ArchitectureDesign
from src.text_validation import DomainName, PrintableText, ensure_printable_text

logger = logging.getLogger(__name__)


# Error codes for E-3, E-9, and E-12
ERROR_GENERATION_FAILED = "ERR_003"


class GenerateArchitectureOutput(BaseModel):
    """
    Output schema for GenerateArchitectureTool.
    
    ENT-12: ArchitectureDesign with overview, components, relationships,
            quality_attributes, api_contracts, shared_data_models,
            event_contracts
    
    Attributes:
        overview: Overview of the architecture design
        components: List of architecture components
        relationships: List of component relationships
        quality_attributes: Quality attribute annotations
        api_contracts: API contract definitions
        shared_data_models: Shared data model definitions
        event_contracts: Event contract definitions
    """

    # ENT-12: ArchitectureDesign overview attribute
    overview: dict[str, Any] = Field(
        default_factory=dict,
        description="Overview of the architecture design"
    )

    # ENT-12: ArchitectureDesign components attribute
    components: list[dict] = Field(
        default_factory=list,
        description="List of architecture components"
    )

    # ENT-12: ArchitectureDesign relationships attribute
    relationships: list[dict] = Field(
        default_factory=list,
        description="List of component relationships"
    )

    # ENT-12: ArchitectureDesign quality_attributes attribute
    quality_attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Quality attribute annotations"
    )

    # ENT-12: ArchitectureDesign api_contracts attribute
    api_contracts: list[dict] = Field(
        default_factory=list,
        description="API contract definitions"
    )

    # ENT-12: ArchitectureDesign shared_data_models attribute
    shared_data_models: list[dict] = Field(
        default_factory=list,
        description="Shared data model definitions"
    )

    # ENT-12: ArchitectureDesign event_contracts attribute
    event_contracts: list[dict] = Field(
        default_factory=list,
        description="Event contract definitions"
    )


class GenerateArchitectureTool:
    """
    MCP tool for generating architecture designs based on requirements.
    
    FR-222: The system SHALL provide a GenerateArchitectureTool class
    AC-222: Verify GenerateArchitectureTool class exists, accepts SoftwareArchitectAgent
    
    This tool generates architecture designs based on requirements, style, domain,
    and selected patterns. It uses SoftwareArchitectAgent for LLM interactions and
    delegates to ArchitecturePipeline for generation.
    
    Attributes:
        _agent: SoftwareArchitectAgent instance for LLM interactions
        _pipeline: ArchitecturePipeline instance for orchestrating generation
    
    Error Handling:
        E-3 (ERR_003): Failed to generate architecture design - logged with provider_message
        E-9 (ERR_009): LLM provider returned error - logged with provider context
    
    DP-4: Factory Pattern - Tool creation with consistent initialization
    DP-7: Adapter Pattern - Adapts FastMCP protocol to internal implementation
    DP-9: Builder Pattern - ArchitectureDesign construction with multiple components
    """

    def __init__(
        self,
        agent: SoftwareArchitectAgent,
        pipeline: ArchitecturePipeline,
        tasks_config: TasksConfig | None = None,
    ) -> None:
        """
        Initialize GenerateArchitectureTool.

        AC-222: Verify GenerateArchitectureTool class exists, accepts SoftwareArchitectAgent

        Args:
            agent: SoftwareArchitectAgent instance for LLM interactions
            pipeline: ArchitecturePipeline instance for orchestrating generation
            tasks_config: TasksConfig for heartbeat settings (None = defaults applied)
        """
        self._agent = agent
        self._pipeline = pipeline
        self._tasks_config = tasks_config

        logger.debug(
            "GenerateArchitectureTool initialized",
            extra={
                "agent_type": type(agent).__name__,
                "pipeline_type": type(pipeline).__name__
            }
        )

    @tool(
        name="generate_architecture",
        description="Generate an architecture design from requirements, style, domain, and selected patterns.",
        tags={"architecture", "generation"},
        annotations=ToolAnnotations(
            title="Generate Architecture",
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=False,  # non-idempotent: each run creates a new LLM generation
            open_world_hint=False,
        ),
    )
    async def generate(  # noqa: PLR0912
        self,
        requirements: Annotated[PrintableText, Field(description="Architecture requirements description (1-100000 chars, must contain visible text)")],
        style: Annotated[PrintableText, Field(description="Architecture style to use (1-100000 chars, must contain visible text)")],
        domain: Annotated[DomainName, Field(description="Target architecture domain (1-200 chars, must contain visible text)")],
        selected_patterns: Annotated[list[str], Field(description="Pattern names to incorporate in the architecture")] = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """
        Generate a new architecture design based on requirements.

        FR-222: GenerateArchitectureTool class generates architecture designs
        CF-3: generate_architecture function with requirements, style, domain, selected_patterns
        API-3: /tools/generate_architecture endpoint

        DF-3: Flow - MCP Client -> MCPArchitectServer -> GenerateArchitectureTool.generate()
              -> ArchitecturePipeline.generate() -> SoftwareArchitectAgent

        This method:
        1. Validates inputs
        2. Resolves pattern names to full pattern dicts via PatternLoader
        3. Delegates to ArchitecturePipeline.generate() with selected patterns
        4. Maps ArchitectureDesign to output dict
        5. Handles E-3 and E-9 errors appropriately

        Args:
            requirements: Architecture requirements description
            style: Architecture style to use
            domain: Target architecture domain
            selected_patterns: Pattern names to incorporate
            ctx: FastMCP context for logging and progress reporting

        Returns:
            dict with generated architecture design

        Error Responses:
            E-3: Failed to generate architecture design (raised as ToolError)
            E-9: LLM provider returned error (raised as ToolError)
        """
        if selected_patterns is None:
            selected_patterns = []

        if ctx is not None:
            await ctx.info(
                f"generate_architecture: domain={domain}, style={style}, "
                f"req_len={len(requirements)}, patterns={len(selected_patterns)}"
            )

        try:
            requirements = ensure_printable_text(requirements, field="requirements")
        except ValueError as e:
            raise ToolError(f"{ERROR_REQUIREMENTS_VALIDATION}: {e}") from e

        try:
            style = ensure_printable_text(style, field="style")
        except ValueError as e:
            raise ToolError(f"{ERROR_REQUIREMENTS_VALIDATION}: {e}") from e

        try:
            domain = ensure_printable_text(domain, field="domain", allow_line_breaks=False)
        except ValueError as e:
            raise ToolError(f"{ERROR_REQUIREMENTS_VALIDATION}: {e}") from e

        resolved = self._resolve_patterns(selected_patterns)

        try:
            hb = self._start_heartbeat(ctx, "generate_architecture")
            try:
                architecture_design = await self._pipeline.generate(
                    requirements=requirements,
                    style=style,
                    domain=domain,
                    selected_patterns=resolved,
                )
            finally:
                if hb is not None:
                    hb.cancel()

            output = self._map_to_output(architecture_design)

            if ctx is not None:
                await ctx.info(
                    f"generate_architecture completed: components={len(output.components)}, "
                    f"relationships={len(output.relationships)}"
                )

            return output.model_dump()

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
                    await ctx.error(f"LLM provider error during generation: {error_msg}")
                raise ToolError(
                    f"{ERROR_LLM_PROVIDER}: LLM provider returned error: {error_msg}"
                ) from e

            if ctx is not None:
                await ctx.error(f"Failed to generate architecture design: {error_msg}")
            raise ToolError(
                f"{ERROR_GENERATION_FAILED}: Failed to generate architecture design: {error_msg}"
            ) from e

    def _resolve_patterns(self, selected_patterns: list[str]) -> list[dict[str, Any]]:
        """Resolve pattern names to full pattern dicts expected by the pipeline."""
        resolved: list[dict[str, Any]] = []
        pattern_loader = getattr(self._pipeline, "_pattern_loader", None)
        for name in selected_patterns:
            if pattern_loader is None:
                logger.warning(
                    "generate_architecture: pattern_loader unavailable, skipping '%s'",
                    name,
                )
                continue
            p = pattern_loader.get_by_name(name)
            if p is None:
                logger.warning(
                    "generate_architecture: pattern '%s' not found in catalogue, skipped",
                    name,
                )
                continue
            resolved.append(p)
        return resolved

    def _start_heartbeat(
        self, ctx: Context | None, label: str
    ) -> asyncio.Task[None] | None:
        """Start a parallel heartbeat that emits progress notifications.

        Keeps client HTTP/stdio idle timers alive during long synchronous calls.
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
                        await ctx.report_progress(progress=step, message=f"{label} in progress")
            except asyncio.CancelledError:
                pass

        return asyncio.create_task(_hb())

    def _map_to_output(self, architecture_design: ArchitectureDesign) -> GenerateArchitectureOutput:
        """
        Map ArchitectureDesign from pipeline to GenerateArchitectureOutput.

        DP-9: Builder Pattern - ArchitectureDesign has many optional fields and nested objects

        Args:
            architecture_design: ArchitectureDesign from ArchitecturePipeline.generate()

        Returns:
            GenerateArchitectureOutput mapped from architecture_design
        """
        from src.tools._adapters import design_to_pydantic
        pd_design = design_to_pydantic(architecture_design)
        return GenerateArchitectureOutput(
            overview=pd_design.overview.model_dump(),
            components=[c.model_dump() for c in pd_design.components],
            relationships=[r.model_dump() for r in pd_design.relationships],
            quality_attributes=pd_design.quality_attributes,
            api_contracts=[a.model_dump() for a in pd_design.api_contracts],
            shared_data_models=[m.model_dump() for m in pd_design.shared_data_models],
            event_contracts=[e.model_dump() for e in pd_design.event_contracts],
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
        # Import LLMError from agent module
        from src.agent import LLMError
        return isinstance(error, LLMError)


# MCP Tool definition function
# ADR-3: MCP Tool-Based API - FastMCP @tool decorator
def generate_architecture_tool(
    agent: SoftwareArchitectAgent,
    pipeline: ArchitecturePipeline,
    tasks_config=None,
) -> GenerateArchitectureTool:
    """
    Factory function to create GenerateArchitectureTool instance.

    DP-4: Factory Pattern - Consistent tool initialization with proper dependencies

    Args:
        agent: SoftwareArchitectAgent instance for LLM interactions
        pipeline: ArchitecturePipeline instance for orchestrating generation
        tasks_config: TasksConfig for heartbeat settings (None = defaults applied)

    Returns:
        GenerateArchitectureTool instance ready for MCP tool registration
    """
    return GenerateArchitectureTool(agent=agent, pipeline=pipeline, tasks_config=tasks_config)
