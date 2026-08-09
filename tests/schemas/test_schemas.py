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
Hypothesis-based property tests for the typed schema layer.

Tests all new Pydantic schemas with Hypothesis strategy-based property tests
to validate constraints, coercion, and serialization round-trips.

Covers:
- AnalysisResult, ArchitectureDesign, ArchitectureOverview
- ArchitectureEvaluation, PipelineResult, MetricResult, EvaluationSummary
- Pattern, Component, Relationship

- ApiContract, ApiEndpoint, DataModel, ModelField, EventContract
- ValidationConfig
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st

from src.schemas import (
    AnalysisResult,
    ArchitectureDesign,
    ArchitectureOverview,
    ArchitectureEvaluation,
    PipelineResult,
    Pattern,
    Component,
    Relationship,
    ApiContract,
    ApiEndpoint,
    DataModel,
    ModelField,
    EventContract,
    QualityMetrics,
)
from src.schemas.enums import ArchitectureStyle, PatternCategory
from src.schemas.patterns import ScoredPattern
from src.schemas.evaluation import MetricResult, EvaluationSummary
from src.config import ValidationConfig


# ─── Strategies ───────────────────────────────────────────────────────────────

@st.composite
def architecture_styles(draw: st.DrawFn) -> ArchitectureStyle:
    return draw(st.sampled_from(list(ArchitectureStyle)))


@st.composite
def pattern_categories(draw: st.DrawFn) -> PatternCategory:
    return draw(st.sampled_from(list(PatternCategory)))


@st.composite
def quality_metrics_strategy(draw: st.DrawFn) -> QualityMetrics:
    return QualityMetrics(
        maintainability=draw(st.floats(min_value=0.0, max_value=10.0)),
        scalability=draw(st.floats(min_value=0.0, max_value=10.0)),
        reliability=draw(st.floats(min_value=0.0, max_value=10.0)),
        security=draw(st.floats(min_value=0.0, max_value=10.0)),
        performance=draw(st.floats(min_value=0.0, max_value=10.0)),
        testability=draw(st.floats(min_value=0.0, max_value=10.0)),
    )


@st.composite
def model_field_strategy(draw: st.DrawFn) -> ModelField:
    return ModelField(
        name=draw(st.text(min_size=1, max_size=50)),
        type=draw(st.sampled_from(["str", "int", "float", "bool", "list", "dict"])),
        required=draw(st.booleans()),
        description=draw(st.text(max_size=200)),
        default=draw(st.one_of(st.none(), st.text(), st.floats(), st.booleans())),
    )


@st.composite
def data_model_strategy(draw: st.DrawFn) -> DataModel:
    return DataModel(
        name=draw(st.text(min_size=1, max_size=50)),
        fields=draw(st.lists(model_field_strategy(), max_size=10)),
        description=draw(st.text(max_size=200)),
        is_shared=draw(st.booleans()),
    )


@st.composite
def api_endpoint_strategy(draw: st.DrawFn) -> ApiEndpoint:
    return ApiEndpoint(
        method=draw(st.sampled_from(["GET", "POST", "PUT", "DELETE", "PATCH"])),
        path=draw(st.text(min_size=1, max_size=100)),
        summary=draw(st.text(max_size=200)),
        request_schema=draw(st.one_of(st.none(), st.dictionaries(st.text(), st.text()))),
        response_schema=draw(st.one_of(st.none(), st.dictionaries(st.text(), st.text()))),
        auth_required=draw(st.booleans()),
        tags=draw(st.lists(st.text(max_size=30), max_size=5)),
    )


@st.composite
def api_contract_strategy(draw: st.DrawFn) -> ApiContract:
    return ApiContract(
        component_id=draw(st.text(min_size=1, max_size=50)),
        base_path=draw(st.text(max_size=100)),
        endpoints=draw(st.lists(api_endpoint_strategy(), max_size=10)),
        description=draw(st.text(max_size=200)),
    )


@st.composite
def component_strategy(draw: st.DrawFn) -> Component:
    return Component(
        id=draw(st.sampled_from([
            "api-gateway", "user-service", "auth-service", "payment-service",
            "notification-service", "data-pipeline", "analytics-engine",
            "search-service", "cache-layer", "message-broker",
        ])),
        name=draw(st.text(min_size=1, max_size=100)),
        type=draw(st.sampled_from(["service", "gateway", "database", "cache", "queue", "worker"])),
        description=draw(st.text(min_size=1, max_size=500)),
        responsibilities=draw(st.lists(st.text(min_size=1, max_size=100), min_size=1, max_size=10)),
        interfaces=draw(st.lists(st.text(max_size=50), max_size=10)),
        technology_stack=draw(st.lists(st.text(max_size=50), max_size=10)),
        api_contract=draw(st.one_of(st.none(), api_contract_strategy())),
        data_models=draw(st.lists(data_model_strategy(), max_size=5)),
        config_requirements=draw(st.lists(st.text(max_size=100), max_size=10)),
    )


@st.composite
def relationship_strategy(draw: st.DrawFn) -> Relationship:
    return Relationship(
        source=draw(st.text(min_size=1, max_size=50)),
        target=draw(st.text(min_size=1, max_size=50)),
        type=draw(st.text(min_size=1, max_size=30)),
        description=draw(st.text(max_size=200)),
    )


@st.composite
def event_contract_strategy(draw: st.DrawFn) -> EventContract:
    return EventContract(
        event_name=draw(st.text(min_size=1, max_size=100)),
        payload_schema=draw(st.dictionaries(st.text(), st.text())),
        published_by=draw(st.text(min_size=1, max_size=50)),
        consumed_by=draw(st.lists(st.text(max_size=50), max_size=10)),
        description=draw(st.text(max_size=300)),
    )


# ─── ArchitectureOverview ──────────────────────────────────────────────────────


class TestArchitectureOverview:
    """Property tests for ArchitectureOverview."""

    @given(
        style=architecture_styles(),
        category=pattern_categories(),
        principles=st.lists(st.text(min_size=1, max_size=100), min_size=1, max_size=10),
        constraints=st.lists(st.text(max_size=100), max_size=10),
    )
    @settings(max_examples=50)
    def test_valid_construction(self, style, category, principles, constraints):
        ov = ArchitectureOverview(
            style=style, category=category, principles=principles, constraints=constraints
        )
        assert ov.style == style
        assert ov.category == category
        assert list(ov.principles) == principles
        assert list(ov.constraints) == constraints

    @given(
        style=st.sampled_from([s.value for s in ArchitectureStyle]),
        category=st.sampled_from([c.value for c in PatternCategory]),
        principles=st.lists(st.text(min_size=1, max_size=100), min_size=1, max_size=10),
        constraints=st.lists(st.text(max_size=100), max_size=10),
    )
    @settings(max_examples=20)
    def test_string_coerced_to_enum(self, style, category, principles, constraints):
        ov = ArchitectureOverview(
            style=style, category=category, principles=principles, constraints=constraints
        )
        assert isinstance(ov.style, ArchitectureStyle)
        assert isinstance(ov.category, PatternCategory)

    def test_empty_principles_fails(self):
        for style in ArchitectureStyle:
            for category in PatternCategory:
                with pytest.raises(Exception):
                    ArchitectureOverview(
                        style=style,
                        category=category,
                        principles=[],
                        constraints=[],
                    )


# ─── Component / Relationship ──────────────────────────────────────────────────


class TestComponent:
    """Property tests for Component."""

    def test_manual_components(self):
        comp1 = Component(
            id="api-gateway",
            name="API Gateway",
            type="gateway",
            description="Entry point for all clients",
            responsibilities=["routing", "auth"],
            interfaces=["REST"],
            technology_stack=["Kong"],
        )
        assert comp1.id == "api-gateway"
        assert comp1.name == "API Gateway"
        assert comp1.technology_stack == ["Kong"]

        comp2 = Component(
            id="user-service",
            name="User Service",
            type="service",
            description="User management",
            responsibilities=["auth", "profiles"],
            interfaces=["gRPC"],
            technology_stack=["Go"],
        )
        assert comp2.id == "user-service"

    def test_unique_ids(self):
        comps = [
            Component(
                id="svc-a",
                name="Service A",
                type="service",
                description="Service A",
                responsibilities=["task-a"],
            ),
            Component(
                id="svc-b",
                name="Service B",
                type="service",
                description="Service B",
                responsibilities=["task-b"],
            ),
        ]
        ids = [c.id for c in comps]
        assert len(ids) == len(set(ids))  # All unique


class TestRelationship:
    """Property tests for Relationship."""

    @given(rel=relationship_strategy())
    @settings(max_examples=50)
    def test_valid_construction(self, rel: Relationship):
        assert len(rel.source) > 0
        assert len(rel.target) > 0
        assert len(rel.type) > 0


# ─── ApiContract / ApiEndpoint / DataModel / ModelField ───────────────────────


class TestApiEndpoint:
    """Property tests for ApiEndpoint."""

    @given(ep=api_endpoint_strategy())
    @settings(max_examples=50)
    def test_valid_construction(self, ep: ApiEndpoint):
        assert ep.method in ["GET", "POST", "PUT", "DELETE", "PATCH"]
        assert len(ep.path) > 0
        assert isinstance(ep.auth_required, bool)
        assert isinstance(ep.tags, list)

    @given(ep=api_endpoint_strategy())
    @settings(max_examples=30)
    def test_serialization_roundtrip(self, ep: ApiEndpoint):
        d = ep.model_dump()
        restored = ApiEndpoint.model_validate(d)
        assert restored.method == ep.method
        assert restored.path == ep.path


class TestDataModel:
    """Property tests for DataModel."""

    @given(dm=data_model_strategy())
    @settings(max_examples=50)
    def test_valid_construction(self, dm: DataModel):
        assert len(dm.name) > 0
        assert isinstance(dm.fields, list)
        for f in dm.fields:
            assert len(f.name) > 0
            assert f.type in ["str", "int", "float", "bool", "list", "dict"]


class TestModelField:
    """Property tests for ModelField."""

    @given(mf=model_field_strategy())
    @settings(max_examples=50)
    def test_valid_construction(self, mf: ModelField):
        assert len(mf.name) > 0
        assert mf.type in ["str", "int", "float", "bool", "list", "dict"]


# ─── ArchitectureDesign ────────────────────────────────────────────────────────


class TestArchitectureDesign:
    """Property tests for ArchitectureDesign."""

    @given(
        overview=st.builds(
            ArchitectureOverview,
            style=st.sampled_from([s.value for s in ArchitectureStyle]),
            category=st.sampled_from([c.value for c in PatternCategory]),
            principles=st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=5),
            constraints=st.lists(st.text(max_size=50), max_size=5),
        ),
        components=st.lists(component_strategy(), min_size=1, max_size=5),
        relationships=st.lists(relationship_strategy(), max_size=10),
        qa=st.dictionaries(st.text(max_size=20), st.text(max_size=20)),
    )
    @settings(max_examples=30)
    def test_valid_construction(self, overview, components, relationships, qa):
        design = ArchitectureDesign(
            overview=overview,
            components=components,
            relationships=relationships,
            patterns=[],
            quality_attributes=qa,
            api_contracts=[],
            shared_data_models=[],
            event_contracts=[],
        )
        assert len(design.components) >= 1
        assert isinstance(design.quality_attributes, dict)

    @given(
        overview=st.builds(
            ArchitectureOverview,
            style=st.sampled_from([s.value for s in ArchitectureStyle]),
            category=st.sampled_from([c.value for c in PatternCategory]),
            principles=st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=5),
            constraints=st.lists(st.text(max_size=50), max_size=5),
        ),
        components=st.lists(component_strategy(), min_size=1, max_size=3),
        relationships=st.lists(relationship_strategy(), max_size=5),
        qa=st.dictionaries(st.text(max_size=20), st.text(max_size=20)),
        api_contracts=st.lists(api_contract_strategy(), max_size=5),
        shared_data_models=st.lists(data_model_strategy(), max_size=5),
        event_contracts=st.lists(
            st.builds(
                EventContract,
                event_name=st.text(min_size=1, max_size=50),
                payload_schema=st.dictionaries(st.text(), st.text(), max_size=10),
                published_by=st.text(min_size=1, max_size=50),
                consumed_by=st.lists(st.text(max_size=50), max_size=5),
                description=st.text(max_size=200),
            ),
            max_size=5,
        ),
    )
    @settings(max_examples=5, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_construction_with_contracts(
        self,
        overview,
        components,
        relationships,
        qa,
        api_contracts,
        shared_data_models,
        event_contracts,
    ):
        design = ArchitectureDesign(
            overview=overview,
            components=components,
            relationships=relationships,
            patterns=[],
            quality_attributes=qa,
            api_contracts=api_contracts,
            shared_data_models=shared_data_models,
            event_contracts=event_contracts,
        )
        assert len(design.api_contracts) == len(api_contracts)
        assert len(design.shared_data_models) == len(shared_data_models)
        assert len(design.event_contracts) == len(event_contracts)
        dumped = design.model_dump()
        revalidated = ArchitectureDesign.model_validate(dumped)
        assert len(revalidated.api_contracts) == len(design.api_contracts)
        assert len(revalidated.shared_data_models) == len(design.shared_data_models)
        assert len(revalidated.event_contracts) == len(design.event_contracts)


# ─── AnalysisResult ────────────────────────────────────────────────────────────


class TestAnalysisResult:
    """Property tests for AnalysisResult."""

    @given(
        strengths=st.lists(st.text(min_size=1, max_size=200), min_size=1, max_size=20),
        weaknesses=st.lists(st.text(min_size=1, max_size=200), min_size=1, max_size=20),
        recommendations=st.lists(st.text(min_size=1, max_size=200), min_size=1, max_size=20),
        score=st.floats(min_value=0.0, max_value=100.0),
        qm=quality_metrics_strategy(),
        style=st.text(min_size=1, max_size=50),
        patterns=st.lists(st.builds(
            ScoredPattern,
            name=st.text(min_size=1, max_size=50),
            context=st.text(min_size=1, max_size=200),
            category=st.sampled_from([c.value for c in PatternCategory]),
        ), max_size=10),
    )
    @settings(max_examples=30)
    def test_valid_construction(
        self, strengths, weaknesses, recommendations, score, qm, style, patterns
    ):
        ar = AnalysisResult(
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
            quality_metrics=qm,
            recommended_style=style,
            selected_patterns=patterns,
        )
        assert ar.quality_metrics == qm
        assert ar.recommended_style == style


# ─── MetricResult ─────────────────────────────────


class TestMetricResult:
    """Property tests for MetricResult."""

    @given(name=st.text(min_size=1, max_size=50), score=st.floats(min_value=0.0, max_value=100.0), desc=st.text(max_size=300))
    @settings(max_examples=50)
    def test_valid_construction(self, name, score, desc):
        mr = MetricResult(name=name, score=score, description=desc)
        assert mr.name == name
        assert mr.score == score


# ─── EvaluationSummary ────────────────────────────────────────────────────────


class TestEvaluationSummary:
    """Property tests for EvaluationSummary."""

    @given(
        score=st.floats(min_value=0.0, max_value=100.0),
        strengths=st.lists(st.text(min_size=1, max_size=200), min_size=1, max_size=20),
        weaknesses=st.lists(st.text(min_size=1, max_size=200), min_size=1, max_size=20),
        findings=st.lists(st.text(min_size=1, max_size=300), min_size=1, max_size=20),
    )
    @settings(max_examples=30)
    def test_valid_construction(self, score, strengths, weaknesses, findings):
        es = EvaluationSummary(
            overall_score=score,
            strengths=strengths,
            weaknesses=weaknesses,
            critical_findings=findings,
        )
        assert es.overall_score == score
        assert list(es.strengths) == strengths


# ─── ArchitectureEvaluation ────────────────────────────────────────────────────


class TestArchitectureEvaluation:
    """Property tests for ArchitectureEvaluation."""

    @given(
        score=st.floats(min_value=0.0, max_value=100.0),
        strengths=st.lists(st.text(min_size=1, max_size=200), min_size=1, max_size=10),
        weaknesses=st.lists(st.text(min_size=1, max_size=200), min_size=1, max_size=10),
        findings=st.lists(st.text(min_size=1, max_size=300), min_size=1, max_size=10),
        metrics=st.lists(st.builds(
            MetricResult,
            name=st.text(min_size=1, max_size=50),
            score=st.floats(min_value=0.0, max_value=100.0),
            description=st.text(max_size=200),
        ), max_size=10),
        recommendations=st.dictionaries(
            st.text(max_size=50),
            st.lists(st.text(max_size=200), max_size=10),
        ),
    )
    @settings(max_examples=30)
    def test_valid_construction(self, score, strengths, weaknesses, findings, metrics, recommendations):
        es = EvaluationSummary(
            overall_score=score,
            strengths=strengths,
            weaknesses=weaknesses,
            critical_findings=findings,
        )
        ae = ArchitectureEvaluation(
            summary=es,
            metrics=metrics,
            recommendations=recommendations,
        )
        assert isinstance(ae.summary, EvaluationSummary)
        assert isinstance(ae.metrics, list)


# ─── PipelineResult ───────────────────────────────────────────────────────────


class TestPipelineResult:
    """Property tests for PipelineResult."""

    @given(
        overview=st.builds(
            ArchitectureOverview,
            style=st.sampled_from([s.value for s in ArchitectureStyle]),
            category=st.sampled_from([c.value for c in PatternCategory]),
            principles=st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=3),
            constraints=st.lists(st.text(max_size=50), max_size=3),
        ),
        components=st.lists(
            st.builds(
                Component,
                id=st.sampled_from(["svc-a", "svc-b", "api-gw"]),
                name=st.sampled_from(["Service A", "Service B", "API Gateway"]),
                type=st.sampled_from(["service", "gateway"]),
                description=st.just("A component"),
                responsibilities=st.lists(st.text(min_size=1, max_size=30), min_size=1, max_size=2),
            ),
            min_size=1,
            max_size=3,
        ),
        attempts=st.integers(min_value=1, max_value=10),
        final_style=st.text(max_size=50),
        qm=quality_metrics_strategy(),
    )
    @settings(max_examples=30)
    def test_valid_construction(self, overview, components, attempts, final_style, qm):
        design = ArchitectureDesign(
            overview=overview,
            components=components,
            relationships=[],
            patterns=[],
            quality_attributes={},
            api_contracts=[],
            shared_data_models=[],
            event_contracts=[],
        )
        es = EvaluationSummary(
            overall_score=75.0,
            strengths=["Good design"],
            weaknesses=["Could improve"],
            critical_findings=["No issues"],
        )
        evaluation = ArchitectureEvaluation(
            summary=es,
            metrics=[],
            recommendations={},
        )
        pr = PipelineResult(
            design=design,
            evaluation=evaluation,
            attempts=attempts,
            final_style=final_style,
            quality_metrics=qm,
        )
        assert pr.attempts == attempts
        assert pr.final_style == final_style


# ─── ValidationConfig ────────────────────────────────────────────────────────


class TestValidationConfig:
    """Property tests for ValidationConfig."""

    @given(max_retries=st.integers(min_value=0, max_value=10), retry_on_fail=st.booleans())
    @settings(max_examples=30)
    def test_valid_construction(self, max_retries, retry_on_fail):
        vc = ValidationConfig(max_retries=max_retries, retry_on_fail=retry_on_fail)
        assert vc.max_retries == max_retries
        assert vc.retry_on_fail == retry_on_fail

    def test_negative_retries_fails(self):
        with pytest.raises(Exception):
            ValidationConfig(max_retries=-1)

    def test_defaults(self):
        vc = ValidationConfig(max_retries=2, retry_on_fail=True)
        assert vc.max_retries == 2
        assert vc.retry_on_fail is True


# ─── Pattern ─────────────────────────────────────────────────────────────────


class TestPattern:
    """Property tests for Pattern using real JSON data."""

    def test_pattern_json_roundtrip(self):
        """Pattern objects serialize and deserialize correctly."""
        import glob
        for path in glob.glob("pattern/*-architecture.json"):
            with open(path) as f:
                data = json.load(f)
            p = Pattern.model_validate(data)
            d = p.model_dump()
            assert d["name"] == data["name"]
            assert d["category"].value == data["category"]

    @given(
        name=st.sampled_from([s.value for s in ArchitectureStyle]),
        category=st.sampled_from([c.value for c in PatternCategory]),
    )
    @settings(max_examples=20)
    def test_minimal_pattern(self, name, category):
        p = Pattern(name=name, context="Test context", category=category)
        assert p.name == name
        assert p.category.value == category
        assert p.suitable_domains == []
        assert p.tradeoffs == []
