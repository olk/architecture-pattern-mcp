# Service Mesh Architecture

## Pattern Overview

[JSON Data](./service-mesh-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Service Mesh Architecture                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                       Data Plane (Sidecar Proxies)                  │  │
│  │                                                                    │  │
│  │  ┌─────────┐       ┌─────────┐       ┌─────────┐                  │  │
│  │  │Service A│───────│  Sidecar │───────│Service B│                  │  │
│  │  │  Pod    │       │  Proxy   │       │  Pod    │                  │  │
│  │  └─────────┘       └────┬────┘       └─────────┘                  │  │
│  │                        │                                        │  │
│  │                   ┌────┴────┐                                   │  │
│  │                   │  iptables│ (transparent)                     │  │
│  │                   └─────────┘                                   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                       Control Plane                               │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐     │  │
│  │  │  Service  │  │   mTLS    │  │ Circuit   │  │   Load    │     │  │
│  │  │ Discovery │  │  Manager  │  │ Breaker   │  │ Balancing │     │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘     │  │
│  │                                                                    │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐     │  │
│  │  │ Observab.│  │   Rate    │  │   Auth    │  │   Retry   │     │  │
│  │  │(Metrics,  │  │ Limiting  │  │  Policy   │  │  Policy   │     │  │
│  │  │ Tracing)  │  │           │  │           │  │           │     │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └───────────┘     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Ambient Mesh**: Sidecar-less architecture that reduces compute consumption and simplifies networking while maintaining mesh benefits.
- **Service Mesh Lite**: Lightweight mesh implementation with reduced resource overhead for smaller deployments.
- **Gateway API Native**: Using the standard Gateway API for ingress and traffic management instead of mesh-specific APIs.
- **Sidecar Proxy**: Per-pod proxy pattern for intercepting and managing network traffic.
- **Zero-Trust Security**: Security model requiring verification of every request regardless of origin.
- **Canary Deployment**: Progressive traffic shifting pattern for safe rollout of new service versions.
- **Circuit Breaker**: Resilience pattern preventing cascade failures by detecting and isolating unhealthy services.