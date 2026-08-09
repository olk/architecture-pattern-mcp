# Actor-Based Architecture Pattern

## Pattern Overview

[JSON Data](./actor-based-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       Actor-Based Architecture                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                         Actor System                                │  │
│  │                                                                    │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │  │
│  │  │   Mailbox   │  │   Mailbox   │  │   Mailbox   │               │  │
│  │  │  ┌───────┐  │  │  ┌───────┐  │  │  ┌───────┐  │               │  │
│  │  │  │Actor │  │  │  │ │Actor │  │  │  │ │Actor │  │               │  │
│  │  │  │  A   │◄─┤  │  │ │  B   │◄─┤  │  │ │  C   │◄─┤               │  │
│  │  │  └───────┘  │  │  └───────┘  │  │  └───────┘  │               │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘               │  │
│  │        │               │               │                           │  │
│  │        └───────────────┼───────────────┘                           │  │
│  │                        ▼                                           │  │
│  │                  ┌─────────────┐                                   │  │
│  │                  │ Dispatcher  │                                     │  │
│  │                  │  (Scheduler) │                                    │  │
│  │                  └─────────────┘                                   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Actor Hierarchy                                 │  │
│  │                                                                    │  │
│  │                       ┌───────────┐                                │  │
│  │                       │   Root    │                                │  │
│  │                       │  Actor    │                                │  │
│  │                       └─────┬─────┘                                │  │
│  │                    ┌────────┼────────┐                             │  │
│  │                    ▼       ▼       ▼                              │  │
│  │               ┌────────┐┌────────┐┌────────┐                       │  │
│  │               │ Order  ││ User   ││Payment │                       │  │
│  │               │ Actor  ││ Actor  ││ Actor  │                       │  │
│  │               └───┬────┘└───┬────┘└───┬────┘                       │  │
│  │                   │        │        │                             │  │
│  │               ┌───┴───┐┌───┴───┐┌───┴───┐                        │  │
│  │               │ Child ││ Child ││ Child │                        │  │
│  │               │Actors ││Actors ││Actors │                        │  │
│  │               └───────┘└───────┘└───────┘                       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Event-Driven Architecture**: Actors naturally emit events; integrates with event sourcing
- **Supervision Tree**: Hierarchical fault recovery pattern fundamental to actor systems
- **Message Router**: Routes messages based on content (extends actor routing)
- **Competing Consumers**: Scales slow actor stages horizontally
- **Event Sourcing**: Persists state as sequence of events; natural fit for actors
- **CQRS**: Separates read/write concerns; actor-based command handlers
- **Let it Crash**: Philosophy embraced by actor supervision; failure is normal
- **Error Kernel Pattern**: Places dangerous operations deep in supervision hierarchy