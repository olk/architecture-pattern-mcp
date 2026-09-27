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

| Phase   | `tools`              | Thoughts (`pre_llm_thoughts`) | Calls per step | Submissions per phase run |
|---------|----------------------|------------------------------|----------------|----------------------------|
| analyze | `["code", "shannon"]`| 4                            | 2              | 2 × `pre_llm_thoughts`     |
| generate| `["code"]`           | 3                            | 1              | 1 × `pre_llm_thoughts`     |
| evaluate| `["shannon"]`        | 3                            | 1              | 1 × `pre_llm_thoughts`     |
| retry   | `["code", "shannon"]`| 2                            | 2              | 2 × `pre_llm_thoughts`     |

The analyze phase uses both tools per step by deliberate design (Plan v5
§8.2): `shannonthinking` provides Shannon-style validation state
(uncertainty, recheckStep, experimentalValidation); `code-reasoning`
provides branch-aware state. Running them in parallel is a
cross-validation pattern — both must accept the same authored thought
for it to be considered validated.

## `code-reasoning` Is the Only Tool Behind the Generated Components

The answer's components, relationships, and deployment strategy are
produced in the **generate** phase, and the generate strategy routes
**`code-reasoning` only** — `shannonthinking` is never called there.
The chain, end to end:

```
src/pipeline.py:844   reasoning_context = await self._reasoning_block(
                          "generate", {"requirements": requirements})
                      → _reasoning_block builds a ReasoningTrace whose
                        tools_called == {"code-reasoning": N}
src/pipeline.py:849   user_prompt = self._build_generate_user_prompt(..., reasoning_context=…)
src/pipeline.py:856   design_response = await self._agent.generate_structured(...)
src/pipeline.py:880   ArchitectureDesign(components=wire.components,
                                            relationships=wire.relationships, …)
```

The generate step agenda states the scope explicitly
(`src/reasoning/config.py:151-170`): *"Map every stated requirement to
concrete component candidates"* → *"Sketch two or three alternative
component decompositions with their key trade-offs"* → *"Commit to one
decomposition and justify the trade-offs against the requirement
priorities."* Every component in the returned design is therefore
grounded in a thought that `code-reasoning` numbered and recorded;
`shannonthinking`'s validation state (uncertainty, recheckStep,
experimentalValidation) plays no part in it.

`shannonthinking` is reserved for **evaluate** (the rubric audit, where
its validation state is the useful part) and pairs with
`code-reasoning` in **analyze** and **retry**.

Verify the routing at runtime instead of trusting the table above:

```bash
uv run python -c "
from src.reasoning.config import ReasoningConfig
from src.reasoning.tools import TOOL_CONTRACTS
for phase, s in ReasoningConfig().per_phase.items():
    print(phase, s.pre_llm_thoughts, [TOOL_CONTRACTS[t].name for t in s.tools])"
```

```
analyze 4 ['code-reasoning', 'shannonthinking']
generate 3 ['code-reasoning']
evaluate 3 ['shannonthinking']
retry 2 ['code-reasoning', 'shannonthinking']
```

`config/config.json` sets `reasoning.enabled` plus the command and
timeout knobs but never `per_phase`, so these defaults are what ships.

### Scope of the Claim: Answer Components vs. Pattern `component_types`

Two different things in this pipeline are named "components" — only one
of them involves the reasoning MCPs:

| Thing | Producer | Reasoning-MCP calls |
|-------|----------|---------------------|
| `ArchitectureDesign.components` in the answer | LLM call at `src/pipeline.py:856` (generate), grounded by the `code-reasoning` trace | yes — `code-reasoning` only |
| Pattern `component_types` → `Component Types:` prompt section | deterministic dedup/render in `_build_pattern_context` (`src/pipeline.py:1402-1494`) | **none** |
| `component://{type}` blueprints | `build_component_blueprints` (`src/resources/components.py:77`), built once at startup (`src/server.py:594-595`) | **none** |

Measured, not inferred (2026-09-27 probe: stub LLM, real stdio servers
via `REASONING_*_CMD` overrides): building the pattern context recorded
0 reasoning completions, while the `generate()` call whose prompt carries
that context recorded exactly the `code-reasoning` trace:

```
_build_pattern_context reasoning calls (must be 0): 0
deterministic 'Component Types:' section present:    True
design.components (from the stubbed answer):         ['api-gateway']
prompt carries <reasoning_context>:                  True
trace lines in prompt: ['[1|code|model|u=0.1] …', '[2|code|model|u=0.1] …', '[3|code|model|u=0.1] …']
shannonthinking anywhere in the design prompt:       False
'Reasoning trace ready': {'phase': 'generate', 'steps': 3, 'tools_called': {'code-reasoning': 3}, 'cached': False}
```

Consequences worth keeping straight:

- A reasoning-MCP outage degrades only the *grounding* of the
  LLM-authored components; the pattern→component-type mapping and the
  `component://` resources are deterministic and unaffected.
- "Why does this component exist?" is answered by the `code-reasoning`
  trace for the answer's components; the `Component Types:` prompt
  section traces to pattern JSON instead, with no MCP involvement on
  that path — do not conflate the two when reading a design.

### Executed Proof: Intent vs. What Actually Ran

The one-liner above prints **intent** — the strategy table. Only an
executed trace proves **wiring**: which MCP servers were actually
spawned, with which payload, and what reached the component-design
call. This probe stubs the generator LLM (so the thoughts are fixed)
but spawns both real stdio servers, then runs the pipeline's own
`generate()`. Save the snippet below as `probe_reasoning_routing.py`
outside the repo (`/tmp`) — it is a throwaway, not a committed tool:

```bash
CONFIG_PATH=config/config.json PYTHONPATH=. uv run python probe_reasoning_routing.py
```

```python
import asyncio
from typing import Any

from src.config import ConfigManager, EmbedderConfig
from src.patterns.loader import PatternLoader
from src.pipeline import ArchitecturePipeline
from src.reasoning.client import ReasoningClient
from src.reasoning.config import ReasoningConfig
from src.reasoning.schemas import ThoughtDraft
from src.schemas.architecture import (
    ArchitectureDesignResponse,
    ArchitectureDesignResponseWire,
    ArchitectureOverviewWire,
)
from src.schemas.components import Component, Relationship

DRAFT = ThoughtDraft(
    thought="Map the SLO requirement onto an API gateway component.",
    phase_tag="model",
    uncertainty=0.2,
    next_needed=True,
    assumptions=["p95 latency budget applies to the edge"],
)


class StubAgent:
    """Stands in for SoftwareArchitectAgent: authors thoughts, returns a design."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.schemas: list[str] = []

    async def generate_structured(self, **kwargs: Any) -> Any:
        schema = kwargs["response_schema"]
        if schema is ThoughtDraft:
            return DRAFT
        self.prompts.append(kwargs["user_prompt"])
        self.schemas.append(schema.__name__)
        return schema(
            overview=ArchitectureOverviewWire(
                reasoning="Gateway fronts the backend.",
                style="layered-monolith",
                category="structural",
                principles=["explicit contracts"],
            ),
            components=[
                Component(id="api_gateway", name="API Gateway", type="gateway",
                          description="Terminates TLS.", responsibilities=["routing"]),
                Component(id="backend", name="Backend", type="service",
                          description="Domain logic.", responsibilities=["domain logic"]),
            ],
            relationships=[Relationship(source="api_gateway", target="backend",
                                        type="sync", description="proxied call")],
            quality_attributes={"performance": "p95 < 200ms"},
        )


async def main() -> None:
    cfg = ReasoningConfig(**ConfigManager.load_config()["reasoning"])
    agent = StubAgent()
    client = ReasoningClient(cfg, agent)
    for phase in ("analyze", "generate", "evaluate", "retry"):
        trace = await client.run_pre_llm(phase, {"requirements": "p95 < 200ms"})
        print(f"{phase:9s} {trace.tool_call_counts}")
    pipeline = ArchitecturePipeline(
        agent=agent,
        pattern_loader=PatternLoader(),
        embedder_config=EmbedderConfig(provider="none", config={}),
        reasoning_client=client,
    )
    design = await pipeline.generate(
        requirements="Serve 10k rps with p95 < 200ms",
        domain="web",
        style="layered-monolith",
        selected_patterns=[],
    )
    prompt = agent.prompts[-1]
    block = prompt.split("<reasoning_context>")[1].split("</reasoning_context>")[0]
    print("design call schema:", agent.schemas[-1])
    print("design prompt header:", block.strip().splitlines()[0].strip())
    print("shannonthinking in design prompt:", "shannonthinking" in prompt)
    print("components:", [c.id for c in design.components])


asyncio.run(main())
```

```
analyze   {'code-reasoning': 4, 'shannonthinking': 4}
generate  {'code-reasoning': 3}
evaluate  {'shannonthinking': 3}
retry     {'code-reasoning': 2, 'shannonthinking': 2}
design call schema: ArchitectureDesignResponse
design prompt header: PHASE: generate | TOOLS: code | STEPS: 3
shannonthinking in design prompt: False
components: ['api_gateway', 'backend']
```

Reading the transcript:

- Per-tool counts equal `pre_llm_thoughts × len(tools)` (8 = 4 × 2 for
  analyze, 3 = 3 × 1 for generate, …), so every configured tool ran
  on every step — the analyze row carrying both keys is the dual
  submission, not a retry.
- The generate row has **no** `shannonthinking` key, and the design
  prompt's `<reasoning_context>` header reads `TOOLS: code` — the
  positive proof that the call producing `components` /
  `relationships` is grounded in a `code-reasoning` trace.
- `shannonthinking in design prompt: False` is the negative proof: no
  Shannon validation state leaks into the component design.
- `design call schema` echoes `retrieval.use_lean_wire_schema`
  (`ArchitectureDesignResponse` here, the full schema; the wire schema
  when the knob is on) — printed so a transcript can't be silently
  attributed to the wrong prompt path.

Two host caveats, neither a defect: the embedded entry point
`/usr/local/lib/node_modules/…` only exists in the image, so on a host
the client logs `embedded binary not found; falling back to npx` and
uses the npx command; and `CONFIG_PATH=config/config.json` is required
because the default `~/.config/architecture-pattern-mcp/config.json`
may hold a legacy retrieval schema. A globally `npm i -g`-installed
pair can be forced via `REASONING_SHANNONTHINKING_CMD` /
`REASONING_CODE_REASONING_CMD` (JSON lists) — a configured command
that differs from the embedded default is used as-is
(`src/reasoning/client.py:198-231`).

### When Generate Skips the Reasoning MCPs Entirely

Two paths in `generate()` produce a design with no `code-reasoning`
trace, and neither is a routing bug:

- `generate(override_user_prompt=…)` (`src/pipeline.py:840-843`)
  bypasses `_reasoning_block` altogether and prompts the agent directly.
- `reasoning.enabled=false`, a missing `ReasoningClient`, a client
  exception, or an empty trace all fall through to
  `render_degraded_context(phase)` (`src/pipeline.py:602-613`): the
  prompt still gets the in-prompt thinking scaffold, but no MCP call is
  made. In `docker logs` the tell is the absence of a `"Reasoning trace
  ready"` INFO record for `phase="generate"`.

Either way the degradation is silent by design — check `tools_called`
before concluding a tool ran.

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
(`src/pipeline.py:_reasoning_block`). With the defaults above: analyze
N=4 (8 total calls = 4 steps × 2 tools), generate N=3 (3 × code),
evaluate N=3 (3 × shannon), retry N=2 (4 total = 2 × 2). The counts
match the strategy's `tools` lists above, multiplied by the number of
thoughts in the phase. Three legitimate reasons for a lower count
(`src/reasoning/client.py:319-420`), all distinguishable from the same
record plus the WARN lines around it:

- the model ended the trace early (`next_needed=false`): fewer `steps`,
  empty `aborted_reason`;
- thought generation failed: `aborted_reason="thought generation failed
  at step N: …"` plus a `"Thought generation failed; trace ends here"`
  WARNING;
- a single tool call failed: the loop continues and the step is still
  recorded (empty `tool_response`), so only `tools_called` drops — the
  tell is a `"Reasoning tool call failed; continuing without its
  feedback"` WARNING.

If `tools_called` ever shows a tool that isn't in the strategy's
`tools` list (or omits one that is), the configuration is out of sync.

Traces for `analyze` and `generate` are cached by content key
(`_CACHEABLE_PHASES`, `src/reasoning/client.py:75`): a repeated phase
call with identical inputs logs the same record with `cached: true`,
carrying the *originating* run's counts while making zero new MCP calls
and zero new thought completions (verified: a second identical
`generate` → `cached=True`, total subprocess spawns still 3, LLM calls
still 3). Check `cached` before attributing counts to fresh spawns —
and a phase that skips the block entirely (see above) logs no record at
all.