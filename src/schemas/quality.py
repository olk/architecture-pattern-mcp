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

# QualityMetrics Pydantic Model
# FR-17: ArchitecturePipeline uses QualityMetrics for quality assessment
# FR-18: The system SHALL support a testability property with default value 7.0 (range 0-10)
# IC-10: QualityMetrics type SHALL have exactly 5 properties with values in range 0-10
# IC-11: testability property SHALL default to 7.0 with range 0-10
# ENT-1: QualityMetrics - Quality assessment metrics for architecture evaluation

from pydantic import BaseModel, Field


class QualityMetrics(BaseModel):
    """Quality assessment metrics for architecture evaluation.
    
    This model represents quality attributes used to score designs based on
    their alignment with user priorities. Used by ArchitecturePipeline for
    quality-weighted scoring.
    
    Attributes:
        maintainability: Code maintainability score (0-10)
        scalability: System scalability score (0-10)
        reliability: System reliability score (0-10)
        security: System security score (0-10)
        performance: System performance score (0-10)
        testability: System testability score (0-10), defaults to 7.0
    """

    # IC-10: 5 required properties with values in range 0-10
    # Each property uses Field constraints for validation: ge=0.0, le=10.0
    maintainability: float = Field(
        ...,
        description="Code maintainability",
        ge=0.0,
        le=10.0
    )
    scalability: float = Field(
        ...,
        description="System scalability",
        ge=0.0,
        le=10.0
    )
    reliability: float = Field(
        ...,
        description="System reliability",
        ge=0.0,
        le=10.0
    )
    security: float = Field(
        ...,
        description="System security",
        ge=0.0,
        le=10.0
    )
    performance: float = Field(
        ...,
        description="System performance",
        ge=0.0,
        le=10.0
    )

    # IC-11: testability property defaults to 7.0 with range 0-10
    # FR-18: testability property with default value 7.0
    testability: float = Field(
        default=7.0,
        description="System testability",
        ge=0.0,
        le=10.0
    )
