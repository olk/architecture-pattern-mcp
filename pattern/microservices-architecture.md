# Microservices Architecture Pattern

## Pattern Overview

[JSON Data](./microservices-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Microservices Architecture                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐            │
│    │   Client    │     │   Client    │     │   Client    │            │
│    │  (Mobile)   │     │    (Web)    │     │    (API)    │            │
│    └──────┬──────┘     └──────┬──────┘     └──────┬──────┘            │
│           │                   │                   │                    │
│           └───────────────────┼───────────────────┘                    │
│                               ▼                                        │
│                    ┌─────────────────────┐                              │
│                    │    API Gateway     │                              │
│                    │  (Auth, Routing,   │                              │
│                    │   Rate Limiting)    │                              │
│                    └──────────┬──────────┘                              │
│                               │                                         │
│     ┌─────────────────────────┼─────────────────────────┐             │
│     │                         │                         │             │
│     ▼                         ▼                         ▼             │
│ ┌────────┐              ┌────────┐              ┌────────┐          │
│ │ Order  │              │ User   │              │Payment │          │
│ │Service │              │Service │              │Service │          │
│ └───┬────┘              └───┬────┘              └───┬────┘          │
│     │                      │                      │                  │
│     ▼                      ▼                      ▼                  │
│ ┌────────┐              ┌────────┐              ┌────────┐          │
│ │ Order  │              │  User  │              │Payment │          │
│ │   DB   │              │   DB   │              │   DB   │          │
│ └────────┘              └────────┘              └────────┘          │
│                                                                          │
│    ┌─────────────────────────────────────────────────────┐             │
│    │              Service Mesh (mTLS, Observability)      │             │
│    └─────────────────────────────────────────────────────┘             │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Pipe-and-Filter**: Composable processing pipelines within microservices
- **Event-Driven Architecture**: Asynchronous communication via events
- **Service Mesh**: Infrastructure layer for service-to-service communication
- **CQRS (Command Query Responsibility Segregation)**: Separate read and write models for queries
- **Saga Pattern**: Distributed transaction management via compensating transactions
- **Database per Service**: Each service owns its database schema
- **API Gateway**: Single entry point for client applications
- **Circuit Breaker**: Resilience pattern for handling downstream failures
- **Strangler Fig**: Incremental migration from monolith to microservices
- **Backend for Frontend (BFF)**: Specialized API gateway per client type