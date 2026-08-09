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
Unit tests for AnalyzeArchitectureTool.

AC-221: Verify AnalyzeArchitectureTool class exists, accepts SoftwareArchitectAgent
Test Case IDs: UT-13, IT-2

Validates:
- FR-221: AnalyzeArchitectureTool class exists
- E-2: No patterns found for domain handling (ERR_002)
- E-9: LLM provider returned error handling (ERR_009)
"""

from unittest.mock import MagicMock

import pytest

from src.agent import SoftwareArchitectAgent

# Import for mocking the pipeline
from src.pipeline import AnalysisResult, ArchitecturePipeline
from src.schemas.quality import QualityMetrics

# Import the tool class and related components
from fastmcp.exceptions import ToolError

from src.tools.analyze import (
    ERROR_LLM_PROVIDER,
    AnalyzeArchitectureOutput,
    AnalyzeArchitectureTool,
    analyze_architecture_tool,
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
def sample_analysis_result():
    """Create a sample AnalysisResult for testing."""
    return AnalysisResult(
        strengths=["High scalability", "Strong maintainability"],
        weaknesses=["Complex initial setup"],
        recommendations=["Consider using patterns for microservices"],
        quality_metrics=QualityMetrics(
            maintainability=8.0,
            scalability=9.0,
            reliability=7.5,
            security=8.0,
            performance=7.0
        ),
        recommended_style="microservices",
        selected_patterns=[
            {"name": "microservices-architecture", "context": "Distributed system design", "category": "structural"},
            {"name": "cqrs-pattern", "context": "Read/write separation", "category": "structural"}
        ],
    )


@pytest.fixture
def sample_quality_metrics():
    """Create sample QualityMetrics for testing."""
    return QualityMetrics(
        maintainability=8.0,
        scalability=9.0,
        reliability=7.5,
        security=8.0,
        performance=7.0,
        testability=7.0
    )


# AC-221: Verify AnalyzeArchitectureTool class exists, accepts SoftwareArchitectAgent

class TestAnalyzeArchitectureToolInit:
    """Test suite for AnalyzeArchitectureTool initialization."""

    def test_tool_initialization_with_agent_and_pipeline(self, mock_agent, mock_pipeline):
        """
        AC-221: Verify AnalyzeArchitectureTool class exists, accepts SoftwareArchitectAgent
        
        given_precondition: SoftwareArchitectAgent initialized
        when_action: System creates AnalyzeArchitectureTool instance
        then_outcome: AnalyzeArchitectureTool class exists with proper initialization
        """
        # When: Creating AnalyzeArchitectureTool with agent and pipeline
        tool = AnalyzeArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # Then: Tool should be initialized properly
        assert tool is not None
        assert isinstance(tool, AnalyzeArchitectureTool)
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
        tool = analyze_architecture_tool(agent=mock_agent, pipeline=mock_pipeline)

        # Then: Should return properly initialized tool
        assert tool is not None
        assert isinstance(tool, AnalyzeArchitectureTool)
        assert tool._agent is mock_agent
        assert tool._pipeline is mock_pipeline


class TestAnalyzeArchitectureOutput:
    """Test suite for AnalyzeArchitectureOutput model."""

    def test_output_model_with_all_fields(self, sample_quality_metrics):
        """
        ENT-4: AnalysisResult with strengths, weaknesses, recommendations, etc.
        
        given_precondition: AnalysisResult data available
        when_action: Creating output model
        then_outcome: All fields are properly set
        """
        # When: Creating output with all fields
        output = AnalyzeArchitectureOutput(
            strengths=["High scalability"],
            weaknesses=["Complex setup"],
            recommendations=["Use patterns"],
            recommended_style="microservices",
            selected_patterns=[{"name": "test-pattern"}],
            quality_metrics={"maintainability": 8.0}
        )

        # Then: All fields should be set correctly
        assert len(output.strengths) == 1
        assert len(output.weaknesses) == 1
        assert len(output.recommendations) == 1
        assert output.recommended_style == "microservices"
        assert len(output.selected_patterns) == 1

    def test_output_model_default_values(self):
        """
        given_precondition: None
        when_action: Creating output with defaults
        then_outcome: Default values are set correctly
        """
        # When: Creating output with minimal data
        output = AnalyzeArchitectureOutput()

        # Then: Default values should be set
        assert output.strengths == []
        assert output.weaknesses == []
        assert output.recommendations == []
        assert output.recommended_style == ""
        assert output.selected_patterns == []
        assert output.quality_metrics is None


class TestAnalyzeArchitectureToolAnalyze:
    """Test suite for AnalyzeArchitectureTool.analyze() method."""

    @pytest.mark.asyncio
    async def test_analyze_returns_output_successfully(
        self,
        mock_agent,
        mock_pipeline,
        sample_analysis_result
    ):
        """
        FR-221: AnalyzeArchitectureTool class analyzes requirements
        
        given_precondition: Pipeline configured with patterns
        when_action: analyze() is called with requirements and domain
        then_outcome: dict is returned with analysis
        """
        # Given: Pipeline returns sample analysis result
        mock_pipeline.analyze.return_value = sample_analysis_result

        tool = AnalyzeArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When: Calling analyze with requirements and domain
        output = await tool.analyze(
            requirements="System needs high scalability",
            domain="microservices"
        )

        # Then: Should return properly formatted output
        assert isinstance(output, dict)
        assert len(output['strengths']) == 2
        assert len(output['weaknesses']) == 1
        assert len(output['recommendations']) == 1
        assert output['recommended_style'] == "microservices"
        assert len(output['selected_patterns']) == 2

    @pytest.mark.asyncio
    async def test_analyze_maps_quality_metrics_correctly(
        self,
        mock_agent,
        mock_pipeline,
        sample_analysis_result
    ):
        """
        ENT-1: QualityMetrics with maintainability, scalability, reliability, security, performance
        
        given_precondition: AnalysisResult with QualityMetrics
        when_action: analyze() is called
        then_outcome: Quality metrics are properly mapped to dict
        """
        # Given: Pipeline returns result with quality metrics
        mock_pipeline.analyze.return_value = sample_analysis_result

        tool = AnalyzeArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When: Calling analyze
        output = await tool.analyze(
            requirements="System needs high scalability",
            domain="microservices"
        )

        # Then: Quality metrics should be mapped correctly
        assert output['quality_metrics'] is not None
        assert "maintainability" in output['quality_metrics']
        assert "scalability" in output['quality_metrics']
        assert "reliability" in output['quality_metrics']
        assert "security" in output['quality_metrics']
        assert "performance" in output['quality_metrics']
        assert "testability" in output['quality_metrics']

    @pytest.mark.asyncio
    async def test_analyze_delegates_to_pipeline(
        self,
        mock_agent,
        mock_pipeline,
        sample_analysis_result
    ):
        """
        DF-2: Flow - MCP Client -> AnalyzeArchitectureTool.analyze()
              -> ArchitecturePipeline.analyze()
        
        given_precondition: Pipeline configured
        when_action: analyze() is called
        then_outcome: Pipeline.analyze is called with correct parameters
        """
        # Given: Pipeline returns sample result
        mock_pipeline.analyze.return_value = sample_analysis_result

        tool = AnalyzeArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When: Calling analyze
        await tool.analyze(
            requirements="System needs high scalability",
            domain="microservices"
        )

        # Then: Pipeline.analyze should be called once with correct parameters
        mock_pipeline.analyze.assert_called_once_with(
            requirements="System needs high scalability",
            domain="microservices"
        )


class TestAnalyzeArchitectureErrorHandling:
    """Test suite for AnalyzeArchitectureTool error handling."""

    @pytest.mark.asyncio
    async def test_llm_error_raises_tool_error(self, mock_agent, mock_pipeline):
        """
        E-9: ERR_009 - LLM provider returned error (HTTP 502, severity: error)
        
        given_precondition: LLM provider returns error
        when_action: analyze() is called
        then_outcome: ToolError is raised
        """
        # Given: Pipeline raises LLMError
        from src.agent import LLMError
        mock_pipeline.analyze.side_effect = LLMError(
            provider="openai",
            error=ERROR_LLM_PROVIDER,
            provider_message="API rate limit exceeded"
        )

        tool = AnalyzeArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When/Then: Should raise ToolError
        with pytest.raises(ToolError):
            await tool.analyze(
                requirements="System needs high scalability",
                domain="microservices"
            )

    @pytest.mark.asyncio
    async def test_no_patterns_error_returns_empty_result(self, mock_agent, mock_pipeline):
        """
        E-2: ERR_002 - No patterns found for domain (HTTP 404, severity: info)
        
        given_precondition: No patterns found for domain
        when_action: analyze() is called
        then_outcome: Empty result is returned with warning message
        """
        # Given: Pipeline raises error indicating no patterns found
        mock_pipeline.analyze.side_effect = Exception("no patterns found for domain")

        tool = AnalyzeArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When: Calling analyze
        output = await tool.analyze(
            requirements="System needs high scalability",
            domain="unknown-domain"
        )

        # Then: Should return empty result with warning
        assert output['strengths'] == []
        assert len(output['weaknesses']) > 0
        assert "No patterns found" in output['weaknesses'][0]
        assert output['recommended_style'] == "layered-monolith"
        assert output['selected_patterns'] == []

    def test_is_llm_error_detects_llm_errors(self, mock_agent, mock_pipeline):
        """
        E-9: Error detection helper method
        
        given_precondition: LLMError instance
        when_action: _is_llm_error() is called
        then_outcome: Returns True for LLMError instances
        """
        # Given: Tool is initialized
        tool = AnalyzeArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When: Checking if LLMError is detected
        from src.agent import LLMError
        error = LLMError(provider="openai", error="ERR_009", provider_message="test")

        # Then: Should return True for LLMError
        assert tool._is_llm_error(error) is True

    def test_is_no_patterns_error_detects_pattern_errors(self, mock_agent, mock_pipeline):
        """
        E-2: Error detection helper method
        
        given_precondition: Exception with "no patterns" message
        when_action: _is_no_patterns_error() is called
        then_outcome: Returns True for no patterns errors
        """
        # Given: Tool is initialized
        tool = AnalyzeArchitectureTool(agent=mock_agent, pipeline=mock_pipeline)

        # When: Checking various error messages
        assert tool._is_no_patterns_error(Exception("no patterns found")) is True
        assert tool._is_no_patterns_error(Exception("no pattern found")) is True
        assert tool._is_no_patterns_error(Exception("pattern not found")) is True
        assert tool._is_no_patterns_error(Exception("empty result")) is True

        # Then: Should return False for other errors
        assert tool._is_no_patterns_error(Exception("connection timeout")) is False
