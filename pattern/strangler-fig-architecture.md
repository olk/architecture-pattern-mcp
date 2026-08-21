# Strangler Fig Architecture

## Context

Evolving large monolithic systems where incremental migration to a modern architecture is required without risking big-bang rewrites. The pattern enables gradual, low-risk replacement of specific modules or capabilities of a monolithic application by incrementally routing traffic to new services, validating behavior, and ultimately decommissioning the old implementation.

## Architecture

```
                     ┌─────────────────┐
  Requests ─────────▶│  Strangler      │
                     │  Gateway (Facade)│
                     └────────┬────────┘
                              │
                    ┌─────────┴──────────┐
                    │                     │
             ┌──────▼──────┐      ┌───────▼──────┐
             │   Legacy    │      │  New Service  │
             │   Monolith  │      │  (migrated)   │
             └─────────────┘      └───────────────┘
```

## Key Characteristics

- **Migration strategy**: Incremental, traffic-based routing
- **Risk**: Low (small, reversible steps)
- **Duration**: Medium-to-long (months to years)
- **Team impact**: Gradual upskilling

## When to Use

- Legacy modernization without service windows
- High-value, high-risk monolith migrations
- Teams learning microservices incrementally

## When to Avoid

- Greenfield projects
- Tightly coupled data layer
- Small teams with limited operational maturity

## Quality Attributes

| Attribute       | Score |
|----------------|-------|
| Scalability    | 7     |
| Maintainability| 8     |
| Reliability    | 7     |
| Security       | 6     |
| Performance    | 5     |
| Simplicity     | 5     |
