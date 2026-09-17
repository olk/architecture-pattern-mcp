# Tool reference — architecture-pattern MCP server

OMP-native reference for the `architecture-pattern` server. The deadline policy that decides which entry point to use and the domain/style vocabulary live in `SKILL.md`; this file carries the per-tool parameter and output detail. Everything below was read off the running server (11 tools, server version 4.0.2) and the server source.

## How to call a tool

```text
write  xd://mcp__architecture_pattern_<tool>     JSON args object → result
read   xd://mcp__architecture_pattern_<tool>     device doc + live input schema
```

- Device names come from the server name lowercased with `-` → `_`; `architecture-pattern` owns `mcp__architecture_pattern_*`.
- Args and results are JSON. On a schema mismatch the error echoes the schema — fix the JSON and retry the same device.
- Do not send FastMCP's injected `_ctx` parameter (it appears in `list_architecture_patterns` / `get_architecture_pattern` schemas but is server-side).
- Every call is bounded by OMP's MCP deadline (`OMP_MCP_TIMEOUT_MS` → per-server `timeout` → 30 s). Measured on this host with the default deadline: the job trio and catalog calls return in ≤ 31 ms, while the LLM tools run 66–197 s and abort:

```text
MCP failure
server: architecture-pattern
tool: analyze_architecture
transport: http
stage: receive
failure: timeout
retryable: no
message: Request timeout after 30000ms
next: Check server health or increase the MCP timeout; the request outcome is unknown.
```

  A timeout does not prove the server stopped — the outcome is unknown, so raise `architecture-pattern`'s `timeout` (or `OMP_MCP_TIMEOUT_MS`) before retrying any LLM tool; jobs submitted before the timeout keep running and can still be polled.

### Error codes

| Code | Meaning | Tools |
|------|---------|-------|
| `ERR_001` | requirements / domain / style failed printable-text validation inside the tool body | analyze, design, evaluate |
| `ERR_002` | no patterns found for the domain | analyze |
| `ERR_003` | generation failed | generate |
| `ERR_004` | supplied design does not meet minimum requirements | evaluate |
| `ERR_009` | LLM provider error (credentials, quota, upstream failure) | analyze, generate, design, evaluate |
| `ERR_010` | configuration file not found | server startup |
| `ERR_011` | server initialization failed | server startup |
| `ERR_012` | malformed architecture overview at an I/O boundary (`ERR_012: overview failed validation`) | evaluate input, generate/design output |
| `ERR_013` | pattern catalog could not be read (`ERR_013: Failed to load pattern catalog: …`) | list_architecture_patterns, get_architecture_pattern |
| `ERR_404` | unknown `job_id` (`ERR_404: Job '<id>' not found.`) | get_architecture_design_status, cancel_architecture_design |
| `ERR_999` | unexpected error captured by the background job task | submit_architecture_design_job |
| — | `Pattern not found: <name>` (no code) | get_architecture_pattern |

Most malformed arguments never reach the tool body: the FastMCP schema validator rejects them first with a raw Pydantic error text, e.g. `1 validation error for call[analyze] requirements String should have at least 1 character` or `value contains disallowed character U+0000 (category Cc)`. Treat that text as the error report; there is no `ERR_` code for it.

## Group 1 — LLM pipeline tools

### `analyze_architecture`

Derives style + pattern recommendations. Does not produce a design.

```ts
{
  requirements: string;  // 1-100000 chars, printable text
  domain: string;        // 1-200 chars
}
```

Latency: one LLM round trip — measured 66.2 s on this host, aborted by OMP's 30 s deadline. Not idempotent.

Output (flat object):

| Field | Content |
|-------|---------|
| `recommended_style` | top-scored `ArchitectureStyle` value |
| `selected_patterns` | top-k patterns (default 5) with their full pattern cards plus `analysis_score` (0–100) |
| `quality_metrics` | requirements-derived weights per attribute (`maintainability`, `scalability`, `reliability`, `security`, `performance`, `testability`), 0–10 |
| `matched_domains` | `{slug, fusion_score, rerank_score}` retrieval results |
| `strengths`, `weaknesses`, `recommendations` | LLM assessment of the requirement set / pattern fit |
| `is_fallback` | `true` when retrieval scored below the threshold and `layered-monolith` was substituted |

### `generate_architecture`

Skips the analyse leg: use it when the style and patterns are already known.

```ts
{
  requirements: string;
  style: string;                        // ArchitectureStyle value, e.g. "microservices"
  domain: string;
  selected_patterns?: string[] | null;  // exact pattern names, e.g. ["saga", "api-gateway"]
}
```

Omit `selected_patterns` to let domain retrieval pick them; unknown names are skipped with a log line, not an error. Latency: one LLM round trip — measured 211.2 s on this host (with a design job running concurrently), so it aborts under OMP's default deadline exactly like `analyze_architecture`. Not idempotent.

Output is the **design dict itself** (not wrapped in `design`): `overview`, `components`, `relationships`, `quality_attributes`, `api_contracts`, `shared_data_models`, `event_contracts` — see [Design dict shape](#design-dict-shape).

### `evaluate_architecture`

```ts
{
  architecture: Record<string, unknown>;  // design dict (see below)
  criteria: string;                       // 1-100000 chars, e.g. "scalability, reliability, security"
  domain: string;                         // 1-200 chars
}
```

Read-only for server state (`readOnlyHint: true`), but still an LLM call — measured 196.9 s, aborts under the default deadline. Not idempotent.

Output is **flattened**, unlike the `evaluation` object inside `design_architecture`:

```ts
{
  summary: string;                  // "Overall score: 35.0/100"
  metrics: Record<string, number>;  // per-attribute score on a 0-10 scale, incl. overall_quality
  recommendations: string[];        // flattened from the per-area map, each tagged with component + rationale
}
```

Input validation is strict — `ERR_012: overview failed validation` when the overview fails. `ERR_004` marks designs that meet the schema but not the minimum-requirements bar.

### `design_architecture`

Full pipeline in one call: analyse → generate → evaluate → refine.

```ts
{
  requirements: string;
  domain: string;
  override_style?: string | null;
}
```

Latency 5–10 minutes: the analyse leg alone measured 66.2 s and a single evaluation 196.9 s, and the pipeline runs both per attempt (up to 3 attempts) → it aborts under OMP's default 30 s deadline. Use the job trio, or raise the server timeout first (see `SKILL.md`). Its tool description recommends using it directly and calls the job trio "only for clients with short request timeouts" — under OMP's deadline that advice is wrong.

Output (same schema as the job's `result`):

| Field | Content |
|-------|---------|
| `design` | full design dict (see below) |
| `evaluation` | full `ArchitectureEvaluation`: `summary{overall_score 0-100, strengths, weaknesses, critical_findings}`, `metrics[]{name, score 0-100, description, findings, recommendations, reasoning}`, `recommendations{area: [...]}` |
| `attempts` | generate attempts performed (1–3 with the default `max_tries`) |
| `final_style` | confirmed style |
| `quality_metrics` | analysis-stage weights (0–10 per attribute) or `null` |
| `final_quality_score` | 0–100 score of the best attempt |
| `matched_domains` | retrieval slugs + fusion scores |
| `is_fallback` | `true` when the `layered-monolith` fallback was used |
| `alternative_styles` | `{pattern_name, style, score}` runner-ups |

Refinement loop: retries while the best score stays below `retrieval.min_quality_score` (default 50), up to `retrieval.max_tries` generate attempts (config default 3).

## Group 2 — async job trio

### `submit_architecture_design_job`

```ts
{ requirements: string; domain: string; override_style?: string | null; }
```

Returns in ~30 ms (measured 0.028 s):

```json
{"job_id": "<uuid>", "status": "pending", "message": "Job <uuid> created. Poll get_architecture_design_status('<uuid>') until status is 'completed', 'failed', or 'cancelled'."}
```

The tool's own description steers away from it ("ONLY use this when the calling client cannot wait") — under OMP's 30 s deadline that is the normal case. `override_style` is accepted without validation at submit time; the design's `overview.style` must still be a valid `ArchitectureStyle`, so a bogus override surfaces inside the job, not as a submit error. Measured: a job submitted with `override_style: "not-a-style"` was still `running` after 26 minutes with no completed attempt logged and had to be cancelled, while normal first attempts finish in 6.5–7.5 minutes. Pass a real style name from `list_architecture_patterns`.

### `get_architecture_design_status`

```ts
{ job_id: string; }
```

Returns in ~10 ms (measured 0.008–0.011 s). Read-only and idempotent.

```json
{"job_id": "...", "status": "running", "message": "Job is actively running the design pipeline.", "created_at": "2026-09-17T09:18:43.674637+00:00", "updated_at": "2026-09-17T09:18:43.692172+00:00"}
```

| Status | `message` | Meaning |
|--------|-----------|---------|
| `pending` | `Job is queued, not yet started.` | queued, pipeline not started |
| `running` | `Job is actively running the design pipeline.` | poll again in 10–30 s |
| `completed` | `Job completed successfully.` | `result` holds the full design output |
| `failed` | `Job failed — see the error field.` | `error` carries `ERR_009:` / `ERR_999:` text |
| `cancelled` | `Job was cancelled by a cancel_architecture_design call.` | report; offer to resubmit |

### `cancel_architecture_design`

```ts
{ job_id: string; }
```

Returns in ~30 ms (measured 0.031 s):

```json
{"job_id": "...", "status": "cancelled", "cancelled": true, "task_was_running": true, "message": "Job ... cancelled. The background task will exit at its next cancellation checkpoint."}
```

Best-effort: the pipeline checks the flag at stage boundaries, so up to one LLM call may still complete and the result is then discarded. Jobs already `completed`, `failed`, or `cancelled` cannot be cancelled; unknown ids return `ERR_404`.

## Group 3 — read-only catalog

### `list_architecture_patterns`

```ts
{ category?: string | null; domain?: string | null; }
```

Returns `[{name, description}]` — a minimal view. Measured: 40 entries, 6.6 KB total (fits OMP's ~10 KB device-output cap in one call). Read-only and idempotent.

- `category`: one of `messaging`, `structural`, `cloud`, `data`, `ai_cognitive`, `specialized`, `api_gateway`, `coordination`, `dataflow`, `presentation`; an unknown value returns `[]` (not an error) — measured.
- `domain`: matched against `pattern.suitable_domains`

### `get_architecture_pattern`

```ts
{ name: string; }   // exact pattern/style name, e.g. "microservices", "pipe-and-filter"
```

Full pattern JSON (~7 KB each; measured 7.2 KB for `microservices`). Read-only and idempotent. Unknown names raise `Pattern not found: <name>`.

All 40 names: `actor-based`, `aiml-centric`, `api-gateway`, `backend-for-frontend`, `blackboard`, `blockchain-based`, `broker`, `clean-architecture`, `client-server`, `command-query-responsibility-segregation`, `data-mesh`, `edge-computing`, `enterprise-service-bus`, `event-driven`, `event-sourcing`, `half-sync-half-async`, `hexagonal`, `hybrid-cloud`, `kappa-architecture`, `lambda-architecture`, `layered-monolith`, `master-slave`, `microkernel-plugin`, `microservices`, `model-view-controller`, `modular-monolith`, `monolithic`, `multi-cloud`, `pipe-and-filter`, `presentation-abstraction-control`, `reactive-architecture`, `reflection-architecture`, `rule-based-system`, `saga`, `serverless`, `service-mesh`, `service-oriented-architecture`, `space-based`, `strangler-fig`, `task-control-architecture`.

The names carry **no** `-architecture` suffix (the files on disk are `<name>-architecture.json`) and match the `ArchitectureStyle` enum used by `style`/`override_style` and `overview.style`.

Pattern JSON keys: `name`, `category`, `context`, `benefits`, `tradeoffs`, `quality_attributes` (0–10 per attribute, includes `simplicity`), `suitable_domains`, `unsuitable_domains`, `use_cases`, `avoid_when`, `component_types`, `technology_stack`, `anti_patterns`, `migration_from`, `migration_to`, `related_patterns`, `design_principles`, `best_practices`.

## MCP resources

The server advertises one concrete resource and three templates:

| URI | Returns |
|-----|---------|
| `pattern://` | all patterns as `{uri, name, description}` (40 entries) |
| `pattern://{name}` | full pattern JSON (same as `get_architecture_pattern`) |
| `template://{name}` | architecture template — exactly one exists: `layered-architecture-template` |
| `component://{type}` | component blueprint, keyed by the slugified component name |

**OMP caveat:** the sibling `agent-pattern` server registers the same three schemes, and OMP picks the target server by connection order, not by resource ownership. Measured on this host the sibling won every scheme:

```text
read mcp://pattern://microservices             → Pattern not found: microservices
read mcp://template://layered-architecture-template → Template not found: layered-architecture-template
read mcp://component://message-queue           → Component blueprint not found: message-queue
```

All three exist on this server (verified directly over MCP). Use the tool route (`get_architecture_pattern`, `list_architecture_patterns`) instead of resource reads for patterns; component blueprints have no tool equivalent, so read `component://<slug>` only from a client where the target server is unambiguous.

Component slugs are `lower → strip non-word/space/hyphen → spaces/underscores → hyphens` applied to each `component_types` entry's name (the part before `:`). Verified live: `api-gateway`, `message-broker`, `load-balancer`, `circuit-breaker`, `service-registry`, `event-bus`, `saga-orchestrator`, `cache`. Not valid: `message-queue`, `database`, `orchestrator`, `api-composition` (no such component types).

## Prompts

Interactive OMP sessions expose each server prompt as a slash command `/architecture-pattern:<prompt-name>` with `key=value` arguments (quote multi-word values); the fetch goes straight to the owning server, so unlike `mcp://` resource reads there is no sibling ambiguity.

| Prompt | Arguments | Effect |
|--------|-----------|--------|
| `design_architecture_workflow` | `requirements*`, `domain` (default `general`), `style` | drives the full design workflow; `style` maps to `override_style` |
| `explore_pattern_catalog` | `domain`, `category` | catalog discovery with the live 40 pattern names embedded |
| `evaluate_my_architecture` | `focus` | structures an existing design, then evaluates it |
| `compare_architecture_styles` | `style_a*`, `style_b*`, `requirements*` | two designs side by side (~2× cost) |

Non-interactive route: `write xd://mcp__architecture_pattern_get_prompt` with `{"name": "<prompt>", "arguments": {...}}` → `{"messages": [{"role": "user", "content": "..."}]}`; `list_prompts` (no args) enumerates them with their arguments. Inspect with `/mcp prompts` in the TUI.

## Tool annotations

As advertised by the running server:

| Tool | readOnlyHint | destructiveHint | idempotentHint |
|------|--------------|-----------------|----------------|
| `design_architecture` | true | false | false |
| `analyze_architecture` | true | false | false |
| `generate_architecture` | true | false | false |
| `evaluate_architecture` | true | false | false |
| `list_architecture_patterns` | true | false | true |
| `get_architecture_pattern` | true | false | true |
| `submit_architecture_design_job` | false | false | false |
| `get_architecture_design_status` | true | false | true |
| `cancel_architecture_design` | false | true | false |
| `list_prompts` | true | false | true |
| `get_prompt` | true | false | true |

`readOnlyHint: true` on the LLM tools means server state is unchanged — it does not make them cheap or safe to call under the default deadline.

## Design dict shape

The dict returned by `generate_architecture` (top level) and nested under `result.design` / `design` by the job trio and `design_architecture`:

```json
{
  "overview": {
    "reasoning": "design rationale (required in generated designs, optional on input)",
    "style": "microservices",
    "category": "structural",
    "principles": ["single-responsibility"],
    "constraints": ["max-100ms-latency"]
  },
  "components": [
    {"id": "order-service", "name": "Order Service", "type": "microservice",
     "description": "Manages the order lifecycle",
     "responsibilities": ["order lifecycle"],
     "interfaces": ["REST"], "technology_stack": ["Node.js", "PostgreSQL"]}
  ],
  "relationships": [
    {"source": "order-service", "target": "payment-service", "type": "sync-http",
     "description": "Payment authorisation call"}
  ],
  "quality_attributes": {"maintainability": "7", "scalability": "8"},
  "api_contracts": [],
  "shared_data_models": [],
  "event_contracts": []
}
```

Validation rules that matter for hand-written input to `evaluate_architecture` (each violation returns `ERR_012: overview failed validation`):

- `overview.style` — one of the 40 `ArchitectureStyle` values above
- `overview.category` — one of the 10 `PatternCategory` values listed under `list_architecture_patterns`
- `overview.principles` — at least one entry; `constraints`, `reasoning` optional
- `components[].id` — kebab-case (`^[a-z][a-z0-9_-]*$`); `name`, `type`, `description` non-empty; `responsibilities` at least one entry
- `relationships[]` — `source`, `target`, `type`, `description` required
- only `overview` and `components[].id/name/type/description/responsibilities` are strictly required; everything else may be omitted or empty

## Server-side knobs that change documented behaviour

Config lives in the server's `config/config.json` (env-overridable) — useful when a measured number here differs:

| Setting | Env | Default | Effect |
|---------|-----|---------|--------|
| `retrieval.max_tries` | `RETRIEVAL_MAX_TRIES` | 3 | max generate attempts before returning the best one |
| `retrieval.min_quality_score` | `RETRIEVAL_MIN_QUALITY_SCORE` | 50 | retry threshold on the 0–100 score |
| `retrieval.style_score_threshold` | `RETRIEVAL_STYLE_SCORE_THRESHOLD` | 50 | below this, `layered-monolith` + `is_fallback: true` |
| `retrieval.top_k_patterns` | `RETRIEVAL_TOP_K_PATTERNS` | 5 | patterns carried into generation |
| `tasks.heartbeat_interval_seconds` | `TASKS_HEARTBEAT_INTERVAL_SECONDS` | 30 | progress notifications (other clients only; OMP's deadline ignores them) |
| `validation.max_retries` | `VALIDATION_MAX_RETRIES` | 2 | LLM-output repair retries on schema violations |
| `pattern_directory` | `PATTERN_DIRECTORY` | `~/.config/architecture-pattern-mcp/pattern` | where the 40 pattern JSON files live |
