# Event Sourcing Architecture Pattern

## Pattern Overview

[JSON Data](./event-sourcing-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Event Sourcing Architecture                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐         ┌─────────────────┐         ┌──────────────┐ │
│  │   Command    │────────►│   Aggregate     │────────►│  Event Store │ │
│  │   (Intent)   │         │   (Business     │         │  (Append-    │ │
│  │              │         │    Logic)       │         │   Only Log)  │ │
│  └──────────────┘         └─────────────────┘         └──────┬───────┘ │
│                                                              │          │
│  ┌──────────────┐         ┌─────────────────┐              │          │
│  │   Snapshot   │◄────────│   Aggregate      │◄─────────────┘          │
│  │   Store     │         │   Rehydration    │                           │
│  └──────────────┘         └─────────────────┘                           │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                      Projections (Read Models)                       │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐      │  │
│  │  │ Dashboard │  │  Search   │  │ Reporting │  │   Audit   │      │  │
│  │  │   View    │  │   Index   │  │   Views   │  │    Log    │      │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘      │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **CQRS (Command Query Responsibility Segregation)**: Separates read and write models, complementing event sourcing for optimized query handling
- **Event Streaming**: Apache Kafka and EventStoreDB provide durable event storage with stream processing capabilities
- **Saga Pattern**: Manages distributed transactions across multiple services using compensating events
- **Snapshot Pattern**: Periodically persists aggregate state to optimize replay performance
- **Event Store Clustering**: Provides high availability and scalability for event storage infrastructure