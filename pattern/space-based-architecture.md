# Space-Based Architecture Pattern

## Pattern Overview

[JSON Data](./space-based-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Space-Based Architecture                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Processing Grid (In-Memory Data Grid)            │  │
│  │                                                                    │  │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐              │  │
│  │  │ Node 1  │  │ Node 2  │  │ Node 3  │  │ Node N  │              │  │
│  │  │┌─────┐ │  │┌─────┐ │  │┌─────┐ │  │┌─────┐ │              │  │
│  │  ││Processing│ ││Processing│ ││Processing│ ││Processing│ │              │  │
│  │  ││ Unit │ │  ││ Unit │ │  ││ Unit │ │  ││ Unit │ │              │  │
│  │  │└─────┘ │  │└─────┘ │  │└─────┘ │  │└─────┘ │              │  │
│  │  │┌─────┐ │  │┌─────┐ │  │┌─────┐ │  │┌─────┐ │              │  │
│  │  ││ Data │ │  ││ Data │ │  ││ Data │ │  ││ Data │ │              │  │
│  │  ││ Cache │ │  ││ Cache │ │  ││ Cache │ │  ││ Cache │ │              │  │
│  │  │└─────┘ │  │└─────┘ │  │└─────┘ │  │└─────┘ │              │  │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘              │  │
│  │         │            │            │            │                  │  │
│  │         └────────────┴────────────┴────────────┘                  │  │
│  │                         │                                        │  │
│  │                  ┌──────┴──────┐                                 │  │
│  │                  │  Virtual   │                                 │  │
│  │                  │  Shared    │                                 │  │
│  │                  │  Memory     │                                 │  │
│  │                  └────────────┘                                 │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      Messaging Grid                                │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐                    │  │
│  │  │  Queue    │  │  Queue    │  │  Queue    │                    │  │
│  │  │  (Shared) │  │  (Shared) │  │  (Shared) │                    │  │
│  │  └───────────┘  └───────────┘  └───────────┘                    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Event-Driven Architecture**: Complements SBA for async inter-component communication
- **CQRS (Command Query Responsibility Segregation)**: Read and write separation pairs well with in-memory grids
- **Microservices**: Processing units can evolve into independent microservices over time
- **Tuple Space**: The original concept from which SBA derives; provides shared memory space for parallel computing
- **Replicated Caching**: Similar to SBA but typically simpler; good stepping stone for teams new to distributed caching

(End of file - total 214 lines)