# Microkernel / Plugin Architecture Pattern

## Pattern Overview

[JSON Data](./microkernel-plugin-architecture.json)

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Microkernel Architecture                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────┐          │
│  │                      Core System (Microkernel)                 │          │
│  │                                                                  │          │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │          │
│  │  │  Plugin    │  │  Lifecycle  │  │   Event    │      │          │
│  │  │  Registry  │  │  Manager    │  │   Bus      │      │          │
│  │  └─────────────┘  └─────────────┘  └─────────────┘      │          │
│  │                                                              │          │
│  │  ┌─────────────────────────────────────────────────┐      │          │
│  │  │            Extension Points (Contracts)              │          │
│  │  │  • Payment Processor Interface                     │          │
│  │  │  • Validator Interface                            │          │
│  │  │  • Processor Interface                            │          │
│  │  └─────────────────────────────────────────────────┘      │          │
│  └─────────────────────────────────────────────────────────────┘          │
│                    │                    │                    │              │
│        ┌───────────┘        ┌───────────┘        ┌───────────┘          │
│        ▼                   ▼                   ▼                          │
│  ┌───────────┐      ┌───────────┐      ┌───────────┐                  │
│  │  Plugin   │      │  Plugin   │      │  Plugin   │                  │
│  │   (A)    │      │   (B)    │      │   (C)    │                  │
│  │ Payment   │      │   Email   │      │ Shipping  │                  │
│  │ Processor │      │  Sender   │      │  Handler  │                  │
│  └───────────┘      └───────────┘      └───────────┘                  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Related Patterns

- **Strategy**: Plugin behavior treated as replaceable implementations
- **Abstract Factory**: Unified plugin creation/loading methods
- **Proxy**: Controls plugin access (auditing, caching, metrics)
- **Mediator**: Aggregates plugin communication through core
- **Facade**: Core serves as external API for plugins
- **Modular Monolith**: Microkernel can be implemented as modular monolith

## Microkernel vs Modular Monolith

| Aspect | Microkernel | Modular Monolith |
|--------|-------------|------------------|
| Core size | Minimal, focused on hosting | Larger, may include domain logic |
| Plugin importance | Plugins contain primary behavior | Modules are co-equal parts |
| Coupling | Plugins independent via contracts | Modules share data/model |
| Deployment | Plugins may be independently deployed | All as single deployment |
| Change frequency | Core stable, plugins change | Changes distributed across modules |

## Evolution Path

```
Monolith → Identify stable core → Extract as microkernel →
Add extension points → Plugins become independent deployables →
If plugin needs scaling/isolation → Extract as microservice
```

---

## Adaptive Object-Model (AOM) Components

The Adaptive Object-Model (AOM) pattern represents classes, attributes, relationships, and behavior as metadata interpreted at runtime. This is a related pattern often used alongside microkernel architectures for maximum flexibility.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                  Adaptive Object-Model Architecture                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────┐      │
│  │                    Metadata Repository                        │      │
│  │  (XML, Database, or Runtime Configuration)                     │      │
│  │                                                               │      │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐           │      │
│  │  │ EntityType │  │PropertyType│  │Relationship │           │      │
│  │  │ Definitions│  │ Definitions│  │    Types    │           │      │
│  │  └─────────────┘  └─────────────┘  └─────────────┘           │      │
│  └───────────────────────────────────────────────────────────────┘      │
│                              │                                            │
│                              ▼                                            │
│  ┌─────────────────────────────────────────────────────────────┐      │
│  │                    AOM Interpreter / Engine                    │      │
│  │                                                               │      │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐           │      │
│  │  │TypeSquare  │  │  Property   │  │  Accountability│         │      │
│  │  │ Validator  │  │  Resolver   │  │    Handler  │           │      │
│  │  └─────────────┘  └─────────────┘  └─────────────┘           │      │
│  └───────────────────────────────────────────────────────────────┘      │
│                              │                                            │
│                              ▼                                            │
│  ┌─────────────────────────────────────────────────────────────┐      │
│  │                    Runtime Object Model                       │      │
│  │                                                               │      │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │      │
│  │  │Customer │  │  Order  │  │Product  │  │CustomEntity│      │      │
│  │  │ (Entity)│  │ (Entity)│  │ (Entity)│  │ (Dynamic)  │      │      │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘        │      │
│  │       │           │           │           │                 │      │
│  │       └───────────┴───────────┴───────────┘                 │      │
│  │                      │                                       │      │
│  │                      ▼                                       │      │
│  │            ┌─────────────────┐                             │      │
│  │            │  Properties     │                             │      │
│  │            │  (Dynamic Attrs)│                             │      │
│  │            └─────────────────┘                             │      │
│  └───────────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────────┘
```

### AOM Core Concepts

| Concept | Description |
|---------|-------------|
| **Metadata Repository** | Stores entity types, property types, relationships as runtime data |
| **TypeSquare** | Architecture formed by applying TypeObject twice: once for entities/types, once for properties/property types |
| **AOM Interpreter** | Runtime engine that reads metadata and constructs runtime objects |
| **Dynamic Entities** | Entities whose structure is determined by metadata, not compiled classes |

### AOM Sub-Patterns

| Pattern | Description | Role in AOM |
|--------|-------------|-------------|
| **TypeObject** | Separates Entity from EntityType - subtypes are instances, not subclasses | Primary building block |
| **Property** | Holds entity attributes as collection of property objects, not instance variables | Enables dynamic attributes |
| **Accountability** | Models relationships between entities as first-class objects with type and cardinality | Handles associations |
| **Strategy** | Encapsulates behavior as objects that can be swapped at runtime | Enables dynamic behavior |

### TypeSquare Architecture

The TypeSquare pattern applies TypeObject twice:

```
┌─────────────────────────────────────────────────────────────────┐
│                    TypeSquare Pattern                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  First TypeObject Application:                                    │
│  ┌─────────────┐         ┌─────────────┐                         │
│  │   Entity    │─────────│ EntityType  │                         │
│  │ (Instance)  │   1:N   │  (Type)     │                         │
│  └─────────────┘         └─────────────┘                         │
│                                                                  │
│  Second TypeObject Application (for Properties):                  │
│  ┌─────────────┐         ┌─────────────┐                         │
│  │  Property  │─────────│PropertyType│                         │
│  │ (Instance)  │   1:N   │  (Type)    │                         │
│  └─────────────┘         └─────────────┘                         │
│                                                                  │
│  Entity has ──► Collection<Property> ──► PropertyType           │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │                  Complete TypeSquare                        │   │
│  │                                                            │   │
│  │  EntityType ──► EntityAttributeCollection ──► PropertyType │   │
│  │      │                          │                           │   │
│  │      │                          ▼                           │   │
│  │      │               ┌─────────────┐                       │   │
│  │      └───────────────►│   Entity   │                       │   │
│  │                      │  (Runtime)  │                       │   │
│  │                      │  has Props  │                       │   │
│  │                      └─────────────┘                       │   │
│  └───────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Property Pattern Implementation

```python
@dataclass
class Property:
    """Holds dynamic attribute as metadata."""
    name: str
    value: Any
    property_type: 'PropertyType'

@dataclass
class PropertyType:
    """Defines the type of a property (string, number, date, entity ref, etc.)."""
    name: str
    data_type: str  # 'string', 'number', 'date', 'entity', 'collection'
    target_entity_type: Optional[str] = None  # For entity references

class Entity:
    """Base class for dynamic entities."""
    entity_type: 'EntityType'
    properties: dict[str, Property]
    
    def get_property(self, name: str) -> Any:
        return self.properties.get(name).value
    
    def set_property(self, name: str, value: Any) -> None:
        prop_type = self.entity_type.get_property_type(name)
        self.properties[name] = Property(name, value, prop_type)
```

### Accountability Pattern (Relationships)

```python
@dataclass
class Accountability:
    """Represents a relationship between two entities."""
    accountability_type: 'AccountabilityType'
    source_entity: 'Entity'
    target_entity: 'Entity'
    metadata: dict[str, Any]

@dataclass
class AccountabilityType:
    """Defines the type of relationship with cardinality."""
    name: str
    source_role: str
    target_role: str
    source_min: int
    source_max: int  # -1 for unlimited
    target_min: int
    target_max: int

# Example: "Customer" is "father of" "Order"
# AccountabilityType defines: father(1:1) -> child(0:N)
```

### Attribute vs Relationship Distinction

| Aspect | Attribute | Relationship (Accountability) |
|--------|-----------|-------------------------------|
| **Value type** | Primitive (string, number, date) | Other Entity |
| **Direction** | Usually one-way | Usually two-way |
| **Cardinality** | Simple (single value or collection) | Defined by AccountabilityType |
| **Storage** | Property.value | Property.value as Entity reference |

### AOM Metadata Schema (XML example)

```xml
<EntityTypes>
  <EntityType name="Customer">
    <PropertyTypes>
      <PropertyType name="name" dataType="string" />
      <PropertyType name="email" dataType="string" />
      <PropertyType name="creditLimit" dataType="number" />
    </PropertyTypes>
    <AccountabilityTypes>
      <AccountabilityType name="placed" targetEntity="Order" sourceCardinality="1:N" />
    </AccountabilityTypes>
  </EntityType>
  
  <EntityType name="Order">
    <PropertyTypes>
      <PropertyType name="orderDate" dataType="date" />
      <PropertyType name="total" dataType="number" />
    </PropertyTypes>
    <AccountabilityTypes>
      <AccountabilityType name="placedBy" targetEntity="Customer" sourceCardinality="1:1" />
    </AccountabilityTypes>
  </EntityType>
</EntityTypes>
```

### AOM vs Reflection

| Aspect | Reflection | Adaptive Object-Model |
|--------|------------|----------------------|
| **Level** | Language-level introspection | Domain-level modeling |
| **Runtime changes** | Limited (can't add/remove methods) | Full flexibility |
| **User-facing** | Usually programmer-only | Can expose to power users |
| **Structure** | Mirrors existing class structure | Defines entirely new types |
| **Business rules** | Encoded in methods | Stored as metadata |

### AOM Implementation Frameworks

| Framework | Language | Key Features |
|-----------|----------|--------------|
| **Esfinge AOM RoleMapper** | Java | Bytecode manipulation, adapter generation |
| **DomainModelEngine** | Java | Product/process models, micro-workflow |
| **Model-Driven Architecture** | Various | OMG MOF, CWM metamodel |

### AOM Benefits

- **Runtime flexibility** - Change entity structure without redeployment
- **User-driven customization** - Power users can modify domain model
- **Dynamic business rules** - Rules stored as data, not code
- **Reduced coupling** - New entity types don't require code changes
- **Audit trail** - All metadata changes can be tracked
- **CRM/ERP alignment** - Natural fit for configurable business applications

### AOM Challenges

- **Performance overhead** - Interpretation at runtime vs direct method calls
- **Type safety loss** - Compiler can't verify dynamic structures
- **Complexity** - Metadata management adds system complexity
- **Query complexity** - Dynamic attributes difficult to index efficiently
- **Testing** - More combinations to test due to runtime flexibility

### When to Use AOM

| Use When | Avoid When |
|----------|-----------|
| Domain models change frequently | Stable domain with rare changes |
| Power users need to modify entity structure | Only developers should modify structure |
| Configurable business rules as data | Business rules require complex logic |
| Building CRM, ERP, or similar configurable systems | Simple CRUD applications |
| Runtime adaptation required without restart | Performance-critical, low-latency requirements |

### AOM Evolution Path

```
Traditional OOP                          Adaptive Object-Model
─────────────────                        ──────────────────────
class Customer {                    EntityType "Customer" {
  name: string                        PropertyType "name": string
  email: string          ====>       PropertyType "email": string
  orders: Order[]                     AccountabilityType "orders" -> Order
}                               }

Changes require code changes      Changes update metadata at runtime
```