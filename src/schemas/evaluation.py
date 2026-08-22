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
Architecture evaluation and pipeline result schemas.

Defines quality assessment and pipeline output structures.
"""

from pydantic import BaseModel, Field

from src.schemas.analysis import MatchedDomain
from src.schemas.design import ArchitectureDesign
from src.schemas.quality import QualityMetrics


class MetricResult(BaseModel):
    """
    Individual quality metric assessment result.
    """

    name: str = Field(
        ...,
        description="Metric name (e.g. 'scalability', 'maintainability')"
    )
    score: float = Field(
        ...,
        ge=0,
        le=100,
        description="Assessment score (0-100)"
    )
    description: str = Field(
        ...,
        description="Metric description"
    )
    findings: list[str] = Field(
        default_factory=list,
        description="Supporting findings for this metric"
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Recommendations to improve this metric"
    )


class EvaluationSummary(BaseModel):
    """
    High-level evaluation summary with score and key findings.
    """

    overall_score: float = Field(
        ...,
        ge=0,
        le=100,
        description="Overall architecture quality score"
    )
    strengths: list[str] = Field(
        default_factory=list,
        description="Architecture strengths"
    )
    weaknesses: list[str] = Field(
        default_factory=list,
        description="Architecture weaknesses"
    )
    critical_findings: list[str] = Field(
        default_factory=list,
        description="Critical findings that must be addressed"
    )


class ArchitectureEvaluation(BaseModel):
    """
    Complete architecture evaluation result.

    Contains metric assessments and recommendations.
    """

    summary: EvaluationSummary = Field(
        ...,
        description="High-level evaluation summary"
    )
    metrics: list[MetricResult] = Field(
        ...,
        description="Per-metric assessment results"
    )
    recommendations: dict[str, list[str]] = Field(
        ...,
        description="Recommendations keyed by area (e.g. {'scalability': [...], 'security': [...]})"
    )


class PipelineResult(BaseModel):
    """
    Complete pipeline output combining design, evaluation, and metadata.

    Returned by the full architecture pipeline (analyze → generate → evaluate → design_loop).
    """

    design: ArchitectureDesign = Field(
        ...,
        description="ArchitectureDesign"
    )
    evaluation: ArchitectureEvaluation = Field(
        ...,
        description="ArchitectureEvaluation"
    )
    attempts: int = Field(
        ...,
        ge=1,
        description="Total generate attempts made (initial + retries)"
    )
    final_style: str = Field(
        ...,
        description="Final architecture style"
    )
    quality_metrics: QualityMetrics | None = Field(
        default=None,
        description="Aggregated quality metrics"
    )
    final_quality_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Final quality score after best attempt"
    )
    matched_domains: list[MatchedDomain] = Field(
        default_factory=list,
        description="Top matched ArchitectureDomain slugs from BM25+FAISS retrieval (max 5)"
    )
    is_fallback: bool = Field(
        default=False,
        description="True when no real domain match was found and the fallback 'layered-monolith' pattern was used"
    )
