# Presentation-Abstraction-Control (PAC)

## Pattern Overview

[JSON Data](./presentation-abstraction-control-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      PAC Architecture                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                     Top-Level Agent                                │  │
│  │  ┌─────────────────────────────────────────────────────────────┐  │  │
│  │  │   Control (Application coordination, menus, global state)   │  │  │
│  │  └─────────────────────────────────────────────────────────────┘  │  │
│  │           │                           │                          │  │
│  │           ▼                           ▼                          │  │
│  │  ┌──────────────────┐       ┌──────────────────┐                │  │
│  │  │   Abstraction    │       │   Presentation   │                │  │
│  │  │ (Business logic) │       │   (UI rendering) │                │  │
│  │  └──────────────────┘       └──────────────────┘                │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                           │
│           ┌──────────────────┼──────────────────┐                       │
│           ▼                  ▼                  ▼                       │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐           │
│  │  Mid-Level      │ │  Mid-Level      │ │  Mid-Level      │           │
│  │  Agent          │ │  Agent          │ │  Agent          │           │
│  │  ┌────┬────┬──┐ │ │  ┌────┬────┬──┐ │ │  ┌────┬────┬──┐ │           │
│  │  │ P  │ A  │ C │ │ │  │ P  │ A  │ C │ │ │  │ P  │ A  │ C │ │           │
│  │  └────┴────┴──┘ │ │  └────┴────┴──┘ │ │  └────┴────┴──┘ │           │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘           │
│                              │                                           │
│           ┌──────────────────┼──────────────────┐                       │
│           ▼                  ▼                  ▼                       │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐           │
│  │  Leaf Agent     │ │  Leaf Agent     │ │  Leaf Agent     │           │
│  │  (Button,       │ │  (Text Field,   │ │  (List,         │           │
│  │   Checkbox)    │ │   Slider)       │ │   Table)        │           │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Hierarchical MVC (HMVC)**: Similar hierarchical structure but allows direct Model-View communication unlike PAC's strict Control mediation
- **PAC-Amodeus**: Multi-user collaborative systems extension of PAC
- **PAC\***: Complex CSCW applications requiring replication support; combines PAC with Dewan's zipper model and Clover model
- **Microservices**: When agent boundaries align with service boundaries, PAC hierarchy can map to microservice decomposition
- **Actor Model**: Distributed systems with independent message processing; replaces hierarchical routing with direct actor communication
- **Model-View-Controller (MVC)**: Flat structure predecessor; PAC extends MVC with hierarchical agent organization
- **Component-Based Architecture**: PAC agents can be implemented as self-contained components with explicit dependencies