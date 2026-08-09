# Task Control Architecture (TCA) Pattern

## Pattern Overview

[JSON Data](./task-control-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    Task Control Architecture (TCA)               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌─────────────────┐    ┌──────────────┐    │
│  │    Human     │    │      TCA        │    │   Module     │    │
│  │    User     │◄──►│    Scheduler    │◄──►│   (Robot)    │    │
│  └──────────────┘    └────────┬────────┘    └──────────────┘    │
│                               │                               │
│                    ┌──────────┼──────────┐                    │
│                    ▼          ▼          ▼                    │
│              ┌─────────┐ ┌─────────┐ ┌─────────┐              │
│              │  Task   │ │ Monitor │ │Resource │              │
│              │Decomp.  │ │         │ │ Manager │              │
│              └─────────┘ └─────────┘ └─────────┘              │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Message Passing Layer                        │  │
│  │   (publish/subscribe + client/server, blocking + async)   │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Pipe-and-Filter**: Complements TCA by providing data flow patterns between task processing stages
- **Scheduler Agent Supervisor**: Azure pattern for coordinating distributed actions as single operations with retry and compensation
- **Event-Driven Architecture**: Evolved from TCA's implicit invocation for decoupled producer-consumer communication
- **Saga Pattern**: Multi-service task coordination with compensation actions for failure recovery
- **Supervisor Pattern**: Akka-style workflow orchestration coordinating multiple worker agents with centralized reliability concerns
- **Task Management & Orchestration**: Systematic task decomposition, progress tracking, and adaptive workflow management
- **Hierarchical Task Networks (HTN)**: Modern AI planning extension of TCA-style task decomposition