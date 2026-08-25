# Workflow Examples

Four tested orchestration recipes for the architecture-pattern-mcp server's tools and prompts.

---

## Workflow 1 — Full Design via `design_architecture`

For clients with heartbeat coverage (Claude Code, OpenCode, Codex CLI). Runs the complete analyse → generate → evaluate → refine pipeline in one blocking call.

```
Call design_architecture with:
  requirements: "ETL pipeline for IoT: ingest 10k events/sec from Kafka,
    parse JSON, enrich with geolocation from Redis, write to InfluxDB and S3"
  domain: "data-processing"
```

**What happens:**
1. Server runs `analyze_architecture` — derives recommended style + top-k patterns
2. Server runs `generate_architecture` with recommended style
3. Server runs `evaluate_architecture` against quality criteria
4. If `final_quality_score < 50`, retry generate (up to 2 times)
5. Returns `{design, evaluation, attempts, final_style, quality_metrics, final_quality_score, matched_domains}`

**Interpreting `attempts > 1`:** the pipeline retried generation automatically. Inspect `evaluation.recommendations` to see what the retried design changed.

**Expected runtime:** 5–10 minutes. Claude Code / OpenCode / Codex CLI handle this via heartbeat notifications every 30 s.

---

## Workflow 2 — Async Job Trio (for timeout-constrained clients)

For clients with hard 60-second timeouts (Claude Desktop, Cursor, TS-SDK agents). Three steps: submit → poll → handle result.

### Step 1 — Submit the job

```
Call submit_architecture_design_job with:
  requirements: "ETL pipeline for IoT: Kafka → JSON parse → Redis geo-enrich → InfluxDB + S3"
  domain: "data-processing"
```

Returns `{job_id: "<uuid>", status: "pending", message: "..."}` immediately.

### Step 2 — Poll until terminal status

```
Call get_architecture_design_status with:
  job_id: "<uuid from step 1>"
```

Poll every 10–30 seconds. Branch on `status`:

| Status received | Action |
|----------------|--------|
| `pending` or `running` | Wait, poll again |
| `completed` | Extract `result.design` and `result.evaluation` |
| `failed` | Read `error` field for error details |
| `cancelled` | Inform user; offer to resubmit |

### Step 3 — Cancel if needed

```
Call cancel_architecture_design with:
  job_id: "<uuid>"
```

Cancellation is best-effort: takes effect at the next pipeline stage boundary.

---

## Workflow 3 — Explore Catalog Then Generate with Specific Patterns

Use the read-only catalog tools to explore, then call `generate_architecture` with explicit pattern selection.

### Explore patterns

```
Call list_architecture_patterns with:
  category: "messaging"
```

```
Call list_architecture_patterns with:
  domain: "e-commerce"
```

### Get full detail on a candidate

```
Call get_architecture_pattern with:
  name: "saga"
```

### Generate with explicit pattern selection

```
Call generate_architecture with:
  requirements: "E-commerce checkout: handle distributed transactions across
    order, payment, and inventory services with saga orchestration"
  style: "microservices"
  domain: "e-commerce"
  selected_patterns: ["saga", "api-gateway", "event-sourcing"]
```

**Why use `generate_architecture` instead of `design_architecture`?** When you already know which style and patterns you want and do not need the full analyse → evaluate pipeline.

---

## Workflow 4 — Evaluate an Existing Architecture Design

When the user already has an architecture and wants quality-attribute scores.

```
Call evaluate_architecture with:
  architecture: {
    "overview": {
      "style": "microservices",
      "category": "distributed",
      "principles": ["single-responsibility", "autonomous-services"],
      "constraints": ["max-100ms-latency", "PCI-DSS-compliance"]
    },
    "components": [
      {"id": "c1", "name": "OrderService", "type": "microservice",
       "description": "Manages order lifecycle", "interfaces": ["REST"], "technology_stack": ["Node.js", "PostgreSQL"]},
      {"id": "c2", "name": "PaymentService", "type": "microservice",
       "description": "Processes payments", "interfaces": ["REST"], "technology_stack": ["Python", "PostgreSQL"]}
    ],
    "relationships": [
      {"source": "c1", "target": "c2", "type": "sync-http", "description": "Payment authorisation call"}
    ],
    "quality_attributes": {"maintainability": "7", "scalability": "8", "reliability": "8", "security": "9", "performance": "7"}
  }
  criteria: "scalability, reliability, security"
  domain: "e-commerce"
```

**Focus on critical findings** (any attribute score < 70) first. Group recommendations by quality attribute.

---

## MCP Prompts (Slash Commands)

Four user-invoked workflow templates. The LLM does not auto-invoke these — the user selects one explicitly.

### `/design_architecture_workflow`

```
/design_architecture_workflow requirements="..." domain="data-processing" style="microservices"
```

Guides the user through: (1) call `design_architecture`, (2) review quality scores, (3) list tradeoffs, (4) if any score < 75, propose refinements via `evaluate_architecture`.

**Prompt argument → tool argument mapping:**
- `style` maps to `override_style` in `design_architecture`

---

### `/explore_pattern_catalog`

```
/explore_pattern_catalog domain="microservices" category="messaging"
```

Dynamically embeds the live pattern catalog (all 40 pattern names) into the prompt body at registration time — so the prompt always reflects the current catalog. Guides the user through: (1) `list_architecture_patterns` with optional filters, (2) `get_architecture_pattern` for the chosen name, (3) `mcp_read_resource(uri='pattern://...')` for full JSON detail.

---

### `/evaluate_my_architecture`

```
/evaluate_my_architecture focus="security"
```

Guides: (1) help user structure their design as a dict, (2) call `evaluate_architecture`, (3) flag critical findings (score < 70), (4) group recommendations by attribute. Extra attention to `security` if `focus` is specified.

---

### `/compare_architecture_styles`

```
/compare_architecture_styles style_a="microservices" style_b="event-driven" requirements="E-commerce platform handling flash sales"
```

Generates two designs side-by-side and compares tradeoffs. **Cost note:** triggers two `generate_architecture` calls — approximately 2× token cost and latency. If both scores are within 5 points, note that either style works.

---

### Tool-Only Clients: `list_prompts` / `get_prompt`

Clients without native `prompts/list` support (e.g. Cursor) can access all four prompts via the generated tools:
```
list_prompts()                           # list available prompts
get_prompt(name="design_architecture_workflow", arguments={...})  # invoke one
```

---

## Interpreting Results

### `final_quality_score`

0–100 scale. Scores ≥ 75 are strong; 50–74 indicate notable tradeoffs; < 50 triggers automatic retry (up to 2 times). After retries, the best attempt is returned regardless of score.

### `attempts`

| Value | Meaning |
|-------|---------|
| `1` | Succeeded first try |
| `2` | First generation was retry-eligible; retry succeeded |
| `3` | Two retries were needed |

`attempts > 1` is not a failure — it means the pipeline self-healed. Inspect `evaluation.recommendations` for what changed.

### `evaluation.recommendations`

Improvement suggestions grouped by quality attribute. Process: (1) address critical findings (score < 70) first, (2) then address recommendations for attributes below target threshold.

### `matched_domains`

Top domain slugs from BM25 + dense retrieval with fusion scores. If the top score is low, the server falls back to `layered-monolith` — this is expected behaviour, not an error.

### `layered-monolith` fallback

When retrieval score < `style_score_threshold` (default 50), the server uses `layered-monolith` as the style. If your requirements clearly call for a different style, pass `override_style` explicitly.

---

## Best Practices

1. **Pass `domain` and `style` as separate structured arguments** — never embed them in the `requirements` text. The server uses domain for pattern retrieval; embedding it loses that signal.

2. **Pick your entry point by client type** — `design_architecture` for heartbeat clients; job trio for 60 s timeout clients. Do not use `design_architecture` with Claude Desktop or Cursor.

3. **Explore the catalog first** when requirements are vague — use `list_architecture_patterns` with domain/category filters to discover candidate patterns before committing to a full design.

4. **Expect `layered-monolith` as fallback** when domain is ambiguous. Pass explicit `override_style` if you know the desired style.

5. **Tune heartbeat interval for borderline clients** — set `TASKS_HEARTBEAT_INTERVAL_SECONDS=45` (keep below the client's idle timeout). This avoids the job trio migration for clients that could otherwise use `design_architecture`.

6. **Use `generate_architecture` with explicit patterns** when you know the style and patterns upfront — skips the analyse phase, saving one LLM round trip.

7. **For full design prefer `design_architecture`** over chaining `analyze_architecture` + `generate_architecture` + `evaluate_architecture` yourself — the pipeline handles retries and refinement automatically.

8. **Cancel via `cancel_architecture_design`** rather than abandoning a timed-out request — the server-side task checks the cancellation flag at stage boundaries, freeing resources.
