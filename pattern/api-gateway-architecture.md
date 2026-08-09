# API Gateway Pattern

## Pattern Overview

[JSON Data](./api-gateway-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         API Gateway Architecture                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────┐     ┌────────────────────────────────────────────────┐   │
│  │  Mobile  │────►│                                                │   │
│  │  Client  │     │              API Gateway                      │   │
│  └──────────┘     │                                                │   │
│                    │  ┌──────────┐  ┌──────────┐  ┌──────────┐  │   │
│  ┌──────────┐     │  │   Auth   │  │   Rate   │  │  Cache   │  │   │
│  │   Web    │────►│  │ Handler  │  │  Limiter │  │          │  │   │
│  │  Client  │     │  └──────────┘  └──────────┘  └──────────┘  │   │
│  └──────────┘     │                                                │   │
│                    │  ┌──────────┐  ┌──────────┐  ┌──────────┐  │   │
│  ┌──────────┐     │  │  Router  │  │Response  │  │   Log    │  │   │
│  │   IoT    │────►│  │          │  │Aggregator│  │          │  │   │
│  │  Device  │     │  └──────────┘  └──────────┘  └──────────┘  │   │
│  └──────────┘     └────────────────────────────────────────────────┘   │
│                                      │                                   │
│              ┌───────────────────────┼───────────────────────┐           │
│              │                       │                       │           │
│              ▼                       ▼                       ▼           │
│     ┌──────────────┐        ┌──────────────┐        ┌──────────────┐    │
│     │  User        │        │   Order      │        │   Product    │    │
│     │  Service     │        │   Service    │        │   Service    │    │
│     └──────────────┘        └──────────────┘        └──────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Backend for Frontend (BFF)**: Dedicated gateway configuration per client type for client-specific data needs
- **Service Mesh**: Complements gateway for east-west traffic management (Istio, Linkerd)
- **Circuit Breaker**: Prevents cascade failures when upstream services are unhealthy
- **Strangler Fig**: Incremental migration strategy from monolith to microservices
- **GraphQL Federation**: API composition pattern for gateway aggregation layer

(End of file - total 175 lines)