# Why the Analyze Phase Submits Each Thought to Both MCP Reasoning Tools

When reading `make docker-logs` for an analyze-phase run, the same `thought`
string appears twice per step — once sent to `code-reasoning`, once to
`shannonthinking` (see calls 1–4 in any captured log). This is by design,
not a duplication bug.

## The Tools Are Scratchpads, Not Reasoners

`shannonthinking` and `code-reasoning` are *structured thinking
scratchpads*: they validate, number, and record thoughts a caller
authors. Neither tool authors its own content. The ThoughtGenerator
loop (`src/reasoning/client.py:_generate_trace`) authors each thought
**with the generator's own LLM** (one `generate_structured` call per
step), then submits it to every tool listed in the phase strategy:

```python
# src/reasoning/client.py:_generate_trace (~line 340)
for tool_kind in strategy.tools:                              # every configured tool
    payload = draft_to_params(tool_kind, draft, step_number, total)
    await self._call_tool(tool_kind, payload)                # same thought, different casing
```

## Per-Phase Tool Selection

The `tools` list is per-phase in `ReasoningConfig.per_phase.<phase>.tools`
(`src/reasoning/config.py`, defaults in `_default_per_phase()`):

| Phase   | `tools`              | Calls per step | Submissions per phase run |
|---------|----------------------|----------------|----------------------------|
| analyze | `["code", "shannon"]`| 2              | 2 × `pre_ll_thoughts`     |
| generate| `["code"]`           | 1              | 1 × `pre_ll_thoughts`     |
| evaluate| `["shannon"]`        | 1              | 1 × `pre_ll_thoughts`     |
| retry   | `["code", "shannon"]`| 2              | 2 × `pre_ll_thoughts`     |

The analyze phase uses both tools per step by deliberate design (Plan v5
§8.2): `shannonthinking` provides Shannon-style validation state
(uncertainty, recheckStep, experimentalValidation); `code-reasoning`
provides branch-aware state. Running them in parallel is a
cross-validation pattern — both must accept the same authored thought
for it to be considered validated.

## Wire Shape Differs, Content Does Not

The two adapters in `src/reasoning/tools.py` only change field casing —
they never mutate the `thought` body:

| Tool             | Wire fields                                                                                              | Bytes |
|------------------|----------------------------------------------------------------------------------------------------------|-------|
| `code-reasoning` | `thought`, `thought_number`, `total_thoughts`, `next_thought_needed` (4 fields, snake_case)              | 153–154 |
| `shannonthinking`| `thought`, `thoughtType`, `thoughtNumber`, `totalThoughts`, `nextThoughtNeeded`, `uncertainty`, `assumptions`, `dependencies` (8 fields, camelCase) | 217–232 |

The `thought` field is byte-identical in both wire payloads. The
differences in **response** structure reflect each tool's bookkeeping:

```json
// code-reasoning — minimal ack + branch state
{"status":"processed","thought_number":2,"total_thoughts":4,
 "next_thought_needed":false,"branches":[],"thought_history_length":1}

// shannonthinking — Shannon-style validation state
{"thoughtNumber":2,"totalThoughts":4,"nextThoughtNeeded":false,
 "thoughtType":"problem_definition","uncertainty":0.05,
 "thoughtHistoryLength":1,"hasExperimentalValidation":false,"hasRecheckStep":false}
```

## Why Responses Never Contain a Thought

Neither response carries an authored `thought` text — only metadata
(numbering, continuation flag, validation state, branch/experiment
flags). This is **by design**: both tools are *scratchpads that record
thoughts the caller authors*, not generators. The ThoughtGenerator
loop is the only thing that authors content; the tools validate,
number, and decide whether to continue.

The naming ("shannon-**thinking**", "code-**reasoning**") reads like a
generator but the contracts confirm scratchpad-only behavior:

```python
# src/reasoning/tools.py:106-129
SHANNON_TOOL = ToolContract(
    kind="shannon", name="shannonthinking",
    probe_payload={"thought": "startup probe",
                   "thoughtType": "problem_definition",
                   "thoughtNumber": 1, "totalThoughts": 1,
                   "nextThoughtNeeded": False, ...},
)
CODE_TOOL = ToolContract(
    kind="code", name="code-reasoning",
    probe_payload={"thought": "startup probe",
                   "thought_number": 1, "total_thoughts": 1,
                   "next_thought_needed": False},
)
```

Inputs: just `thought` (body) + numbering/control fields. **Nothing
else flows in; nothing thought-shaped flows back.** The tools have
no LLM inside — they're pure validators/recorders, and their npm
packages (`@mettamatt/code-reasoning`, `olaservo/shannon-thinking`)
are pure-JS state machines.

The module docstring makes this explicit
(`src/reasoning/config.py:34-37`):

> Both tools are scratchpads, not reasoning engines: a caller must
> AUTHOR each thought. The ReasoningClient's ThoughtGenerator loop
> does that with this server's own LLM, then submits the thought to
> the tool for structuring.

And the client (`src/reasoning/client.py:23-31`):

> The two reasoning MCP servers are structured SCRATCHPADS: they
> validate, number, branch, and record thoughts that a CALLER
> authors.

If the tools echoed thoughts back, the wire would carry every
thought twice (once in the request, once in the response), doubling
log volume and risking accidental re-disclosure. The lean
request-only content / response-only metadata split is deliberate.

## Dual Submission as a Runtime Integrity Check

Because the same thought body goes to both tools, the two DEBUG log lines
per step carrying **byte-identical `thought` values** is a runtime
sanity check that the wire adapters don't mutate the body — only re-case
field names. An adapter regression that accidentally truncated, rewrote,
or rewrote fields would show up as a divergence between the two log
lines at the same `(phase, step)` and be visible immediately.

This is also why the pre-call DEBUG line logs `payload_keys` (the
shape) but only later versions log the full `thought` (the body) —
the keys list is the shape contract, the thought is the content.

## How to Change It

To restrict analyze (or any phase) to a single tool, edit
`src/reasoning/config.py:_default_per_phase()["analyze"].tools` to
`["shannon"]` (or `["code"]`). This loses the dual-tool
cross-validation pattern — keep the trade-off in mind.

## Verifying in `docker logs`

A clean analyze run produces `tools_called={"code-reasoning": N,
"shannonthinking": N}` in the `"Reasoning trace ready"` INFO record
(`src/pipeline.py:_reasoning_block`). For the captured run: N=2 for
analyze (4 total calls = 2 steps × 2 tools), N=3 for evaluate (3 ×
shannon), N=3 for generate (3 × code). The counts match the strategy's
`tools` lists above, multiplied by the number of thoughts in the
phase. If `tools_called` ever shows a tool that isn't in the
strategy's `tools` list (or omits one that is), the configuration is
out of sync.