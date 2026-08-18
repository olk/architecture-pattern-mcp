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
EvaluateArchitectureTool - MCP tool for evaluating architecture designs against criteria.

FR-223: The system SHALL provide an EvaluateArchitectureTool class
API-4: /tools/evaluate_architecture endpoint (POST) for evaluating architecture designs
CF-4: evaluate_architecture function with architecture, criteria, and domain parameters
DF-4: Evaluate with pattern benchmarking flow

Error Handling:
- E-4: ERR_004 - Architecture does not meet minimum requirements (HTTP 400, severity: warn)
- E-9: ERR_009 - LLM provider returned error (HTTP 502, severity: error)
- E-12: ERR_012 - Malformed architecture overview at I/O boundary (HTTP 400, severity: warn)

Implementation Notes:
- Uses FastMCP @tool decorator for MCP protocol
- Pydantic v2 for input validation
- Delegates to ArchitecturePipeline for evaluation with pattern benchmarking
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
from src.schemas.design import ArchitectureDesign
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from fastmcp.tools.base import ToolAnnotations

from src.agent import ERROR_LLM_PROVIDER, LLMError, SoftwareArchitectAgent
from src.errors import ERROR_INVALID_ARCHITECTURE, MalformedArchitectureOverviewError
from src.pipeline import ArchitectureEvaluation, ArchitecturePipeline

logger = logging.getLogger(__name__)


# Error codes for E-4, E-9, and E-12
ERROR_MIN_REQUIREMENTS = "ERR_004"


class EvaluateArchitectureOutput(BaseModel):
    """
    Output schema for EvaluateArchitectureTool.
    
    ENT-13: ArchitectureEvaluation with summary, metrics, recommendations
    
    Attributes:
        summary: Evaluation summary text
        metrics: Quality metrics dictionary (e.g., maintainability, scalability, reliability, security, performance)
        recommendations: List of architecture recommendations
    """

    # ENT-13: ArchitectureEvaluation summary attribute
    summary: str = Field(
        default="",
        description="Evaluation summary text"
    )

    # ENT-13: ArchitectureEvaluation metrics attribute
    metrics: dict[str, float] = Field(
        default_factory=dict,
        description="Quality metrics (maintainability, scalability, reliability, security, performance)"
    )

    # ENT-13: ArchitectureEvaluation recommendations attribute
    recommendations: list[str] = Field(
        default_factory=list,
        description="Architecture recommendations"
    )


class EvaluateArchitectureTool:
    """
    MCP tool for evaluating architecture designs against specified criteria and domain.
    
    FR-223: The system SHALL provide an EvaluateArchitectureTool class
    AC-223: Verify EvaluateArchitectureTool class exists, accepts SoftwareArchitectAgent
    
    This tool evaluates architecture designs using SoftwareArchitectAgent for LLM-based
    evaluation and delegates to ArchitecturePipeline for pattern benchmarking.
    
    Attributes:
        _agent: SoftwareArchitectAgent instance for LLM interactions
        _pipeline: ArchitecturePipeline instance for orchestrating evaluation
    
    Error Handling:
        E-4 (ERR_004): Architecture does not meet minimum requirements - logged with architecture context
        E-9 (ERR_009): LLM provider returned error - logged with provider context
    
    DP-4: Factory Pattern - Tool creation with consistent initialization
    DP-7: Adapter Pattern - Adapts FastMCP protocol to internal implementation
    """

    def __init__(
        self,
        agent: SoftwareArchitectAgent,
        pipeline: ArchitecturePipeline
    ) -> None:
        """
        Initialize EvaluateArchitectureTool.
        
        AC-223: Verify EvaluateArchitectureTool class exists, accepts SoftwareArchitectAgent
        
        Args:
            agent: SoftwareArchitectAgent instance for LLM interactions
            pipeline: ArchitecturePipeline instance for orchestrating evaluation
        """
        self._agent = agent
        self._pipeline = pipeline

        logger.debug(
            "EvaluateArchitectureTool initialized",
            extra={
                "agent_type": type(agent).__name__,
                "pipeline_type": type(pipeline).__name__
            }
        )

    @tool(
        name="evaluate_architecture",
        description="Evaluate an architecture design against specified criteria and domain using pattern benchmarking.",
        tags={"architecture", "evaluation"},
        annotations=ToolAnnotations(
            title="Evaluate Architecture",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def evaluate(
        self,
        architecture: Annotated[dict[str, Any], Field(description="Architecture design as dictionary")],
        criteria: Annotated[str, Field(description="Evaluation criteria description", min_length=1)],
        domain: Annotated[str, Field(description="Target architecture domain", min_length=1)],
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """
        Evaluate an architecture design against specified criteria and domain.
        
        FR-223: EvaluateArchitectureTool class evaluates architecture designs
        CF-4: evaluate_architecture function with architecture, criteria, domain
        API-4: /tools/evaluate_architecture endpoint
        
        DF-4: Flow - MCP Client -> MCPArchitectServer -> EvaluateArchitectureTool.evaluate()
              -> ArchitecturePipeline.evaluate() -> pattern benchmarking
        
        This method:
        1. Converts architecture dict to ArchitectureDesign
        2. Checks minimum requirements (E-4)
        3. Delegates to ArchitecturePipeline.evaluate() for pattern benchmarking
        4. Maps ArchitectureEvaluation to output dict
        5. Handles E-4 and E-9 errors appropriately
        
        Args:
            architecture: Architecture design as dictionary
            criteria: Evaluation criteria description
            domain: Target architecture domain
            ctx: FastMCP context for logging and progress reporting
            
        Returns:
            dict with evaluation results
            
        Error Responses:
            E-4: Architecture does not meet minimum requirements (raised as ToolError)
            E-9: LLM provider returned error (raised as ToolError)
        """
        if ctx is not None:
            await ctx.info(
                f"evaluate_architecture: domain={domain}, criteria_len={len(criteria)}, "
                f"arch_keys={list(architecture.keys()) if architecture else []}"
            )

        try:
            architecture_design = self._convert_to_architecture_design(architecture)

            if not self._check_minimum_requirements(architecture_design):
                if ctx is not None:
                    await ctx.error("Architecture does not meet minimum requirements")
                raise ToolError(
                    f"{ERROR_MIN_REQUIREMENTS}: Architecture does not meet minimum requirements"
                )

            evaluation = await self._pipeline.evaluate(
                architecture=architecture_design,
                criteria=criteria,
                domain=domain,
            )

            output = self._map_to_output(evaluation)

            if ctx is not None:
                await ctx.info(
                    f"evaluate_architecture completed: summary_len={len(output.summary)}, "
                    f"metrics={len(output.metrics)}"
                )

            return output.model_dump()

        except LLMError as e:
            if ctx is not None:
                await ctx.error(f"LLM provider error during evaluation: {e.provider_message}")
            raise ToolError(
                f"{ERROR_LLM_PROVIDER}: LLM provider returned error: {e.provider_message}"
            ) from e

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
            if ctx is not None:
                await ctx.error(f"Unexpected error during evaluation: {error_msg}")
            raise ToolError(f"{ERROR_LLM_PROVIDER}: Evaluation failed: {error_msg}") from e

    def _convert_to_architecture_design(self, architecture: dict[str, Any]) -> ArchitectureDesign:
        """
        Convert architecture dictionary to ArchitectureDesign instance.

        Args:
            architecture: Architecture design as dictionary

        Returns:
            ArchitectureDesign instance
        """
        from src.tools._adapters import design_from_dict
        return design_from_dict(architecture)

    def _check_minimum_requirements(self, architecture: ArchitectureDesign) -> bool:
        """
        Check if architecture meets minimum requirements.
        
        E-4: ERR_004 - Architecture does not meet minimum requirements
        
        Minimum requirements:
        - Must have at least one component
        - Must have an overview
        
        Args:
            architecture: ArchitectureDesign to check
            
        Returns:
            True if architecture meets minimum requirements
        """
        if not architecture.components:
            return False

        if not architecture.overview:
            return False

        return True

    def _map_to_output(self, evaluation: ArchitectureEvaluation) -> EvaluateArchitectureOutput:
        """
        Map ArchitectureEvaluation from pipeline to EvaluateArchitectureOutput.
        
        Args:
            evaluation: ArchitectureEvaluation from ArchitecturePipeline.evaluate()
            
        Returns:
            EvaluateArchitectureOutput mapped from evaluation
        """
        metrics_dict = {m.name: m.score / 10.0 for m in evaluation.metrics}
        recommendations_list = []
        for recs in evaluation.recommendations.values():
            recommendations_list.extend(recs)

        return EvaluateArchitectureOutput(
            summary=f"Overall score: {evaluation.summary.overall_score:.1f}/100",
            metrics=metrics_dict,
            recommendations=recommendations_list
        )


# MCP Tool definition function
# ADR-3: MCP Tool-Based API - FastMCP @tool decorator
def evaluate_architecture_tool(
    agent: SoftwareArchitectAgent,
    pipeline: ArchitecturePipeline
) -> EvaluateArchitectureTool:
    """
    Factory function to create EvaluateArchitectureTool instance.
    
    DP-4: Factory Pattern - Consistent tool initialization with proper dependencies
    
    Args:
        agent: SoftwareArchitectAgent instance for LLM interactions
        pipeline: ArchitecturePipeline instance for orchestrating evaluation
        
    Returns:
        EvaluateArchitectureTool instance ready for MCP tool registration
    """
    return EvaluateArchitectureTool(agent=agent, pipeline=pipeline)
