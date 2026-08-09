# Pipe-and-Filter Architecture Pattern

## Pattern Overview

[JSON Data](./pipe-and-filter-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Pipe-and-Filter Architecture                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                         Data Flow                             │  │
│  │                                                               │  │
│  │  ┌─────┐     ┌─────┐     ┌─────┐     ┌─────┐     ┌─────┐      │  │
│  │  │ Pipe│────►│ Pipe│────►│ Pipe│────►│ Pipe│────►│ Pipe│      │  │
│  │  │  1  │     │  2  │     │  3  │     │  4  │     │  5  │      │  │
│  │  └──┬──┘     └──┬──┘     └──┬──┘     └──┬──┘     └──┬──┘      │  │
│  │     │           │           │           │           │         │  │
│  │     ▼           ▼           ▼           ▼           ▼         │  │
│  │  ┌────────┐ ┌────────┐ ┌───────────┐ ┌────────┐ ┌────────┐    │  │
│  │  │Filter A│ │Filter B│ │  Filter C │ │Filter D│ │Filter E│    │  │
│  │  │ (Parse)│ │(Valid) │ │(Transform)│ │(Enrich)│ │(Output)│    │  │
│  │  └────────┘ └────────┘ └───────────┘ └────────┘ └────────┘    │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Filter Types

| Type | Description | Examples |
|------|-------------|----------|
| **Producer (Source)** | Generates data | FileReader, API client, EventEmitter |
| **Transformer** | Modifies data format | Parser, translator, serializer |
| **Validator** | Checks data quality | Schema validator, bounds checker |
| **Enricher** | Adds context to data | GeoIP lookup, user enrichment |
| **Router** | Routes data based on rules | Content-based routing, conditional split |
| **Consumer (Sink)** | Outputs data | FileWriter, Database writer, API responder |

## Core Components

| Component | Description |
|-----------|-------------|
| **Pipe** | Conduit passing data between filters (queue, channel, stream) |
| **Filter** | Processing unit with single responsibility |
| **Data Source** | Input origin (file, stream, API, event) |
| **Data Sink** | Output destination (file, database, API) |
| **Pipeline** | Composed sequence of filters |
| **Message Broker** | Optional intermediate buffer for distributed部署 |

## Related Patterns

- **Event-Driven Consumer**: Decouples producers from consumers
- **Message Router**: Routes data based on content (extends basic routing)
- **Competing Consumers**: Scales slow filter stages horizontally
- **Compensating Transaction**: Handles failures with rollback
- **Content Filter**: Removes unwanted data from messages
