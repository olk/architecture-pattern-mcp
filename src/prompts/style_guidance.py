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

"""Canonical-shape guidance for each ArchitectureStyle, injected into the
GENERATE-phase system prompt.

The GENERATE system prompt is cached per style, so a dict lookup here costs
nothing at steady state. Every ArchitectureStyle enum value MUST have an
explicit entry (enforced by tests/unit/test_style_guidance.py); the default
is reserved for styles added to the enum without corresponding guidance.

Entry constraints (also test-enforced):
- non-empty and at least 50 characters (meaningful guidance)
- at most 800 characters (bounds the per-style prompt size)
"""

DEFAULT_STYLE_GUIDANCE = (
    "Design a minimal, well-structured system of 3-10 components, each owning a "
    "single clear responsibility, communicating via the protocols the requirements "
    "demand (HTTP for synchronous calls, events for asynchronous ones). Prefer "
    "proven, boring technology and keep every component relationship explicit."
)

STYLE_GUIDANCE: dict[str, str] = {
    "actor-based": (
        "All computation as actors exchanging async messages; no shared mutable state; "
        "supervision hierarchies for fault tolerance. Components: actors grouped by bounded "
        "context, mailbox/queue infrastructure, supervisor hierarchy, optional cluster "
        "sharding. Tech: Akka/Pekko, Erlang/OTP, Orleans, Dapr actors. Avoid synchronous "
        "blocking calls between actors."
    ),
    "aiml-centric": (
        "Center the design on the ML lifecycle: ingestion, feature pipeline, training, "
        "registry, serving, monitoring and retraining. Components: feature store, training "
        "pipeline, model registry, inference service (batch and online), drift monitor. "
        "Tech: MLflow, Feast, KServe/SageMaker, Airflow/Kubeflow. Keep training and serving "
        "environments reproducible."
    ),
    "api-gateway": (
        "Single entry point that routes, authenticates, rate-limits and shapes requests "
        "before backend services. Components: gateway, auth/identity provider, backend "
        "services, config/service registry. Tech: Kong, Envoy, AWS API Gateway, Apigee, "
        "Redis for quotas. Keep the gateway thin: routing and cross-cutting policy only, "
        "no business logic."
    ),
    "backend-for-frontend": (
        "One dedicated facade per client type (web, mobile, partner), each aggregating and "
        "shaping backend APIs to that client's exact needs. Components: per-client BFF "
        "services, shared domain services, identity provider. Tech: GraphQL (Apollo/DGS) "
        "or thin REST facades on Node/Spring Boot. Business logic stays in domain services, "
        "never in BFFs."
    ),
    "blackboard": (
        "A shared blackboard knowledge store plus independent knowledge sources that react "
        "to the solution state and contribute partial solutions; a control component "
        "schedules contributions. Components: blackboard store, knowledge sources, control "
        "shell. Suited to opportunistic problem-solving (speech recognition, planning). "
        "Tech: Redis or document store plus a worker pool."
    ),
    "blockchain-based": (
        "Distributed ledger as source of truth; smart contracts encode business rules; "
        "consensus provides trustless agreement. Components: peer nodes, consensus layer, "
        "smart contracts, off-chain storage, gateway/API service. Tech: Hyperledger Fabric, "
        "Ethereum, Corda. Keep large data and PII off-chain with hashes anchoring on-chain."
    ),
    "broker": (
        "A message broker decouples requesters from servers: clients send requests to the "
        "broker, which forwards them to registered servers and returns replies. Components: "
        "clients, broker, servers, registration service. Tech: RabbitMQ, ZeroMQ, gRPC with "
        "a queue. Good for heterogeneous distributed systems needing location transparency."
    ),
    "command-query-responsibility-segregation": (
        "Separate the write model (commands, validation, invariants) from read models "
        "(denormalized projections tuned for queries); events propagate changes. Components: "
        "command API, write store, event bus, projector, read store, query API. Tech: "
        "PostgreSQL, Kafka, Elasticsearch, EventStoreDB. Accept eventual consistency and "
        "version projections."
    ),
    "data-mesh": (
        "Decentralize data ownership to domain teams; data is a product with SLOs, "
        "discoverable via a self-serve platform under federated governance. Components: "
        "domain data products, data platform (catalog, discovery, contracts), governance "
        "service. Tech: DataHub/Collibra, lakehouse tables (Iceberg/Delta), dbt."
    ),
    "edge-computing": (
        "Process data at or near the source on edge nodes; the cloud handles aggregation, "
        "training and the control plane. Components: edge nodes/gateways, message fabric to "
        "cloud, central aggregation, fleet management. Tech: K3s, MQTT (EMQX), AWS "
        "Greengrass/Azure IoT Edge. Design for intermittent connectivity and local autonomy."
    ),
    "enterprise-service-bus": (
        "A central bus mediates communication between services: routing, transformation, "
        "orchestration, protocol adaptation. Components: ESB runtime, adapters, service "
        "registry, orchestration engine. Tech: MuleSoft, WSO2, Apache Camel for lighter "
        "builds. Guard against a central bottleneck: keep orchestration coarse-grained."
    ),
    "event-driven": (
        "Async-first design around a message broker: producers emit domain events to topics, "
        "consumers react independently. Events are contracts: schema registry, versioning, "
        "idempotent consumers, dead-letter queues, at-least-once delivery. Components: "
        "producers, consumers, broker, schema registry, DLQ store. Tech: Kafka, RabbitMQ, "
        "Pulsar, SQS + EventBridge."
    ),
    "event-sourcing": (
        "Persist every state change as an immutable event; current state is a projection of "
        "the event stream. Components: command handlers, event store, projectors, snapshots, "
        "upcasters for schema evolution. Tech: EventStoreDB, Axon, Kafka as a log, PostgreSQL "
        "event tables. Plan replay performance and deletion/GDPR handling early."
    ),
    "half-sync-half-async": (
        "Split processing into an async upper layer that accepts events, a synchronous middle "
        "layer that processes tasks deterministically, and an async lower layer for I/O "
        "completion; queues mediate between layers. Components: event dispatcher, sync task "
        "workers, completion handlers, inter-layer queues. Tech: thread pools with queues, "
        "asyncio with executors, Kafka consumers."
    ),
    "hexagonal": (
        "Domain logic at the core, isolated behind ports (interfaces); adapters implement "
        "protocols and persistence outside, and the core never imports adapters. Components: "
        "domain core, use-case services, port interfaces, driving/driven adapters. Tech: "
        "FastAPI adapter, SQLAlchemy adapter, in-memory fakes for tests. Infrastructure "
        "becomes swappable."
    ),
    "hybrid-cloud": (
        "Split workloads between on-premises and public cloud behind a portable runtime layer "
        "with consistent networking and identity. Components: on-prem cluster, cloud "
        "workloads, dedicated interconnect, unified identity, management plane. Tech: "
        "Kubernetes with Anthos/Azure Arc, Terraform, Vault. Classify workloads by data "
        "gravity and compliance."
    ),
    "kappa-architecture": (
        "Stream-only: treat everything as a stream and reprocess by replaying the log instead "
        "of maintaining a batch layer. Components: ingest topics, stream processors, serving "
        "store, log retention/replay jobs. Tech: Kafka with Flink/Kafka Streams, ksqlDB. "
        "Simpler ops than lambda; ensure long retention or compacted reprocessing topics."
    ),
    "lambda-architecture": (
        "Parallel batch and speed layers over the same immutable log: batch produces accurate "
        "views on delay, speed produces approximate real-time views, serving merges both. "
        "Components: ingestion log, batch processor, speed processor, serving database. Tech: "
        "Spark, Flink, Cassandra/HBase. Heavy operational footprint - justify before choosing."
    ),
    "layered-monolith": (
        "Single deployable with strict horizontal layers: presentation, business, persistence, "
        "database; dependencies point downward only. Components: controllers, service layer, "
        "repository layer, shared database. Tech: Spring Boot, Django, Laravel. Enforce layer "
        "boundaries with module rules or code review."
    ),
    "microkernel-plugin": (
        "Minimal core providing essential orchestration plus plug-in modules that add features "
        "through a stable contract. Components: core system, plugin registry/loader, plugin "
        "modules, versioned plugin API. Tech: OSGi, PF4J, Python entry-points, HashiCorp "
        "go-plugin. Keep the plugin contract backward-compatible and isolate plugin failures."
    ),
    "microservices": (
        "Independently deployable services, each owning its data store; sync calls via "
        "REST/gRPC, async via events; sagas for cross-service workflows; API gateway as the "
        "single entry point. Components: gateway, domain services, per-service databases, "
        "event broker, optional service mesh. Tech: Kubernetes, Envoy/Istio, Kafka, "
        "per-service PostgreSQL. Design for eventual consistency."
    ),
    "model-view-controller": (
        "Separate model (state and rules), view (rendering) and controller (input handling); "
        "controllers update models, views observe models. Components: models, view "
        "templates/components, controllers/router, front controller/dispatcher. Tech: "
        "Django, Rails, Spring MVC, or React + Redux for SPA interpretations. Keep views "
        "passive and models view-agnostic."
    ),
    "modular-monolith": (
        "Single deployable composed of strictly bounded modules, each owning its data and "
        "exposing an internal API; no cross-module database access. Components: modules per "
        "bounded context, shared kernel, single database with schema separation. Tech: Spring "
        "Modulith, import-linter/ArchUnit enforcement. Boundaries enable later extraction to "
        "services."
    ),
    "monolithic": (
        "Single deployable unit containing all functionality with a shared database; simplest "
        "build, test and deploy story. Components: application server, relational database, "
        "optional background workers. Tech: one framework (FastAPI/Django/Rails), PostgreSQL, "
        "cron or systemd workers. Optimize for iteration speed; introduce seams for future "
        "splits."
    ),
    "multi-cloud": (
        "Distribute workloads across two or more clouds for resilience or data-residency "
        "rules, behind a portable abstraction. Components: cloud-agnostic containerized "
        "workloads, per-cloud data services, unified CI/CD, cross-cloud networking, cost "
        "management. Tech: Kubernetes, Terraform, Crossplane, Istio multicluster."
    ),
    "pipe-and-filter": (
        "Processing as a linear or graph sequence of stateless filters connected by pipes; "
        "each filter transforms data independently and scales or is replaced in isolation. "
        "Components: source, ordered filters, sink, pipeline runtime with backpressure. Tech: "
        "Kafka Streams, Apache Beam, Logstash, Unix pipes. Keep filters stateless and "
        "single-purpose."
    ),
    "presentation-abstraction-control": (
        "A hierarchy of cooperative agents, each with presentation (UI), abstraction (domain "
        "data) and control (mediation); controls communicate up and down the agent tree. "
        "Components: agent tree of PAC triads, control bus. Suited to nested, independently "
        "navigable UIs (IDEs, multi-panel dashboards). Keep agent contracts explicit."
    ),
    "reactive-architecture": (
        "Responsive, resilient, elastic, message-driven: non-blocking communication, "
        "backpressure, supervisor-based failure isolation. Components: message-driven "
        "services, bounded contexts with explicit protocols, backpressure-aware streams, "
        "supervision hierarchy. Tech: Akka, Project Reactor/Vert.x, Kafka with reactive "
        "clients. Model failure as a first-class flow."
    ),
    "reflection-architecture": (
        "A base level does the work while a meta level observes and modifies base structure "
        "and behavior at runtime for self-adaptation. Components: base-level services, meta "
        "model, reflective runtime hooks, adaptation policies. Suited to self-healing or "
        "adaptive platforms. Tech: service mesh with dynamic config, OSGi, policy engines "
        "like OPA."
    ),
    "rule-based-system": (
        "Declarative rules plus an inference engine evaluate facts held in working memory via "
        "forward or backward chaining. Components: working memory/fact store, rule base, "
        "inference engine, fact ingestion, explanation/audit output. Tech: durable_rules, "
        "Drools, OPA/Rego. Keep rules declarative and independently testable."
    ),
    "saga": (
        "Long-running distributed transactions as sequences of local transactions with "
        "compensating actions on failure; choreography via events or a central orchestrator. "
        "Components: saga orchestrator or event choreography, participating services, "
        "compensation handlers, saga state store. Tech: Temporal, Camunda, Kafka "
        "choreography. Make every step idempotent."
    ),
    "serverless": (
        "Compose from managed function-as-a-service plus managed services; event-triggered "
        "functions, pay-per-use, scale to zero. Components: functions per use case, event "
        "sources, managed database/queue/storage, API gateway, observability. Tech: AWS "
        "Lambda with SQS/DynamoDB, Cloud Functions, Knative. Watch cold starts, execution "
        "limits and lock-in."
    ),
    "service-mesh": (
        "A dedicated infrastructure layer for service-to-service traffic: mTLS, retries, "
        "timeouts, traffic shifting and telemetry via sidecars. Components: data-plane "
        "sidecars, control plane, ingress gateway, telemetry backend. Tech: Istio, Linkerd, "
        "Consul Connect, Cilium. Application services stay policy-free; policy lives in "
        "mesh configuration."
    ),
    "service-oriented-architecture": (
        "Coarse-grained, contract-first services sharing an enterprise backbone; centralized "
        "governance, registry and bus-mediated composition. Components: business services, "
        "ESB/mediation, service registry, canonical data model. Tech: WSDL/SOAP legacy stacks "
        "or Camel-based modern SOA, MuleSoft. Heavier governance than microservices; suits "
        "enterprise integration."
    ),
    "space-based": (
        "Partitioned processing units backed by an in-memory data grid; load is balanced "
        "through the space and asynchronously replicated to a persistent store, removing the "
        "central database bottleneck. Components: processing units, data grid, "
        "replication/persistence service, gateway/load balancer. Tech: GigaSpaces XAP, "
        "Hazelcast/Infinispan, Redis. Ideal for bursty, high-volume, low-latency loads."
    ),
    "task-control-architecture": (
        "A control layer decomposes goals into tasks and schedules them; a task layer executes "
        "and reports back. Components: controller/planner, task executors, task queue, "
        "status/feedback channel, optional shared blackboard. Suited to robotics, autonomous "
        "systems and job orchestration. Tech: ROS task frameworks, Temporal, Airflow."
    ),
    "strangler-fig": (
        "Incrementally replace a legacy system: a routing facade sends traffic slice by slice "
        "to new services until the legacy core can be retired. Components: routing facade, "
        "new replacement services, the legacy system, event capture to sync coexisting data. "
        "Tech: Envoy/nginx routing rules, feature flags, change data capture with Debezium."
    ),
    "clean-architecture": (
        "Concentric layers: entities, use cases, interface adapters, frameworks/drivers; "
        "dependencies point inward only. Components: domain entities, use-case interactors, "
        "controllers/presenters, framework adapters. Tech: language-agnostic; FastAPI/Flask "
        "in the outer ring, a pure-Python domain core. The domain imports nothing "
        "framework-specific."
    ),
    "client-server": (
        "Two-tier split: clients handle presentation while a central server owns business "
        "logic and data; clients communicate via request/response APIs. Components: client "
        "applications, server application, relational database, shared file/object storage. "
        "Tech: REST/gRPC server (FastAPI/Spring), PostgreSQL, web or mobile clients. Scale "
        "via vertical growth or read replicas."
    ),
    "master-slave": (
        "A master coordinates and distributes work; replicated workers execute in parallel "
        "and return results for aggregation. Components: master/coordinator, worker pool, "
        "work queue, result aggregation, health/failover management. Tech: Celery with Redis, "
        "Kafka consumer groups, Kubernetes Jobs. Use leader/worker naming if terminology "
        "matters to your organization."
    ),
}


def get_style_guidance(style: str) -> str:
    """Return canonical-shape guidance for ``style`` with a safe default fallback."""
    return STYLE_GUIDANCE.get(style, DEFAULT_STYLE_GUIDANCE)
