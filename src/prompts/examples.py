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

from src.schemas.analysis import AnalysisResult
from src.schemas.architecture import ArchitectureDesignResponse
from src.schemas.components import Component, Relationship
from src.schemas.contracts import ApiContract, ApiEndpoint, DataModel, EventContract, ModelField
from src.schemas.design import ArchitectureOverview
from src.schemas.evaluation import ArchitectureEvaluation, EvaluationSummary, MetricResult
from src.schemas.enums import ArchitectureDomain, ArchitectureStyle, PatternCategory
from src.schemas.patterns import ScoredPattern
from src.schemas.quality import QualityMetrics


def _fmt(label: str, obj) -> str:
    """Format a Pydantic model as a readable JSON code block."""
    return f"{label}:\n```json\n{obj.model_dump_json(indent=2)}\n```"


# ─── ArchitectureDesignResponse ─────────────────────────────────────────────
# Slimmed event-driven microservices design (2 components for brevity)

ARCHITECTURE_DESIGN_EXAMPLE = _fmt(
    "Example architecture design response",
    ArchitectureDesignResponse(
        overview=ArchitectureOverview(
            style=ArchitectureStyle.EVENT_DRIVEN,
            category=PatternCategory.MESSAGING,
            principles=["async-first communication via Kafka", "schema-first contract definition", "independent deployability"],
            constraints=["PCI-DSS compliance", "10k orders/min"],
        ),
        components=[
            Component(
                id="api-gateway",
                name="API Gateway",
                type="gateway",
                description="Entry point for all client requests, handles auth and routing",
                responsibilities=["authentication", "rate limiting", "request routing"],
                interfaces=["REST", "HTTPS"],
                technology_stack=["Kong", "Redis"],
                api_contract=None,
                data_models=[],
                config_requirements=["KONG_ADMIN_API_KEY", "REDIS_URL"],
            ),
            Component(
                id="order-service",
                name="Order Service",
                type="service",
                description="Manages order lifecycle and emits order events",
                responsibilities=["order creation", "status tracking", "event emission"],
                interfaces=["REST", "Kafka Producer"],
                technology_stack=["FastAPI", "Kafka", "PostgreSQL"],
                api_contract=ApiContract(
                    component_id="order-service",
                    base_path="/api/v1/orders",
                    description="Order management API",
                    endpoints=[
                        ApiEndpoint(
                            method="POST",
                            path="/",
                            summary="Create order",
                            request_schema={
                                "type": "object",
                                "properties": {
                                    "customer_id": {"type": "string"},
                                    "items": {"type": "array"},
                                },
                                "required": ["customer_id", "items"],
                            },
                            response_schema={
                                "type": "object",
                                "properties": {
                                    "order_id": {"type": "string"},
                                    "status": {"type": "string"},
                                },
                            },
                            auth_required=True,
                            tags=["orders"],
                        ),
                    ],
                ),
                data_models=[],
                config_requirements=["DATABASE_URL", "KAFKA_BROKERS"],
            ),
        ],
        relationships=[
            Relationship(
                source="api-gateway",
                target="order-service",
                type="http",
                description="Proxies /api/v1/orders/* to order-service",
            ),
            Relationship(
                source="order-service",
                target="payment-service",
                type="async",
                description="Emits order.created events to payment-service",
            ),
        ],
        quality_attributes={
            "maintainability": "8/10",
            "scalability": "9/10",
            "reliability": "8/10",
            "security": "8/10",
            "performance": "9/10",
        },
        api_contracts=[
            ApiContract(
                component_id="order-service",
                base_path="/api/v1/orders",
                description="Order API",
                endpoints=[
                    ApiEndpoint(
                        method="POST",
                        path="/",
                        summary="Create order",
                        request_schema={
                            "type": "object",
                            "properties": {"customer_id": {"type": "string"}, "items": {"type": "array"}},
                            "required": ["customer_id", "items"],
                        },
                        response_schema={
                            "type": "object",
                            "properties": {"order_id": {"type": "string"}, "status": {"type": "string"}},
                        },
                        auth_required=True,
                        tags=["orders"],
                    ),
                ],
            ),
        ],
        shared_data_models=[
            DataModel(
                name="Order",
                description="Order entity shared across services",
                is_shared=True,
                fields=[
                    ModelField(name="order_id", type="string", required=True, description="Unique order ID"),
                    ModelField(name="customer_id", type="string", required=True, description="Customer reference"),
                    ModelField(name="status", type="string", required=True, description="Order status"),
                ],
            ),
        ],
        event_contracts=[
            EventContract(
                event_name="order.created",
                payload_schema={
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"},
                        "customer_id": {"type": "string"},
                    },
                },
                published_by="order-service",
                consumed_by=["payment-service"],
                description="Emitted when a new order is placed",
            ),
        ],
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
                findings=["Clear module boundaries", "API-first design"],
                recommendations=["Add integration test coverage", "Document event schema registry"],
            ),
            MetricResult(
                name="scalability",
                score=90.0,
                description="Event-driven design enables horizontal scaling",
                findings=["Kafka allows independent consumer scaling", "Stateless services scale horizontally"],
                recommendations=["Add Kafka partitioning by customer_id", "Configure HPA on order-service"],
            ),
            MetricResult(
                name="reliability",
                score=75.0,
                description="Missing retry policies and circuit breakers hurt reliability",
                findings=["No retry queues for failed message processing", "No bulkhead isolation"],
                recommendations=["Add retry DLQ for payment-service", "Implement circuit breakers"],
            ),
            MetricResult(
                name="security",
                score=80.0,
                description="JWT and TLS configured; WAF missing",
                findings=["JWT auth on all endpoints", "TLS in transit for Kafka"],
                recommendations=["Add WAF ahead of API gateway", "Enable request size limits on Kong"],
            ),
            MetricResult(
                name="performance",
                score=88.0,
                description="Low-latency Kafka processing meets SLA",
                findings=["Kafka median latency <5ms", "Async processing decouples services"],
                recommendations=["Add connection pooling for PostgreSQL", "Cache user sessions in Redis"],
            ),
            MetricResult(
                name="overall_quality",
                score=82.5,
                description="Weighted average across all quality dimensions",
                findings=[],
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
