# CQRS (Command Query Responsibility Segregation) Architecture Pattern

## Pattern Overview

[JSON Data](./command-query-responsibility-segregation-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CQRS Architecture                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐          ┌─────────────────┐          ┌────────────┐   │
│  │   Clients   │─────────►│   Command Bus    │─────────►│  Command   │   │
│  │             │          │                  │          │  Handlers  │   │
│  └──────────────┘          └─────────────────┘          └─────┬──────┘   │
│                                                                  │       │
│                                                                  ▼       │
│  ┌──────────────┐          ┌─────────────────┐          ┌────────────┐   │
│  │   Clients   │◄─────────│   Query Bus     │◄─────────│   Query    │   │
│  │             │          │                  │          │  Handlers  │   │
│  └──────────────┘          └─────────────────┘          └─────┬──────┘   │
│                                                                  │       │
└──────────────────────────────────────────────────────────────────────────┘
                               │                    │
                               ▼                    ▼
                     ┌─────────────────┐    ┌─────────────────┐
                     │  Write Store    │    │   Read Store    │
                     │  (PostgreSQL)   │    │ (Elasticsearch, │
                     │  Optimized for  │    │  Redis, MongoDB)│
                     │  Consistency    │    │  Optimized for  │
                     └─────────────────┘    │   Queries      │
                                              └─────────────────┘
```

## Related Patterns

- **Event Sourcing**: Full audit trail with temporal queries; CQRS often uses event store on write side
- **Event-Driven Architecture**: Natural integration; events flow from command side to projections
- **Service Mesh**: With proper domain boundaries, enables distributed CQRS
- **Serverless Event-Driven Functions**: Event-driven integration at scale
- **Message Router**: Routes data based on content for branching command/query flows
- **Competing Consumers**: Scales slow projection workers horizontally
- **Compensating Transaction**: Handles failures with rollback in distributed systems
- **Outbox Pattern**: Ensures atomic writes with event publishing