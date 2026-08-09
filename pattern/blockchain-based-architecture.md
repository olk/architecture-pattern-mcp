# Blockchain-Based Architecture Pattern

## Pattern Overview

[JSON Data](./blockchain-based-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Blockchain-Based Architecture                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      Blockchain Network                          │  │
│  │                                                                    │  │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐           │  │
│  │  │  Node   │  │  Node   │  │  Node   │  │  Node   │           │  │
│  │  │    A    │──│    B    │──│    C    │──│    D    │           │  │
│  │  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘           │  │
│  │       │           │           │           │                      │  │
│  │       └───────────┴───────────┴───────────┘                      │  │
│  │                         │                                        │  │
│  │                    ┌────┴────┐                                   │  │
│  │                    │ Consensus│                                  │  │
│  │                    │  Layer   │                                   │  │
│  │                    └─────────┘                                   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    Block Structure                               │  │
│  │                                                                    │  │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐           │  │
│  │  │Block N  │  │BlockN+1 │  │BlockN+2 │  │BlockN+3 │           │  │
│  │  │Header   │──│Header   │──│Header   │──│Header   │           │  │
│  │  │• Prev   │  │• Prev   │  │• Prev   │  │• Prev   │           │  │
│  │  │• Hash   │  │• Hash   │  │• Hash   │  │• Hash   │           │  │
│  │  │• Merkle │  │• Merkle │  │• Merkle │  │• Merkle │           │  │
│  │  │• Tx Root│  │• Tx Root│  │• Tx Root│  │• Tx Root│           │  │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘           │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Event-Driven Architecture**: Blockchain events trigger downstream consumers; smart contracts emit events that flow into message buses
- **Service Mesh**: Provides interoperability between different blockchain networks; Hyperledger Cacti enables cross-chain communication
- **Distributed Ledger Pattern**: Central to blockchain; variations include permissioned (Fabric, Corda) and public (Ethereum, Solana)
- **Decentralized Identity**: Self-sovereign identity management on blockchain for verifiable credentials
- **Oracle Pattern**: Bridges blockchain with external data sources; Chainlink and Band Protocol provide decentralized oracle services
- **Sidecar Pattern**: Off-chain data layer acts as sidecar to blockchain for compliance, reporting, and complex queries
- **Gateway Pattern**: API gateway for low-risk integration with legacy systems; provides request/response interface to blockchain