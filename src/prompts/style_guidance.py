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
    ),    # --- catalog expansion: guidance for 88 new styles ---
    "auto-scaling": (
        "Workload capacity must track demand instead of being fixed in "
        "advance. Shape: Autoscaler controller, Metrics source, Scale target, "
        "Scaling policy and stabilization window, Node autoscaler. Prefer: "
        "Kubernetes HorizontalPodAutoscaler, Kubernetes "
        "VerticalPodAutoscaler, Cluster Autoscaler, Karpenter."
    ),
    "background-sync": (
        "An application must keep working when it is not in the foreground — "
        "refreshing content, uploading telemetry, draining a write queue, "
        "reconciling local state with a server — under a throttling OS. Shape: Work "
        "request, Constraints, Scheduler, Worker, Expedited quota manager. "
        "Prefer: Android Jetpack WorkManager, JobScheduler, Android Doze and "
        "App Standby, Service Worker Background Sync."
    ),
    "batch-integration": (
        "Two enterprise systems have to stay in sync — an ERP and a CRM, a "
        "SaaS platform and a mainframe, a supplier portal and a data "
        "warehouse — and the movement of records between them is bulk. Shape: "
        "Batch Job Scope, Record Queue / Stepping Queue, Batch Step, Batch "
        "Aggregator, Record Filter / Accept Policy. Prefer: Salesforce Bulk "
        "API 2.0, Apache Camel, Azure Data Factory."
    ),
    "batch-processing": (
        "Work arrives as a volume too large to hold in memory or finish "
        "inside a request: a nightly settlement run, a million-row import, "
        "media transcoding, a parameter sweep of 250,000 simulations. Shape: "
        "Job, Step, ItemReader, ItemProcessor, ItemWriter. Prefer: Spring "
        "Batch, Azure Batch, Apache Spark, AWS Batch."
    ),
    "blue-green-deployment": (
        "A production workload must be upgraded to a new version with "
        "near-zero downtime and with a rollback that is a routing change "
        "rather than a redeployment. Shape: Blue environment, Green "
        "environment, Traffic router, Deployment pipeline, Verification "
        "suite. Prefer: Azure Front Door, Azure Application Gateway, Azure "
        "DNS, Azure Spring Apps named deployments."
    ),
    "burn-mint-bridge": (
        "A natively multi-chain token (stablecoin, governance, or utility "
        "token deployed on several chains) must move between chains while "
        "staying the same canonical asset everywhere. Shape: Burn/Mint Token "
        "Contract, Bridge Adapter / Token Pool, Attestation / Messaging "
        "Network, Rate Limiter, Nonce / Replay Registry. Prefer: Solidity, "
        "Chainlink CCIP BurnMintTokenPool, LayerZero OFTBurnMint / "
        "OFTBurnSelfMint, Wormhole NTT."
    ),
    "canary-deployment": (
        "A release candidate must be exposed to a small, time-limited slice "
        "of real production traffic, evaluated against objective criteria, "
        "and only then promoted — or automatically rolled back. Shape: Canary "
        "fleet, Control fleet, Traffic router, Analysis service, Metric "
        "pipeline. Prefer: Google SRE canary analysis, Istio, Argo Rollouts, "
        "Flagger."
    ),
    "carbon-credit-tokenization": (
        "Voluntary carbon markets track credits (1 credit = 1 tCO2e with a "
        "project, methodology, and vintage) in centralized registries such as "
        "Verra, Gold Standard, and Puro.earth. Shape: Registry Adapter, "
        "Bridge Relayer, BatchNFT Contract, TCO2 Token Contract, Escrow "
        "Contract. Prefer: Solidity, Toucan Protocol, Polygon."
    ),
    "ccip-messaging": (
        "Multi-chain applications that must move arbitrary data and token "
        "value between heterogeneous blockchains without trusting a single "
        "bridge custodian. Shape: Router, OnRamp, OffRamp, TokenPool + "
        "TokenAdminRegistry, Committee Verifier + optional CCVs. Prefer: "
        "Chainlink CCIP v2.0, Solidity TokenPools, RMNProxy/RMN curse "
        "contracts."
    ),
    "change-data-capture": (
        "A service owns a database whose contents other services, search "
        "indexes, and warehouses need, but the producer cannot be changed: it "
        "is a vendor product, another team's release train, or a broker-unaware service. Shape: CDC "
        "connector (Debezium), Outbox table, Single Message Transform "
        "(EventRouter SMT), Message broker / topic. Prefer: Apache Kafka and "
        "Kafka Connect, Debezium, PostgreSQL logical replication slots, MySQL "
        "binlog."
    ),
    "chaos-engineering": (
        "A distributed system's resilience properties are mostly claims. "
        "Shape: Steady-State Definition, Hypothesis, Fault Injector, Blast "
        "Radius Controller, Control and Experimental Cohorts. Prefer: Chaos "
        "Monkey, Chaos Kong, Chaos Mesh, Gremlin."
    ),
    "compactor": (
        "Two shapes of the same problem. Shape: Compaction trigger, File "
        "group planner, Rewriter / cleaner worker, Commit manager, Tombstone "
        "(delete marker). Prefer: Apache Kafka log cleaner, Apache Iceberg "
        "RewriteDataFiles, Delta Lake OPTIMIZE."
    ),
    "container-pattern": (
        "A workload is packaged as an OCI/Docker image and deployed as one or "
        "more containers, and the design must exploit what containers make "
        "easy — layered images, filesystem and namespace. Shape: Application "
        "container, Init container, Sidecar container, Ambassador container, "
        "Adapter container. Prefer: Docker, OCI Image Spec, Kubernetes Pods, "
        "Kubernetes init containers."
    ),
    "data-timestamping": (
        "Systems that must prove a document, dataset, media file, or log "
        "existed at or before a specific time without trusting a centralized "
        "timestamp authority: prior-art evidence, audit trails. Shape: Client "
        "Hasher, Batch Aggregator / Calendar Server, Anchor Writer, Proof "
        "Store, Independent Verifier. Prefer: OpenTimestamps, Bitcoin "
        "OP_RETURN anchors, Ethereum transaction data-field anchors."
    ),
    "database-per-service": (
        "A microservices application needs each service to own its persistent "
        "data so that the service can be developed, deployed and scaled "
        "independently of every other service. Shape: Service-local database, "
        "Per-service database user, API boundary, Saga orchestrator or "
        "choreography, CQRS materialized view. Prefer: PostgreSQL, MySQL, "
        "MongoDB, Neo4j."
    ),
    "database-sharding": (
        "A single relational store has hit its write ceiling: more CPUs or "
        "IOPS on one machine will not fix it, because the limit is the "
        "machine, and the fix is to spread the data across many. Shape: "
        "Coordinator / Router, Shard, Distribution Key, Shard Map / Placement "
        "Metadata, Co-location Group. Prefer: Citus, PostgreSQL, MySQL, "
        "Amazon Aurora."
    ),
    "dataset-tracker": (
        "A dataset is a thing that changes under you. Shape: Dataset entity, "
        "Job / DataFlow entity, Run entity, RunEvent, DatasetEvent. Prefer: "
        "OpenLineage, Marquez, DataHub, OpenMetadata."
    ),
    "device-lifecycle": (
        "An IoT or edge fleet must be enrolled, authenticated, grouped, "
        "described, found and retired as a population rather than device by "
        "device. Shape: Device registry, Provisioning template, Claim "
        "certificate, Client certificate, IoT policy. Prefer: AWS IoT Core "
        "device registry, AWS IoT thing groups, AWS IoT fleet indexing."
    ),
    "device-shadow": (
        "A constrained or intermittently connected device must be "
        "controllable and observable from apps and cloud services even while "
        "it is offline. Shape: Shadow document, Shadow type, Reserved MQTT "
        "topics, REST API, Client token. Prefer: AWS IoT Device Shadow "
        "service, MQTT, AWS IoT Rules, Persistent MQTT sessions."
    ),
    "dynamic-joiner": (
        "Enriching an unbounded stream against a reference table that keeps "
        "changing under you. Shape: Probe stream, Build side, Temporal join "
        "operator, Temporal table function, Lookup join operator. Prefer: "
        "Flink FOR SYSTEM_TIME AS OF, Kafka Streams KStream-KTable joins."
    ),
    "dynamic-late-data-integrator": (
        "A result has already been published for time period T, and then a "
        "record whose event time falls inside T arrives. Shape: Tolerance "
        "policy, Lateness histogram, Window / partition state with retention, "
        "Late-firing trigger, Changelog / retraction encoder. Prefer: Flink "
        "side outputs."
    ),
    "eip4844-blobs": (
        "Ethereum L2 rollups must post their compressed batch data to L1 so "
        "any honest prover can reconstruct state and challenge fraud, but "
        "posting as calldata is expensive: every byte is executed. Shape: "
        "Blob-Carrying Transaction (type-0x03), Blob Sidecar, KZG Commitment "
        "Store, Blob-Gas Fee Market. Prefer: Ethereum execution clients, "
        "Ethereum consensus clients, Optimistic rollup stacks, ZK rollup "
        "stacks."
    ),
    "event-time-processing": (
        "This pattern is the discipline of choosing and honouring the clock, "
        "not the watermark mechanism itself: a watermark pattern can be "
        "embedded in a processing-time pipeline and be perfectly. Shape: "
        "Timestamp assigner, Watermark generator, WatermarkStrategy, Idle "
        "status signal, Event-time clock (operator-local)."
    ),
    "external-configuration-store": (
        "Applications ship with configuration baked into deployment packages "
        "— files on disk, resource bundles, build-time constants — so "
        "changing an endpoint, a feature flag, or a batch size. Shape: "
        "Configuration Store, Configuration Client / Library, Local Cache, "
        "Change Notification Channel, Revision / Snapshot Store. Prefer: "
        "Azure App Configuration, Spring Cloud Config Server, Consul KV, "
        "HashiCorp Vault."
    ),
    "failover": (
        "A running service has a designated active instance serving all "
        "traffic and one or more passive instances that are replicated, "
        "standby-ready and not serving. Shape: Active/primary instance, "
        "Passive/standby instance, Fencing device, Cluster membership and "
        "quorum layer, Resource manager. Prefer: Pacemaker, Corosync, DRBD, "
        "sbd watchdog fencing."
    ),
    "fault-tolerance": (
        "In any distributed system, components fail — a replica dies, a "
        "network partition splits a cluster, a bad deploy corrupts state, a "
        "dependency returns nonsense. Shape: Redundant Resource Pair, Error "
        "Detector, Supervisor, Watchdog, Failure Unit / Bulkhead. Prefer: "
        "Kubernetes, etcd / ZooKeeper, Keepalived / VRRP, HAProxy."
    ),
    "feature-engineering-pipeline": (
        "A model is trained on a table built by one code path and served "
        "features produced by another, and the model works offline and fails "
        "in production. Shape: Feature definition, Feature view, Feature "
        "service, Entity dataframe, Offline store. Prefer: Feast, Apache "
        "Spark streaming feature jobs, Apache Flink, Apache Beam."
    ),
    "flashbots-protect": (
        "On Ethereum-like chains every pending transaction gossiped to the "
        "public mempool is visible to MEV searcher bots, which frontrun, "
        "sandwich, and backrun user swaps, causing slippage and revert fees. Shape: "
        "Private RPC Endpoint, Relay / Bundle Pool, Builder Network, Status "
        "and Cancellation API, MEV-Share Node. Prefer: Ethereum JSON-RPC, "
        "Protect Transaction Status API."
    ),
    "flow-interruption-detector": (
        "This pattern is deliberately not a lag detector. Shape: Arrival "
        "expectation, Expectation registry, Absence check, Continuity / gap "
        "detector, Idleness-versus-interruption discriminator. Prefer: Kafka "
        "consumer offsets and the Admin API."
    ),
    "full-loader": (
        "The full loader is the extract-load half of EL, and its whole "
        "argument is that it has no moving parts. Shape: Native export "
        "command, Stage / landing zone, Bulk load command, Load history / "
        "manifest, Atomic swap. Prefer: Snowflake COPY INTO, Snowflake "
        "internal and external stages, PostgreSQL COPY TO and COPY FROM."
    ),
    "green-blockchain-patterns": (
        "Proof-of-work blockchains secure consensus by competitive hashing, "
        "consuming country-scale electricity (Bitcoin mining used ~173 TWh "
        "and emitted ~86 MtCO2 in 2020-2021). Shape: Efficient Consensus "
        "Layer, Finality Gadget, Parallel Execution Engine, Green Scoring "
        "Module, Carbon Retirement Pallet. Prefer: Ethereum PoS, Algorand "
        "PPoS with VRF sortition, Cosmos SDK."
    ),
    "incremental-loader": (
        "The incremental loader processes only what changed since the last "
        "successful run, which makes it a stateful machine whether or not the "
        "code admits it. Shape: Delta selector, Delta-state checkpoint, "
        "Bootstrap condition, Unique key / merge key, Apply strategy. Prefer: "
        "dbt incremental materializations."
    ),
    "lag-detector": (
        "This pattern is a measurement instrument, not a repair mechanism, "
        "and it is not the same as a flow interruption detector. Shape: "
        "Offset collector, Lag calculator, Time-normalised estimator, "
        "Exporter, Grouping and aggregation layer. Prefer: Prometheus and "
        "Alertmanager, kafka-lag-exporter, "
        "prometheus-kafka-consumer-group-exporter."
    ),
    "late-data-detector": (
        "A late-data detector is an instrument, not a repair mechanism — that "
        "distinction is the whole pattern. Shape: Tolerance / grace "
        "configuration, Late-classification point, Side-output late channel, "
        "Delay histogram, Late-rate counter. Prefer: Kafka Streams window "
        "grace periods, Apache Kafka record timestamps."
    ),
    "layerzero-omnichain": (
        "An application must send arbitrary messages or move assets between "
        "heterogeneous blockchains (EVM, Solana, Move) without trusting an "
        "intermediate chain, running full light clients on every. Shape: "
        "Endpoint (Immutable Interface), MessageLib Registry, UlnConfig "
        "(Quorum Policy), DVN (Decentralized Verifier Network), Executor. "
        "Prefer: Solidity OApp/OFT/ONFT, DVN providers."
    ),
    "light-client-bridge": (
        "Two sovereign blockchains need to move assets or messages between "
        "them without trusting a custodial committee or multisig. Shape: "
        "Light Client Contract, Relayer, Updater Contract, Proof Verifier, "
        "Application Contract. Prefer: IBC and ibc-go."
    ),
    "liquid-restaking-lrt": (
        "Proof-of-stake capital restaked into additional validation duties "
        "(EigenLayer-style AVS security) earns extra yield but becomes "
        "illiquid: positions are delegated, slashable under each AVS. Shape: "
        "Deposit Pool Vault, LRT Token (ERC-20), Config Registry, Delegation "
        "Router, Allocation Guard. Prefer: Solidity, EigenLayer core "
        "contracts, Beacon-chain state proofs, Merkle reward distribution "
        "claims."
    ),
    "load-balancing": (
        "A service runs as N identical instances behind one address, and "
        "something must decide which instance receives each request. Shape: "
        "Load Balancer, Endpoint Set / Cluster, Selection Algorithm, Health "
        "Checker, Slow Start Controller. Prefer: NGINX / NGINX Plus, Envoy, "
        "HAProxy, Kubernetes Service and kube-proxy."
    ),
    "lock-mint-bridge": (
        "Moving asset value from a source chain to a destination chain that "
        "share no state, for a token the bridge does not control. Shape: "
        "Vault / Lockbox, Wrapped Token, Attestation Network, Minter "
        "Controller, Burn Handler. Prefer: Solidity, Chainlink CCIP."
    ),
    "mev-boost-pattern": (
        "On proof-of-stake Ethereum the validator selected to propose a slot "
        "must produce a full execution block, but building the most valuable "
        "block requires MEV search, private orderflow access. Shape: "
        "MEV-Boost Sidecar, Relay, Block Builder, Consensus and Validator "
        "Client, Relay Monitor. Prefer: Ethereum Builder API specification, "
        "MEV-Boost relays, Builder multiplexers."
    ),
    "mev-share-pattern": (
        "On Ethereum-like chains a user swap creates backrunnable value "
        "(arbitrage, liquidation) that public-mempool searchers capture in "
        "full, with the user keeping none and often suffering. Shape: "
        "Orderflow Originator, MEV-Share Node (Matchmaker), SSE Event Stream, "
        "Searcher Bidders, Block Builders."
    ),
    "micro-frontend": (
        "A backend decomposed into microservices still presents a single "
        "large frontend monolith: one browser application, one repository, "
        "one release train, and dozens of teams editing it. Shape: Host / "
        "Container, Remote / Micro Frontend, Shared Scope, remoteEntry, "
        "Integration Mechanism. Prefer: webpack Module Federation, Module "
        "Federation Runtime, Nx Module Federation, Angular."
    ),
    "microservices-sprawl": (
        "ANTI-PATTERN. Shape: Excess services, Anemic CRUD services, "
        "Coordinated release train, Distributed monolith, Coupling fabric. "
        "Prefer: Service mesh, CI/CD per service, Distributed tracing, API "
        "gateway."
    ),
    "mtls": (
        "A system whose services, devices, or partners call each other across "
        "a network that nobody owns end to end. Shape: Workload / service "
        "instance, Internal CA / workload CA, SPIRE agent (per node). Prefer: "
        "TLS 1.3, SPIFFE / SPIRE, cert-manager, HashiCorp Vault PKI."
    ),
    "multi-signature": (
        "Blockchain wallets and on-chain treasuries where a single private "
        "key is an unacceptable single point of failure: theft, loss, or "
        "insider abuse of one key must never move funds. Shape: Owner "
        "Registry, Proposal Builder, Signature Collector, Threshold Verifier, "
        "Nonce and Replay Guard. Prefer: Bitcoin Script, Safe, OpenZeppelin "
        "MultiSignerERC7913, BIP32/BIP43/BIP45 HD derivation."
    ),
    "multi-stage-deployment": (
        "A deployment pipeline is structured as an ordered sequence of stages "
        "— build, test, deploy to development, deploy to staging, deploy to "
        "production — where each stage is a logical boundary. Shape: Stage, "
        "Deployment job, Environment, Approval/check, Artifact. Prefer: Azure "
        "Pipelines multi-stage YAML, Azure DevOps Environments and approvals, "
        "AWS CodePipeline, AWS CodeBuild."
    ),
    "native-restaking-eigenlayer": (
        "Ethereum validators lock ETH to secure layer 1, leaving tens of "
        "billions in staked capital idle while new protocols "
        "(data-availability layers, bridges, oracles, sequencers, keeper "
        "networks. Shape: EigenPod, EigenPodManager, DelegationManager, "
        "AllocationManager, Operator. Prefer: Ethereum beacon chain, "
        "EigenLayer core contracts, EIP-4788 beacon block root oracle, "
        "EigenDA."
    ),
    "offline-first": (
        "An application treats the copy of the data on the user's device as "
        "the primary copy, not a cache of a server's. Shape: Local replica, "
        "Sync engine, Operation log, Conflict resolution, Sync transport. "
        "Prefer: CRDTs, SQLite / IndexedDB / Realm, WebRTC peer-to-peer data "
        "channels, Server relay for coordination."
    ),
    "on-chain-aggregation": (
        "Base-layer execution caps throughput (Ethereum L1 processes roughly "
        "a dozen transactions per second) and charges gas per transaction, "
        "pricing out micropayments, order-book updates, and high-frequency workloads. Shape: "
        "Sequencer, Batcher / Batch Poster, Data-Availability Layer, Rollup / "
        "Verifier Contract, Prover or Challenger. Prefer: Solidity rollup and "
        "verifier contracts, OP Stack components, Zero-knowledge proof "
        "systems."
    ),
    "operator-pattern": (
        "A stateful application on Kubernetes requires operational knowledge "
        "— how to install it, how to seed it, how to resize it, how to back "
        "it up, how to upgrade it between versions, how to fail. Shape: "
        "CustomResourceDefinition, Custom Resource instance, Controller / "
        "reconciler, Work queue and informers, Finalizer. Prefer: Operator "
        "Framework, Operator SDK, controller-runtime, Kubernetes "
        "CustomResourceDefinitions."
    ),
    "optimistic-bridge": (
        "Two sovereign blockchains need to move assets or general messages "
        "between them, but per-message verification on the destination "
        "(light-client header checks or ZK proof verification) is too. Shape: "
        "Home Contract, Replica Contract, Updater (Proposer), Watcher "
        "(Challenger), Relayer. Prefer: Nomad optics contracts, UMA "
        "Optimistic Oracle V3."
    ),
    "optimistic-rollup": (
        "Ethereum L1 processes roughly 15-30 TPS with volatile gas fees, "
        "which prices out high-volume applications (payments, trading, "
        "gaming, social) while keeping L1-grade settlement. Shape: "
        "Sequencer / Batcher, Proposer / Asserter. Prefer: OP Stack, L1 "
        "bridge and dispute-game contracts."
    ),
    "oracle-pattern": (
        "Smart contracts execute deterministically and can only read onchain "
        "state, yet lending, derivatives, insurance, prediction markets, "
        "gaming, and automation depend on offchain facts: asset. Shape: "
        "Oracle Nodes, Data Sources, Aggregator Contract, Proxy Contract, "
        "Consumer Contract. Prefer: Chainlink Data Feeds, Chainlink Offchain "
        "Reporting, Chainlink VRF v2.5."
    ),
    "passthrough-replicator": (
        "A source topic, or an external system that writes to one, must be "
        "republished to a destination topic — renamed, re-partitioned, "
        "re-keyed, filtered, or routed — with no aggregation, no. Shape: "
        "Source processor, Key/value re-map, Repartition topic, Sink "
        "processor, Provenance header. Prefer: Apache Kafka, Kafka Streams, "
        "Confluent Replicator, Kafka Connect."
    ),
    "pattern-matching-cep": (
        "A business event is only recognizable after several events have "
        "occurred, in a specific order, within a bounded time span — 'order "
        "created, then payment declined, then customer cancelled. Shape: "
        "Pattern, Condition, Time constraint, Pattern stream, Process "
        "function. Prefer: Apache Flink CEP, Kafka Streams, Drools, Drools "
        "Fusion."
    ),
    "plasma": (
        "Ethereum L1 settles only 15-30 TPS with volatile gas fees, pricing "
        "out high-volume payments while remaining the most secure settlement "
        "layer available. Shape: Root Contract (PlasmaFramework), Child-Chain "
        "Operator, Watcher Network, Exit Game Contracts (PaymentExitGame), "
        "Token Vaults. Prefer: OMG PlasmaFramework root contracts, MoreVP "
        "exit protocol."
    ),
    "pos-energy-efficiency": (
        "A public or consortium ledger needs Sybil-resistant block "
        "production, but proof-of-work secures it by burning country-scale "
        "electricity in a mining race (Ethereum miners drew ~44-78 TWh/yr. "
        "Shape: Validator Client, Consensus Client, Execution Client, RANDAO "
        "Beacon, Deposit and Slashing Contract. Prefer: Ethereum, Beacon "
        "Chain consensus clients, Cardano, Algorand."
    ),
    "progressive-web-app": (
        "A web application that must start reliably on slow or absent "
        "connections, serve the content the user last interacted with, and "
        "update itself in place. Shape: Service worker, Application shell, "
        "Cache Storage, Fetch handler, Lifecycle controller. Prefer: Service "
        "Worker API, Cache Storage API, IndexedDB, Web App Manifest."
    ),
    "request-batch": (
        "A client needs several independent operations from the same provider "
        "— read a user, list their files, fetch their permissions — and "
        "issues them one at a time. Shape: Request Bundle, Batch Endpoint, "
        "Metadata Element, Bundle Dispatcher, Response Bundle. Prefer: "
        "Microsoft Graph $batch, Facebook Graph API Batch Requests, Apollo "
        "Client apollo-link-batch-http."
    ),
    "responsive-design": (
        "One product must be served to phones, tablets, laptops, televisions "
        "and embedded screens that differ in viewport width, pixel density, "
        "input modality, network class and CPU budget. Shape: "
        "Breakpoint ladder, Media-query layer, Container-query context, "
        "Client-hint negotiator, Edge media transformer. Prefer: CSS media "
        "queries, CSS container queries, HTTP Client Hints, srcset and sizes "
        "attributes."
    ),
    "rollup-as-a-service": (
        "A product team needs its own application-specific chain with custom "
        "fees, throughput, and governance, but building rollup infrastructure "
        "from scratch demands deep Ethereum client. Shape: Sequencer/Batcher, "
        "Prover (ZK stacks), Data-Availability Writer, Settlement/Bridge "
        "Contracts, Full Nodes and RPC Fleet. Prefer: OP Stack, Arbitrum "
        "Orbit, Polygon CDK / AggLayer, zkSync ZK Stack."
    ),
    "secretless-connector": (
        "An application must authenticate to a database, broker, or HTTP "
        "service, but the credential must not exist inside the application "
        "process. Shape: Secretless Broker (sidecar), Service Connector (pg, "
        "mysql, http, ..), Credential Provider, Target service / database. "
        "Prefer: Secretless, Kubernetes sidecar containers, CyberArk Conjur, "
        "HashiCorp Vault."
    ),
    "secrets-management": (
        "An estate in which credentials - database passwords, API keys, OAuth "
        "client secrets, SSH keys, encryption keys - live in source "
        "repositories, environment variables, CI variables and config. Shape: "
        "Vault server (HA, seal/unseal), Secret provider / SDK or agent, Auth "
        "method bound to platform identity. Prefer: HashiCorp Vault, External "
        "Secrets Operator, Sealed Secrets, cert-manager."
    ),
    "shared-database": (
        "This is an architecture ANTI-PATTERN catalog entry, not a "
        "recommendation. Shape: Shared database server, Shared schema, Shared "
        "credentials or broad grants, Hot table, Compatibility window. "
        "Prefer: MySQL, PostgreSQL, SQL Server, Oracle Database."
    ),
    "sidecar": (
        "A primary application needs cross-cutting peripheral functionality — "
        "logging and metrics shipping, secret and config fetching, service "
        "discovery, outbound mTLS termination, retry and sync. Shape: Primary "
        "application container, Sidecar container, Co-location unit, Local "
        "API surface, Lifecycle ordering mechanism. Prefer: Kubernetes Pods, "
        "Envoy, Linkerd2 proxy, Dapr / daprd sidecar."
    ),
    "sidechain-validator": (
        "A parent chain (Bitcoin, Ethereum) is congested, expensive, or "
        "unwilling to hard-fork in custom execution rules, yet its asset must "
        "stay the unit of account. Shape: Sidechain Validator Set, Sidechain "
        "Execution Nodes, Two-Way Peg Bridge, Checkpoint Anchor, Checkpoint "
        "Proposer and Relayers. Prefer: RSK / Rootstock, Liquid Network, "
        "Polygon PoS, Gnosis Chain."
    ),
    "skew-detector": (
        "Aggregate throughput and cluster utilisation look healthy, yet one "
        "key, tenant, partition or worker carries a disproportionate share of "
        "the work and caps total throughput. Shape: Distribution sampler, Lag "
        "comparator, Key profiler, Skew classifier, Remediation advisor. "
        "Prefer: Apache Kafka, Apache Spark Adaptive Query Execution, Apache "
        "Flink, Prometheus."
    ),
    "sla-misses-detector": (
        "A data pipeline's promise is not 'the process is up' but 'data is "
        "fresh, complete and correct within X'. Shape: SLI definitions, "
        "Objective store, Burn-rate evaluator, Multiwindow gate, Severity "
        "classifier. Prefer: Prometheus, Alertmanager, Google Cloud "
        "Monitoring, Grafana."
    ),
    "smart-contract-pattern": (
        "Multiple parties need a shared agreement executed exactly as written "
        "without relying on a trusted intermediary. Shape: Smart Contract, "
        "Virtual Machine Runtime, Ledger State, Transaction and Event "
        "Interface, Metering and Endorsement Policy. Prefer: Solidity, Vyper, "
        "Ethereum Virtual Machine, Hyperledger Fabric chaincode."
    ),
    "state-channel": (
        "Two or more known parties expect a high frequency of small transfers "
        "or rapid contract interactions (micropayments, gaming moves, "
        "streaming money, IoT device settlement) where L1 throughput. Shape: "
        "Adjudicator Contract, Channel Client, Funding Module, Dispute "
        "Registry, Watchtower. Prefer: Lightning Network, Raiden Network, "
        "Perun / go-perun framework, Nitro / go-nitro protocol."
    ),
    "stateful-processing": (
        "Aggregations, joins and windowed computations must remember what "
        "came before — a running count per key, the last N minutes of a "
        "join's other side, an accumulating session. Shape: State store, "
        "Changelog topic, Cache layer, Commit protocol, Transactional buffer. "
        "Prefer: Apache Kafka, Kafka Streams, Apache Flink, RocksDB."
    ),
    "stateful-sessionizer": (
        "Raw telemetry arrives as sparse, individually meaningless events "
        "with no session identifier — page views, API calls, heartbeats. "
        "Shape: Session window assigner, Gap extractor, Session store, "
        "Merging window function, Merging trigger. Prefer: Apache Flink, "
        "Apache Kafka Streams, Apache Spark Structured Streaming, ClickHouse."
    ),
    "static-content-hosting": (
        "A web application's request stream mixes two very different kinds of "
        "traffic. Shape: Object Storage Container, Static Website Endpoint, "
        "Content Delivery Network, Custom Domain and TLS. Prefer: Azure CDN, "
        "Amazon S3, AWS CloudFront."
    ),
    "static-joiner": (
        "A stream must be enriched with reference data that changes rarely — "
        "currency and geo tables, product catalogues, feature flags, model "
        "metadata, tenant configuration — so issuing a network. Shape: "
        "Reference source, Global/local reference table, Broadcast join "
        "operator, External lookup operator, Refresh mechanism. Prefer: "
        "Apache Kafka, Kafka Streams, Apache Spark, Apache Flink."
    ),
    "stream-bridging": (
        "Data is produced outside the streaming platform — a REST endpoint, a "
        "relational table exposed through change data capture, a legacy "
        "broker, a file drop, an edge gateway — and must enter the bus. Shape: "
        "Foreign source adapter, Bridge component, Dynamic destination "
        "resolver, Connector, Local buffer. Prefer: Spring Cloud Stream "
        "StreamBridge, Apache Kafka, Kafka Connect, Debezium."
    ),
    "streaming-processing": (
        "An unbounded sequence of events must be transformed continuously, "
        "one record at a time, with results visible in milliseconds rather "
        "than at the end of a batch window. Shape: Partitioned log, Source "
        "processor, Stateless operator, Stateful operator, Changelog and "
        "commit protocol. Prefer: Apache Kafka Streams, Apache Flink, Kafka "
        "Streams Processor API, RocksDB."
    ),
    "time-series-iot": (
        "Thousands of devices emit millions of timestamped samples on "
        "periodic schedules, into a schema that is defined by the fleet "
        "rather than by a single designer, where series are strongly. Shape: "
        "Time-series model, Columnar chunk, Chunk group, Statistics tiers, "
        "Downsampling / continuous aggregate. Prefer: Apache IoTDB / TsFile, "
        "InfluxDB, Apache Druid."
    ),
    "tokenization": (
        "Issuers need to represent ownership in illiquid real-world assets "
        "(real estate, private credit, treasuries, commodities, art, fund "
        "equity) as blockchain tokens that enable fractional. Shape: Token "
        "Contract, Issuance/Redemption Controller, Identity Registry, "
        "Compliance Module, Custody/SPV Adapter. Prefer: Solidity."
    ),
    "valet-key": (
        "Cloud storage and queues can serve a client upload or download "
        "directly, but only if the client holds credentials for the store. "
        "Shape: Valet key service / token issuer API, Stored access policy, "
        "Upload-complete notification handler. Prefer: AWS S3 pre-signed "
        "URLs, Azure Blob Storage user-delegation SAS, Google Cloud Storage "
        "V4 signed URLs."
    ),
    "validium": (
        "Validium is a Layer-2 scaling architecture for chains like Ethereum "
        "that pairs off-chain execution with on-chain validity proofs but "
        "keeps transaction data off the base chain. Shape: Sequencer / "
        "Operator, Prover (zk-SNARK/zk-STARK circuit), L1 Verifier Contract, "
        "L1 Main Contract."
    ),
    "vertical-partitioner": (
        "One wide entity is decomposed along field groups — hot versus cold, "
        "sensitive versus public, indexed versus blob — into separate "
        "partitions, columns, files or topics, so each access path. Shape: "
        "Field group, Key selector, Repartition topic, Co-partitioning "
        "contract, Merge operator. Prefer: Apache Kafka, Kafka Streams, "
        "Columnar stores, Object storage partitioned layouts."
    ),
    "vertical-partitioner-removal": (
        "The vertical split is designed specifically so a whole field group, "
        "subject or segment can be removed independently while everything "
        "around it stays intact — a right-to-erasure request. Shape: "
        "Per-subject key record, Tombstone, Erasable-field group, Purge "
        "manifest, Immutability guard. Prefer: Per-subject DEK wrapped by a "
        "KEK, AWS KMS / GCP Cloud KMS / Vault Transit, Apache Kafka."
    ),
    "watermark-pattern": (
        "Events arrive out of order, so an operator cannot tell when it is "
        "safe to close a window. Shape: Watermark generator, Watermark "
        "propagation, Event-time clock, Watermark minimiser, Idleness "
        "detector. Prefer: Apache Flink watermark strategies, Apache Kafka "
        "Streams, Apache Beam, Apache Spark Structured Streaming."
    ),
    "windowing-pattern": (
        "A stream is unbounded, so no aggregate over 'everything' is "
        "computable. Shape: Window assigner, Window state store, Trigger, "
        "Grace or allowed lateness, Emit policy. Prefer: Apache Kafka "
        "Streams, Apache Flink, Apache Spark Structured Streaming, Apache "
        "Beam."
    ),
    "wormhole-messaging": (
        "Independent blockchains with no shared consensus or trust need to "
        "exchange arbitrary messages and value. Shape: Emitter Contract, Core "
        "Contract, Guardian Node, Guardian Watcher, VAA (Verifiable Action "
        "Approval). Prefer: Wormhole Core Contracts, Wormhole TypeScript and "
        "Solidity SDKs."
    ),
    "write-ahead-log": (
        "State that must survive a crash is written to a durable, ordered log "
        "before it is considered committed, and recovery replays that log. "
        "Shape: Changelog topic, Local state store, Commit protocol, "
        "Transactional state store, Position/checkpoint file. Prefer: Apache "
        "Kafka changelog topics, Kafka Streams state stores, RocksDB, Apache "
        "Flink."
    ),
    "zero-trust-architecture": (
        "An organization whose assets no longer sit behind one boundary: "
        "remote users, bring-your-own-device, SaaS tenants, and cloud "
        "workloads outside the enterprise-owned network. Shape: Policy engine "
        "(PE), Policy administrator (PA), Control plane, Data plane. Prefer: "
        "NIST SP 800-207, OIDC / OAuth 2.0, SPIFFE / SPIRE."
    ),
    "zk-rollup": (
        "Ethereum L1 processes roughly 15-30 TPS with volatile gas fees, "
        "pricing out high-volume applications (payments, trading, gaming) "
        "while remaining the most secure and decentralized settlement. Shape: "
        "Sequencer, Prover, L1 Rollup Contract, L1 Verifier Contract, "
        "Data-Availability Publisher. Prefer: ZK Stack / zkSync Era, "
        "Starknet, Polygon zkEVM."
    ),
}



def get_style_guidance(style: str) -> str:
    """Return canonical-shape guidance for ``style`` with a safe default fallback."""
    return STYLE_GUIDANCE.get(style, DEFAULT_STYLE_GUIDANCE)
