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
Architecture analysis result schema.

Output from the ANALYZE phase of the pipeline.
"""

from pydantic import BaseModel, Field

from src.schemas.patterns import ScoredPattern
from src.schemas.quality import QualityMetrics


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
