# Tool Reference

All nine tools exposed by the architecture-pattern-mcp server. Parameter types are Pydantic-validated; descriptions are verbatim from the server's `inputSchema`.

---

## Group 1 — LLM Pipeline Tools

### `analyze_architecture`

Analyses requirements and domain → recommended style, top-k patterns, quality-attribute weights, and matched domain slugs. Does NOT produce a full design.

```python
analyze_architecture(
    requirements: str,      # 1–100000 chars printable text
    domain: str,            # 1–200 chars; e.g. "data-processing", "e-commerce"
) -> dict
```

**Key output fields:**
- `recommended_style`: architecture style name (e.g. `"microservices"`)
- `alternative_styles`: runner-up styles with scores
- `quality_metrics`: {scalability, maintainability, reliability, security, performance} — weights 0–1
- `matched_domains`: top BM25+FAISS retrieval results with fusion scores

Long-running (LLM call). Not idempotent.

---

### `generate_architecture`

Generates a full architecture design using the specified style and selected patterns. Requires a style — use `analyze_architecture` first to get recommendations, or pass `override_style` to `design_architecture` instead.

```python
generate_architecture(
    requirements: str,          # 1–100000 chars
    style: str,                # architecture style name, e.g. "microservices", "event-driven"
    domain: str,               # 1–200 chars
    selected_patterns: list[str] | None = None,  # pattern names, e.g. ["pipe-and-filter", "saga"]
) -> dict
```

**Note:** `selected_patterns` is optional. When omitted the server auto-selects top-k patterns based on domain retrieval. Pass explicit pattern names to force inclusion of specific patterns (e.g. `["saga"]` for distributed transaction handling).

**Key output fields:**
- `design.overview.style`: confirmed style used
- `design.components`: list of {id, name, type, description, interfaces, technology_stack}
- `design.relationships`: list of {source, target, type, description}
- `design.api_contracts`, `design.data_models`, `design.event_contracts`

Long-running (LLM call). Not idempotent.

---

### `evaluate_architecture`

Scores an existing architecture design against specified criteria and domain via pattern benchmarking. Annotated `readOnlyHint=True` (server state is unchanged) but still triggers an LLM call and is long-running.

```python
evaluate_architecture(
    architecture: dict,     # Architecture design as dictionary
    criteria: str,           # 1–100000 chars; evaluation focus, e.g. "scalability, reliability"
    domain: str,            # 1–200 chars
) -> dict
```

**Expected `architecture` dict shape:**
```python
{
  "overview": {"style": "...", "category": "...", "principles": [...], "constraints": [...]},
  "components": [{"id": "...", "name": "...", "type": "...", "description": "...",
                  "interfaces": [...], "technology_stack": [...]}],
  "relationships": [{"source": "...", "target": "...", "type": "...", "description": "..."}],
  "quality_attributes": {"maintainability": "8", "scalability": "9", ...}
}
```

**Key output fields:**
- `evaluation.summary`: overall assessment
- `evaluation.metrics`: per-attribute scores (each 1–10)
- `evaluation.recommendations`: improvement suggestions grouped by quality attribute
- `evaluation.risks`: identified risks with severity

Long-running (LLM call). Not idempotent.

---

### `design_architecture`

Full pipeline: `analyze_architecture` → `generate_architecture` → `evaluate_architecture` → up to 2 automatic retries if quality < 50. Returns both the design and its evaluation in one call.

```python
design_architecture(
    requirements: str,                          # 1–100000 chars
    domain: str,                               # 1–200 chars
    override_style: str | None = None,         # force a specific style
) -> dict
```

**Use this unless** your client has a hard 60-second timeout** (Claude Desktop, Cursor, TS-SDK agents) — in those cases use the job trio instead.

**Key output fields (from `DesignArchitectureOutput`):**
- `design`: full architecture dict (overview, components, relationships, contracts)
- `evaluation`: evaluation dict (summary, metrics, recommendations, risks)
- `attempts`: number of generate attempts made (1 = succeeded first try; >1 = retry succeeded)
- `final_style`: confirmed style name
- `quality_metrics`: analysis-stage quality attribute weights
- `final_quality_score`: 0–100 overall quality score after best attempt
- `matched_domains`: top matched domain slugs with fusion scores

**Retry logic:** if `final_quality_score < 50` after generation, the pipeline retries (up to 2 times). `attempts > 1` indicates a retry was needed — inspect `evaluation.recommendations` to understand what changed.

Long-running (5–10 min; 3–9 LLM round trips). Not idempotent.

---

## Group 2 — Async Job Trio

For clients with hard 60-second request timeouts (Claude Desktop, Cursor, TS-SDK agents). Returns `job_id` immediately; poll `get_architecture_design_status` every 10–30 seconds.

### `submit_architecture_design_job`

```python
submit_architecture_design_job(
    requirements: str,              # 1–100000 chars
    domain: str,                   # 1–200 chars
    override_style: str | None = None,
) -> dict
```

Returns immediately:
```python
{
    "job_id": "<uuid>",
    "status": "pending",
    "message": "Job <uuid> created. Poll get_architecture_design_status('<uuid>') until status is 'completed', 'failed', or 'cancelled'."
}
```

Store the `job_id` — there is no `tasks/list` equivalent; the client owns the handle.

---

### `get_architecture_design_status`

```python
get_architecture_design_status(
    job_id: str,   # returned by submit_architecture_design_job
) -> dict
```

**Status values (`JobStatus` enum):**

| Status | Meaning |
|--------|---------|
| `pending` | Job queued, pipeline not yet started |
| `running` | Pipeline active; wait and poll again |
| `completed` | Done — full design is in `result` field |
| `failed` | Pipeline error — `error` field contains message |
| `cancelled` | Cancelled by `cancel_architecture_design` |

**Polling loop:**
```python
while True:
    result = get_architecture_design_status(job_id)
    if result["status"] == "completed":
        design = result["result"]["design"]
        evaluation = result["result"]["evaluation"]
        break
    elif result["status"] in ("failed", "cancelled"):
        handle_error(result)
        break
    sleep(15)  # poll every 10–30 s
```

Returns `{job_id, status, message, created_at, updated_at}` plus `result` when completed or `error` when failed.

---

### `cancel_architecture_design`

Best-effort cancellation. Takes effect at the next pipeline stage boundary (may take up to one LLM call).

```python
cancel_architecture_design(
    job_id: str,   # returned by submit_architecture_design_job
) -> dict
```

Returns `{cancelled: bool, status: <current status>}`.
Cannot cancel jobs that are already `completed`, `failed`, or `cancelled`.

---

## Group 3 — Read-Only Pattern Catalog

Fast, idempotent. Safe for exploration before committing to an expensive pipeline call.

### `list_architecture_patterns`

Returns a **minimal view** (name + one-line description) of all patterns, optionally filtered.

```python
list_architecture_patterns(
    category: str | None = None,   # messaging, structural, cloud, data, ai_cognitive,
                                   # specialized, api_gateway, coordination, dataflow, presentation
    domain: str | None = None,    # matches against pattern.suitable_domains
) -> list[dict[str, str]]
```

**For full pattern JSON** use `get_architecture_pattern(name=...)` — do not try to parse the minimal list entries.

Valid `category` values: `messaging`, `structural`, `cloud`, `data`, `ai_cognitive`, `specialized`, `api_gateway`, `coordination`, `dataflow`, `presentation`.

---

### `get_architecture_pattern`

Returns the **full JSON** for one pattern by exact name.

```python
get_architecture_pattern(
    name: str,   # e.g. "microservices", "pipe-and-filter", "event-driven"
) -> dict
```

**Pattern JSON shape:**
```python
{
    "category": "...",
    "name": "...",
    "context": "when this pattern applies",
    "benefits": ["...", "..."],
    "tradeoffs": ["...", "..."],
    "quality_attributes": {
        "scalability": 8, "maintainability": 7, "reliability": 8,
        "security": 6, "performance": 7, "simplicity": 5
    },
    "suitable_domains": ["data-processing", "e-commerce", ...],
    "component_types": ["...", "..."],
    "technology_stack": ["...", "..."],
    "design_principles": ["...", "..."],
    "best_practices": ["...", "..."]
}
```

Raises `ToolError` if the pattern name is not found. Use `list_architecture_patterns` first to discover exact names.

---

## MCP Resources

| URI | What it returns |
|-----|-----------------|
| `pattern://{name}` | Full pattern JSON (same as `get_architecture_pattern`) |
| `template://{name}` | Architecture template by name |
| `component://{type}` | Component blueprint (e.g. `component://message-queue`) |

Access via `mcp_read_resource(server="architecture-pattern", uri="pattern://microservices")`.

---

## Tool Annotations Reference

| Tool | readOnlyHint | destructiveHint | idempotentHint |
|------|-------------|----------------|-----------------|
| `analyze_architecture` | — | — | No |
| `generate_architecture` | — | — | No |
| `evaluate_architecture` | **True** | False | No |
| `design_architecture` | — | — | No |
| `submit_architecture_design_job` | — | — | N/A |
| `get_architecture_design_status` | True | False | **True** |
| `cancel_architecture_design` | False | **True** | No |
| `list_architecture_patterns` | True | False | **True** |
| `get_architecture_pattern` | True | False | **True** |

`readOnlyHint=True` on `evaluate_architecture` means the server's own state is unchanged (it benchmarks, not writes). It still invokes the LLM and is long-running.
