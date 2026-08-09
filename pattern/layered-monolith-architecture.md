# Layered Monolith Architecture Pattern

## Pattern Overview

[JSON Data](./layered-monolith-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Layered Monolith Architecture                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Presentation Layer                            │  │
│  │  • REST Controllers, API endpoints                              │  │
│  │  • Request/Response DTOs                                         │  │
│  │  • Input validation, auth delegation                            │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                 │                                          │
│                                 ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Application Layer                             │  │
│  │  • Use case orchestration, command handlers                      │  │
│  │  • Transaction boundaries (one use case = one transaction)      │  │
│  │  • Cross-cutting concerns (logging, monitoring)                  │  │
│  │  • Domain event publishing                                       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                 │                                          │
│                                 ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      Domain Layer                                │  │
│  │  • Business logic, domain services                               │  │
│  │  • Domain entities, value objects, aggregates                    │  │
│  │  • Repository interfaces (ports)                                │  │
│  │  • Domain events, invariants                                     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                 │                                          │
│                                 ▼                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                   Infrastructure Layer                          │  │
│  │  • Repository implementations                                    │  │
│  │  • Database access, ORM, migrations                             │  │
│  │  • External service adapters                                    │  │
│  │  • Caching, messaging implementations                            │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Deployment Artifact                           │  │
│  │            Single JAR / Docker Image / Deployable Unit           │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

| Pattern | Relationship | Key Difference |
|---------|--------------|----------------|
| **Modular Monolith** | Evolution target | Organizes by business domain (vertical slices) vs technical concern (horizontal layers) |
| **Vertical Slice Monolith** | Alternative target | Feature changes contained within slice vs ripple across layers |
| **Hexagonal Architecture** | Alternative target | Ports/adapters for external dependencies vs layered structure |
| **Microservices** | Long-term extraction | Independent deployment vs single deployment unit |
| **Clean Architecture** | Related | Similar layered principles but with different organization (screaming architecture) |

### Comparison: Layered vs Modular Monolith

| Aspect | Layered Monolith | Modular Monolith |
|--------|------------------|-----------------------------------|
| **Organization** | Horizontal layers by technical concern | Vertical slices by business capability |
| **Change Scope** | Feature changes ripple across layers | Feature changes contained within slice |
| **Team Autonomy** | Teams may interfere in shared layers | Clear module ownership |
| **Domain Locality** | Business logic scattered across services | Domain logic contained end-to-end |
| **Extraction Path** | Harder to extract services | Natural seams for microservice extraction |
| **Familiarity** | Very familiar, good for teaching | Less familiar, better for complex domains |
| **Best For** | CRUD apps, simple domains | Complex domains with volatile business rules |