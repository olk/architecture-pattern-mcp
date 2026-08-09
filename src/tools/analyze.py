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
AnalyzeArchitectureTool - MCP tool for analyzing requirements and deriving architecture recommendations.

FR-221: The system SHALL provide an AnalyzeArchitectureTool class
API-2: /tools/analyze_architecture endpoint (POST) for analyzing requirements
CF-2: analyze_architecture function with requirements and domain parameters
DF-2: Analyze with PatternLoader filtering flow

Error Handling:
- E-2: ERR_002 - No patterns found for domain (HTTP 404, severity: info)
- E-9: ERR_009 - LLM provider returned error (HTTP 502, severity: error)

Implementation Notes:
- Uses FastMCP @tool decorator for MCP protocol
- Pydantic v2 for input validation
- Delegates to ArchitecturePipeline for pattern selection and LLM analysis
- Factory Pattern (DP-4) for consistent tool initialization

Architecture:
- ADR-1: Python 3.12+ with FastMCP for MCP Protocol Implementation
- ADR-3: MCP Tool-Based API with Four Core Tools
- DP-7: Adapter Pattern for protocol interface adaptation
"""

import logging
from typing import Annotated, Any

from pydantic import BaseModel, Field

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from fastmcp.tools.base import ToolAnnotations

from src.agent import ERROR_LLM_PROVIDER, SoftwareArchitectAgent
from src.patterns.retriever import DEFAULT_FALLBACK_PATTERN_NAME
from src.pipeline import AnalysisResult, ArchitecturePipeline

logger = logging.getLogger(__name__)


class AnalyzeArchitectureOutput(BaseModel):
    """
    Output schema for AnalyzeArchitectureTool.

    ENT-4: AnalysisResult with strengths, weaknesses, recommendations,
           quality_metrics, recommended_style, selected_patterns

    Attributes:
        strengths: List of identified architecture strengths
        weaknesses: List of identified architecture weaknesses
        recommendations: List of architecture recommendations
        recommended_style: Recommended architecture style
        selected_patterns: List of selected architecture patterns
        quality_metrics: Quality assessment metrics
    """

    strengths: list[str] = Field(
        default_factory=list,
        description="Identified architecture strengths"
    )

    weaknesses: list[str] = Field(
        default_factory=list,
        description="Identified architecture weaknesses"
    )

    recommendations: list[str] = Field(
        default_factory=list,
        description="Architecture recommendations"
    )

    recommended_style: str = Field(
        default="",
        description="Recommended architecture style"
    )

    selected_patterns: list[dict] = Field(
        default_factory=list,
        description="Selected architecture patterns"
    )

    quality_metrics: dict | None = Field(
        default=None,
        description="Quality assessment metrics"
    )


class AnalyzeArchitectureTool:
    """
    MCP tool for analyzing requirements and deriving architecture recommendations.
    
    FR-221: The system SHALL provide an AnalyzeArchitectureTool class
    AC-221: Verify AnalyzeArchitectureTool class exists, accepts SoftwareArchitectAgent
    
    This tool analyzes requirements and derives architecture recommendations with
    pattern filtering. It uses SoftwareArchitectAgent for LLM interactions and
    delegates to ArchitecturePipeline for pattern selection.
    
    Attributes:
        _agent: SoftwareArchitectAgent instance for LLM interactions
        _pipeline: ArchitecturePipeline instance for orchestrating analysis
    
    Error Handling:
        E-2 (ERR_002): No patterns found for domain - logged with domain context
        E-9 (ERR_009): LLM provider returned error - logged with provider context
    
    # DP-4: Factory Pattern - Tool creation with consistent initialization
    # DP-7: Adapter Pattern - Adapts FastMCP protocol to internal implementation
    """

    def __init__(
        self,
        agent: SoftwareArchitectAgent,
        pipeline: ArchitecturePipeline
    ) -> None:
        """
        Initialize AnalyzeArchitectureTool.
        
        AC-221: Verify AnalyzeArchitectureTool class exists, accepts SoftwareArchitectAgent
        
        Args:
            agent: SoftwareArchitectAgent instance for LLM interactions
            pipeline: ArchitecturePipeline instance for orchestrating analysis
        """
        self._agent = agent
        self._pipeline = pipeline

        logger.debug(
            "AnalyzeArchitectureTool initialized",
            extra={
                "agent_type": type(agent).__name__,
                "pipeline_type": type(pipeline).__name__
            }
        )

    @tool(
        name="analyze_architecture",
        description="Analyze requirements and derive architecture recommendations using pattern matching and domain similarity.",
        tags={"architecture", "analysis"},
        annotations=ToolAnnotations(
            title="Analyze Architecture",
            readOnlyHint=True,
        ),
    )
    async def analyze(
        self,
        requirements: Annotated[str, Field(description="Architecture requirements description", min_length=1)],
        domain: Annotated[str, Field(description="Target architecture domain", min_length=1)],
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """
        Analyze requirements and derive architecture recommendations.
        
        FR-221: AnalyzeArchitectureTool class analyzes requirements
        CF-2: analyze_architecture function with requirements and domain
        API-2: /tools/analyze_architecture endpoint
        
        DF-2: Flow - MCP Client -> MCPArchitectServer -> AnalyzeArchitectureTool.analyze()
              -> ArchitecturePipeline.analyze() -> PatternLoader.filter_by_domain()
        
        This method:
        1. Validates inputs
        2. Delegates to ArchitecturePipeline.analyze()
        3. Maps AnalysisResult to output dict
        4. Handles E-2 and E-9 errors appropriately
        
        Args:
            requirements: Architecture requirements description
            domain: Target architecture domain
            ctx: FastMCP context for logging and progress reporting
            
        Returns:
            dict with analysis results
            
        Error Responses:
            E-2: No patterns found for domain (returns empty result)
            E-9: LLM provider returned error (raised as ToolError)
        """
        if ctx is not None:
            await ctx.info(f"analyze_architecture: domain={domain}, req_len={len(requirements)}")

        try:
            analysis_result = await self._pipeline.analyze(
                requirements=requirements,
                domain=domain
            )

            output = self._map_to_output(analysis_result)

            if ctx is not None:
                await ctx.info(
                    f"analyze_architecture completed: strengths={len(output.strengths)}, "
                    f"patterns={len(output.selected_patterns)}"
                )

            return output.model_dump()

        except Exception as e:
            error_msg = str(e)

            if self._is_llm_error(e):
                if ctx is not None:
                    await ctx.error(f"LLM provider error during analysis: {error_msg}")
                raise ToolError(f"{ERROR_LLM_PROVIDER}: LLM provider returned error: {error_msg}") from e

            if self._is_no_patterns_error(e):
                if ctx is not None:
                    await ctx.info(f"No patterns found for domain: {domain}")
                return AnalyzeArchitectureOutput(
                    strengths=[],
                    weaknesses=["No patterns found for specified domain"],
                    recommendations=[f"Consider alternative domain or expand pattern database for: {domain}"],
                    recommended_style=DEFAULT_FALLBACK_PATTERN_NAME,
                    selected_patterns=[],
                    quality_metrics=None
                ).model_dump()

            if ctx is not None:
                await ctx.error(f"Unexpected error during analysis: {error_msg}")
            raise

    def _map_to_output(self, analysis_result: AnalysisResult) -> AnalyzeArchitectureOutput:
        """
        Map AnalysisResult from pipeline to AnalyzeArchitectureOutput.

        Delegates to ``analysis_to_pydantic`` which validates into ``ScoredPattern``
        so that ``analysis_score`` and ``fusion_score`` survive the boundary.
        """
        from src.tools._adapters import analysis_to_pydantic
        pd_result = analysis_to_pydantic(analysis_result)
        return AnalyzeArchitectureOutput(
            strengths=pd_result.strengths,
            weaknesses=pd_result.weaknesses,
            recommendations=pd_result.recommendations,
            recommended_style=pd_result.recommended_style,
            selected_patterns=[p.model_dump() for p in pd_result.selected_patterns],
            quality_metrics=pd_result.quality_metrics.model_dump() if pd_result.quality_metrics else None,
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

    def _is_no_patterns_error(self, error: Exception) -> bool:
        """
        Check if error indicates no patterns found for domain.
        
        E-2: ERR_002 - No patterns found for domain
        
        This checks for common error messages indicating no patterns found.
        
        Args:
            error: Exception to check
            
        Returns:
            True if error indicates no patterns found
        """
        error_msg = str(error).lower()
        no_patterns_indicators = [
            "no patterns",
            "no pattern",
            "pattern not found",
            "empty result",
            "no matching"
        ]
        return any(indicator in error_msg for indicator in no_patterns_indicators)


# MCP Tool definition function
# ADR-3: MCP Tool-Based API - FastMCP @tool decorator
def analyze_architecture_tool(
    agent: SoftwareArchitectAgent,
    pipeline: ArchitecturePipeline
) -> AnalyzeArchitectureTool:
    """
    Factory function to create AnalyzeArchitectureTool instance.
    
    DP-4: Factory Pattern - Consistent tool initialization with proper dependencies
    
    Args:
        agent: SoftwareArchitectAgent instance for LLM interactions
        pipeline: ArchitecturePipeline instance for orchestrating analysis
        
    Returns:
        AnalyzeArchitectureTool instance ready for MCP tool registration
    """
    return AnalyzeArchitectureTool(agent=agent, pipeline=pipeline)
