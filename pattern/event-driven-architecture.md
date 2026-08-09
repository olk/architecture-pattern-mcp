# Event-Driven Architecture Pattern

## Pattern Overview

[JSON Data](./event-driven-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     Event-Driven Architecture                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      Event Producer                                │  │
│  │   (Application, Service, IoT Device - detects state changes)      │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                │                                          │
│                                ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      Event Channel                                 │  │
│  │              (Message Broker / Event Bus)                          │  │
│  │        Amazon EventBridge | SNS | Kafka | Pub/Sub               │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                │                                          │
│              ┌─────────────────┼─────────────────┐                       │
│              ▼                 ▼                 ▼                       │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐        │
│  │  Event Consumer  │ │  Event Consumer  │ │  Event Consumer  │        │
│  │   (Service A)    │ │   (Service B)    │ │   (Service C)    │        │
│  └──────────────────┘ └──────────────────┘ └──────────────────┘        │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Event Sourcing**: Store state changes as a sequence of events for audit trails and replay capability
- **CQRS**: Separate read and write models for complex domains with different performance characteristics
- **Pub/Sub**: One event published, multiple consumers receive their own copy independently
- **Event Streaming**: Ordered, durable event log with replay capability (Apache Kafka pattern)
- **Choreography**: Each service reacts to events independently without central orchestrator
- **Orchestration**: Central coordinator manages multi-step business workflows with compensation
- **Pipe-and-Filter**: Can be combined with EDA for stream processing pipelines

---

## References

- [AWS Architecture Blog: Best practices for implementing event-driven architectures](https://aws.amazon.com/blogs/architecture/best-practices-for-implementing-event-driven-architectures-in-your-organization/)
- [Microsoft Azure: Event-Driven Architecture Style](https://learn.microsoft.com/en-us/azure/architecture/guide/architecture-styles/event-driven)
- [Confluent: Event-Driven Architecture](https://www.confluent.io/learn/event-driven-architecture/)
- [Gravitee: Event-Driven Architecture Patterns](https://www.gravitee.io/blog/event-driven-architecture-patterns)