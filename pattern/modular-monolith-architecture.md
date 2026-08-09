# Modular Monolith Architecture Pattern

## Pattern Overview

[JSON Data](./modular-monolith-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Modular Monolith Architecture                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Shared Kernel (Core)                            │  │
│  │  • Common types, interfaces, shared utilities                      │  │
│  │  • Stable, rarely changes                                         │  │
│  │  • Minimal business logic                                         │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                  │                                        │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐           │
│  │  Catalog        │  │  Ordering      │  │  Inventory     │           │
│  │  Module         │  │  Module        │  │  Module        │           │
│  │                 │  │                 │  │                 │           │
│  │  • Catalog API  │  │  • Order API   │  │  • Stock API   │           │
│  │  • Products     │  │  • Orders     │  │  • Warehouses  │           │
│  │  • Categories   │  │  • Cart       │  │  • Suppliers   │           │
│  │  • Search       │  │  • Checkout   │  │  • Transfers  │           │
│  │                 │  │                 │  │                 │           │
│  │  ┌───────────┐ │  │  ┌───────────┐ │  │  ┌───────────┐ │           │
│  │  │  Domain   │ │  │  │  Domain   │ │  │  │  Domain   │ │           │
│  │  │  Entities │ │  │  │  Entities │ │  │  │  Entities │ │           │
│  │  │ Services  │ │  │  │ Services  │ │  │  │ Services  │ │           │
│  │  │ Repos     │ │  │  │ Repos     │ │  │  │ Repos     │ │           │
│  │  └───────────┘ │  │  └───────────┘ │  │  └───────────┘ │           │
│  └───────┬────────┘  └───────┬────────┘  └───────┬────────┘           │
│          │                   │                   │                      │
│          └───────────────────┼───────────────────┘                      │
│                              ▼                                          │
│                    ┌─────────────────┐                                 │
│                    │  Shared Module   │                                 │
│                    │  (Optional)      │                                 │
│                    │  • Logging       │                                 │
│                    │  • Auth          │                                 │
│                    │  • Notifications │                                 │
│                    └─────────────────┘                                 │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Deployment Artifact                            │  │
│  │            Single JAR / Docker Image / Deployable Unit             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

### Modular Monolith vs Related Patterns

| Aspect | Modular Monolith | Microkernel | Microservices |
|--------|------------------|-------------|---------------|
| **Structure** | Domain modules with clear boundaries | Core + plugins | Independently deployable services |
| **Deployment** | Single unit | Single unit with hot-swappable plugins | Independent deployments |
| **Plugin Model** | Optional runtime plugin support | Explicit plugin architecture | N/A |
| **Data** | Module-owned or shared | Plugins can have own data | Each service owns data |
| **Coupling** | Low (explicit dependencies) | Very low (plugin isolation) | Varies |
| **Complexity** | Medium | Medium | High |
| **Maintainability** | High (domain alignment) | High (plugin isolation) | Medium-High |
| **Team Autonomy** | Medium | High | High |

### Quality Metrics Comparison

| Metric | Modular Monolith | Microservices |
|--------|-----------------|---------------|
| Deploy Time | 100% (baseline) | ~20% per service |
| Integration Bugs | 100% (fewer bugs) | ~25% more bugs |
| Developer Ramp-up | 100% (faster) | ~33% slower |
| Build Time | Fast | Slower (per-service) |
| Operational Overhead | Low | High |
| Test Automation | High | Medium |

### Evolution Paths

```
Modular Monolith
     │
     ├──► Extract Plugin ──► Microkernel Architecture
     │     (runtime flexibility)
     │
     ├──► Extract Module ──► Service (microservice)
     │     (independent scaling)
     │
     └──► Add Plugin ──► Plugin-Ready Modular Monolith
           (runtime extensibility)
```

### Real-World Implementations

| Project | Approach | Description |
|---------|----------|-------------|
| **Shopify** | Modular monolith | Domain modules with clear ownership, moving to services gradually |
| **Ruby on Rails** | Modularity via engines | Engine-based modularization for large applications |
| **Appsmith** | Modular monolith | Clear module boundaries for team autonomy |
| **Gusto** | Modular monolith | Domain-oriented decomposition |
| **Service Weaver** | Google framework | Combines monolith development velocity with microservices benefits |
| **Keel (Ktor)** | Plugin-ready microkernel | Ktor-based modular monolith kernel with hot-swappable plugins |