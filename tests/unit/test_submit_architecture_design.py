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
Unit tests for the async submit_architecture_design_job / get_architecture_design_status trio.

Covers:
- FR-224 parity: stored job result contains all fields that
  design_architecture returns (including matched_domains, is_fallback,
  alternative_styles)
- Job lifecycle: PENDING -> RUNNING -> COMPLETED
- get_architecture_design_status returns parsed result with all fields intact
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent import SoftwareArchitectAgent
from src.pipeline import ArchitecturePipeline
from src.schemas.analysis import MatchedDomain
from src.schemas.contracts import ApiContract, ApiEndpoint, EventContract
from src.schemas.design import ArchitectureDesign, ArchitectureOverview
from src.schemas.components import Component, Relationship
from src.schemas.enums import ArchitectureStyle, PatternCategory
from src.schemas.evaluation import (
    ArchitectureEvaluation,
    EvaluationSummary,
    MetricResult,
    PipelineResult,
)
from src.schemas.quality import QualityMetrics
from src.tools.design import DesignArchitectureOutput, pipeline_result_to_output
from src.tools.get_architecture_design_status import GetArchitectureDesignStatusTool
from src.tools.jobs import JobsStore
from src.tools.submit_architecture_design import (
    SubmitArchitectureDesignJobTool,
    submit_architecture_design_job_tool,
)


@pytest.fixture
def mock_agent():
    """Create a mock SoftwareArchitectAgent."""
    return MagicMock(spec=SoftwareArchitectAgent)


@pytest.fixture
def mock_pipeline():
    """Create a mock ArchitecturePipeline."""
    pipeline = MagicMock(spec=ArchitecturePipeline)
    pipeline.run_design = AsyncMock()
    return pipeline


@pytest.fixture
def sample_pipeline_result():
    """Create a PipelineResult with matched_domains and is_fallback populated."""
    design = ArchitectureDesign(
        overview=ArchitectureOverview(
            style=ArchitectureStyle.ACTOR_BASED,
            category=PatternCategory.STRUCTURAL,
            principles=["principle1", "principle2"],
            score=87.5,
        ),
        components=[
            Component(
                id="api-gateway",
                name="API Gateway",
                type="gateway",
                description="API Gateway component",
                responsibilities=["routing"],
            ),
        ],
        relationships=[
            Relationship(source="api-gateway", target="user-service", type="http", description=""),
        ],
        quality_attributes={"scalability": "high"},
        api_contracts=[
            ApiContract(
                component_id="api-gateway",
                base_path="/api",
                endpoints=[
                    ApiEndpoint(
                        method="GET",
                        path="/health",
                        summary="",
                        request_schema=None,
                        response_schema=None,
                        auth_required=False,
                        tags=[],
                    )
                ],
                description="Health endpoint",
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
            overall_score=82.0,
            strengths=["Strong separation of concerns"],
            weaknesses=["Consider adding caching"],
            critical_findings=[],
        ),
        metrics=[
            MetricResult(
                name="scalability",
                score=9.0,
                description="Scalability assessment",
                findings=[],
                recommendations=[],
            ),
        ],
        recommendations={"scalability": ["Add horizontal scaling"], "security": ["Add rate limiting"]},
    )

    return PipelineResult(
        design=design,
        evaluation=evaluation,
        attempts=1,
        final_style="actor-based",
        quality_metrics=QualityMetrics(
            scalability=9.0,
            maintainability=8.0,
            reliability=8.5,
            security=8.0,
            performance=7.5,
        ),
        final_quality_score=82.0,
        matched_domains=[
            MatchedDomain(slug="microservices", fusion_score=0.95),
            MatchedDomain(slug="event-driven", fusion_score=0.72),
        ],
        is_fallback=False,
    )


@pytest.fixture
def sample_pipeline_result_fallback():
    """PipelineResult with is_fallback=True and empty matched_domains."""
    design = ArchitectureDesign(
        overview=ArchitectureOverview(
            style=ArchitectureStyle.LAYERED_MONOLITH,
            category=PatternCategory.STRUCTURAL,
            principles=["principle1"],
        ),
        components=[
            Component(
                id="app",
                name="Application",
                type="application",
                description="Monolithic application core",
                responsibilities=["business logic"],
            ),
        ],
        relationships=[],
        quality_attributes={},
        api_contracts=[],
        shared_data_models=[],
        event_contracts=[],
    )

    evaluation = ArchitectureEvaluation(
        summary=EvaluationSummary(
            overall_score=60.0,
            strengths=[],
            weaknesses=["Fallback pattern — limited domain match"],
            critical_findings=["Used layered-monolith fallback"],
        ),
        metrics=[
            MetricResult(
                name="overall_quality",
                score=60.0,
                description="",
                findings=[],
                recommendations=[],
            ),
        ],
        recommendations={},
    )

    return PipelineResult(
        design=design,
        evaluation=evaluation,
        attempts=3,
        final_style="layered-monolith",
        final_quality_score=60.0,
        matched_domains=[],
        is_fallback=True,
    )


class TestSubmitArchitectureDesignJobTool:
    """Test suite for SubmitArchitectureDesignJobTool."""

    def test_factory_function(self, mock_agent, mock_pipeline):
        """DP-4: Factory function creates a properly initialised tool."""
        tool = submit_architecture_design_job_tool(
            agent=mock_agent, pipeline=mock_pipeline
        )
        assert tool is not None
        assert isinstance(tool, SubmitArchitectureDesignJobTool)
        assert tool._agent is mock_agent
        assert tool._pipeline is mock_pipeline

    @pytest.mark.asyncio
    async def test_submit_job_returns_job_id_and_pending_job(
        self, mock_agent, mock_pipeline, jobs_store: JobsStore
    ):
        """submit_job returns immediately with a job_id and stores a PENDING job."""
        tool = SubmitArchitectureDesignJobTool(agent=mock_agent, pipeline=mock_pipeline)
        result = await tool.submit_job(
            requirements="Build a scalable ETL pipeline",
            domain="data engineering",
        )

        assert "job_id" in result
        assert result["status"] == "pending"
        job = await jobs_store.get_job(result["job_id"])
        assert job is not None
        assert job["status"] == "pending"
        assert job["requirements"] == "Build a scalable ETL pipeline"
        assert job["domain"] == "data engineering"
        assert job["override_style"] is None


class TestPipelineResultToOutputParity:
    """Verify pipeline_result_to_output produces identical fields to DesignArchitectureOutput."""

    def test_all_eight_fields_present(self, sample_pipeline_result):
        """
        pipeline_result_to_output must include all DesignArchitectureOutput fields.

        FR-224 / parity: design_architecture and the async job path must return
        the same field set.
        """
        output = pipeline_result_to_output(sample_pipeline_result)
        dump = output.model_dump()

        expected_keys = {
            "design",
            "evaluation",
            "attempts",
            "final_style",
            "quality_metrics",
            "final_quality_score",
            "matched_domains",
            "is_fallback",
            "alternative_styles",
        }
        assert set(dump.keys()) == expected_keys

    def test_matched_domains_values(self, sample_pipeline_result):
        """matched_domains must serialize with slug and fusion_score."""
        output = pipeline_result_to_output(sample_pipeline_result)
        dump = output.model_dump()

        assert len(dump["matched_domains"]) == 2
        assert dump["matched_domains"][0]["slug"] == "microservices"
        assert dump["matched_domains"][0]["fusion_score"] == 0.95
        assert dump["matched_domains"][1]["slug"] == "event-driven"
        assert dump["matched_domains"][1]["fusion_score"] == 0.72

    def test_is_fallback_false(self, sample_pipeline_result):
        """is_fallback=False when domain matched."""
        output = pipeline_result_to_output(sample_pipeline_result)
        assert output.is_fallback is False
        assert output.model_dump()["is_fallback"] is False

    def test_is_fallback_true(self, sample_pipeline_result_fallback):
        """is_fallback=True and matched_domains=[] when using fallback pattern."""
        output = pipeline_result_to_output(sample_pipeline_result_fallback)
        dump = output.model_dump()
        assert dump["is_fallback"] is True
        assert dump["matched_domains"] == []

    def test_parity_with_design_architecture_output_keys(
        self, sample_pipeline_result
    ):
        """
        Keys of pipeline_result_to_output dump must exactly match
        keys of DesignArchitectureOutput(...).model_dump().

        This is the canonical parity assertion: both code paths produce
        structurally identical output.
        """
        expected_keys = set(DesignArchitectureOutput().model_dump().keys())
        actual_keys = set(pipeline_result_to_output(sample_pipeline_result).model_dump().keys())
        assert actual_keys == expected_keys


class TestRunJobStoresAllFields:
    """Test that _run_job stores a result with all fields including matched_domains, is_fallback, and alternative_styles."""

    @pytest.mark.asyncio
    async def test_run_job_stores_matched_domains_and_is_fallback(
        self,
        mock_agent,
        mock_pipeline,
        sample_pipeline_result,
        jobs_store: JobsStore,
    ):
        """
        After _run_job completes, the stored result JSON must contain
        matched_domains and is_fallback fields (FR-224 parity fix).
        """
        mock_pipeline.run_design.return_value = sample_pipeline_result
        tool = SubmitArchitectureDesignJobTool(agent=mock_agent, pipeline=mock_pipeline)

        job_id = await jobs_store.create_job(
            requirements="Build a scalable ETL pipeline",
            domain="data engineering",
        )

        await tool._run_job(
            job_id=job_id,
            requirements="Build a scalable ETL pipeline",
            domain="data engineering",
            override_style=None,
        )

        job = await jobs_store.get_job(job_id)
        assert job["status"] == "completed"

        stored_result = json.loads(job["result"])
        assert "matched_domains" in stored_result
        assert stored_result["matched_domains"][0]["slug"] == "microservices"
        assert stored_result["matched_domains"][0]["fusion_score"] == 0.95
        assert "is_fallback" in stored_result
        assert stored_result["is_fallback"] is False
        assert "final_style_score" not in stored_result
        assert stored_result["design"]["overview"]["score"] == 87.5

    @pytest.mark.asyncio
    async def test_run_job_stores_fallback_fields(
        self,
        mock_agent,
        mock_pipeline,
        sample_pipeline_result_fallback,
        jobs_store: JobsStore,
    ):
        """Fallback case: is_fallback=True and matched_domains=[] must be stored."""
        mock_pipeline.run_design.return_value = sample_pipeline_result_fallback
        tool = SubmitArchitectureDesignJobTool(agent=mock_agent, pipeline=mock_pipeline)

        job_id = await jobs_store.create_job(
            requirements="Build a system",
            domain="unknown-domain-xyz",
        )

        await tool._run_job(
            job_id=job_id,
            requirements="Build a system",
            domain="unknown-domain-xyz",
            override_style=None,
        )

        job = await jobs_store.get_job(job_id)
        stored_result = json.loads(job["result"])
        assert stored_result["is_fallback"] is True
        assert stored_result["matched_domains"] == []


class TestGetArchitectureDesignStatusReturnsAllFields:
    """Test that get_architecture_design_status surfaces all 8 fields when completed."""

    @pytest.mark.asyncio
    async def test_get_status_returns_matched_domains_and_is_fallback(
        self,
        mock_agent,
        mock_pipeline,
        sample_pipeline_result,
        jobs_store: JobsStore,
    ):
        """
        get_architecture_design_status must return the full 8-field result
        (including matched_domains and is_fallback) when status is completed.
        """
        mock_pipeline.run_design.return_value = sample_pipeline_result
        tool = SubmitArchitectureDesignJobTool(agent=mock_agent, pipeline=mock_pipeline)

        job_id = await jobs_store.create_job(
            requirements="Build a scalable ETL pipeline",
            domain="data engineering",
        )
        await tool._run_job(
            job_id=job_id,
            requirements="Build a scalable ETL pipeline",
            domain="data engineering",
            override_style=None,
        )

        status_tool = GetArchitectureDesignStatusTool()
        status = await status_tool.get_status(job_id=job_id)

        assert status["status"] == "completed"
        assert "result" in status

        result = status["result"]
        assert "matched_domains" in result
        assert result["matched_domains"][0]["slug"] == "microservices"
        assert result["matched_domains"][0]["fusion_score"] == 0.95
        assert "is_fallback" in result
        assert result["is_fallback"] is False

    @pytest.mark.asyncio
    async def test_get_status_returns_error_on_failure(
        self,
        mock_agent,
        mock_pipeline,
        jobs_store: JobsStore,
    ):
        """Failed jobs must return the error string instead of raising."""
        mock_pipeline.run_design.side_effect = RuntimeError("LLM provider unreachable")
        tool = SubmitArchitectureDesignJobTool(agent=mock_agent, pipeline=mock_pipeline)

        job_id = await jobs_store.create_job(
            requirements="Build a system",
            domain="data engineering",
        )
        await tool._run_job(
            job_id=job_id,
            requirements="Build a system",
            domain="data engineering",
            override_style=None,
        )

        status_tool = GetArchitectureDesignStatusTool()
        status = await status_tool.get_status(job_id=job_id)

        assert status["status"] == "failed"
        assert "error" in status
        assert "LLM provider" in status["error"]
