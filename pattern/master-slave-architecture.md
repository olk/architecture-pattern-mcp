# Master-Slave (Leader-Follower) Architecture

## Context

Distributed computing systems where a designated master node coordinates work distribution, task scheduling, and result aggregation across a pool of worker slave nodes. The pattern is particularly suited to batch processing, parallel computation, and compute-intensive workloads that can be cleanly partitioned.

## Architecture

```
              ┌─────────────────┐
              │      Master      │
              │  (Coordinator)   │
              │  Task Queue +    │
              │  Scheduler       │
              └────────┬────────┘
                       │ assign tasks
           ┌──────────┼──────────┐
           │          │          │
    ┌──────▼──┐ ┌────▼──┐ ┌────▼──┐
    │  Slave  │ │ Slave │ │ Slave │
    │ Worker  │ │Worker │ │Worker │
    └─────────┘ └──────┘ └──────┘
         │           │          │
         └───────────┴──────────┘
                   report
```

## Key Characteristics

- **Centralized coordination**: Master owns scheduling decisions
- **Horizontal scalability**: Add slaves to increase throughput
- **Batch-oriented**: Optimized for partitioned workloads
- **Fault tolerance**: Master replication or task reassignment

## When to Use

- Batch processing pipelines
- Distributed data processing (map-reduce)
- Parallel computation (video encoding, ML training)
- Build farms and compiler toolchains

## When to Avoid

- Sub-millisecond response requirements
- Request-response APIs
- Geographically distributed high-latency workers
- Fine-grained, low-latency interactive workloads

## Quality Attributes

| Attribute       | Score |
|----------------|-------|
| Scalability    | 8     |
| Maintainability| 5     |
| Reliability    | 7     |
| Security       | 5     |
| Performance    | 8     |
| Simplicity     | 5     |
