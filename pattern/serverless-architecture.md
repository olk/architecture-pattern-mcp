# Serverless Architecture Pattern

## Pattern Overview

[JSON Data](./serverless-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Serverless Architecture                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Cloud Provider Infrastructure                 │  │
│  │                                                                    │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │  │
│  │  │  Compute    │  │   Event     │  │   Storage   │            │  │
│  │  │  (Lambda,   │  │  Sources    │  │   (S3,      │            │  │
│  │  │  Functions) │  │  (Queues)   │  │   DynamoDB) │            │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘            │  │
│  │                                                                    │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │  │
│  │  │   API       │  │   Auth &    │  │   Monitoring│            │  │
│  │  │  Gateway    │  │   Security  │  │   (CloudWatch│            │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘            │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Function Execution                            │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐                   │  │
│  │  │ Function  │  │ Function  │  │ Function  │                   │  │
│  │  │    A      │  │    B      │  │    C      │                   │  │
│  │  │ (trigger) │  │ (process) │  │ (persist) │                   │  │
│  │  └───────────┘  └───────────┘  └───────────┘                   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Pipe-and-Filter**: Functions can be composed in pipeline patterns for data transformation workflows
- **Event-Driven Architecture**: Serverless is natural implementation for event-driven patterns
- **CQRS (Command Query Responsibility Segregation)**: Separate read/write functions and data stores for different access patterns
- **Saga Pattern**: Distributed transactions across multiple serverless functions with compensating actions
- **Circuit Breaker**: Prevents cascade failures by monitoring downstream service health
- **Strangler Fig**: Incrementally migrate monolith endpoints to serverless via API Gateway routing
- **Fan-out Pattern**: Single event triggers multiple parallel function executions
- **Materialized View**: Pre-aggregate data in optimized formats using serverless functions