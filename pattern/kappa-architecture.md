# Kappa Architecture Pattern

## Pattern Overview

[JSON Data](./kappa-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Kappa Architecture                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                         Data Flow                                  │  │
│  │                                                                    │  │
│  │              Incoming Events (Immutable Log)                       │  │
│  │                         │                                          │  │
│  │                         ▼                                          │  │
│  │              ┌─────────────────────┐                               │  │
│  │              │   Message Queue     │                               │  │
│  │              │   (Kafka/Pulsar)    │                               │  │
│  │              │                     │                               │  │
│  │              │  • Retained        │                               │  │
│  │              │  • Replayable      │                               │  │
│  │              │  • Immutable       │                               │  │
│  │              └──────────┬──────────┘                               │  │
│  │                         │                                          │  │
│  │                         ▼                                          │  │
│  │              ┌─────────────────────┐                               │  │
│  │              │  Stream Processor  │                               │  │
│  │              │  (Flink/Spark)     │                               │  │
│  │              │                     │                               │  │
│  │              │  Same Code ─────┐  │                               │  │
│  │              │  for Both       │  │                               │  │
│  │              │  Real-time &     │  │                               │  │
│  │              │  Historical      │  │                               │  │
│  │              └──────────┬──────┘  │                               │  │
│  │                         │         │                               │  │
│  │                         │         │ (replay)                      │  │
│  │                         ▼         ▼                                │  │
│  │              ┌─────────────────────┐                               │  │
│  │              │  Serving Layer    │                               │  │
│  │              │  (Results/        │                               │  │
│  │              │  Projections)     │                               │  │
│  │              └─────────────────────┘                               │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Event-Driven Architecture**: Decouples producers from consumers via event channels
- **CQRS (Command Query Responsibility Segregation)**: Separates read and write concerns; natural fit with Kappa's serving layer
- **Event Sourcing**: Stores state changes as a sequence of events; complements Kappa's log-centric approach
- **Lambda Architecture**: Predecessor pattern with separate batch and speed layers; Kappa simplifies by eliminating batch path
- **Pipe-and-Filter**: Kappa can be viewed as a specialized pipe-and-filter where filters are stream operators and pipes are Kafka topics
- **Saga Pattern**: Complements Kappa for distributed transactions across microservices
- **Materialized View Pattern**: Kappa's serving layer implements materialized views updated by stream processing