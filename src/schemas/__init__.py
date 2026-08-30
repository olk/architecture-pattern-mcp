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
Schema package — Pydantic v2 models for MCP architecture pattern system.

Exports all typed schemas for FastMCP tool I/O boundaries and validation.

Modules:
- enums: PatternCategory, ArchitectureDomain, ArchitectureStyle
- quality: QualityMetrics
- contracts: ApiEndpoint, ApiContract, ModelField, DataModel, EventContract
- components: Component, Relationship
- deployment: (removed)
- evaluation: MetricResult, EvaluationSummary, ArchitectureEvaluation, PipelineResult
- patterns: Pattern
- design: ArchitectureOverview, ArchitectureDesign
- analysis: AnalysisResult
- architecture: ArchitectureOverviewWire (LLM-facing overview, reasoning required)
              ArchitectureDesignResponse (LLM wire schema — dict-based, lax validation)
              ArchitectureDesignResponseWire (lean wire schema for generation)
"""

from src.schemas.analysis import AnalysisResult
from src.schemas.architecture import (
    ArchitectureDesignResponse,
    ArchitectureDesignResponseWire,
    ArchitectureOverviewWire,
)
from src.schemas.contracts import (
    ApiContract,
    ApiEndpoint,
    DataModel,
    EventContract,
    ModelField,
)
from src.schemas.components import Component, Relationship

from src.schemas.design import ArchitectureDesign, ArchitectureOverview
from src.schemas.enums import (
    ArchitectureDomain,
    ArchitectureStyle,
    PatternCategory,
)
from src.schemas.evaluation import (
    ArchitectureEvaluation,
    EvaluationSummary,
    MetricResult,
    PipelineResult,
)
from src.schemas.patterns import Pattern
from src.schemas.quality import QualityMetrics

__all__ = [
    # enums
    "ArchitectureDomain",
    "ArchitectureStyle",
    "PatternCategory",
    # quality
    "QualityMetrics",
    # contracts
    "ApiContract",
    "ApiEndpoint",
    "DataModel",
    "EventContract",
    "ModelField",
    # components
    "Component",
    "Relationship",
    # evaluation
    "ArchitectureEvaluation",
    "EvaluationSummary",
    "MetricResult",
    "PipelineResult",
    # patterns
    "Pattern",
    # design
    "ArchitectureDesign",
    "ArchitectureOverview",
    # analysis
    "AnalysisResult",
    # architecture (LLM wire schema)
    "ArchitectureOverviewWire",
    "ArchitectureDesignResponse",
    "ArchitectureDesignResponseWire",
]
