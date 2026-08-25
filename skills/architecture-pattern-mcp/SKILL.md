---
name: architecture-pattern-mcp
description: >
  Designs software system architectures via the architecture-pattern MCP server: analyses
  requirements, selects from 40 patterns (microservices, event-driven, hexagonal,
  pipe-and-filter, layered-monolith and 35 more), generates full designs with components,
  relationships, API contracts, data models, and event contracts, and evaluates quality
  across scalability, maintainability, reliability, security, and performance. Use when
  designing a new system, comparing architecture styles, evaluating an existing design,
  or exploring the pattern catalog. Triggers on requests to design the architecture
  for X, compare microservices vs event-driven, evaluate this architecture, choose an
  architecture pattern for X, or any system design or software architecture task. Do
  NOT use for implementing individual features, DevOps or IaC configuration, code-level
  refactoring, or single-component class design. Requires the architecture-pattern
  MCP server connected.
---

## Critical Rules

### Client timeout matrix — pick the right entry point

| Client | Timeout | Use this |
|--------|---------|----------|
| Claude Code, OpenCode, Codex CLI | ~300 s (heartbeat-reset) | `design_architecture` directly |
| Claude Desktop, Cursor, TS-SDK agents | 60 s (hardcoded) | Job trio: `submit_architecture_design_job` → poll `get_architecture_design_status` every 10–30 s |
| MCP clients with custom timeouts | varies | If timeout < 5 min, prefer job trio |

The `TASKS_HEARTBEAT_INTERVAL_SECONDS` env var (default 30 s) controls the heartbeat interval. Increase it toward 60 s for clients with tight idle limits.

### Structured arguments — domain and style are separate parameters

- `requirements`: free-text description of what the system must do
- `domain`: problem-space tag (e.g. `data-processing`, `e-commerce`, `microservices`) — filters which patterns apply; pass as a separate argument, **never** embed in `requirements`
- `override_style` / `style`: architecture style name (e.g. `microservices`, `event-driven`, `hexagonal`) — **always** pass as its own argument; `override_style` takes precedence over the server-derived style

### Domain ≠ Style vocabulary

- **Domain** (~376 slugs): problem-space classification — answers "which patterns are relevant?" Retrieved via BM25 + dense embedding + cross-encoder rerank
- **Style** (~40 names): architecture decision — answers "which architecture was chosen?" Scored by requirements-weighted ranking; `layered-monolith` is the fallback when retrieval score < threshold

---

## Overview

The architecture-pattern-mcp server provides a full architecture design pipeline:

1. **Analyse** requirements + domain → recommended style + top-k matching patterns with quality-attribute scores
2. **Generate** a concrete architecture: components, relationships, API contracts, data models, event contracts
3. **Evaluate** the design against quality attributes (scalability, maintainability, reliability, security, performance)
4. **Refine** — up to 2 automatic retries if quality score < 50

The server ships 40 built-in patterns (microservices, event-driven, hexagonal, pipe-and-filter, layered-monolith, space-based, saga, CQRS, and 32 more). Custom patterns can be added via JSON files in the pattern directory.

---

## When to Use This Skill

**Use when the user asks to:**
- Design the architecture for a new system
- Compare architecture styles (e.g. microservices vs event-driven)
- Evaluate an existing architecture design
- Explore the pattern catalog to find the right pattern
- Choose an architecture pattern for a given domain

**Do NOT use for:**
- Implementing individual features or writing code
- DevOps, IaC, or infrastructure configuration
- Refactoring a single class or function
- Choosing a design pattern for one component

**Tune heartbeat intervals** if borderline on timeout: set `TASKS_HEARTBEAT_INTERVAL_SECONDS=45` (below client idle limit).

---

## Entry-Point Decision Guide

```
Does the user have an existing architecture design?
├── YES → evaluate_architecture(architecture, criteria, domain)
└── NO
    ├── Want to explore patterns first?
    │   ├── list_architecture_patterns(category?, domain?)   ← fast, idempotent
    │   └── get_architecture_pattern(name)                  ← full JSON
    │
    ├── Want a full design + evaluation?
    │   ├── Claude Code / OpenCode / Codex CLI
    │   │   → design_architecture(requirements, domain, override_style?)
    │   └── Claude Desktop / Cursor / TS-SDK
    │       → submit_architecture_design_job → poll get_architecture_design_status
    │
    └── Want to generate with specific style + patterns?
        → generate_architecture(requirements, style, domain, selected_patterns?)
```

---

## Tools Quick Reference

| Tool | Purpose | Latency | Idempotent | See |
|------|---------|---------|------------|-----|
| `analyze_architecture` | Derive style + pattern recommendations from requirements | Long (LLM) | No | references/tools.md |
| `generate_architecture` | Produce design with specified style + patterns | Long (LLM) | No | references/tools.md |
| `evaluate_architecture` | Score existing design against quality criteria | Long (LLM) | No | references/tools.md |
| `design_architecture` | Full pipeline: analyse → generate → evaluate → refine | 5–10 min | No | references/tools.md |
| `submit_architecture_design_job` | Start long job; returns job_id immediately | Fast return | N/A | references/tools.md |
| `get_architecture_design_status` | Poll job status; result when `completed` | Fast | Yes | references/tools.md |
| `cancel_architecture_design` | Best-effort cancel at next stage boundary | Fast | No | references/tools.md |
| `list_architecture_patterns` | List all / filtered patterns (minimal view) | Fast | Yes | references/tools.md |
| `get_architecture_pattern` | Full pattern JSON by name | Fast | Yes | references/tools.md |

---

## Resources & Prompts at a Glance

### MCP Resources
```
pattern://{name}     # Full pattern JSON (e.g. pattern://event-driven)
template://{name}    # Architecture template
component://{type}   # Component blueprint (e.g. component://message-queue)
```

### Slash-Command Prompts (4 total)
| Prompt | Args | What it does |
|--------|------|--------------|
| `/design_architecture_workflow` | `requirements*`, `domain="general"`, `style` | Full analyse → generate → evaluate → refine pipeline |
| `/explore_pattern_catalog` | `domain`, `category` | Live catalog discovery; embeds pattern names dynamically |
| `/evaluate_my_architecture` | `focus` | Guide user through evaluate_architecture; prioritises score < 70 |
| `/compare_architecture_styles` | `style_a*`, `style_b*`, `requirements*` | Two designs side-by-side; ~2× token cost |

Tool-only clients (no native prompts protocol): use `list_prompts` and `get_prompt` instead.

For full detail see `references/tools.md` and `references/workflows.md`.
