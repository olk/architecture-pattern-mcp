# AI/ML-Centric Architecture

## Pattern Overview

[JSON Data](./aiml-centric-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     AI/ML-Centric Architecture                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    ML Platform Infrastructure                      │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐     │  │
│  │  │  Feature  │  │  Model    │  │  Training │  │   Model   │     │  │
│  │  │  Store    │  │  Registry │  │  Pipeline │  │  Serving  │     │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      ML Pipeline Flow                             │  │
│  │                                                                    │  │
│  │  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐       │  │
│  │  │  Data   │───►│ Feature │───►│ Train   │───►│ Evaluate │       │  │
│  │  │  Ingest │    │ Extract │    │  Model  │    │  Model   │       │  │
│  │  └─────────┘    └─────────┘    └─────────┘    └─────────┘       │  │
│  │       │                                            │             │  │
│  │       ▼                                            ▼             │  │
│  │  ┌─────────┐                               ┌─────────┐          │  │
│  │  │  Data   │                               │  Model  │          │  │
│  │  │  Store  │                               │ Register│          │  │
│  │  └─────────┘                               └─────────┘          │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Inference Serving                               │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐     │  │
│  │  │ Online    │  │ Batch     │  │  Model    │  │ Feature   │     │  │
│  │  │ Inference │  │ Inference │  │ Monitor   │  │ Store     │     │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Pipe-and-Filter Architecture**: Complements ML pipelines where data flows through sequential transformation stages (feature extraction, validation, training)
- **Event-Driven Architecture**: Enables real-time feature updates and asynchronous model triggering
- **Microservices Architecture**: Decomposes ML platform into independently deployable services (feature store, model registry, serving, monitoring)
- **CQRS (Command Query Responsibility Segregation)**: Separates read (inference) and write (training) operations in ML systems
- **Circuit Breaker**: Protects ML services from cascade failures during high load or model degradation
- **Bulkhead**: Isolates ML compute resources from other workloads to ensure predictable performance
- **Service Mesh**: Manages communication between ML components with observability, security, and resilience features

## ML Pipeline Stages

| Stage | Description | Tools |
|-------|-------------|-------|
| **Data Ingestion** | Collect data from sources with validation and quality checks | Airflow, Kafka, Spark, dbt |
| **Feature Engineering** | Transform raw data into features with point-in-time correctness | Spark, Pandas, Feast, Tecton |
| **Feature Validation** | Verify feature quality, freshness, and distribution | Great Expectations, Evidently |
| **Training** | Train model on features with experiment tracking | TensorFlow, PyTorch, XGBoost, MLflow |
| **Evaluation** | Validate model metrics against thresholds and baselines | MLflow, Weights & Biases, Ray |
| **Model Registry** | Register validated model with full metadata and lineage | MLflow, SageMaker, Neptune |
| **Serving** | Deploy model for inference with monitoring | TorchServe, Triton, KServe, BentoML |
| **Monitoring** | Track model performance, drift, and health | Evidently, Arize, Prometheus, Grafana |

## ML Inference Patterns

| Pattern | Description | Latency | Use Case |
|---------|-------------|---------|----------|
| **Online Inference** | Real-time prediction via REST/gRPC API | <100ms | Fraud detection, recommendations, search ranking |
| **Batch Inference** | Offline scoring on scheduled intervals | Minutes-hours | Churn analysis, risk scoring, reporting |
| **Streaming Inference** | Process event streams with real-time scoring | <10ms | Anomaly detection, real-time pricing, IoT |
| **Shadow Mode** | Test model alongside production without traffic split | - | Model validation before full deployment |
| **A/B Testing** | Compare model versions with traffic split | - | Model improvement validation |
| **Canary Deployment** | Gradually shift traffic to new model version | - | Safe rollout with monitoring |