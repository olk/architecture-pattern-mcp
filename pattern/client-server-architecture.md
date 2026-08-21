# Client-Server Architecture

## Context

Distributed systems where clients initiate requests and servers provide responses over a network. The foundational pattern for virtually all networked applications, APIs, and web services.

## Architecture

```
  ┌─────────┐         Network          ┌─────────────────┐
  │         │ ◀──────────────────────▶ │                 │
  │ Client  │   HTTP/REST/gRPC/etc.    │     Server     │
  │         │                           │                 │
  └─────────┘                           └────────┬────────┘
                                                 │
                                        ┌────────▼────────┐
                                        │   Load Balancer   │
                                        └────────┬────────┘
                                                 │
                                        ┌────────▼────────┐
                                        │   Data Store     │
                                        └─────────────────┘
```

## Key Characteristics

- **Request-response**: Fundamental interaction pattern
- **Stateless server**: Each request is self-contained
- **Centralized logic**: Business rules on the server
- **Heterogeneous clients**: Web, mobile, API consumers

## When to Use

- Web applications
- Mobile backends
- REST/gRPC API services
- Internal tools and enterprise applications

## When to Avoid

- Real-time systems
- Sub-millisecond latency requirements
- Highly concurrent stateful workloads
- Systems requiring offline operation

## Quality Attributes

| Attribute       | Score |
|----------------|-------|
| Scalability    | 7     |
| Maintainability| 6     |
| Reliability    | 6     |
| Security       | 7     |
| Performance    | 6     |
| Simplicity     | 8     |
