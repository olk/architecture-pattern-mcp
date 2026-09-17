# Workflows — architecture-pattern MCP in OMP

Recipes for the four jobs this server is used for. Tool parameters and output fields are in
`tools.md`; the entry-point rules (deadline, job trio) are in `SKILL.md`.

Every call below is a JSON write to a device:

```text
write xd://mcp__architecture_pattern_<tool>  <json args>
```

---

## Recipe 1 — Full design via the job trio (default)

Use this whenever the user wants a design. With OMP's default 30 s deadline the job-trio calls
are also the only ones that fit: `analyze_architecture` measured 66.2 s and `evaluate_architecture`
196.9 s in a test, both aborted by the deadline, and `design_architecture` alone runs 5–10 minutes.

**Step 1 — submit** (returns in ~30 ms):

```json
{"requirements": "ETL pipeline for IoT telemetry: ingest 10k events/sec from Kafka, parse JSON payloads, enrich with geolocation from Redis, write to InfluxDB and S3, with dead-letter handling",
 "domain": "data-processing"}
```

→ `{"job_id": "df4d6e18-…", "status": "pending", "message": "Job df4d6e18-… created. Poll …"}`

**Step 2 — record the `job_id`** before polling. There is no job-listing tool; the id is the only
handle, and the server persists it in SQLite (`~/.config/architecture-pattern-mcp/jobs.db`), so a
later turn or a restarted client can still resume polling it. Write it to a scratch file
(e.g. `.omp/architecture-pattern-job.txt`) if the poll loop may outlive the turn.

**Step 3 — poll** every 10–30 s with `{"job_id": "df4d6e18-…"}`:

| `status` | Action |
|----------|--------|
| `pending` / `running` | wait, poll again |
| `completed` | read `result.design` and `result.evaluation` |
| `failed` | report `error` (carries `ERR_009:` for provider failures, `ERR_999:` otherwise) |
| `cancelled` | report; offer to resubmit |

Between polls, interleave useful work (or `bash sleep 15`); the poll call itself is ~10 ms.

**Step 4 — cancel** if the user changes their mind or the job is no longer needed:

```json
{"job_id": "df4d6e18-…"}
```

→ `{"status": "cancelled", "cancelled": true, "task_was_running": true, …}` — takes effect at the
next stage boundary, so up to one LLM call may still land (and is then discarded).

**What the pipeline did:** analyse (style + top-k patterns) → generate → evaluate → refine while
the best score stays below 50, up to `retrieval.max_tries` generate attempts (config default 3).
Normal first attempts measured 395 s and 454 s in the server log (both stopped early at scores
71.0 / 71.4), so expect the whole job to land in the 5–10 minute range.

---

## Recipe 2 — One-shot `design_architecture`

Only for a user who prefers one blocking call and accepts a multi-minute turn. First raise the
deadline for this server in `~/.omp/agent/mcp.json`:

```json
"architecture-pattern": { "type": "http", "url": "http://localhost:8050/mcp", "timeout": 900000 }
```

- `timeout` is milliseconds; `0` disables the client-side deadline entirely.
- `OMP_MCP_TIMEOUT_MS` overrides every per-server value process-wide.
- A project `.omp/mcp.json` entry shadows the user entry; the user file's `disabledServers`
  beats `enabledServers` in every source.
- Run `/mcp reload` after editing, then confirm with `/mcp list`.

Then in one call:

```json
{"requirements": "Cloud-native e-commerce platform: product catalogue, cart, checkout, payments and inventory across five teams",
 "domain": "e-commerce-platforms",
 "override_style": "microservices"}
```

Expect 5–10 minutes; the result carries `design`, `evaluation`, `attempts`, `final_style`,
`quality_metrics`, `final_quality_score`, `matched_domains`, `is_fallback`, `alternative_styles`.
`override_style` is not validated against the style catalogue at call time: an unknown value flows
into generation as a generic style instead of erroring, but the design's `overview.style` must
still validate against the 40 `ArchitectureStyle` values, so prefer a real name from
`list_architecture_patterns`.

---

## Recipe 3 — Explore the catalog, then generate with chosen patterns

**List by category** (fast, no LLM):

```json
{"category": "messaging"}
```

→ 5 patterns for `messaging`; unknown categories return `[]`, so a typo looks like an empty
catalog — cross-check against the 10 valid category values in `tools.md`.

**Narrow by domain** instead when the category is unclear:

```json
{"domain": "e-commerce-platforms"}
```

**Fetch a candidate in full:**

```json
{"name": "saga"}
```

**Generate with the style and patterns you picked** (skips the analyse leg, one LLM round trip —
raise the timeout first, Recipe 2):

```json
{"requirements": "E-commerce checkout: handle distributed transactions across order, payment and inventory services with saga orchestration",
 "style": "microservices",
 "domain": "e-commerce-platforms",
 "selected_patterns": ["saga", "api-gateway", "event-sourcing"]}
```

Pattern names are exact and carry no `-architecture` suffix; useful ones here include `saga`,
`event-driven`, `event-sourcing`, `api-gateway`, `backend-for-frontend`, `service-mesh`,
`strangler-fig`, `serverless`, `hexagonal`, `pipe-and-filter`, `lambda-architecture`,
`kappa-architecture`, `modular-monolith`, `microkernel-plugin`. Unknown `selected_patterns`
entries are skipped with a log line, not an error.

---

## Recipe 4 — Evaluate an existing design

```json
{"architecture": {"overview": {"style": "microservices", "category": "structural",
                               "principles": ["single-responsibility", "autonomous-services"],
                               "constraints": ["max-100ms-latency"]},
                  "components": [{"id": "order-service", "name": "Order Service", "type": "microservice",
                                  "description": "Manages the order lifecycle",
                                  "responsibilities": ["order lifecycle"],
                                  "interfaces": ["REST"], "technology_stack": ["Node.js", "PostgreSQL"]},
                                 {"id": "payment-service", "name": "Payment Service", "type": "microservice",
                                  "description": "Processes payments",
                                  "responsibilities": ["payment authorisation"],
                                  "interfaces": ["REST"], "technology_stack": ["Python", "PostgreSQL"]}],
                  "relationships": [{"source": "order-service", "target": "payment-service",
                                     "type": "sync-http", "description": "Payment authorisation call"}],
                  "quality_attributes": {"maintainability": "7", "scalability": "8"}},
 "criteria": "scalability, reliability, security",
 "domain": "e-commerce-platforms"}
```

Returns `{summary, metrics, recommendations}` — `summary` is a string carrying the overall `n/100`
score, `metrics` maps attribute → score on a **0–10** scale (including `overall_quality`), and
`recommendations` is a flat string list (the per-area map is flattened, each entry tagged with the
component it targets). The call is an LLM round trip — measured 196.9 s, so it needs the raised
timeout from Recipe 2.

Input validation is strict: `overview.style` must be one of the 40 `ArchitectureStyle` values,
`overview.category` one of the 10 categories, `principles` needs at least one entry, and every
component needs a kebab-case `id` plus a non-empty `responsibilities` list — otherwise
`ERR_012: overview failed validation` comes back in ~10 ms, before any LLM work. See the design
dict shape in `tools.md` for the minimum viable payload.

Report order: state the overall score first, then metrics below ~7 on the 0–10 scale, then the
recommendations grouped by the component/attribute they target.

---

## Recipe 5 — Prompts (both routes)

Interactive TUI — one slash command per server prompt, `key=value` args, quote multi-word values:

```text
/architecture-pattern:design_architecture_workflow requirements="ETL pipeline for IoT telemetry" domain="data-processing" style="event-driven"
/architecture-pattern:explore_pattern_catalog domain="e-commerce-platforms" category="messaging"
/architecture-pattern:evaluate_my_architecture focus="security"
/architecture-pattern:compare_architecture_styles style_a="microservices" style_b="event-driven" requirements="Flash-sale e-commerce platform"
```

`/mcp prompts` lists the connected prompts; `/mcp resources` lists resources.

Non-interactive (agent-driven, works in scripts and headless runs):

```json
{"name": "design_architecture_workflow",
 "arguments": {"requirements": "…", "domain": "data-processing", "style": "microservices"}}
```

→ `{"messages": [{"role": "user", "content": "…"}]}`; follow the returned instructions in the
current turn. `list_prompts` (no args) enumerates prompt names and arguments.

Cost note: `compare_architecture_styles` triggers two `generate_architecture` calls — roughly 2×
tokens and latency, and each one needs a raised timeout. If the two designs score within ~5 points
of each other, say so and pick either.

---

## Interpreting results

### `final_quality_score`

0–100. ≥ 75 strong; 50–74 workable with named tradeoffs; < 50 means the pipeline regenerated and
still returned its best attempt — surface `evaluation.recommendations` instead of presenting the
design as finished.

### `attempts`

| Value | Meaning |
|-------|---------|
| 1 | succeeded first try |
| 2 | first attempt scored below `min_quality_score` (50); the retry succeeded |
| 3 | two retries — the default `retrieval.max_tries` ceiling |

`attempts > 1` is the loop self-healing, not a failure — read the recommendations to see what
changed.

### `evaluation.recommendations`

A map keyed by area (`{"scalability": [...], "security": [...]}`) inside `design_architecture` /
job results; `evaluate_architecture` flattens it to a list. Fix critical findings first — metric
score < 70 on the pipeline's 0–100 scale (the workflow prompts' "below 75/70" thresholds refer to
the same 0–100 scale) — then work down the attributes the user cares about.

### `matched_domains` and fallback

Top domain slugs with `fusion_score` and `rerank_score`. When the top score is below
`retrieval.style_score_threshold` (50) or `is_fallback` is `true`, the analyser substituted
`layered-monolith` — expected behaviour. Pass `override_style` (design/submit) or `style`
(generate) when the requirement clearly calls for another style.

### `alternative_styles`

`{pattern_name, style, score}` runner-ups (present in `design_architecture` and job results; the
bare `analyze_architecture` call returns `selected_patterns` with `analysis_score` instead). Use
them to present a genuine second option — e.g. `microservices` → `modular-monolith` — instead of an
invented comparison.

---

## Troubleshooting (OMP-specific)

| Symptom | Cause | Fix |
|---------|-------|-----|
| `MCP failure … failure: timeout … Request timeout after 30000ms` | OMP's per-request MCP deadline; server progress notifications do not extend it | use the job trio, or set `"timeout": 900000` (or `0`) for `architecture-pattern` and `/mcp reload`. The aborted call's outcome is unknown — a job submitted before the timeout can still be polled; a one-shot call was discarded |
| `read mcp://pattern://microservices` says `Pattern not found: microservices` | `pattern://` (and `template://`, `component://`) are registered by both pattern servers; OMP picked the sibling | read patterns via `get_architecture_pattern` |
| `read mcp://template://layered-architecture-template` says `Template not found` | same sibling collision; the template exists on this server | use a client where the target server is unambiguous, or skip templates |
| `ERR_012: overview failed validation` on evaluate | hand-written design failed schema validation | use the design dict shape in `tools.md`; check `overview.style`/`category` and component `id`/`responsibilities` |
| `1 validation error for call[analyze] …` (no `ERR_` code) | FastMCP schema validation rejected the argument before the tool ran | fix the argument (blank/stripped requirements, control characters, over-length strings) |
| Tool list changed / calls fail after an edit to `src/` | OMP keeps stale MCP connections | `/mcp reload` (full) or `/mcp reconnect architecture-pattern` |
| `ERR_009` | LLM provider problem on the server side (model, credentials, quota) | report the message; do not retry blindly — check the server's generator config |
| Job stuck in `running` past ~15 min | server-side pipeline stall or provider hang | `cancel_architecture_design`, then resubmit; check server logs |
