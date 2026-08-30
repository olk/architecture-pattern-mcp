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

"""Complete JSON examples for structured-output prompts.

Each example populates ALL fields (including optional) with realistic
data. Validated at import time via Pydantic instantiation — if the schema
changes, import fails and CI breaks.

If you modify a Pydantic schema, you MUST update the corresponding example here.
"""

from src.schemas.analysis import AnalysisResult, RequirementWeights
from src.schemas.architecture import (
    ArchitectureDesignResponse,
    ArchitectureOverviewWire,
)
from src.schemas.components import Component, Relationship
from src.schemas.contracts import ApiContract, ApiEndpoint, DataModel, EventContract, ModelField
from src.schemas.evaluation import ArchitectureEvaluation, EvaluationSummary, MetricResult
from src.schemas.enums import ArchitectureDomain, ArchitectureStyle, PatternCategory
from src.schemas.patterns import ScoredPattern
from src.schemas.quality import QualityMetrics


def _fmt(label: str, obj) -> str:
    """Format a Pydantic model as a readable JSON code block."""
    return f"{label}:\n```json\n{obj.model_dump_json(indent=2)}\n```"


# ─── ArchitectureDesignResponse ─────────────────────────────────────────────
# Deliberately domain- and style-neutral (layered monolith, generic user
# registry): demonstrates schema shape, cross-reference integrity, and honest
# quality scoring without injecting a specific domain or technology bias.
# The GENERATE system prompt instructs the model to adapt — not copy — it.

ARCHITECTURE_DESIGN_EXAMPLE = _fmt(
    "Example architecture design response",
    ArchitectureDesignResponse(
        overview=ArchitectureOverviewWire(
            reasoning=(
                "Requirements describe a user registry with create/read access and "
                "no explicit scale or integration demands. A layered monolith is the "
                "simplest shape that satisfies them: one service owns validation and "
                "user rules, one relational database owns persistence; dependencies "
                "point downward only so modules can be extracted later. Trade-off "
                "accepted: vertical-only scaling until read volume justifies replicas."
            ),
            style=ArchitectureStyle.LAYERED_MONOLITH,
            category=PatternCategory.STRUCTURAL,
            principles=[
                "single deployable unit",
                "layer dependencies point downward only",
                "schema-first HTTP API",
            ],
            constraints=["single relational datastore", "stateless service tier"],
        ),
        components=[
            Component(
                id="user-service",
                name="User Service",
                type="service",
                description="Handles user registration, lookup, and profile updates",
                responsibilities=[
                    "validate registration input",
                    "persist user records",
                    "expose user REST endpoints",
                ],
                interfaces=["REST"],
                technology_stack=["FastAPI"],
                api_contract=ApiContract(
                    component_id="user-service",
                    base_path="/api/v1/users",
                    description="User management API",
                    endpoints=[
                        ApiEndpoint(
                            method="POST",
                            path="/",
                            summary="Register a new user",
                            request_schema={
                                "type": "object",
                                "properties": {
                                    "email": {"type": "string", "format": "email"},
                                },
                                "required": ["email"],
                            },
                            auth_required=False,
                            tags=["users"],
                        ),
                        ApiEndpoint(
                            method="GET",
                            path="/{user_id}",
                            summary="Fetch a user by id",
                            response_schema={
                                "type": "object",
                                "properties": {
                                    "user_id": {"type": "string"},
                                    "email": {"type": "string"},
                                    "display_name": {"type": "string"},
                                },
                            },
                            auth_required=True,
                            tags=["users"],
                        ),
                    ],
                ),
                data_models=[],
                config_requirements=["DATABASE_URL"],
            ),
            Component(
                id="user-database",
                name="User Database",
                type="database",
                description="Relational store for user records",
                responsibilities=[
                    "persist user rows",
                    "enforce unique email constraint",
                ],
                interfaces=["SQL"],
                technology_stack=["PostgreSQL"],
                api_contract=None,
                data_models=[],
                config_requirements=["POSTGRES_PASSWORD"],
            ),
        ],
        relationships=[
            Relationship(
                source="user-service",
                target="user-database",
                type="data-flow",
                description="Reads and writes user records over SQL",
            ),
        ],
        quality_attributes={
            "maintainability": "7/10",
            "scalability": "5/10",
            "reliability": "6/10",
            "security": "6/10",
            "performance": "6/10",
        },
        api_contracts=[],
        shared_data_models=[
            DataModel(
                name="User",
                description="User entity shared between service logic and persistence",
                is_shared=True,
                fields=[
                    ModelField(name="user_id", type="string", required=True, description="Unique user ID"),
                    ModelField(name="email", type="string", required=True, description="Unique email address"),
                    ModelField(name="display_name", type="string", required=False, description="Public display name"),
                ],
            ),
        ],
        event_contracts=[],
    ),
)


# ─── ArchitectureEvaluation ────────────────────────────────────────────────
# Evaluation of the e-commerce microservices design above

ARCHITECTURE_EVALUATION_EXAMPLE = _fmt(
    "Example evaluation response",
    ArchitectureEvaluation(
        summary=EvaluationSummary(
            overall_score=82.5,
            strengths=[
                "Clear event-driven boundaries via Kafka topics",
                "Schema-first API contract enforcement via OpenAPI",
                "Idempotent handlers prevent duplicate processing",
                "Independent deployability of all services",
            ],
            weaknesses=[
                "No retry policies on Kafka consumers — message loss risk on crash",
                "API gateway lacks rate limiting configuration",
                "No distributed tracing for observability",
            ],
            critical_findings=[
                "Payment consumer has no manual acknowledgment — message lost on crash",
                "API gateway has no rate limiting or WAF configured",
                "PostgreSQL connections not pooled — exhaustion risk under load",
            ],
        ),
        metrics=[
            MetricResult(
                name="maintainability",
                score=85.0,
                description="Service separation and clean contracts support maintainability",
                reasoning=(
                    "Checked: (1) service boundaries — one bounded context per "
                    "service (orders, payments, inventory), no shared databases; "
                    "(2) contract-first coupling — OpenAPI schemas on every "
                    "synchronous endpoint; (3) independent deployability — each "
                    "service owns its pipeline; (4) testability hooks — no stated "
                    "integration-test surface. Pattern best practices met on 3 of "
                    "4 checks; docked for absent test strategy."
                ),
                findings=["Clear module boundaries", "API-first design"],
                recommendations=["Add integration test coverage", "Document event schema registry"],
            ),
            MetricResult(
                name="scalability",
                score=90.0,
                description="Event-driven design enables horizontal scaling",
                reasoning=(
                    "Checked: (1) stateless services — order-service and "
                    "inventory-service hold no session state; (2) consumer "
                    "scale-out — Kafka consumers scale per topic; (3) partitioning "
                    "strategy — no partition key defined, so parallelism is "
                    "underutilized; (4) gateway scalability — Kong is stateless "
                    "behind a load balancer. Strong baseline; docked for missing "
                    "partition keys."
                ),
                findings=["Kafka allows independent consumer scaling", "Stateless services scale horizontally"],
                recommendations=["Add Kafka partitioning by customer_id", "Configure HPA on order-service"],
            ),
            MetricResult(
                name="reliability",
                score=75.0,
                description="Missing retry policies and circuit breakers hurt reliability",
                reasoning=(
                    "Checked: (1) every async consumer has retry/DLQ — "
                    "payment-service lacks manual ack so messages are lost on "
                    "crash; (2) bulkhead isolation across services — none "
                    "configured; (3) idempotent handlers — present in "
                    "inventory-service but not payment-service; (4) circuit "
                    "breakers for downstream calls — none. Event-driven pattern "
                    "expectations require retry+DLQ; the design violates 1 of 4 "
                    "critical items, hence 75 not 85."
                ),
                findings=["No retry queues for failed message processing", "No bulkhead isolation"],
                recommendations=["Add retry DLQ for payment-service", "Implement circuit breakers"],
            ),
            MetricResult(
                name="security",
                score=80.0,
                description="JWT and TLS configured; WAF missing",
                reasoning=(
                    "Checked: (1) authn on external endpoints — JWT on all REST "
                    "routes; (2) internal traffic encryption — TLS in transit for "
                    "Kafka; (3) edge protection — no WAF or rate limiting on Kong; "
                    "(4) payload encryption for PII — absent on event payloads. "
                    "Two of four checks pass; edge protection gap is the main "
                    "deduction."
                ),
                findings=["JWT auth on all endpoints", "TLS in transit for Kafka"],
                recommendations=["Add WAF ahead of API gateway", "Enable request size limits on Kong"],
            ),
            MetricResult(
                name="performance",
                score=88.0,
                description="Low-latency Kafka processing meets SLA",
                reasoning=(
                    "Checked: (1) async decoupling — order placement returns "
                    "before payment processing; (2) broker latency — Kafka median "
                    "under 5ms supports the p99 budget; (3) database connection "
                    "management — no pooling configured on PostgreSQL, exhaustion "
                    "risk under load; (4) caching — no session or read cache. "
                    "Strong async design; docked for unpooled connections."
                ),
                findings=["Kafka median latency <5ms", "Async processing decouples services"],
                recommendations=["Add connection pooling for PostgreSQL", "Cache user sessions in Redis"],
            ),
            MetricResult(
                name="overall_quality",
                score=82.5,
                description="Weighted average across all quality dimensions",
                reasoning=(
                    "Aggregation: scalability (90) and performance (88) are "
                    "strengths backed by concrete evidence; maintainability (85) "
                    "and security (80) are solid; reliability (75) is pulled down "
                    "by the missing retry/ack configuration, which also drives two "
                    "critical findings. Weighted toward reliability and security "
                    "because their gaps are production blockers: 82.5."
                ),
                findings=["Reliability gaps cap the overall score"],
                recommendations=["Address critical findings before production launch"],
            ),
        ],
        recommendations={
            "reliability": [
                "Add retry queues with exponential backoff for payment consumer",
                "Implement circuit breakers using Resilience4j",
                "Enable manual Kafka consumer commit mode",
            ],
            "security": [
                "Configure Kong WAF plugin with OWASP ruleset",
                "Add rate limiting: 100 req/min per customer_id",
                "Enable field-level encryption for PII in Kafka payloads",
            ],
            "scalability": [
                "Partition Kafka topics by customer_id for parallel processing",
                "Configure HPA on order-service with Kafka lag metric",
            ],
            "observability": [
                "Add OpenTelemetry tracing to all services",
                "Ship Kafka consumer lag metrics to Prometheus",
            ],
        },
    ),
)


# ─── AnalysisResult ─────────────────────────────────────────────────────
# Analysis for e-commerce domain with event-driven microservices requirements

ANALYSIS_RESULT_EXAMPLE = _fmt(
    "Example analysis response",
    AnalysisResult(
        strengths=[
            "Strong fit with event-driven microservices pattern — async communication decouples services naturally",
            "Clear component boundaries align with e-commerce bounded contexts (orders, users, payments)",
            "Schema-first API contracts enforce agreement between frontend and backend teams",
        ],
        weaknesses=[
            "Higher operational complexity — Kafka, PostgreSQL, and multiple services require dedicated SRE coverage",
            "Distributed tracing and observability stack not yet configured",
            "Team has limited Kafka expertise — estimated 2-week ramp-up time",
        ],
        recommendations=[
            "Use Confluent Cloud or MSK for managed Kafka to reduce operational overhead",
            "Add OpenTelemetry auto-instrumentation in all services from day one",
            "Implement circuit breakers and retry policies before first production deployment",
            "Establish event schema registry for contract governance",
        ],
        quality_metrics=QualityMetrics(
            maintainability=8.0,
            scalability=9.0,
            reliability=7.5,
            security=7.0,
            performance=8.5,
        ),
        recommended_style="event-driven",
        selected_patterns=[
            ScoredPattern(
                analysis_score=86.5,
                fusion_score=0.0333,
                name="event-driven",
                context="Systems requiring asynchronous communication and loose coupling between services",
                category=PatternCategory.MESSAGING,
                benefits=[
                    "Loose coupling via message topics",
                    "Independent service scaling",
                    "Fault isolation through async boundaries",
                ],
                tradeoffs=[
                    "Eventual consistency complexity",
                    "Debugging distributed async flows",
                    "Message ordering guarantees are weaker than RPC",
                ],
                quality_attributes={
                    "maintainability": 7.0,
                    "scalability": 9.0,
                    "reliability": 7.0,
                    "security": 6.0,
                    "performance": 9.0,
                },
                suitable_domains=[
                    ArchitectureDomain.E_COMMERCE,
                    ArchitectureDomain.FINTECH,
                    ArchitectureDomain.REAL_TIME_ANALYTICS,
                    ArchitectureDomain.ORDER_MANAGEMENT,
                ],
                unsuitable_domains=[
                    ArchitectureDomain.STRONG_CONSISTENCY_REQUIREMENTS,
                    ArchitectureDomain.LOW_LATENCY_REQUIREMENTS,
                ],
                best_practices=[
                    "Use schema registry for event contracts",
                    "Implement idempotent consumers",
                    "Add retry queues with dead-letter topics",
                ],
                component_types=[
                    "Message Broker: Kafka for async event delivery",
                    "Event Handler: Service that consumes and processes events",
                    "Event Producer: Service that emits domain events",
                ],
                design_principles=[
                    "Event-first thinking",
                    "Idempotent operations",
                    "Consumer-driven contract testing",
                ],
                anti_patterns=[
                    "Chatty APIs over events",
                    "Event polling instead of push",
                    "Monolithic event schemas",
                ],
            ),
            ScoredPattern(
                analysis_score=78.0,
                fusion_score=0.0250,
                name="api-gateway",
                context="Multiple backend services requiring unified entry point",
                category=PatternCategory.API_GATEWAY,
                benefits=[
                    "Single entry point for all clients",
                    "Centralised authentication and rate limiting",
                ],
                tradeoffs=[
                    "Additional hop latency",
                    "Gateway becomes single point of failure if not HA",
                ],
                quality_attributes={
                    "maintainability": 8.0,
                    "scalability": 8.0,
                    "reliability": 7.0,
                    "security": 9.0,
                    "performance": 7.0,
                },
                suitable_domains=[
                    ArchitectureDomain.E_COMMERCE,
                    ArchitectureDomain.MOBILE_APPLICATIONS,
                    ArchitectureDomain.MULTI_TENANT_SAAS,
                ],
                unsuitable_domains=[
                    ArchitectureDomain.SIMPLE_CRUD,
                    ArchitectureDomain.IOT_SENSOR_DATA,
                ],
                best_practices=[
                    "Keep gateway logic minimal — delegate to services",
                    "Use managed gateway (Kong, AWS API Gateway)",
                ],
                component_types=[
                    "Gateway Router: routes requests to backend services",
                    "Auth Handler: validates JWT tokens",
                    "Rate Limiter: enforces quota per client",
                ],
                design_principles=[
                    "Gateway as thin proxy",
                    "Authentication at edge",
                ],
                anti_patterns=[
                    "Business logic in gateway",
                    "Stateful session affinity without sticky sessions",
                ],
            ),
        ],
    ),
)


# ─── RequirementWeights ─────────────────────────────────────────────────────
# Three contrasting examples for the ANALYZE-phase weight-extraction prompt:
# peaked priorities / sparse low-signal / explicit anti-requirement.
# Validated at import time via Pydantic instantiation — schema drift fails CI.
# Rendered in the ANALYZE system prompt via model_dump_json (no markdown
# fences, so the LLM never echoes fences into its structured output).
# Invariant: the maximum weight equals 1.0 in every example, mirroring the
# normalisation hard constraint in the prompt.

REQUIREMENT_WEIGHTS_EXAMPLE_PEAKED = RequirementWeights(
    scalability=1.0,
    maintainability=0.3,
    reliability=0.9,
    security=0.9,
    performance=0.7,
    simplicity=0.4,
)

REQUIREMENT_WEIGHTS_EXAMPLE_SPARSE = RequirementWeights(
    scalability=0.2,
    maintainability=0.3,
    reliability=0.2,
    security=0.2,
    performance=0.2,
    simplicity=1.0,
)

REQUIREMENT_WEIGHTS_EXAMPLE_NEGATIVE = RequirementWeights(
    scalability=0.0,
    maintainability=0.4,
    reliability=0.3,
    security=0.3,
    performance=0.3,
    simplicity=1.0,
)
