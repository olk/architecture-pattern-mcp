# Service-Oriented Architecture (SOA)

## Pattern Overview

[JSON Data](./service-oriented-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Service-Oriented Architecture (SOA)                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Enterprise Service Bus (ESB)                    │  │
│  │                                                                    │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐     │  │
│  │  │  Message  │  │   Data    │  │   BPM     │  │  Service  │     │  │
│  │  │  Router   │  │ Transform │  │  Engine   │  │  Registry │     │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘     │  │
│  │                                                                    │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐     │  │
│  │  │ Protocol │  │  Error    │  │  Audit    │  │   SLA     │     │  │
│  │  │ Mediator │  │  Handler  │  │  Logger   │  │  Manager  │     │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │  CRM     │  │   ERP    │  │  Custom  │  │  Legacy  │           │
│  │ Service │  │ Service  │  │ Service  │  │ Service  │           │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘           │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Event-Driven Architecture**: Complements SOA by adding async messaging for decoupled services
- **API Gateway**: Provides unified entry point replacing some ESB routing functions
- **Microservices Architecture**: Evolved from SOA with independent deployment focus
- **Service Mesh**: Infrastructure layer for service-to-service communication in microservices
- **Strangler Fig Pattern**: Enables incremental migration from ESB to microservices
- **Enterprise Service Bus**: Core component pattern for SOA implementations
- **Message Router**: Distributes messages based on content within ESB context
- **Canonical Protocol**: Standardizes communication format across services