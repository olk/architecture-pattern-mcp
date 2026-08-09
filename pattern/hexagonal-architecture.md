# Hexagonal Architecture (Ports and Adapters)

## Pattern Overview

[JSON Data](./hexagonal-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Hexagonal Architecture                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│                              ┌─────────┐                                │
│                              │ External│                                │
│                              │  World  │                                │
│                              └────┬────┘                                │
│                                   │                                      │
│                    ┌─────────────┼─────────────┐                        │
│                    ▼             ▼             ▼                        │
│              ┌───────────┐ ┌───────────┐ ┌───────────┐                  │
│              │   HTTP    │ │  Database │ │   Message │                  │
│              │  Adapter  │ │  Adapter  │ │  Adapter  │                  │
│              └─────┬─────┘ └─────┬─────┘ └─────┬─────┘                  │
│                    │             │             │                          │
│                    └─────────────┼─────────────┘                          │
│                              │                                            │
│  ┌───────────────────────────┼──────────────────────────────────────┐  │
│  │                           ▼                                         │  │
│  │  ┌─────────────────────────────────────────────────────────────┐ │  │
│  │  │                      PORTS (Interfaces)                       │ │  │
│  │  │                                                              │ │  │
│  │  │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │ │  │
│  │  │   │  Inbound   │  │  Outbound   │  │  Outbound   │          │ │  │
│  │  │   │   Ports    │  │   Ports     │  │   Ports     │          │ │  │
│  │  │   │ (Driving) │  │ (Driven)    │  │ (Driven)    │          │ │  │
│  │  │   │            │  │            │  │            │          │ │  │
│  │  │   │ • IOrder   │  │ • IOrder   │ │ • IEvent    │          │ │  │
│  │  │   │   Service  │  │   Repo     │ │   Publisher │          │ │  │
│  │  │   └─────────────┘  └─────────────┘  └─────────────┘          │ │  │
│  │  └─────────────────────────────────────────────────────────────┘ │  │
│  │                           │                                       │  │
│  │                           ▼                                       │  │
│  │  ┌─────────────────────────────────────────────────────────────┐ │  │
│  │  │                      DOMAIN (Core)                             │ │  │
│  │  │                                                              │ │  │
│  │  │   ┌───────────┐  ┌───────────┐  ┌───────────┐               │ │  │
│  │  │   │ Entities  │  │ Value     │  │ Domain    │               │ │  │
│  │  │   │           │  │ Objects   │  │ Services  │               │ │  │
│  │  │   │ • Order   │  │ • Money   │  │           │               │ │  │
│  │  │   │ • LineItem│  │ • Address │  │ • Pricing │               │ │  │
│  │  │   └───────────┘  └───────────┘  └───────────┘               │ │  │
│  │  └─────────────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Onion Architecture**: Similar pattern emphasizing inward dependencies; often considered a variant of hexagonal architecture with more explicit layering

- **Clean Architecture**: Similar principles with separate layers for entities, use cases, and interface adapters; popularized by Robert C. Martin

- **CQRS (Command Query Responsibility Segregation)**: Complements hexagonal architecture by separating read and write operations; driving ports can be split into command and query handlers

- **Event-Driven Architecture**: Uses domain events published through outbound ports to decouple services; natural evolution from hexagonal architecture

- **Service Mesh**: Provides infrastructure for service-to-service communication; works well with hexagonal architecture's bounded context isolation

- **Strangler Fig Pattern**: Migration strategy for incrementally replacing monolith with hexagonal services; maintain production stability during transition