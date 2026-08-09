# Lambda Architecture

## Pattern Overview

[JSON Data](./lambda-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Lambda Architecture                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│                           Incoming Data                                   │
│                    (Events, Logs, User Actions)                           │
│                              │                                           │
│                    ┌─────────┴─────────┐                                 │
│                    ▼                   ▼                                  │
│           ┌──────────────┐     ┌──────────────┐                         │
│           │  Batch Layer  │     │  Speed Layer  │                         │
│           │              │     │  (Stream)     │                         │
│           │  • HDFS/S3   │     │  • Kafka      │                         │
│           │  • Spark/Hive│     │  • Flink/     │                         │
│           │  • Full      │     │    Spark      │                         │
│           │    recompute │     │  Streaming    │                         │
│           └──────┬───────┘     └──────┬───────┘                         │
│                  │                     │                                 │
│                  ▼                     ▼                                  │
│           ┌──────────────┐     ┌──────────────┐                         │
│           │  Batch Views  │     │  Real-time   │                         │
│           │  (Accurate,   │     │  Views       │                         │
│           │   complete)   │     │  (Approx,    │                         │
│           │               │     │   latest)    │                         │
│           └──────┬───────┘     └──────┬───────┘                         │
│                  │                     │                                 │
│                  └──────────┬──────────┘                                 │
│                             ▼                                            │
│                    ┌──────────────┐                                      │
│                    │   Serving    │                                      │
│                    │    Layer      │                                      │
│                    │  (Merge +    │                                      │
│                    │   Query)     │                                      │
│                    └──────────────┘                                      │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Kappa Architecture**: Eliminates batch layer entirely; uses stream replay for historical recomputation when batch and stream logic are identical
- **Medallion Architecture**: Lakehouse pattern with bronze/silver/gold tiers; provides incremental data quality progression
- **Event-Driven Microservices**: For more granular service decomposition beyond batch/speed separation
- **Pipe-and-Filter**: Composable data transformation for individual processing stages within layers
- **Competing Consumers**: Scales slow processing stages horizontally across replicas
- **Compensating Transaction**: Handles failures with rollback in distributed processing
- **Content Filter**: Removes unwanted data from messages at filter stage

(End of file - total 507 lines)