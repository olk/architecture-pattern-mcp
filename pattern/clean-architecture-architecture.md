# Clean Architecture

## Context

Software systems requiring strong separation between business logic and external frameworks, databases, and UI layers. Clean Architecture organizes a system into concentric layers with a strict dependency rule: all dependencies point inward toward the domain core.

## Layer Structure

```
  ┌──────────────────────────────────────────────┐
  │  Frameworks & Drivers (UI, DB, Web, etc.)    │
  ├──────────────────────────────────────────────┤
  │  Interface Adapters (Controllers, Gateways)    │
  ├──────────────────────────────────────────────┤
  │  Application Business Rules (Use Cases)       │
  ├──────────────────────────────────────────────┤
  │  Enterprise Business Rules (Entities)  ◀──────│
  └──────────────────────────────────────────────┘
                Dependencies point inward
```

## Key Characteristics

- **Dependency rule**: Inner layers never depend on outer layers
- **Framework independence**: Domain has zero framework imports
- **Testability**: Business rules testable with in-memory data
- **Database independence**: Repository interfaces, not implementations

## When to Use

- Long-lived applications with complex business logic
- Systems where domain portability matters
- Teams prioritizing maintainability over initial speed

## When to Avoid

- Simple CRUD applications
- Prototypes and POCs
- Projects with strict latency requirements

## Quality Attributes

| Attribute       | Score |
|----------------|-------|
| Scalability    | 6     |
| Maintainability| 9     |
| Reliability    | 7     |
| Security       | 7     |
| Performance    | 5     |
| Simplicity     | 4     |
