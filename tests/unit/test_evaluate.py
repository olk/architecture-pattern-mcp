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
Unit tests for EvaluateArchitectureTool.

AC-223: Verify EvaluateArchitectureTool class exists, accepts SoftwareArchitectAgent
Test Case IDs: UT-13, IT-4

Validates:
- FR-223: EvaluateArchitectureTool class exists
- E-4: Architecture does not meet minimum requirements (ERR_004)
- E-9: LLM provider returned error (ERR_009)
"""

from unittest.mock import MagicMock

import pytest

from src.agent import LLMError, SoftwareArchitectAgent

# Import for mocking the pipeline
from src.pipeline import (
    ArchitectureEvaluation,
    ArchitecturePipeline,
)
from src.schemas.design import ArchitectureDesign
from src.schemas.enums import ArchitectureStyle

# Import the tool class and related components
from fastmcp.exceptions import ToolError

from src.tools.evaluate import (
    ERROR_LLM_PROVIDER,
    EvaluateArchitectureOutput,
    EvaluateArchitectureTool,
    evaluate_architecture_tool,
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
    pipeline = MagicMock(spec=ArchitecturePipeline)
    return pipeline


@pytest.fixture
def sample_architecture_design():
    """Create a sample ArchitectureDesign for testing."""
    return {
        "overview": {
            "style": "actor-based",
            "category": "structural",
            "principles": ["principle1"],
            "constraints": []
        },
        "components": [
            {
                "id": "api-gateway",
                "name": "API Gateway",
                "type": "gateway",
                "description": "API Gateway for routing requests",
                "responsibilities": ["routing", "authentication"]
            },
            {
                "id": "user-service",
                "name": "User Service",
                "type": "service",
                "description": "User management service",
                "responsibilities": ["user CRUD", "authentication"]
            }
        ],
        "relationships": [
            {"from": "api-gateway", "to": "user-service", "type": "http"}
        ],
        "quality_attributes": {"scalability": "high", "maintainability": "medium"},
        "api_contracts": [],
        "shared_data_models": [],
        "event_contracts": [],
    }


@pytest.fixture
def sample_architecture_evaluation():
    """Create a sample ArchitectureEvaluation for testing."""
    from src.schemas.evaluation import EvaluationSummary, MetricResult
    return ArchitectureEvaluation(
        summary=EvaluationSummary(
            overall_score=79.0,
            strengths=["Good scalability score: 9.0/10", "Good security score: 8.0/10"],
            weaknesses=["Low performance score: 7.0/10"],
            critical_findings=["Risk: API Gateway: API exposure risk"],
        ),
        metrics=[
            MetricResult(name="maintainability", score=80.0, description="Maintainability metric"),
            MetricResult(name="scalability", score=90.0, description="Scalability metric"),
            MetricResult(name="reliability", score=75.0, description="Reliability metric"),
            MetricResult(name="security", score=80.0, description="Security metric"),
            MetricResult(name="performance", score=70.0, description="Performance metric"),
            MetricResult(name="overall_quality", score=79.0, description="Overall quality"),
        ],
        recommendations={
            "general": [
                "Address: API Gateway: API exposure risk - ensure proper auth and rate limiting",
                "Consider patterns with better criteria alignment: microservices-architecture"
            ]
        }
    )


@pytest.fixture
def sample_architecture_design_object():
    """Create a sample ArchitectureDesign object for testing."""
    return ArchitectureDesign(
        overview={
            "style": "actor-based",
            "category": "structural",
            "principles": ["test principle"],
            "constraints": []
        },
        components=[
            {
                "id": "api-gateway",
                "name": "API Gateway",
                "type": "gateway",
                "description": "API Gateway for routing requests",
                "responsibilities": ["routing"]
            }
        ],
        relationships=[],
        quality_attributes={},
        api_contracts=[],
        shared_data_models=[],
        event_contracts=[],
    )


# AC-223: Verify EvaluateArchitectureTool class exists, accepts SoftwareArchitectAgent

class TestEvaluateArchitectureToolInit:
    """Test suite for EvaluateArchitectureTool initialization."""

    def test_tool_initialization_with_agent_and_pipeline(self, mock_agent, mock_pipeline):
        """
        AC-223: Verify EvaluateArchitectureTool class exists, accepts SoftwareArchitectAgent
        
        given_precondition: SoftwareArchitectAgent initialized
        when_action: System creates EvaluateArchitectureTool instance
        then_outcome: EvaluateArchitectureTool class exists with proper initialization
        """
        # When: Creating EvaluateArchitectureTool with agent and pipeline
        tool = EvaluateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # Then: Tool should be initialized properly
        assert tool is not None
        assert isinstance(tool, EvaluateArchitectureTool)
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
        tool = evaluate_architecture_tool(agent=mock_agent, pipeline=mock_pipeline)

        # Then: Should return properly initialized tool
        assert tool is not None
        assert isinstance(tool, EvaluateArchitectureTool)
        assert tool._agent is mock_agent
        assert tool._pipeline is mock_pipeline


class TestEvaluateArchitectureOutput:
    """Test suite for EvaluateArchitectureOutput model."""

    def test_output_model_with_all_fields(self, sample_architecture_evaluation):
        """
        ENT-13: ArchitectureEvaluation with summary, metrics, recommendations
        
        given_precondition: ArchitectureEvaluation data available
        when_action: Creating output model
        then_outcome: All fields are properly set
        """
        metrics_dict = {m.name: m.score / 10.0 for m in sample_architecture_evaluation.metrics}
        recommendations_list = []
        for recs in sample_architecture_evaluation.recommendations.values():
            recommendations_list.extend(recs)

        # When: Creating output with all fields
        output = EvaluateArchitectureOutput(
            summary=f"Overall score: {sample_architecture_evaluation.summary.overall_score:.1f}/100",
            metrics=metrics_dict,
            recommendations=recommendations_list
        )

        # Then: All fields should be set correctly
        assert output.summary == f"Overall score: {sample_architecture_evaluation.summary.overall_score:.1f}/100"
        assert output.metrics == metrics_dict
        assert len(output.recommendations) == 2

    def test_output_model_default_values(self):
        """
        given_precondition: None
        when_action: Creating output with defaults
        then_outcome: Default values are set correctly
        """
        # When: Creating output with minimal data
        output = EvaluateArchitectureOutput()

        # Then: Default values should be set
        assert output.summary == ""
        assert output.metrics == {}
        assert output.recommendations == []


class TestEvaluateArchitectureToolEvaluate:
    """Test suite for EvaluateArchitectureTool.evaluate() method."""

    @pytest.mark.asyncio
    async def test_evaluate_returns_output_successfully(
        self,
        mock_agent,
        mock_pipeline,
        sample_architecture_design,
        sample_architecture_evaluation
    ):
        """
        FR-223: EvaluateArchitectureTool class evaluates architecture designs
        
        given_precondition: Pipeline configured with evaluation result
        when_action: evaluate() is called with architecture, criteria, and domain
        then_outcome: dict is returned with evaluation
        """
        # Given: Pipeline returns sample evaluation
        mock_pipeline.evaluate.return_value = sample_architecture_evaluation

        tool = EvaluateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When: Calling evaluate with architecture, criteria, and domain
        output = await tool.evaluate(
            architecture=sample_architecture_design,
            criteria="quality,maintainability,scalability",
            domain="microservices"
        )

        # Then: Should return properly formatted output
        assert isinstance(output, dict)
        assert output['summary'] == f"Overall score: {sample_architecture_evaluation.summary.overall_score:.1f}/100"
        expected_metrics = {m.name: m.score / 10.0 for m in sample_architecture_evaluation.metrics}
        assert output['metrics'] == expected_metrics
        assert len(output['recommendations']) == 2

    @pytest.mark.asyncio
    async def test_evaluate_delegates_to_pipeline(
        self,
        mock_agent,
        mock_pipeline,
        sample_architecture_design,
        sample_architecture_evaluation
    ):
        """
        DF-4: Flow - MCP Client -> EvaluateArchitectureTool.evaluate()
              -> ArchitecturePipeline.evaluate()
        
        given_precondition: Pipeline configured
        when_action: evaluate() is called
        then_outcome: Pipeline.evaluate is called with correct parameters
        """
        # Given: Pipeline returns sample evaluation
        mock_pipeline.evaluate.return_value = sample_architecture_evaluation

        tool = EvaluateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When: Calling evaluate
        await tool.evaluate(
            architecture=sample_architecture_design,
            criteria="quality,maintainability",
            domain="microservices"
        )

        # Then: Pipeline.evaluate should be called once with correct parameters
        mock_pipeline.evaluate.assert_called_once()
        call_args = mock_pipeline.evaluate.call_args
        assert call_args.kwargs["criteria"] == "quality,maintainability"
        assert call_args.kwargs["domain"] == "microservices"

    @pytest.mark.asyncio
    async def test_evaluate_converts_architecture_dict_to_design(
        self,
        mock_agent,
        mock_pipeline,
        sample_architecture_design,
        sample_architecture_evaluation
    ):
        """
        CF-4: RPARAM-9 - architecture parameter (valid ArchitectureDesign structure)
        
        given_precondition: Pipeline configured
        when_action: evaluate() is called with architecture dict
        then_outcome: ArchitectureDesign object is passed to pipeline
        """
        # Given: Pipeline returns sample evaluation
        mock_pipeline.evaluate.return_value = sample_architecture_evaluation

        tool = EvaluateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When: Calling evaluate
        await tool.evaluate(
            architecture=sample_architecture_design,
            criteria="quality",
            domain="microservices"
        )

        # Then: Pipeline should receive ArchitectureDesign object
        call_args = mock_pipeline.evaluate.call_args
        architecture_arg = call_args.kwargs["architecture"]
        assert isinstance(architecture_arg, ArchitectureDesign)
        assert architecture_arg.overview.style == ArchitectureStyle.ACTOR_BASED


class TestEvaluateArchitectureErrorHandling:
    """Test suite for EvaluateArchitectureTool error handling."""

    @pytest.mark.asyncio
    async def test_minimum_requirements_not_met_raises_error(
        self,
        mock_agent,
        mock_pipeline
    ):
        """
        E-4: ERR_004 - Architecture does not meet minimum requirements (HTTP 400, severity: warn)

        given_precondition: Architecture has no components or overview
        when_action: evaluate() is called
        then_outcome: ToolError is raised (validation or minimum requirements error)
        """
        # Given: Architecture with no components (fails minimum requirements)
        # Note: overview must be valid to reach the minimum-requirements check
        invalid_architecture = {
            "overview": {"style": "actor-based", "category": "structural", "principles": ["p1"]},
            "components": []
        }

        tool = EvaluateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When/Then: Should raise ToolError
        with pytest.raises(ToolError) as exc_info:
            await tool.evaluate(
                architecture=invalid_architecture,
                criteria="quality",
                domain="microservices"
            )

        error_msg = str(exc_info.value)
        assert "ERR_004" in error_msg or "ERR_009" in error_msg

    @pytest.mark.asyncio
    async def test_llm_error_raises_evaluate_architecture_error(self, mock_agent, mock_pipeline):
        """
        E-9: ERR_009 - LLM provider returned error (HTTP 502, severity: error)
        
        given_precondition: LLM provider returns error
        when_action: evaluate() is called
        then_outcome: ToolError is raised with ERR_009
        """
        # Given: Pipeline raises LLMError
        mock_pipeline.evaluate.side_effect = LLMError(
            provider="openai",
            error=ERROR_LLM_PROVIDER,
            provider_message="API rate limit exceeded"
        )

        tool = EvaluateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        architecture_dict = {
            "overview": {"style": "actor-based", "category": "structural", "principles": ["p1"]},
            "components": [{"id": "c1", "name": "Component 1", "type": "service", "description": "A component", "responsibilities": ["test"]}]
        }

        # When/Then: Should raise ToolError
        with pytest.raises(ToolError) as exc_info:
            await tool.evaluate(
                architecture=architecture_dict,
                criteria="quality",
                domain="microservices"
            )

        error_msg = str(exc_info.value)
        assert ERROR_LLM_PROVIDER in error_msg

    @pytest.mark.asyncio
    async def test_empty_architecture_components_raises_error(self, mock_agent, mock_pipeline):
        """
        E-4: ERR_004 - Architecture must have at least one component

        given_precondition: Architecture has overview but no components
        when_action: evaluate() is called
        then_outcome: ToolError is raised (validation or minimum requirements error)
        """
        # Given: Architecture with overview but no components
        partial_architecture = {
            "overview": {"style": "actor-based", "category": "structural", "principles": ["p1"]},
            "components": []
        }

        tool = EvaluateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When/Then: Should raise ToolError
        with pytest.raises(ToolError) as exc_info:
            await tool.evaluate(
                architecture=partial_architecture,
                criteria="quality",
                domain="microservices"
            )

        error_msg = str(exc_info.value)
        assert "ERR_004" in error_msg or "ERR_009" in error_msg or "ERR_012" in error_msg

    @pytest.mark.asyncio
    async def test_empty_architecture_overview_raises_error(self, mock_agent, mock_pipeline):
        """
        E-4: ERR_004 - Architecture must have an overview

        given_precondition: Architecture has components but no overview
        when_action: evaluate() is called
        then_outcome: ToolError is raised (validation or minimum requirements error)
        """
        # Given: Architecture with components but no overview
        partial_architecture = {
            "overview": {},
            "components": [{"id": "c1", "name": "Component 1", "type": "service", "description": "A component", "responsibilities": ["test"]}]
        }

        tool = EvaluateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When/Then: Should raise ToolError
        with pytest.raises(ToolError) as exc_info:
            await tool.evaluate(
                architecture=partial_architecture,
                criteria="quality",
                domain="microservices"
            )

        error_msg = str(exc_info.value)
        assert "ERR_004" in error_msg or "ERR_009" in error_msg or "ERR_012" in error_msg


class TestEvaluateArchitectureCheckMinimumRequirements:
    """Test suite for _check_minimum_requirements method."""

    def test_valid_architecture_passes_check(self, mock_agent, mock_pipeline, sample_architecture_design_object):
        """
        given_precondition: Valid ArchitectureDesign
        when_action: _check_minimum_requirements() is called
        then_outcome: Returns True
        """
        # Given: Tool is initialized
        tool = EvaluateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When: Checking valid architecture
        result = tool._check_minimum_requirements(sample_architecture_design_object)

        # Then: Should return True
        assert result is True

    def test_architecture_with_no_components_fails_check(self, mock_agent, mock_pipeline, sample_architecture_design_object):
        """
        given_precondition: ArchitectureDesign with no components
        when_action: _check_minimum_requirements() is called
        then_outcome: Returns False
        """
        # Given: ArchitectureDesign with no components
        tool = EvaluateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)
        sample_architecture_design_object.components = []

        # When: Checking architecture
        result = tool._check_minimum_requirements(sample_architecture_design_object)

        # Then: Should return False
        assert result is False

    def test_architecture_with_no_overview_fails_check(self, mock_agent, mock_pipeline, sample_architecture_design_object):
        """
        given_precondition: ArchitectureDesign with no overview
        when_action: _check_minimum_requirements() is called
        then_outcome: Returns False
        """
        # Given: ArchitectureDesign with no overview
        tool = EvaluateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)
        sample_architecture_design_object.overview = {}

        # When: Checking architecture
        result = tool._check_minimum_requirements(sample_architecture_design_object)

        # Then: Should return False
        assert result is False


class TestEvaluateArchitectureConvertToDesign:
    """Test suite for _convert_to_architecture_design method."""

    def test_convert_dict_to_design_object(self, mock_agent, mock_pipeline, sample_architecture_design):
        """
        given_precondition: Architecture dict with all fields
        when_action: _convert_to_architecture_design() is called
        then_outcome: Returns ArchitectureDesign object with all fields
        """
        # Given: Tool is initialized
        tool = EvaluateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When: Converting dict to design object
        design = tool._convert_to_architecture_design(sample_architecture_design)

        # Then: Should return ArchitectureDesign with all fields
        assert isinstance(design, ArchitectureDesign)
        assert design.overview.style == ArchitectureStyle.ACTOR_BASED
        assert len(design.components) == 2
        assert design.components[0].id == "api-gateway"
        assert len(design.relationships) == 1

    def test_convert_dict_with_missing_fields(self, mock_agent, mock_pipeline):
        """
        given_precondition: Architecture dict with missing optional fields
        when_action: _convert_to_architecture_design() is called
        then_outcome: Returns ArchitectureDesign with defaults for missing fields
        """
        # Given: Tool is initialized
        tool = EvaluateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When: Converting incomplete dict
        incomplete_architecture = {
            "overview": {"style": "actor-based", "category": "structural", "principles": ["p1"]},
            "components": [{"id": "c1", "name": "Single", "type": "service", "description": "One component", "responsibilities": ["test"]}]
        }

        design = tool._convert_to_architecture_design(incomplete_architecture)

        # Then: Should return ArchitectureDesign with defaults
        assert isinstance(design, ArchitectureDesign)
        assert design.overview.style == ArchitectureStyle.ACTOR_BASED
        assert len(design.components) == 1
        assert design.relationships == []


class TestEvaluateArchitectureMapToOutput:
    """Test suite for _map_to_output method."""

    def test_map_evaluation_to_output(self, mock_agent, mock_pipeline, sample_architecture_evaluation):
        """
        ENT-13: ArchitectureEvaluation mapped to EvaluateArchitectureOutput
        
        given_precondition: ArchitectureEvaluation from pipeline
        when_action: _map_to_output() is called
        then_outcome: Returns EvaluateArchitectureOutput with all fields
        """
        # Given: Tool is initialized
        tool = EvaluateArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When: Mapping evaluation to output
        output = tool._map_to_output(sample_architecture_evaluation)

        # Then: Should return output with all fields mapped
        assert isinstance(output, EvaluateArchitectureOutput)
        assert output.summary == f"Overall score: {sample_architecture_evaluation.summary.overall_score:.1f}/100"
        expected_metrics = {m.name: m.score / 10.0 for m in sample_architecture_evaluation.metrics}
        assert output.metrics == expected_metrics
        expected_recs = []
        for recs in sample_architecture_evaluation.recommendations.values():
            expected_recs.extend(recs)
        assert output.recommendations == expected_recs
