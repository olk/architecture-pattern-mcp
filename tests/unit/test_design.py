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
Unit tests for DesignArchitectureTool.

AC-224: Verify DesignArchitectureTool class exists and delegates to pipeline.run
Test Case IDs: UT-14, IT-1

Validates:
- FR-224: DesignArchitectureTool class exists
- E-1: Requirements validation fails handling (ERR_001)
- E-9: LLM provider returned error handling (ERR_009)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent import SoftwareArchitectAgent

from src.pipeline import ArchitecturePipeline
from src.schemas.contracts import ApiContract, ApiEndpoint, EventContract

from src.schemas.design import ArchitectureDesign, ArchitectureOverview
from src.schemas.components import Component, Relationship
from src.schemas.enums import ArchitectureStyle, PatternCategory
from src.schemas.evaluation import ArchitectureEvaluation, EvaluationSummary, MetricResult, PipelineResult

# Import the tool class and related components
from src.tools.design import (
    ERROR_LLM_PROVIDER,
    DesignArchitectureOutput,
    DesignArchitectureTool,
    design_architecture_tool,
)

from src.errors import ERROR_REQUIREMENTS_VALIDATION

# Test fixtures

@pytest.fixture
def mock_agent():
    """Create a mock SoftwareArchitectAgent."""
    agent = MagicMock(spec=SoftwareArchitectAgent)
    agent._config = MagicMock()
    agent._config.llm_provider = "openai"
    agent._config.llm_model = "gpt-4"
    return agent


@pytest.fixture
def mock_pipeline():
    """Create a mock ArchitecturePipeline."""
    pipeline = MagicMock(spec=ArchitecturePipeline)
    pipeline.run_design = AsyncMock()
    return pipeline


@pytest.fixture
def sample_refined_architecture():
    """Create a sample RefinedArchitecture for testing."""
    design = ArchitectureDesign(
        overview=ArchitectureOverview(
            style=ArchitectureStyle.ACTOR_BASED,
            category=PatternCategory.STRUCTURAL,
            principles=["principle1", "principle2"],
        ),
        components=[
            Component(id="api-gateway", name="API Gateway", type="gateway", description="API Gateway component", responsibilities=["routing"]),
            Component(id="user-service", name="User Service", type="service", description="User Service component", responsibilities=["user management"]),
            Component(id="order-service", name="Order Service", type="service", description="Order Service component", responsibilities=["order management"]),
        ],
        relationships=[
            Relationship(source="api-gateway", target="user-service", type="http", description=""),
            Relationship(source="api-gateway", target="order-service", type="http", description=""),
        ],
        quality_attributes={"scalability": "high", "maintainability": "high"},
        api_contracts=[
            ApiContract(
                component_id="user-service",
                base_path="/api/users",
                endpoints=[ApiEndpoint(method="GET", path="/users", summary="", request_schema=None, response_schema=None, auth_required=True, tags=[])],
                description="User API",
            ),
        ],
        shared_data_models=[],
        event_contracts=[
            EventContract(
                event_name="UserCreated",
                payload_schema={"user_id": "string"},
                published_by="user-service",
                consumed_by=[],
                description="",
            ),
        ],
    )

    evaluation = ArchitectureEvaluation(
        summary=EvaluationSummary(
            overall_score=85.5,
            strengths=["Good architecture design"],
            weaknesses=["Consider additional monitoring"],
            critical_findings=["None"]
        ),
        metrics=[
            MetricResult(name="overall_quality", score=85.5, description="Overall quality", findings=[], recommendations=[])
        ],
        recommendations={}
    )

    return PipelineResult(
        design=design,
        evaluation=evaluation,
        attempts=2,
        final_style="actor-based",
        final_quality_score=85.5
    )


@pytest.fixture
def sample_architecture_design():
    """Create a sample ArchitectureDesign for testing."""
    return ArchitectureDesign(
        overview=ArchitectureOverview(
            style=ArchitectureStyle.ACTOR_BASED,
            category=PatternCategory.STRUCTURAL,
            principles=["principle1"],
        ),
        components=[
            Component(id="api-gateway", name="API Gateway", type="gateway", description="API Gateway component", responsibilities=["routing"]),
            Component(id="user-service", name="User Service", type="service", description="User Service component", responsibilities=["user management"]),
        ],
        relationships=[
            Relationship(source="api-gateway", target="user-service", type="http", description=""),
        ],
        quality_attributes={"scalability": "high"},
        api_contracts=[],
        shared_data_models=[],
        event_contracts=[],
    )


# AC-224: Verify DesignArchitectureTool class exists, accepts SoftwareArchitectAgent

class TestDesignArchitectureToolInit:
    """Test suite for DesignArchitectureTool initialization."""

    def test_tool_initialization_with_agent_and_pipeline(self, mock_agent, mock_pipeline):
        """
        AC-224: Verify DesignArchitectureTool class exists, accepts SoftwareArchitectAgent
        
        given_precondition: SoftwareArchitectAgent initialized
        when_action: System creates DesignArchitectureTool instance
        then_outcome: DesignArchitectureTool class exists with proper initialization
        """
        # When: Creating DesignArchitectureTool with agent and pipeline
        tool = DesignArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # Then: Tool should be initialized properly
        assert tool is not None
        assert isinstance(tool, DesignArchitectureTool)
        assert tool._agent is mock_agent
        assert tool._pipeline is mock_pipeline

    def test_factory_function_creates_tool(self, mock_agent, mock_pipeline):
        """
        DP-4: Factory Pattern - Consistent tool initialization
        
        given_precondition: agent and pipeline available
        when_action: Factory function is called
        then_outcome: Properly initialized tool is returned
        """
        # When: Using factory function to create tool
        tool = design_architecture_tool(agent=mock_agent, pipeline=mock_pipeline)

        # Then: Should return properly initialized tool
        assert tool is not None
        assert isinstance(tool, DesignArchitectureTool)
        assert tool._agent is mock_agent
        assert tool._pipeline is mock_pipeline


class TestDesignArchitectureOutput:
    """Test suite for DesignArchitectureOutput model."""

    def test_output_model_with_all_fields(self, sample_refined_architecture):
        """
        FR-224: Returns PipelineResult combining ArchitectureDesign and ArchitectureEvaluation
        ENT-12: ArchitectureDesign with overview, components, relationships, patterns, etc.
        
        given_precondition: RefinedArchitecture data available
        when_action: Creating output model
        then_outcome: All fields are properly set
        """
        # When: Creating output with all fields
        output = DesignArchitectureOutput(
            design={
                "overview": {"title": "Test Architecture"},
                "components": [{"id": "test", "name": "Test Component"}],
                "relationships": [],
                "patterns": [],
                "quality_attributes": {},
                "api_contracts": [],
                "shared_data_models": [],
                "event_contracts": [],
            },
            attempts=2,
            final_quality_score=85.5
        )

        # Then: All fields should be set correctly
        assert "overview" in output.design
        assert output.attempts == 2
        assert output.final_quality_score == 85.5

    def test_output_model_default_values(self):
        """
        given_precondition: None
        when_action: Creating output with defaults
        then_outcome: Default values are set correctly
        """
        # When: Creating output with minimal data
        output = DesignArchitectureOutput()

        # Then: Default values should be set
        assert output.design == {}
        assert output.attempts == 1
        assert output.final_quality_score == 0.0


class TestDesignArchitectureToolDesign:
    """Test suite for DesignArchitectureTool.design() method."""

    @pytest.mark.asyncio
    async def test_design_returns_output_successfully(
        self,
        mock_agent,
        mock_pipeline,
        sample_refined_architecture
    ):
        """
        FR-224: DesignArchitectureTool class delegates to pipeline.run
        
        given_precondition: Pipeline configured with patterns
        when_action: design() is called with requirements and domain
        then_outcome: dict is returned with complete design
        """
        mock_pipeline.run_design.return_value = sample_refined_architecture

        tool = DesignArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        output = await tool.design(
            requirements="System needs high scalability",
            domain="microservices"
        )

        assert isinstance(output, dict)
        assert "design" in output
        assert output["attempts"] == 2
        assert output["final_quality_score"] == 85.5

    @pytest.mark.asyncio
    async def test_design_with_override_style(
        self,
        mock_agent,
        mock_pipeline,
        sample_refined_architecture
    ):
        """
        CF-1: OPARAM-1 (override_style) parameter
        
        given_precondition: Pipeline configured
        when_action: design() is called with override_style
        then_outcome: Pipeline.run is called with override_style as style
        """
        mock_pipeline.run_design.return_value = sample_refined_architecture

        tool = DesignArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        await tool.design(
            requirements="System needs high scalability",
            domain="microservices",
            override_style="event-driven"
        )

        mock_pipeline.run_design.assert_called_once_with(
            requirements="System needs high scalability",
            domain="microservices",
            style="event-driven"
        )

    @pytest.mark.asyncio
    async def test_design_delegates_to_pipeline(
        self,
        mock_agent,
        mock_pipeline,
        sample_refined_architecture
    ):
        """
        DF-1: Flow - MCP Client -> DesignArchitectureTool.design()
              -> ArchitecturePipeline.run()
        
        given_precondition: Pipeline configured
        when_action: design() is called
        then_outcome: Pipeline.run is called with correct parameters
        """
        mock_pipeline.run_design.return_value = sample_refined_architecture

        tool = DesignArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        await tool.design(
            requirements="System needs high scalability",
            domain="microservices"
        )

        mock_pipeline.run_design.assert_called_once_with(
            requirements="System needs high scalability",
            domain="microservices",
            style=None
        )

    @pytest.mark.asyncio
    async def test_design_maps_design_correctly(
        self,
        mock_agent,
        mock_pipeline,
        sample_refined_architecture
    ):
        """
        ENT-12: ArchitectureDesign - Complete architecture design
        
        given_precondition: RefinedArchitecture with ArchitectureDesign
        when_action: design() is called
        then_outcome: ArchitectureDesign is properly mapped to dict
        """
        mock_pipeline.run_design.return_value = sample_refined_architecture

        tool = DesignArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        output = await tool.design(
            requirements="System needs high scalability",
            domain="microservices"
        )

        design = output["design"]
        assert "overview" in design
        assert "components" in design
        assert "relationships" in design
        assert len(design["components"]) == 3

    @pytest.mark.asyncio
    async def test_design_preserves_populated_contracts(
        self,
        mock_agent,
        mock_pipeline,
        sample_refined_architecture
    ):
        """
        api_contracts, shared_data_models, and event_contracts from PipelineResult
        are preserved verbatim in the tool's output dict.
        """
        mock_pipeline.run_design.return_value = sample_refined_architecture

        tool = DesignArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        output = await tool.design(
            requirements="System needs high scalability",
            domain="microservices"
        )

        design = output["design"]
        assert len(design["api_contracts"]) == 1
        assert design["api_contracts"][0]["component_id"] == "user-service"
        assert design["api_contracts"][0]["base_path"] == "/api/users"
        assert len(design["shared_data_models"]) == 0
        assert len(design["event_contracts"]) == 1
        assert design["event_contracts"][0]["event_name"] == "UserCreated"


class TestDesignArchitectureErrorHandling:
    """Test suite for DesignArchitectureTool error handling."""

    @pytest.mark.asyncio
    async def test_empty_requirements_raises_error(self, mock_agent, mock_pipeline):
        """
        E-1: ERR_001 - Requirements validation fails (HTTP 400, severity: warn)
        
        given_precondition: Empty requirements provided
        when_action: design() is called
        then_outcome: ToolError is raised with ERR_001
        """
        from fastmcp.exceptions import ToolError

        tool = DesignArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        with pytest.raises(ToolError) as exc_info:
            await tool.design(
                requirements="",
                domain="microservices"
            )

        assert ERROR_REQUIREMENTS_VALIDATION in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_domain_raises_error(self, mock_agent, mock_pipeline):
        """
        E-1: ERR_001 - Requirements validation fails (HTTP 400, severity: warn)
        
        given_precondition: Empty domain provided
        when_action: design() is called
        then_outcome: ToolError is raised with ERR_001
        """
        from fastmcp.exceptions import ToolError

        tool = DesignArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        with pytest.raises(ToolError) as exc_info:
            await tool.design(
                requirements="Valid requirements",
                domain=""
            )

        assert ERROR_REQUIREMENTS_VALIDATION in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_whitespace_only_requirements_raises_error(self, mock_agent, mock_pipeline):
        """
        E-1: ERR_001 - Requirements validation fails (HTTP 400, severity: warn)

        given_precondition: Whitespace-only requirements provided
        when_action: design() is called
        then_outcome: ToolError is raised with ERR_001
        """
        from fastmcp.exceptions import ToolError

        tool = DesignArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        with pytest.raises(ToolError) as exc_info:
            await tool.design(
                requirements="   ",
                domain="microservices"
            )

        assert ERROR_REQUIREMENTS_VALIDATION in str(exc_info.value)

    @pytest.mark.parametrize(
        ("bad_value", "bad_field"),
        [
            ("\t\t", "requirements"),
            (" \t \n ", "requirements"),
            ("\u200b\u200c", "requirements"),
            ("\ufeff", "requirements"),
            ("\x00", "requirements"),
            ("", "domain"),
            ("   ", "domain"),
            ("\t", "domain"),
            ("\u200b", "domain"),
        ],
    )
    @pytest.mark.asyncio
    async def test_invalid_text_rejected_before_pipeline(
        self, mock_agent, mock_pipeline, bad_value: str, bad_field: str
    ) -> None:
        """ERR_001 validation fails for tab-only, mixed-whitespace, zero-width, control chars."""
        from fastmcp.exceptions import ToolError

        tool = DesignArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)
        mock_pipeline.run_design = AsyncMock()  # ensure not called

        kwargs = {"requirements": "valid architecture requirements", "domain": "microservices"}
        kwargs[bad_field] = bad_value

        with pytest.raises(ToolError) as exc_info:
            await tool.design(**kwargs)

        assert ERROR_REQUIREMENTS_VALIDATION in str(exc_info.value)
        mock_pipeline.run_design.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_llm_error_raises_tool_error(self, mock_agent, mock_pipeline):
        """
        E-9: ERR_009 - LLM provider returned error (HTTP 502, severity: error)
        
        given_precondition: LLM provider returns error
        when_action: design() is called
        then_outcome: ToolError is raised with ERR_009
        """
        from fastmcp.exceptions import ToolError
        from src.agent import LLMError

        mock_pipeline.run_design.side_effect = LLMError(
            provider="openai",
            error=ERROR_LLM_PROVIDER,
            provider_message="API rate limit exceeded"
        )

        tool = DesignArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        with pytest.raises(ToolError) as exc_info:
            await tool.design(
                requirements="System needs high scalability",
                domain="microservices"
            )

        assert ERROR_LLM_PROVIDER in str(exc_info.value)

    def test_is_llm_error_detects_llm_errors(self, mock_agent, mock_pipeline):
        """
        E-9: Error detection helper method
        
        given_precondition: LLMError instance
        when_action: _is_llm_error() is called
        then_outcome: Returns True for LLMError instances
        """
        from src.agent import LLMError

        tool = DesignArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)
        error = LLMError(provider="openai", error="ERR_009", provider_message="test")

        assert tool._is_llm_error(error) is True

    def test_is_llm_error_rejects_non_llm_errors(self, mock_agent, mock_pipeline):
        """
        E-9: Error detection helper method
        
        given_precondition: Non-LLM error instance
        when_action: _is_llm_error() is called
        then_outcome: Returns False for non-LLMError instances
        """
        tool = DesignArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)
        error = ValueError("Invalid input")

        assert tool._is_llm_error(error) is False



