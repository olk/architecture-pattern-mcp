# Edge Computing Architecture

## Pattern Overview

[JSON Data](./edge-computing-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Edge Computing Architecture                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                        Cloud (Central)                            │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐       │  │
│  │  │  AI/ML    │  │  Data     │  │  Global   │  │  Legacy   │       │  │
│  │  │  Training │  │  Analytics│  │   Rules   │  │  Systems  │       │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                           │
│                    ◄─────────┴──────── ──►                               │
│                    (Sync/Async replication)                              │
│                              │                                           │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Edge Layer (Regional)                          │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐       │  │
│  │  │ Regional  │  │  Local    │  │  Device   │  │   Edge    │       │  │
│  │  │ Aggregation│  │  Storage  │  │  Gateway  │  │  Compute  │       │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                           │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      Edge Layer (Near-Device)                     │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐       │  │
│  │  │   IoT     │  │  Sensor   │  │  Local    │  │   Edge    │       │  │
│  │  │  Gateway  │  │  Aggreg.  │  │   Cache   │  │  Analytics│       │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                           │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                        Device Layer                               │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐       │  │
│  │  │   Edge    │  │   IoT     │  │  Smart    │  │  Wearable │       │  │
│  │  │  Device   │  │  Sensors  │  │  Cameras  │  │  Devices  │       │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Pipe-and-Filter**: Composable data processing at edge layer
- **Circuit Breaker**: Graceful degradation when cloud unreachable
- **Store-and-Forward**: Durable buffering during connectivity loss
- **Event-Driven Architecture**: Decoupled communication between layers
- **CQRS (Command Query Responsibility Segregation)**: Separates read/write for edge optimization
- **Saga Pattern**: Distributed transaction management across edge and cloud
- **Outbox Pattern**: Reliable event publishing for distributed edge systems
- **Tale-Triggered Compute**: Event-driven execution without persistent infrastructure
