# Broker / Object Request Broker (ORB) Pattern

## Pattern Overview

[JSON Data](./broker-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Broker Architecture                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────┐         ┌─────────────┐         ┌──────────┐            │
│  │  Client  │◄───────►│   Broker    │◄───────►│  Server  │            │
│  │  Proxy   │         │ (ORB Core)  │         │  Proxy   │            │
│  └──────────┘         └──────┬──────┘         └──────────┘            │
│                               │                                       │
│                        ┌──────┴──────┐                                │
│                        ▼             ▼                                │
│                  ┌─────────┐   ┌─────────┐                          │
│                  │ Naming  │   │ Message │                          │
│                  │ Service │   │ Router  │                          │
│                  └─────────┘   └─────────┘                          │
│                                                                  │
│  ┌───────────────┐              ┌───────────────┐             │
│  │ Stub (client) │              │ Skeleton (server) │             │
│  │ - marshall   │              │ - unmarshall     │             │
│  │ - delegates  │              │ - dispatch       │             │
│  └───────────────┘              └───────────────┘             │
└─────────────────────────────────────────────────────────────────────────┘
```

## CORBA Architecture

```
Client Application                                    Server Application
      │                                                    │
      │    ┌─────────────────┐                              │
      │    │   Client Stub   │                              │
      │    │  (generated    │                              │
      │    │   from IDL)    │                              │
      │    └────────┬────────┘                              │
      │             │                                       │
      │    ┌────────▼────────┐      ┌─────────▼──────────┐  │
      │    │      ORB        │◄────►│        ORB         │  │
      │    │   (client-side) │      │   (server-side)    │  │
      │    └────────┬────────┘      └─────────┬──────────┘  │
      │             │                         │              │
      │    ┌────────▼────────┐      ┌─────────▼──────────┐  │
      │    │  Dynamic        │      │   Server Skeleton   │  │
      │    │  Invocation     │      │   (generated from    │  │
      │    │  Interface (DII) │      │    IDL)             │  │
      │    └─────────────────┘      └─────────┬──────────┘  │
      │                                      │               │
      └──────────────────────────────────────┘               │
                    │                                             │
              Network (IIOP, SOAP, etc.)                         │
```

## Related Patterns

- **Pipe-and-Filter**: Complements broker by providing inline data transformation within the pipeline
- **Event-Driven Architecture**: Broker pattern is a foundational building block for event-driven systems
- **Message Router**: Routes messages based on content (extends broker routing capabilities)
- **Competing Consumers**: Scales slow consumer stages horizontally across multiple instances
- **Dead Letter Queue**: Handles message processing failures with separate error queue
- **Saga Pattern**: Coordinates distributed transactions across multiple services via broker
- **Competing Consumers**: Enables parallel processing of messages by multiple workers
- **Circuit Breaker**: Prevents cascading failures when broker or consumers are overwhelmed
- **Service Mesh**: Evolved pattern that moves broker functionality to sidecar proxies
- **API Gateway**: Entry point that can route to broker-backed services