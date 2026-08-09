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
Unit tests for GenerateArchitectureTool.

AC-222: Verify GenerateArchitectureTool class exists, accepts SoftwareArchitectAgent
Test Case IDs: UT-13, IT-3

Validates:
- FR-222: GenerateArchitectureTool class exists
- E-3: Failed to generate architecture design handling (ERR_003)
- E-9: LLM provider returned error handling (ERR_009)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent import LLMError, SoftwareArchitectAgent

# Import for mocking the pipeline
from src.pipeline import ArchitecturePipeline
from src.schemas.contracts import ApiContract, ApiEndpoint, DataModel, EventContract, ModelField

from src.schemas.design import ArchitectureDesign, ArchitectureOverview
from src.schemas.components import Component, Relationship
from src.schemas.enums import ArchitectureStyle, PatternCategory

# Import the tool class and related components
from fastmcp.exceptions import ToolError

from src.tools.generate import (
    ERROR_GENERATION_FAILED,
    ERROR_LLM_PROVIDER,
    GenerateArchitectureOutput,
    GenerateArchitectureTool,
    generate_architecture_tool,
)

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
    pipeline = MagicMock()
    pipeline.generate = AsyncMock()
    # Provide a mock pattern_loader that returns None so names resolve to
    # nothing (the tool logs a WARNING and proceeds with empty patterns).
    loader = MagicMock()
    loader.get_by_name.return_value = None
    pipeline._pattern_loader = loader
    return pipeline


@pytest.fixture
def sample_architecture_design():
    """Create a sample ArchitectureDesign for testing."""
    return ArchitectureDesign(
        overview=ArchitectureOverview(
            style=ArchitectureStyle.ACTOR_BASED,
            category=PatternCategory.STRUCTURAL,
            principles=["principle1", "principle2"],
        ),
        components=[
            Component(
                id="api-gateway",
                name="API Gateway",
                type="gateway",
                description="Entry point for all client requests",
                responsibilities=["routing", "authentication", "rate limiting"],
            ),
            Component(
                id="user-service",
                name="User Service",
                type="service",
                description="User management microservice",
                responsibilities=["user CRUD", "authentication"],
            ),
        ],
        relationships=[
            Relationship(source="api-gateway", target="user-service", type="http", description=""),
        ],
        quality_attributes={
            "scalability": "high",
            "maintainability": "high",
            "reliability": "medium",
        },
        api_contracts=[
            ApiContract(
                component_id="user-service",
                base_path="/api/users",
                endpoints=[
                    ApiEndpoint(method="GET", path="/users", summary="", request_schema=None, response_schema=None, auth_required=True, tags=[]),
                    ApiEndpoint(method="GET", path="/users/{id}", summary="", request_schema=None, response_schema=None, auth_required=True, tags=[]),
                ],
                description="User API",
            ),
        ],
        shared_data_models=[
            DataModel(
                name="User",
                fields=[
                    ModelField(name="id", type="str"),
                    ModelField(name="name", type="str"),
                    ModelField(name="email", type="str"),
                ],
                description="User data model",
            ),
        ],
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


# AC-222: Verify GenerateArchitectureTool class exists, accepts SoftwareArchitectAgent

class TestGenerateArchitectureToolInit:
    """Test suite for GenerateArchitectureTool initialization."""

    def test_tool_initialization_with_agent_and_pipeline(self, mock_agent, mock_pipeline):
        """
        AC-222: Verify GenerateArchitectureTool class exists, accepts SoftwareArchitectAgent
        
        given_precondition: SoftwareArchitectAgent initialized
        when_action: System creates GenerateArchitectureTool instance
        then_outcome: GenerateArchitectureTool generates valid ArchitectureDesign
        """
        tool = GenerateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        assert tool is not None
        assert tool._agent is mock_agent
        assert tool._pipeline is mock_pipeline

    def test_tool_initialization_logs_debug_message(self, mock_agent, mock_pipeline, caplog):
        """Test that initialization logs a debug message."""
        import logging
        caplog.set_level(logging.DEBUG)

        tool = GenerateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        assert "GenerateArchitectureTool initialized" in caplog.text


class TestGenerateArchitectureOutput:
    """Test suite for GenerateArchitectureOutput Pydantic model."""

    def test_valid_output_with_all_fields(self, sample_architecture_design):
        """Test valid output with all fields."""
        output = GenerateArchitectureOutput(
            overview=sample_architecture_design.overview.model_dump(),
            components=[c.model_dump() for c in sample_architecture_design.components],
            relationships=[r.model_dump() for r in sample_architecture_design.relationships],
            quality_attributes=sample_architecture_design.quality_attributes,
            api_contracts=[a.model_dump() for a in sample_architecture_design.api_contracts],
            shared_data_models=[m.model_dump() for m in sample_architecture_design.shared_data_models],
            event_contracts=[e.model_dump() for e in sample_architecture_design.event_contracts],
        )

        assert output.overview["style"] == sample_architecture_design.overview.style.value
        assert len(output.components) == 2
        assert len(output.relationships) == 1

    def test_empty_output(self):
        """Test output with default values."""
        output = GenerateArchitectureOutput()

        assert output.overview == {}
        assert output.components == []
        assert output.relationships == []


class TestGenerateArchitectureToolGenerate:
    """Test suite for GenerateArchitectureTool.generate() method."""

    @pytest.mark.asyncio
    async def test_generate_success(self, mock_agent, mock_pipeline, sample_architecture_design):
        """
        AC-222: Verify GenerateArchitectureTool class generates valid ArchitectureDesign

        given_precondition: SoftwareArchitectAgent initialized
        when_action: System creates GenerateArchitectureTool instance and calls generate()
        then_outcome: GenerateArchitectureTool returns valid ArchitectureDesign
        """
        # Wire the pattern_loader mock so name "CQRS" resolves to a stub pattern dict.
        cqrs_dict = {"name": "CQRS", "context": "Read/write segregation", "category": "structural",
                     "quality_attributes": {"maintainability": 7, "scalability": 7,
                                            "reliability": 7, "security": 7, "performance": 7}}
        mock_pipeline._pattern_loader.get_by_name.return_value = cqrs_dict
        mock_pipeline.generate.return_value = sample_architecture_design

        tool = GenerateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        result = await tool.generate(
            requirements="Build a scalable web application",
            style="microservices",
            domain="web applications",
            selected_patterns=["CQRS"]
        )

        mock_pipeline.generate.assert_called_once_with(
            requirements="Build a scalable web application",
            style="microservices",
            domain="web applications",
            selected_patterns=[cqrs_dict]
        )

        assert result['overview'] == sample_architecture_design.overview.model_dump()
        assert len(result['components']) == 2

    @pytest.mark.asyncio
    async def test_generate_logs_info_on_start(self, mock_agent, mock_pipeline, sample_architecture_design):
        """Test that generate() logs info message at start via ctx."""
        from unittest.mock import MagicMock, AsyncMock

        mock_pipeline.generate.return_value = sample_architecture_design
        ctx = MagicMock()
        ctx.info = AsyncMock()
        ctx.error = AsyncMock()

        tool = GenerateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)
        await tool.generate(
            requirements="Build a scalable web application",
            style="microservices",
            domain="web applications",
            selected_patterns=[],
            ctx=ctx
        )

        ctx.info.assert_called()
        info_calls = ctx.info.call_args_list
        first_call_args = info_calls[0][0][0]
        assert "generate_architecture" in first_call_args
        assert "microservices" in first_call_args

    @pytest.mark.asyncio
    async def test_generate_logs_info_on_completion(self, mock_agent, mock_pipeline, sample_architecture_design):
        """Test that generate() logs info message on completion via ctx."""
        from unittest.mock import MagicMock, AsyncMock

        mock_pipeline.generate.return_value = sample_architecture_design
        ctx = MagicMock()
        ctx.info = AsyncMock()
        ctx.error = AsyncMock()

        tool = GenerateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)
        result = await tool.generate(
            requirements="Build a scalable web application",
            style="microservices",
            domain="web applications",
            selected_patterns=[],
            ctx=ctx
        )

        ctx.info.assert_called()
        info_calls = ctx.info.call_args_list
        last_call_args = info_calls[-1][0][0]
        assert "generate_architecture completed" in last_call_args


class TestGenerateArchitectureErrorHandling:
    """Test suite for GenerateArchitectureTool error handling."""

    @pytest.mark.asyncio
    async def test_llm_error_raises_generate_error(self, mock_agent, mock_pipeline):
        """
        E-9: ERR_009 - LLM provider returned error

        given_precondition: LLM provider error occurs
        when_action: generate() is called
        then_outcome: ToolError is raised with ERR_009
        """
        llm_error = LLMError(provider="openai", error="ERR_009", provider_message="API key invalid")
        mock_pipeline.generate.side_effect = llm_error

        tool = GenerateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        with pytest.raises(ToolError) as exc_info:
            await tool.generate(
                requirements="Build a scalable web application",
                style="microservices",
                domain="web applications",
                selected_patterns=[]
            )

        error_msg = str(exc_info.value)
        assert ERROR_LLM_PROVIDER in error_msg
        assert "LLM provider returned error" in error_msg

    @pytest.mark.asyncio
    async def test_llm_error_logs_error_with_context(self, mock_agent, mock_pipeline):
        """
        E-9: ERR_009 - LLM provider returned error logging context

        Validates that ctx.error is called with error details
        """
        from unittest.mock import MagicMock, AsyncMock

        llm_error = LLMError(provider="openai", error="ERR_009", provider_message="API key invalid")
        mock_pipeline.generate.side_effect = llm_error
        ctx = MagicMock()
        ctx.info = AsyncMock()
        ctx.error = AsyncMock()

        tool = GenerateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        with pytest.raises(ToolError):
            await tool.generate(
                requirements="Build a scalable web application",
                style="microservices",
                domain="web applications",
                selected_patterns=[],
                ctx=ctx
            )

        ctx.error.assert_called()
        call_args = ctx.error.call_args[0][0]
        assert "LLM provider error during generation" in call_args

    @pytest.mark.asyncio
    async def test_generation_failure_raises_error(self, mock_agent, mock_pipeline):
        """
        E-3: ERR_003 - Failed to generate architecture design

        given_precondition: Generation fails for non-LLM reason
        when_action: generate() is called
        then_outcome: ToolError is raised with ERR_003
        """
        mock_pipeline.generate.side_effect = Exception("Generation failed due to invalid requirements")

        tool = GenerateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        with pytest.raises(ToolError) as exc_info:
            await tool.generate(
                requirements="Build a scalable web application",
                style="microservices",
                domain="web applications",
                selected_patterns=[]
            )

        error_msg = str(exc_info.value)
        assert ERROR_GENERATION_FAILED in error_msg
        assert "Failed to generate architecture design" in error_msg

    @pytest.mark.asyncio
    async def test_generation_failure_logs_error_with_context(self, mock_agent, mock_pipeline):
        """
        E-3: ERR_003 - Failed to generate architecture design logging context

        Validates that ctx.error is called with error details
        """
        from unittest.mock import MagicMock, AsyncMock

        mock_pipeline.generate.side_effect = Exception("Invalid requirements format")
        ctx = MagicMock()
        ctx.info = AsyncMock()
        ctx.error = AsyncMock()

        tool = GenerateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        with pytest.raises(ToolError):
            await tool.generate(
                requirements="Build a scalable web application",
                style="microservices",
                domain="web applications",
                selected_patterns=[],
                ctx=ctx
            )

        ctx.error.assert_called()
        call_args = ctx.error.call_args[0][0]
        assert "Failed to generate architecture design" in call_args


class TestGenerateArchitectureToolFactory:
    """Test suite for generate_architecture_tool factory function."""

    def test_factory_creates_tool_with_correct_dependencies(self, mock_agent, mock_pipeline):
        """
        DP-4: Factory Pattern - Consistent tool initialization with proper dependencies
        
        given_precondition: agent and pipeline available
        when_action: factory function is called
        then_outcome: Tool instance created with correct dependencies
        """
        tool = generate_architecture_tool(agent=mock_agent, pipeline=mock_pipeline)

        assert tool is not None
        assert tool._agent is mock_agent
        assert tool._pipeline is mock_pipeline


class TestMapToOutput:
    """Test suite for _map_to_output helper method."""

    def test_maps_all_fields_correctly(self, mock_agent, mock_pipeline, sample_architecture_design):
        """Test that all ArchitectureDesign fields are mapped to output."""
        tool = GenerateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        output = tool._map_to_output(sample_architecture_design)

        assert output.overview["style"] == sample_architecture_design.overview.style.value
        assert output.overview["category"] == sample_architecture_design.overview.category.value
        assert len(output.components) == len(sample_architecture_design.components)
        assert output.components[0]["id"] == sample_architecture_design.components[0].id
        assert output.quality_attributes == sample_architecture_design.quality_attributes


class TestIsLlmError:
    """Test suite for _is_llm_error helper method."""

    def test_returns_true_for_llm_error(self, mock_agent, mock_pipeline):
        """Test that LLMError returns True."""
        tool = GenerateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        error = LLMError(provider="openai", error="ERR_009", provider_message="API key invalid")
        assert tool._is_llm_error(error) is True

    def test_returns_false_for_generic_error(self, mock_agent, mock_pipeline):
        """Test that generic Exception returns False."""
        tool = GenerateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        error = Exception("Some other error")
        assert tool._is_llm_error(error) is False
