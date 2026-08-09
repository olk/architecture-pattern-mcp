# Backend for Frontend (BFF) Pattern

## Pattern Overview

[JSON Data](./backend-for-frontend-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Backend for Frontend Architecture                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │                     Mobile Clients                               │     │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐                       │     │
│  │  │  iOS    │  │Android  │  │  Mobile Web                     │     │
│  │  │  App    │  │  App    │  │  (PWA)   │                       │     │
│  │  └────┬────┘  └────┬────┘  └────┬────┘                       │     │
│  │       │            │            │                               │     │
│  │       └────────────┼────────────┘                               │     │
│  │                    │                                             │     │
│  │                    ▼                                             │     │
│  │         ┌─────────────────────┐                                  │     │
│  │         │   Mobile BFF       │                                  │     │
│  │         │  • Bandwidth optimized                                 │     │
│  │         │  • Minimal data transfer                               │     │
│  │         │  • Aggressive caching                                  │     │
│  │         │  • Offline-friendly                                    │     │
│  │         └─────────────────────┘                                  │     │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────┐     │
│  │                     Web Clients                                 │     │
│  │  ┌─────────┐  ┌─────────┐                                      │     │
│  │  │   Web   │  │  Admin  │                                      │     │
│  │  │   SPA   │  │  Portal │                                      │     │
│  │  └────┬────┘  └────┬────┘                                      │     │
│  │       │            │                                            │     │
│  │       └────────────┼────────────────────────────────────────────┘    │
│  │                    ▼                                                     │
│  │         ┌─────────────────────┐                                    │
│  │         │    Web BFF          │                                    │
│  │         │  • Rich data        │                                    │
│  │         │  • Real-time (SSE)  │                                    │
│  │         │  • Complex queries  │                                    │
│  │         │  • Session auth     │                                    │
│  │         └─────────────────────┘                                    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                    │                                       │
│                                    ▼                                       │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │                      Backend Services                              │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │   │
│  │  │   User    │  │  Order   │  │ Product  │  │Inventory │        │   │
│  │  │  Service  │  │  Service │  │  Service │  │  Service │        │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │   │
│  └────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **API Gateway**: Provides single entry point for all clients; BFF extends this by adding client-specific logic and ownership
- **GraphQL Federation**: Alternative approach where clients specify exact data needs; BFF remains relevant when client requirements diverge significantly
- **Strangler Fig Pattern**: Enables incremental extraction of BFFs from monolithic backends through gradual routing migration
- **Circuit Breaker**: Complements BFF resilience by preventing cascading failures from downstream service outages
- **Event-Driven Architecture**: Provides alternative for asynchronous client updates; BFF can consume events and push via SSE/WebSocket for real-time experiences