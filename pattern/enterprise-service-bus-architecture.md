# Enterprise Service Bus (ESB) Pattern

## Pattern Overview

[JSON Data](./enterprise-service-bus-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Message Bus / ESB Architecture                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐        │
│  │  ERP     │     │   CRM    │     │  Custom  │     │  legacy  │        │
│  │  System  │     │  System  │     │  App #1  │     │  System  │        │
│  └────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘        │
│       │                │                │                │               │
│       ▼                ▼                ▼                ▼               │
│  ┌─────────────────────────────────────────────────────────────┐        │
│  │                    Message Bus (ESB)                          │        │
│  │                                                              │        │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │        │
│  │  │  Message    │  │   Content   │  │   Message   │          │        │
│  │  │  Listener   │──│   Based     │──│   Router    │          │        │
│  │  │  (Adapter)  │  │   Router    │  │             │          │        │
│  │  └─────────────┘  └─────────────┘  └─────────────┘          │        │
│  │                                                              │        │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │        │
│  │  │  Message    │  │   Data      │  │   Message   │          │        │
│  │  │  Filter     │  │  Trans-     │──│   Validator │          │        │
│  │  │             │  │  former     │  │             │          │        │
│  │  └─────────────┘  └─────────────┘  └─────────────┘          │        │
│  │                                                              │        │
│  │  ┌─────────────────────────────────────────────────────┐    │        │
│  │  │              Message Repository (Audit Log)           │    │        │
│  │  └─────────────────────────────────────────────────────┘    │        │
│  └──────────────────────────────────────────────────────────────┘        │
│                           │                                               │
│         ┌─────────────────┼─────────────────┐                            │
│         ▼                 ▼                 ▼                             │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐                    │
│  │  Service A  │   │  Service B  │   │  Service C  │                    │
│  └─────────────┘   └─────────────┘   └─────────────┘                    │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Message Router**: Routes data based on content (extends basic routing)
- **Event-Driven Consumer**: Decouples producers from consumers asynchronously
- **Pub/Sub (Publish-Subscribe)**: One sender, multiple subscribers for event-driven notifications
- **Dead Letter Queue**: Captures and processes failed messages for error handling
- **Content-Based Router**: Routes messages based on message content and metadata
- **Competing Consumers**: Scales message processing horizontally across multiple consumers
- **API Gateway**: Acts as single entry point for microservice architectures (modern ESB alternative)
- **Message Broker**: Provides async messaging infrastructure (Kafka, RabbitMQ for event-driven ESB alternatives)