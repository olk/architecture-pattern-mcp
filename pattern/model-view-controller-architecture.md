# Model-View-Controller (MVC) Architecture Pattern

## Pattern Overview

[JSON Data](./model-view-controller-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      MVC Architecture                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                           User                                   │    │
│  └─────────────────────────────┬───────────────────────────────────┘    │
│                                │                                        │
│                                ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                          View                                    │    │
│  │  (Presentation layer - UI rendering, user input capture)        │    │
│  │                                                                   │    │
│  │  • Renders data from Model                                       │    │
│  │  • Sends user actions to Controller                              │    │
│  │  • No business logic                                             │    │
│  │  • Multiple views for same Model possible                        │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                │                                        │
│                    user actions │ updates                               │
│                                ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                        Controller                               │    │
│  │  (Input handling - routes commands, coordinates Model/View)      │    │
│  │                                                                   │    │
│  │  • Receives user input                                           │    │
│  │  • Processes requests                                            │    │
│  │  • Manipulates Model                                              │    │
│  │  • Selects View for response                                     │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                │                                        │
│                    business logic │ data access                         │
│                                ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                          Model                                   │    │
│  │  (Business logic - data, rules, state management)                │    │
│  │                                                                   │    │
│  │  • Data and state                                               │    │
│  │  • Business rules and logic                                     │    │
│  │  • Notifies View of changes (in classic MVC)                    │    │
│  │  • Independent of UI                                            │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **MVVM (Model-View-ViewModel)**: Extends MVC with bindable ViewModel for rich client applications
- **MVP (Model-View-Presenter)**: Presenter mediates between View and Model with passive View
- **Clean Architecture**: Layered architecture emphasizing use cases and entities
- **Event-Driven Architecture**: Decouples producers from consumers via message passing
- **Repository Pattern**: Abstracts data access behind repository interfaces
- **Service Layer Pattern**: Introduces service classes for business logic orchestration