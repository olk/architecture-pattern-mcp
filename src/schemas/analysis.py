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
Architecture analysis result schemas.

Output from the ANALYZE phase of the pipeline, including requirement-priority
weights extracted from the requirements text.
"""

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.patterns import ScoredPattern
from src.schemas.quality import QualityMetrics

# Canonical quality-attribute keys present in every pattern's quality_attributes.
# Verified uniform across the 35-pattern catalogue. Used for deterministic
# requirements-aware scoring of candidates in the analyze phase.
QUALITY_ATTRIBUTE_KEYS: tuple[str, ...] = (
    "scalability",
    "maintainability",
    "reliability",
    "security",
    "performance",
    "simplicity",
)


class RequirementWeights(BaseModel):
    """Requirement priority weights (0.0-1.0) extracted from requirements.

    Produced by a single LLM call in the analyze phase. Each weight expresses
    how strongly the requirements emphasise that quality attribute. Consumed
    by the analyze phase's deterministic pattern scoring, and surfaced in the
    GENERATE user prompt so the model can weigh design trade-offs against
    the stated priorities.
    """

    model_config = ConfigDict(extra="allow")

    scalability: float = Field(default=0.0, ge=0.0, le=1.0)
    maintainability: float = Field(default=0.0, ge=0.0, le=1.0)
    reliability: float = Field(default=0.0, ge=0.0, le=1.0)
    security: float = Field(default=0.0, ge=0.0, le=1.0)
    performance: float = Field(default=0.0, ge=0.0, le=1.0)
    simplicity: float = Field(default=0.0, ge=0.0, le=1.0)

    def as_dict(self) -> dict[str, float]:
        """Return the weights keyed by quality-attribute name."""
        return {k: float(getattr(self, k)) for k in QUALITY_ATTRIBUTE_KEYS}


class MatchedDomain(BaseModel):
    """
    A resolved architecture domain slug from the BM25+FAISS hybrid retriever.

    Returned in tool outputs so calling agents can see which domain slugs
    were matched and how confidently (fusion score and, when reranking ran,
    cross-encoder rerank logit).
    """

    slug: str = Field(..., description="ArchitectureDomain slug (e.g. 'e-commerce', 'payment-processing')")
    fusion_score: float = Field(..., description="RRF fusion score for this slug (higher = better match)")
    rerank_score: float | None = Field(
        default=None,
        description="Cross-encoder rerank logit for this slug (None when reranking did not run).",
    )


class StyleCandidate(BaseModel):
    """
    A runner-up architecture pattern from the analyze phase.

    Surfaced in design tool outputs so calling agents can see which other
    patterns the analyzer scored highly but the pipeline did not select as
    the final architecture. Excludes the entry whose name equals the
    ``final_style`` actually delivered; empty when the pipeline fell back
    to the default pattern.
    """

    name: str = Field(
        ...,
        description="ArchitectureStyle value of the runner-up pattern (e.g. 'kappa-architecture')",
    )
    score: float = Field(
        ...,
        description=(
            "Effective sort score from the analyze phase (blended_score when blending is active, "
            "otherwise analysis_score)"
        ),
    )


class AnalysisResult(BaseModel):
    """
    Result of architecture requirements analysis.

    Contains strengths, weaknesses, recommendations, quality metrics,
    and selected patterns from the ANALYZE phase.
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
    quality_metrics: QualityMetrics | None = Field(
        default=None,
        description="Quality assessment metrics"
    )
    recommended_style: str = Field(
        ...,
        description="Architecture style best suited for the requirements"
    )
    selected_patterns: list[ScoredPattern] = Field(
        default_factory=list,
        description="Patterns selected during analysis, ordered by analysis_score descending",
    )
    matched_domains: list[MatchedDomain] = Field(
        default_factory=list,
        description="Top matched ArchitectureDomain slugs from BM25+FAISS retrieval (max 5, ordered by fusion score)"
    )
    is_fallback: bool = Field(
        default=False,
        description="True when no real domain match was found and the fallback 'layered-monolith' pattern was used"
    )
