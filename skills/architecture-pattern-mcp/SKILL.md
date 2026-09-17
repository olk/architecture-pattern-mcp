---
name: architecture-pattern-mcp
description: Designs software system architectures via the architecture-pattern MCP server (OMP server name `architecture-pattern`). Analyses requirements and domain, selects from 40 patterns (microservices, event-driven, hexagonal, pipe-and-filter, layered-monolith and 35 more), generates full designs with components, relationships, API contracts, data models and event contracts, and evaluates quality across scalability, maintainability, reliability, security, performance and testability. Use when designing a new system, comparing architecture styles, evaluating an existing design, or exploring the pattern catalog. Triggers on requests to design the architecture for X, compare microservices vs event-driven, evaluate this architecture, choose an architecture pattern for X. Do NOT use for implementing individual features, DevOps or IaC configuration, code-level refactoring, or single-component class design. Requires the architecture-pattern MCP server connected.
---

# architecture-pattern MCP

Architecture design pipeline exposed by the `architecture-pattern` MCP server on this host:

1. **Analyse** requirements + domain → recommended style, top-k patterns with scores, quality-attribute weights, matched domain slugs
2. **Generate** the design: overview, components, relationships, quality attributes, API contracts, shared data models, event contracts
3. **Evaluate** against quality attributes → per-metric scores, findings, recommendations keyed by area
4. **Refine** — regenerates while the best score stays below 50, up to `retrieval.max_tries` attempts (config default 3)

40 built-in patterns (one JSON file each in the server's pattern directory), 372 `ArchitectureDomain` slugs, 10 pattern categories, 4 workflow prompts, 11 tools.

## OMP constraints (read first)

### 1. OMP is a short-timeout client → the async job trio is the default entry point

OMP applies one MCP request deadline, resolved in this order: `OMP_MCP_TIMEOUT_MS` env → the server's `timeout` field (milliseconds) in `~/.omp/agent/mcp.json` → **30 000 ms default**. It is a single timer per request (`src/mcp/timeout.ts`, `src/mcp/transports/http.ts`); server progress notifications do **not** extend it, so the server's 30 s heartbeat buys nothing here.

`architecture-pattern` has no `timeout` entry in `~/.omp/agent/mcp.json` on this host, so the 30 s deadline applies. Measured against `http://localhost:8050/mcp` in that configuration:

| Call | Device | Latency |
|------|--------|---------|
| `submit_architecture_design_job` | `xd://mcp__architecture_pattern_submit_architecture_design_job` | 0.03 s |
| `get_architecture_design_status` | `xd://mcp__architecture_pattern_get_architecture_design_status` | 0.01 s |
| `cancel_architecture_design` | `xd://mcp__architecture_pattern_cancel_architecture_design` | 0.03 s |
| `list_architecture_patterns` / `get_architecture_pattern` | catalog devices | 0.01 s |
| `analyze_architecture` | `xd://mcp__architecture_pattern_analyze_architecture` | 66.2 s → aborted at 30 s by OMP |
| `generate_architecture` | `xd://mcp__architecture_pattern_generate_architecture` | 211.2 s → aborts |
| `evaluate_architecture` | `xd://mcp__architecture_pattern_evaluate_architecture` | 196.9 s → aborts |
| `design_architecture` | `xd://mcp__architecture_pattern_design_architecture` | 5–10 min → aborts |

Attempting the one-shot call under the default deadline yields, verbatim:

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

The timeout does not stop the server: in a test the aborted `analyze_architecture` call kept running and logged `analyze_architecture completed` ~2 minutes later, while its result went nowhere. The outcome is unknown — a background job submitted before the timeout keeps running and can still be polled. The server's own tool descriptions still call `design_architecture` the default and the job trio "only for clients with short request timeouts (Cursor, Claude Desktop)"; under OMP's 30 s deadline **OMP is that client** — use the job trio, whose result survives in the server's job store.

To run the blocking one-shot pipeline instead, raise the deadline for this server — edit `~/.omp/agent/mcp.json`:

```json
"architecture-pattern": { "type": "http", "url": "http://localhost:8050/mcp", "timeout": 900000 }
```

`"timeout": 0` disables client-side MCP timeouts for the server. Then `/mcp reload`. A project `.omp/mcp.json` entry shadows the user entry; the user file's `disabledServers`/`enabledServers` win over both.

For non-OMP clients: the job trio works everywhere; the blocking tools need a request deadline of ≥ 10 minutes (or progress-heartbeat support, which this server emits every 30 s).

### 2. Tools are `xd://` devices

```text
write  xd://mcp__architecture_pattern_<tool>   JSON args object → tool result
read   xd://mcp__architecture_pattern_<tool>   device doc + current input schema
```

Device prefix = server name lowercased with `-` → `_` (`architecture-pattern` → `mcp__architecture_pattern`). Invalid args echo the schema — fix the JSON and retry, do not switch tools.

### 3. `domain` and `style` are separate arguments — never embed them in `requirements`

- `requirements` — free text of what the system must do (1–100 000 chars, printable; control/format characters are rejected)
- `domain` — problem-space tag (1–200 chars, e.g. `data-processing`, `e-commerce-platforms`, `iot-data-processing`); drives BM25 + dense + cross-encoder pattern retrieval over 372 slugs. Results are `{slug, fusion_score, rerank_score}` in `matched_domains`.
- `style` / `override_style` — architecture decision (1–100 000 chars), one of the 40 `ArchitectureStyle` names; **the same vocabulary as pattern names**, e.g. `microservices`, `event-driven`, `kappa-architecture`, `pipe-and-filter`, `layered-monolith`. `override_style` (design/submit) and `style` (generate) win over the analyse-derived style.

An unknown style string is **not** rejected: guidance falls back to a generic default and the override flows into generation. If retrieval's top score is below `retrieval.style_score_threshold` (default 50), the server falls back to `layered-monolith` and sets `is_fallback: true` — expected behaviour, not an error.

### 4. Do not read patterns through `mcp://pattern://…` on this host

The server advertises `pattern://`, `pattern://{name}`, `template://{name}`, `component://{type}`, and OMP reads MCP resources with `read mcp://<resource-uri>`. But the sibling `agent-pattern` server registers the same three schemes, and OMP resolves a resource URI by server order (`src/internal-urls/mcp-protocol.ts`), not by which server owns the resource. Measured on this host the sibling won every scheme: the bare `read mcp://pattern://` list returned the sibling's 61 agent patterns, `read mcp://pattern://microservices` failed with `Pattern not found: microservices` (the sibling's error), and `mcp://template://layered-architecture-template` failed with `Template not found` even though this server serves it. Use `get_architecture_pattern` / `list_architecture_patterns` — the tool route is authoritative and unambiguous.

### 5. Job ids are the only durable handle

`submit_architecture_design_job` returns a `job_id` and the server persists jobs in SQLite (`~/.config/architecture-pattern-mcp/jobs.db`, override `ARCHITECTURE_PATTERN_JOBS_DB`) — there is no job-listing tool. A `job_id` survives a turn boundary, a client restart, or an OMP timeout, but only if you keep it: write it to a scratch file (e.g. `.omp/architecture-pattern-job.txt`) when the poll loop may outlive the turn.

## Entry-point decision guide

```text
Existing design to score?
├── YES → evaluate_architecture (device mcp__architecture_pattern_evaluate_architecture)
└── NO
    ├── Explore the catalog first   → list_architecture_patterns (category?/domain?) → get_architecture_pattern(name)
    ├── Full design + evaluation    → job trio: submit_architecture_design_job → get_architecture_design_status
    │                                  (use design_architecture directly only when the server timeout in
    │                                   ~/.omp/agent/mcp.json is >= 600000 or 0)
    └── Known style + patterns      → generate_architecture (skips the analyse leg)
```

## Device quick reference

| Device suffix | Purpose | Latency | Notes |
|---------------|---------|---------|-------|
| `design_architecture` | Full pipeline, one call | 5–10 min | needs a raised MCP timeout |
| `analyze_architecture` | Style + pattern recommendations | 66 s measured | aborts under the 30 s deadline |
| `generate_architecture` | Design from explicit `style` + `selected_patterns` | 211 s measured | aborts under the 30 s deadline |
| `evaluate_architecture` | Score an existing design dict | 197 s measured | aborts under the 30 s deadline |
| `submit_architecture_design_job` | Start pipeline, returns `job_id` | 0.03 s | default entry point |
| `get_architecture_design_status` | Poll job; `result` when `completed` | 0.01 s | idempotent |
| `cancel_architecture_design` | Best-effort cancel at stage boundary | 0.03 s | not idempotent |
| `list_architecture_patterns` | Minimal pattern view (`name`, `description`) | 0.01 s | idempotent; unknown `category` returns `[]` |
| `get_architecture_pattern` | Full pattern JSON by exact name | 0.01 s | idempotent; unknown name raises `Pattern not found: <name>` |
| `list_prompts`, `get_prompt` | Workflow prompt templates | fast | tool route for prompt clients |

## Job trio recipe

1. **Submit** — `write xd://mcp__architecture_pattern_submit_architecture_design_job` with `{"requirements": "...", "domain": "...", "override_style": null}` → `{"job_id": "<uuid>", "status": "pending", "message": "Job <uuid> created. Poll get_architecture_design_status('<uuid>') until status is 'completed', 'failed', or 'cancelled'."}`
2. **Persist the `job_id`** (see constraint 5) before polling.
3. **Poll** — `write xd://mcp__architecture_pattern_get_architecture_design_status` with `{"job_id": "..."}` every 10–30 s (interleave other work or `bash sleep 15`); branch on `status`:

| Status | `message` | Action |
|--------|-----------|--------|
| `pending` | `Job is queued, not yet started.` | poll again after 10–30 s |
| `running` | `Job is actively running the design pipeline.` | poll again after 10–30 s |
| `completed` | `Job completed successfully.` | read `result` (same schema as `design_architecture`) |
| `failed` | `Job failed — see the error field.` | report `error` |
| `cancelled` | `Job was cancelled by a cancel_architecture_design call.` | report; offer to resubmit |

4. **Cancel** — `write xd://mcp__architecture_pattern_cancel_architecture_design` with `{"job_id": "..."}` → `{"job_id": "...", "status": "cancelled", "cancelled": true, "task_was_running": true, "message": "..."}`. Best-effort: the pipeline checks the flag at stage boundaries, so up to one LLM call may still land. Terminal jobs cannot be cancelled (`ERR_404` for unknown ids).

## Interpreting results

- `final_quality_score` (0–100): ≥ 75 strong, 50–74 workable with named tradeoffs, < 50 means the pipeline regenerated and still returned its best attempt
- `attempts` (1–3 with the default `max_tries`): > 1 means the pipeline self-healed — read `evaluation.recommendations` to see what changed
- `evaluation.summary.overall_score` (0–100), `strengths`, `weaknesses`, `critical_findings`; `evaluation.metrics[]` carries `{name, score 0–100, description, findings, recommendations}` per attribute
- `evaluation.recommendations` is a map keyed by area (`{"scalability": [...], "security": [...]}`); `evaluate_architecture` flattens it to a list and scores 0–10
- `final_style` + `alternative_styles` (`{pattern_name, style, score}` runner-ups) — present a genuine second option instead of an invented comparison
- `matched_domains`: retrieval slugs with `fusion_score`/`rerank_score`; a low top score (or `is_fallback: true`) explains the `layered-monolith` fallback

## Prompts (workflow templates)

Interactive OMP sessions expose each server prompt as a slash command named `<server>:<prompt>`, with `key=value` arguments:

```text
/architecture-pattern:design_architecture_workflow requirements="..." domain="data-processing" style="microservices"
/architecture-pattern:explore_pattern_catalog domain="e-commerce-platforms" category="messaging"
/architecture-pattern:evaluate_my_architecture focus="security"
/architecture-pattern:compare_architecture_styles style_a="microservices" style_b="event-driven" requirements="..."
```

`/mcp prompts` lists what is connected. Outside the interactive TUI, call the tool route instead: `write xd://mcp__architecture_pattern_get_prompt` with `{"name": "design_architecture_workflow", "arguments": {"requirements": "...", "domain": "..."}}` (arguments: `requirements*`, `domain`, `style` for the design workflow; `style_a*`, `style_b*`, `requirements*` for the comparison — that one costs two `generate_architecture` calls).

## Reference files

- `skill://architecture-pattern-mcp/references/tools.md` — per-tool schemas, exact output fields, error codes, the deadline-failure format, tool annotations, and the design-dict shape
- `skill://architecture-pattern-mcp/references/workflows.md` — recipes (job trio, raised-timeout one-shot, catalog → generate, evaluate, prompts), result interpretation, and OMP troubleshooting
