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
Tool adapters — converts internal pipeline dataclasses to typed Pydantic models.

Used at the FastMCP tool boundary to produce validated typed output.
All conversions use Pydantic lax mode (the default) to handle LLM-friendly coercion.

Pipeline dataclasses (internal, unchanged):
    AnalysisResult, ArchitectureDesign, ArchitectureEvaluation, RefinedArchitecture

Typed Pydantic models (FastMCP I/O boundary):
    AnalyzeArchitectureOutput, GenerateArchitectureOutput, EvaluateArchitectureOutput,
    DesignArchitectureOutput, plus the shared schema types they reference.

Validation contract:
    Adapter helpers raise MalformedArchitectureOverviewError (ERR_012) when
    input data fails strict Pydantic validation.  Tool handlers map that to
    ToolError so the MCP client can retry with corrected input.
    No silent placeholder synthesis occurs at the adapter boundary.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from src.errors import ERROR_INVALID_ARCHITECTURE, MalformedArchitectureOverviewError

if TYPE_CHECKING:
    from src.pipeline import (
        AnalysisResult as AnalysisResultDC,
    )

from src.schemas import (
    ArchitectureDesign,
    ArchitectureOverview,
    Component,
    DataModel,
    EventContract,
    ModelField,
    Relationship,
    QualityMetrics as QualityMetricsPD,
)
from src.schemas.analysis import AnalysisResult, MatchedDomain
from src.schemas.patterns import ScoredPattern
from src.schemas.contracts import ApiContract, ApiEndpoint
from src.schemas.quality import QualityMetrics as QualityMetricsDC

logger = logging.getLogger(__name__)


def _lint_convert[T](klass: type[T], data: dict[str, Any]) -> T:
    """Coerce a dict to a typed Pydantic model using lax validation."""
    return klass.model_validate(data)  # type: ignore[return-value]


def _safe_preview(data: dict[str, Any], max_len: int = 200) -> dict[str, Any]:
    """Return a redacted preview of untrusted input for logging."""
    preview: dict[str, Any] = {}
    for k, v in list(data.items())[:10]:
        if isinstance(v, str) and len(v) > max_len:
            preview[k] = v[:max_len] + "..."
        else:
            preview[k] = v
    return preview


# ─── QualityMetrics ────────────────────────────────────────────────────────────


def quality_metrics_to_pydantic(dc: QualityMetricsDC | None) -> QualityMetricsPD | None:
    """Convert pipeline QualityMetrics dataclass to typed Pydantic model."""
    if dc is None:
        return None
    return QualityMetricsPD(
        maintainability=dc.maintainability,
        scalability=dc.scalability,
        reliability=dc.reliability,
        security=dc.security,
        performance=dc.performance,
        testability=dc.testability,
    )


# ─── AnalysisResult ───────────────────────────────────────────────────────────


def analysis_to_pydantic(dc: AnalysisResultDC) -> AnalysisResult:
    """
    Convert pipeline AnalysisResult dataclass to typed AnalysisResult Pydantic model.

    Handles:
    - quality_metrics: QualityMetrics | None → QualityMetricsPD | None
    - selected_patterns: list[dict] → list[ScoredPattern] (preserves analysis_score
      and fusion_score metadata injected by the two-stage analyze phase)
    - All other fields passed through directly (names match between DC and Pydantic)
    """
    qm = quality_metrics_to_pydantic(dc.quality_metrics)

    patterns: list[ScoredPattern] = []
    for p in dc.selected_patterns:
        if isinstance(p, ScoredPattern):
            patterns.append(p)
        elif hasattr(p, "model_dump"):
            patterns.append(ScoredPattern.model_validate(p.model_dump()))
        elif isinstance(p, dict):
            patterns.append(_lint_convert(ScoredPattern, p))

    matched_domains = [
        MatchedDomain(
            slug=d["slug"],
            fusion_score=d["fusion_score"],
            rerank_score=d.get("rerank_score"),
        )
        for d in dc.matched_domains
    ]

    return AnalysisResult(
        strengths=list(dc.strengths),
        weaknesses=list(dc.weaknesses),
        recommendations=list(dc.recommendations),
        quality_metrics=qm,
        recommended_style=dc.recommended_style,
        selected_patterns=patterns,
        matched_domains=matched_domains,
        is_fallback=bool(dc.is_fallback),
    )


# ─── ArchitectureDesign ───────────────────────────────────────────────────────


def design_from_dict(data: dict[str, Any]) -> ArchitectureDesign:
    """
    Convert a raw dict (from API/MCP input) to typed ArchitectureDesign Pydantic model.

    This is the entry point for tool input that arrives as unstructured dicts
    before being passed to the pipeline layer.

    Raises MalformedArchitectureOverviewError (ERR_012) when the overview
    fails validation.
    """
    components = [_parse_component(c) for c in data.get("components", [])]
    relationships = [_parse_relationship(r) for r in data.get("relationships", [])]
    event_contracts = [_parse_event_contract(e) for e in data.get("event_contracts", [])]

    return ArchitectureDesign(
        overview=_parse_overview(data.get("overview", {})),
        components=components,
        relationships=relationships,
        quality_attributes=dict(data.get("quality_attributes", {})),
        api_contracts=[],
        shared_data_models=[_lint_convert(DataModel, d) for d in data.get("shared_data_models", [])],
        event_contracts=event_contracts,
    )


def _parse_overview(data: dict[str, Any]) -> ArchitectureOverview:
    """
    Validate and convert a raw overview dict to ArchitectureOverview.

    Raises MalformedArchitectureOverviewError (ERR_012) when required fields
    (style, category, principles[min_length=1]) fail Pydantic validation.
    No silent fallback is synthesised — the caller (tool handler) propagates
    the error to the MCP client.
    """
    try:
        return ArchitectureOverview.model_validate(data)
    except ValidationError as exc:
        logger.warning(
            "Malformed architecture overview: %s",
            exc.errors(include_url=False),
            extra={"payload_preview": _safe_preview(data)},
        )
        raise MalformedArchitectureOverviewError(
            code=ERROR_INVALID_ARCHITECTURE,
            locator="overview",
            errors=exc.errors(),
        ) from exc


def _parse_component(data: dict[str, Any]) -> Component:
    if isinstance(data, Component):
        return data
    api_contract = None
    if data.get("api_contract"):
        try:
            ac_data = data["api_contract"]
            endpoints = [
                ApiEndpoint(
                    method=e["method"],
                    path=e["path"],
                    summary=e.get("summary", ""),
                    request_schema=e.get("request_schema"),
                    response_schema=e.get("response_schema"),
                    auth_required=e.get("auth_required", True),
                    tags=list(e.get("tags", [])),
                )
                for e in ac_data.get("endpoints", [])
            ]
            api_contract = ApiContract(
                component_id=ac_data.get("component_id", ""),
                base_path=ac_data.get("base_path", ""),
                endpoints=endpoints,
                description=ac_data.get("description", ""),
            )
        except (KeyError, TypeError):
            pass

    data_models = []
    for dm in data.get("data_models", []):
        if isinstance(dm, dict):
            data_models.append(
                DataModel(
                    name=dm.get("name", ""),
                    fields=[
                        ModelField(
                            name=f.get("name", ""),
                            type=f.get("type", "str"),
                            required=f.get("required", True),
                            description=f.get("description", ""),
                            default=f.get("default"),
                        )
                        for f in dm.get("fields", [])
                    ],
                    description=dm.get("description", ""),
                    is_shared=dm.get("is_shared", False),
                )
            )

    description = data.get("description", "")
    if not description:
        description = data.get("name", "Component")
    responsibilities = list(data.get("responsibilities", []))
    if not responsibilities:
        responsibilities = [f"Handle {data.get('name', 'component')} responsibilities"]

    return Component(
        id=data.get("id", ""),
        name=data.get("name", ""),
        type=data.get("type", ""),
        description=description,
        responsibilities=responsibilities,
        interfaces=list(data.get("interfaces", [])),
        technology_stack=list(data.get("technology_stack", [])),
        api_contract=api_contract,
        data_models=data_models,
        config_requirements=list(data.get("config_requirements", [])),
    )


def _parse_relationship(data: dict[str, Any]) -> Relationship:
    if isinstance(data, Relationship):
        return data
    return Relationship(
        source=data.get("source", ""),
        target=data.get("target", ""),
        type=data.get("type", ""),
        description=data.get("description", ""),
    )


def _parse_event_contract(data: dict[str, Any]) -> EventContract:
    if isinstance(data, EventContract):
        return data
    return EventContract(
        event_name=data.get("event_name", ""),
        payload_schema=data.get("payload_schema", {}),
        published_by=data.get("published_by", ""),
        consumed_by=list(data.get("consumed_by", [])),
        description=data.get("description", ""),
    )


def design_to_pydantic(dc: ArchitectureDesign | dict[str, Any]) -> ArchitectureDesign:
    """
    Convert pipeline ArchitectureDesign to typed ArchitectureDesign Pydantic model.

    If already an ArchitectureDesign, validates and returns.
    If a dict, validates as ArchitectureDesign.
    Uses lax validation — Pydantic coerces compatible types automatically.

    Raises MalformedArchitectureOverviewError (ERR_012) when the overview
    fails validation.
    """
    if isinstance(dc, dict):
        dc = ArchitectureDesign.model_validate(dc)
    return dc

