# Saga Pattern

## Pattern Overview

[JSON Data](./saga-pattern-architecture.json)

## Architecture Diagram

### Saga Orchestration Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Saga Orchestration Architecture                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                     Saga Orchestrator                             │  │
│  │                                                                   │  │
│  │   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐     │  │
│  │   │ Step 1  │───►│ Step 2  │───►│ Step 3  │───►│ Step 4  │     │  │
│  │   │ Reserve │    │ Process │    │  Ship   │    │ Confirm │     │  │
│  │   │Inventory│    │Payment  │    │ Order   │    │ Order   │     │  │
│  │   └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘     │  │
│  │        │              │              │              │            │  │
│  └────────┼──────────────┼──────────────┼──────────────┼────────────┘  │
│           │              │              │              │               │
│           ▼              ▼              ▼              ▼               │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐  │
│  │  Inventory   │ │   Payment    │ │   Shipping   │ │   Order      │  │
│  │   Service    │ │   Service    │ │   Service    │ │   Service    │  │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Compensation Flow (on failure)                 │  │
│  │                                                                   │  │
│  │   Compensate Step 3 ──► Compensate Step 2 ──► Compensate Step 1   │  │
│  │   (Cancel Ship)       (Refund Payment)     (Release Inventory)   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Orchestration-Based Saga Flow

```
Order Created Event
       │
       ▼
┌─────────────────┐
│     Reserve     │    ◄── Compensate: Release Inventory
│    Inventory    │
└────────┬────────┘
         │ Inventory Reserved
         ▼
┌─────────────────┐
│    Process      │    ◄── Compensate: Refund Payment
│     Payment     │
└────────┬────────┘
         │ Payment Processed
         ▼
┌─────────────────┐
│    Schedule     │    ◄── Compensate: Cancel Shipping
│     Shipping    │
└────────┬────────┘
         │ Shipping Scheduled
         ▼
┌─────────────────┐
│    Confirm      │
│     Order       │
└─────────────────┘
```

### Choreography-Based Saga

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│Order Service │      │   Payment    │      │  Inventory   │
│              │      │   Service    │      │   Service    │
└──────┬───────┘      └──────┬───────┘      └──────┬───────┘
       │                     │                     │
       │──publish───────────►│                     │
       │  OrderCreatedEvent  │                     │
       │                     │──subscribe─────────►│
       │                     │  PaymentProcessed   │
       │                     │                     │──subscribe──►┐
       │◄────────────────────│                     │             │
       │  payment-failed    │                     │             ▼
       │                     │                     │  inventory-released
       │◄────────────────────────────────────────│  order-cancelled
       │                     │                     │
       │                     │◄───────────────────┘
       │                     │   payment-failed
       └─────────────────────┘
```

## Related Patterns

- **Event-Driven Architecture**: Sagas emit events that drive reactive behaviors in participant services
- **Transactional Outbox**: Ensures atomicity between local DB changes and event publishing
- **Command Query Responsibility Segregation (CQRS)**: Useful for reconstructing saga state in choreography-based sagas
- **Retry Pattern**: Transient failures should be retried with exponential backoff before triggering compensation
- **Circuit Breaker**: Prevents cascade failures when downstream services are unavailable
- **Semantic Locking**: Application-level locks prevent downstream reads from acting on dirty intermediate state
- **Workflow Engine**: Saga orchestrator evolves into a general-purpose workflow engine (Temporal, AWS Step Functions)