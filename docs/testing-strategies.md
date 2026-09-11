# Testing Strategies — architecture-pattern-mcp (The Layered Testing Program)

## 1. Problem Statement: Testing Code Nobody Fully Reads

The server's code is LLM-generated and ~13,400 raw lines (~10,200 excluding
blanks and comments; measured 2026-09-09 — the earlier "~8,800 LOC" figure is
superseded); no human reads all of it.
Testing carries a double burden here:

1. **The code is untrusted** — and fails in *characteristic, statistically
   documented* ways:

   | Failure mode | Evidence |
   |---|---|
   | 45% of AI-generated code samples fail OWASP security checks (150+ models) | Veracode study |
   | 19.7% of recommended packages don't exist → **slopsquatting** (attackers register hallucinated names) | USENIX Security '25 |
   | ~1.7× issue rate in AI-co-authored PRs | CodeRabbit dataset |
   | 90% adoption, 30% distrust — engineers ship code they don't fully trust | DORA 2025 |
   | > 25% of new code at Google is AI-generated, "reviewed and accepted by engineers" | Google |

2. **The tests are untrusted too.** The same-model circularity finding: up to
   **68% of AI-generated test suites validated bugs instead of catching
   them** — the same blind spots shape code and tests when one model writes
   both. A green suite therefore proves less than it appears to; the testing
   program must include oracles *against the tests themselves*.

### 1.1 Design principles for this program

| # | Principle | Enforcement in this repo |
|---|---|---|
| P1 | **Decorrelated oracles.** Layers are chosen so their blind spots do not overlap; residuals multiply instead of add (`formal_verification.md` §6.1) | The §2 stack: type system / sampling / mutation / interleaving / proof are orthogonal bug-class owners |
| P2 | **Vacuity control everywhere.** Every oracle must be able to fail; an oracle that cannot fail is deleted | Mutant-kill rules: `.fizz` assertions must each kill ≥ 1 garden mutant; Hypothesis oracles face the same mutmut audit |
| P3 | **One definition of green.** Hooks, agent loops, and CI execute literally the same `make` targets | All layers delegate to Make targets (§5); no duplicated commands |
| P4 | **The agent is untrusted.** AGENTS.md rules are advisory for an LLM; enforcement is mechanical | CI re-runs the full gate set on every push regardless of what the agent did locally |
| P5 | **Honest claims.** Every layer states what it certifies *and its boundary* — sampled ≠ exhaustive ≠ ∀-inputs; bounded model ≠ unbounded theorem | Per-layer claim wording in §2 and the trust stories of both plans (§9 each) |
| P6 | **Cheapest-first sequencing.** A bug should be caught by the cheapest layer able to catch it | §5 duty matrix orders checks by cost; expensive layers are path-filtered |

## 2. The Stack at a Glance

The layers below, ordered cheapest-first (the first-amendment additions L1b
and L9 slot into the ordering; the count sentence was dropped — it went stale
once and would again). "Gate" = where enforcement is mandatory.

| # | Layer | Tool(s) | Bug class it owns | Cost | Gate | Primary evidence |
|---|---|---|---|---|---|---|
| L0 | Static analysis | ruff, mypy `--strict` (zuban), + async linters (flake8-async, blockpath) | style, type errors, blocking-calls-in-async, check-then-act smells | ms–s | pre-commit + CI | blockpath: 51% of blocking calls sit at call depth ≥ 2, invisible to per-file linters; 98.2% precision |
| L1 | Unit testing | pytest (`tests/unit/`) | chosen-input functional behaviour, regressions | s | pre-push + CI | 85–90% coverage target for AI code (vs 70–80% human) |
| L1b | MCP boundary fuzzing | Hypothesis (schema-derived + malformed payload strategies) | **boundary-shape robustness**: malformed nested payloads, coercion edges, oversized inputs, wrong-arity calls — no unhandled exception escapes, structured errors only, no traceback leaks | s–min | CI (advisory Phase 0 → blocking Phase 1) | in-repo (§3.2a); counters "schema validation = boundary robustness" trust-by-proxy |
| L2 | Property-based testing | Hypothesis (+ `hypothesis[crosshair]`) | input-space edge cases: shape, length, Unicode, boundaries | s–min | CI | Anthropic agentic PBT: real numpy/scipy/pandas bugs, 86% of top-priority reports valid |
| L3 | Mutation testing | mutmut + planted-bug gardens (Python garden, `.fizz` garden) | **tests-the-tests**: tautological tests, vacuous assertions | min–h | manual/nightly | crucible: LLM test suites 65% → 99% mutation score via tester/critic loop; 68% circularity |
| L4 | Model checking | FizzBee — exhaustive + seeded simulation (`.fizz` specs) | **all interleavings up to bounds**: races, crash windows, deadlocks, guard gaps; liveness under fairness | s–min | pre-push (path-filtered) + CI | SlateDB GC-boundary bug; Shopify weekend pilot |
| L5 | Deductive verification | — (*retired 2026-09*) | ∀-inputs decision-logic properties, now pinned by the L1/L2 oracles (`tests/unit/`, `tests/verification/test_normalization_idempotence.py`) | — | — | — |
| L6 | Deterministic simulation | simloom / frontrun (Phase-0 head-to-head) | real asyncio schedules of the *real implementation*, replayable seeds | h (bounded search) | Phase-0 experiment | FoundationDB/TigerBeetle school; simloom `systematic=True` = bounded proof on unmodified asyncio |
| L7 | Dependency & supply chain | deptry, `uv.lock` pinning, (candidate: pip-audit) | hallucinated/unused/vulnerable deps, slopsquatting | s | pre-push + CI | USENIX '25: 19.7% hallucinated packages |
| L8 | Spec & doc-level testing | NL-Doc cross-consistency gate, property-ID ledger checks, SpecPylot-style spec inference | intent drift: code ≠ docstring ≠ contract ≠ model | min | advisory → blocking per plan | VLP: intermediate-artifact validation 84% vs 40% direct review; Clover six-way consistency |
| L9 | LLM-output contract corpus | in-repo `tests/eval/` corpus + structural invariant assertions (run under `ARCH_BENCH_LLM`) | **structural well-formedness of LLM output** (the T1.5 slice): cited pattern names exist, component/event reference closure, producer+consumer pairs, score ranges, section completeness; prompt/model drift detection | min (LLM API) | advisory drift gate on prompt/model changes | VLP intent-layer evidence; owned by §3.9a — never judges design quality (T2) |
| L10 | Human review + canaries | PR review on critical paths; post-merge canaries; nightly TCB canaries | intent, design quality (T2), tool regressions | h | PR-required for critical paths | DORA 2025; AxDafny lesson: verified ≠ performant |

Explicitly **out of scope for any layer**: semantic quality of LLM output
(T2) — the architecture designs themselves are judged by evaluation rubrics
and human review, never by a theorem or a test. That boundary is the core
claim of `formal_verification.md` and is repeated here because testing
programs fail most often by silent scope creep. (L9 sits deliberately close
to this boundary and is worded to stay on the T1 side: it certifies
*well-formedness and internal consistency* of output, never whether the
design is *good* — see §3.9a.)

## 3. Layer Details

### 3.1 L0 — Static analysis: the free layer

Existing: ruff + mypy `--strict` (AGENTS.md gates; zuban LSP in the editor).
This is the one layer with zero runtime cost and (for its fragment) sound
verdicts — it is also a *prerequisite* for the mutmut layer (mutmut uses it
to filter mutants).

**Addition (async linters — restated here because it is a testing
layer, not a verification layer):** async-aware linters —
[flake8-async](https://flake8-async.readthedocs.io/) (blocking calls in async
functions, sync primitives in async context, missing awaits) and
[blockpath](https://pypi.org/project/blockpath/) (cross-module call-graph
reachability for blocking calls). Benchmark rationale: 51% of blocking calls
in surveyed repositories sit at depth ≥ 2 where per-file linters are blind
(ruff ASYNC flagged 0 of 81 such sites), at 98.2% measured precision. Wired
as `make verify-async-lint`; advisory through Phase 0, blocking from Phase 1.
The `jobs.py` check-then-act race is exactly this layer's bug class — it
should have been caught *before* any runtime oracle was written.

### 3.2 L1 — Unit testing discipline for AI-generated code

`tests/unit/` remains the **behavioural oracle** for every modification class
in both verification programs (the no-runtime-change rule is defined *as*
"unit suite stays green"). Discipline points specific to AI code:

- **Coverage target 85–90%** (industry guidance for AI-generated code vs
  70–80% human) — but coverage is a *lagging* indicator, never a gate: it
  measures execution, not assertion quality. The assertion-quality audit is
  L3's job.
- **Test-first sequencing against tautologies:** for LLM-authored features,
  the review step checks that each new test could plausibly fail (the
  "would this test catch an obviously broken implementation?" question).
  Mechanically: any test that survives all L3 mutants of its own module is
  flagged.
- **Determinism:** tests pin seeds, freeze time, and use in-memory stores;
  asyncio tests use explicit event-loop fixtures so failures replay.
- **The unit suite is the oracle for refactors.** Module splits, merges,
  guarded transitions — all land with the unit suite green
  *before* any verification artifact claims anything about the new shape.
- **Secret canary (first September 2026 amendment).** A unit/integration test
  sets a distinctive fake API key, drives a design call through a mock LLM
  transport that captures every outbound payload, and asserts — together with
  a `caplog` capture — that the key value never appears outside the
  configuration boundary. **Extended by E4 (second September 2026
  amendment):** the canary additionally asserts the key never appears in
  *persisted* job state — the `jobs.result`/`jobs.error` columns and the raw
  DB file bytes — closing the leak path a prompt/log-only version misses (a
  failed or cancelled job persists its `error` text to SQLite, and the DB
  file outlives the process). This buys the practical assurance that Tier E's
  `--sif` proof targets (secrets never reach prompts/log sinks) at roughly 1%
  of its cost, from day one; the `--sif` phase proceeds only where the canary
  or review demonstrates residual risk the canary cannot cover. Delivered as
  Week-0 task W0-3 ([`week-0-task-breakdown.md`](week-0-task-breakdown.md)).

### 3.2a L1b — MCP boundary fuzzing: the tool-call surface (first September 2026 amendment)

T1's promise is "fails on **no** input" — but until this layer existed, that
promise was only exercised for *single string fields* (Tier A totality) and
*schema mirroring* (Tier D). The server's actual external attack surface is
the **MCP tool-call boundary**: arbitrary JSON-RPC arguments arriving from any
client, flowing JSON-RPC → FastMCP → Pydantic → handler. No existing layer
owns the *composition* of transport framing with schema validation — the
decorrelation check (§4.1) passes where the single-field layers do not.

**Mechanism.** Hypothesis strategies derived from the FastMCP tool schemas,
plus handcrafted malformed-payload generators: valid inputs at boundaries;
wrong types at every nesting level; oversized and deeply nested structures;
missing/extra/duplicate keys; invalid enum values; wrong-arity calls; payload
shape permutations. Tools are invoked in-process (no transport needed).

**Assertions (the layer's claim template, §P5 wording):** for *every*
generated payload, (a) no unhandled exception escapes the tool invocation;
(b) every error response matches the defined structured error shape; (c) no
traceback or internal-path text appears in any response. A violation is a
T1 bug of exactly the class the trust story claims cannot happen.

**Gate:** CI, collected by `make verify-hypothesis-oracles` (same target
family as L2 — no new Make target). Advisory through Phase 0 (findings tune
the payload generators), blocking from Phase 1 under the standard §4.4
lifecycle. Cost: days to stand up; seconds per CI run. L1 duty: any change to
tool signatures or schemas updates the payload generators in the same PR
(§5 duty matrix).

### 3.3 L2 — Property-based testing (Hypothesis)

PBT is the sampling layer that decorrelates from unit tests: instead of
chosen inputs, generated inputs; instead of example assertions, *properties*.
Evidence: Anthropic's agentic PBT study — LLM-inferred Hypothesis properties
found real numpy/scipy/pandas bugs, with 56% of reports valid and 86% of
top-priority ones; property inference is viable exactly when
counterexample-refined.

**In this repo (locked decision):** every proven
or modeled property is re-stated as an executable Hypothesis test under
`tests/verification/`, keyed by the shared property IDs (`J-1`–`J-4`, `P-1`,
`FC-*`/`FP-*` with filled oracle columns in
`verify/fizz/README.md`). Rationale: the model could be vacuous; the
test checks *observed behaviour*; together they pin both directions (P1).
Direction of the implication matters and is stated per property: the
Hypothesis oracle *samples* what the model *exhaustively checks up to
bounds*.

Backends: `hypothesis[crosshair]` adds a symbolic backend to the same
properties (CrossHair as the "weak but useful peer" — never treated as a
proof; its bounded-search blind spots are documented). Run gate:
`make verify-hypothesis-oracles` — which also collects the trace-replay
tests of the FizzBee program (§3.4 there), making one target the home of
"executable oracles".

**Reasoning-client oracle (E5, second September 2026 amendment).** The LLM
transport boundary (`src/reasoning/client.py`: LiteLLM + httpx timeouts,
retries, error mapping) was previously owned by no layer — unverified and
unmodeled (not a `.fizz` target). A Phase-0 Hypothesis
oracle closes the gap cheaply: simulated transport delays/timeouts/failures
must produce a structured `ToolError`/`LLMError` mapping, never a hang, and
retry counts stay within the configured bound (`timeout ⇒ structured error,
bounded retries`). Decorrelated from the unit suite: generated schedules of
failure injection instead of chosen cases. Runs under
`make verify-hypothesis-oracles`; added to the §5 duty matrix for
`src/reasoning/` changes.

### 3.4 L3 — Mutation testing: who tests the tests?

The layer that directly attacks the 68% circularity finding. Two mechanisms:

1. **mutmut over Tier A/B/C modules + `tests/verification/`**
   (`make mutation-tests`, testing-strategies §5.2): audits the *Python* oracles.
   Synergy: mutmut's mypy-based mutant filtering raises mutant quality in a
   `--strict` codebase. Caveat (mutmut's own docs): the type filter can hide
   valid mutants — filter survivors are a *hint*, never a verdict.
2. **Planted-bug gardens as the vacuity authority** (both plans): hand-planted
   mutants with expected-kill annotations — the Python garden
   (≥ 20 mutants, four classes: off-by-one, None-deref, unbounded loop,
   shape/KeyError) audits the decision logic; the FizzBee garden (≥ 15
   mutants: guard drop, transition swap, assertion weaken, bound overflow)
   audits model assertions. Rule: every `.fizz` assertion must kill ≥ 1
   garden mutant or carry a `# spec-explains:` justification; per-phase prune
   passes delete the dead weight (the DARe 88%-removable finding, applied
   twice).

Evidence for the layer: crucible (tester/critic LLM loop over mutmut) raised
AI-suite mutation scores 65% → 99%; Nightjar's pipeline found 74 bugs in 34
packages with zero false positives using mutation as one stage. Optional
later: a crucible-style loop over the survivor lists.

**Garden-canary rule (TCB guard, both plans §6.3/§6.4):** nightly re-runs of
the gardens against pinned tool versions; a mutant that stops being killed
after a dependency bump blocks the bump until triaged.

### 3.5 L4 — Model checking (FizzBee): exhaustive over schedules

Owned by [`fizzbee-verification-plan.md`](fizzbee-verification-plan.md);
summarized here because the *testing strategy* matters at stack level:

- **Exhaustive mode** (`fizz <spec>`, concurrency ≤ 2, bounded): the gate.
  A green run means *no interleaving up to the stated bounds* violates the
  assertions — evidence no sampling layer can produce. Fault injection
  (crash at yield points, message loss, partition) is implicit.
- **Seeded simulation** (`fizz -x --seed S --parallel W`, nightly): the
  sampling layer for schedules — 10 published anchor seeds + 990 random,
  concurrency 3, relaxed bounds. Violations replay deterministically and
  graduate into trace-replay tests. Simulation finds are *leads*, not gates —
  but untriaged real finds block the nightly job.
- **Anti-PBT-confusion rule:** exhaustive checking is not "fuzzing that
  passed". The claim it licenses is bounded-universal (§P5); simulation alone
  would license only "not found in N runs". Both are kept because they sit at
  different points of the budget/concurrency curve (FizzBee plan §5.6).

### 3.6 L5 — Deductive verification: retired (2026-09)

The L5 layer (deductive verification of the decision modules with
Requires/Ensures/Invariant contracts) was removed in September 2026.  The
∀-input decision properties it certified are now pinned by the L1 behavioral
oracles and the L2 Hypothesis oracle (`tests/unit/`,
`tests/verification/test_normalization_idempotence.py`, N-1..N-4) — see
`docs/verification.md` L5 for the removal summary and the property-by-property
hand-off table.

### 3.7 L6 — Deterministic simulation testing (DST): the real implementation's schedules

The third exploration cell (`formal_verification.md` §2.7): seeded
schedulers, virtual clocks, and in-memory fault injection over the *actual*
asyncio code — no model, no twin, no drift. Status in this repo: a **Phase-0
head-to-head sub-experiment** (simloom
`systematic=True` vs frontrun DPOR on the real `jobs.py`, explicit acceptance
numbers: ≥ 2 of `J-1`–`J-4` **including ≥ 1 of the discriminating pair
`J-1`/`J-2`** within bounded exploration — E1, second September 2026
amendment, so the near-trivial `J-3`/`J-4` cannot carry the criterion). This document's
position: DST is adopted only through that experiment's outcome; it is
recorded as its own stack layer so the decision (and its rejection criteria)
survive in one place. Field caveat from SlateDB's DST report: simulation
harnesses drift toward false positives as configuration space grows —
constrain exploration to meaningful states, and treat "zero bugs since
inception" as a harness-smell, not a success.

### 3.8 L7 — Dependency and supply-chain testing

AI code hallucinates dependencies (19.7% of recommended packages in the
USENIX '25 study — and attackers now register those names: slopsquatting).
Current gates: `deptry` (`make depcheck`), fully pinned `uv.lock`. Additions,
in priority order: (1) an import-inventory diff in review for any new
third-party import (AGENTS.md already requires typed-lib/stub checks — the
diff makes it mechanical); (2) a vulnerability scanner (pip-audit or
equivalent) as a pre-push/CI advisory, promotable like the other advisory
layers; (3) a repository allowlist for new sources — the slopsquatting
defence is structural (new package names need a human decision), not
scan-based.

### 3.9 L8 — Testing the specs and docs (intent layer)

The newest layer, and the one aimed at the failure mode *above* the code:
intent drift between prompt, docstring, contract, model, and implementation.

- **NL-Doc cross-consistency gate** (`make verify-cross-consistency`,
  formal_verification.md §3.1 VLP entry): a *second* LLM summarizes each
  decision-module function; summary
  is diffed against docstring + property documentation. Evidence: VLP
  (pass@1 28.7–73.2% → 65.4–93.5% via validated intermediate artifacts) and
  Fakhoury et al. (validating an intermediate artifact beats direct code
  review 84% vs 40%). Advisory in Phases 0–1, promotable at > 10% divergence.
  **Checker identity pinned (E3, second September 2026 amendment):** each run
  records the checker model's identity and version in the property-ID ledger;
  the promotion trigger is scored against a *named* model, and a silently
  downgraded checker is a gate-avoidance finding — the mechanical counter
  to a weak second model inflating a clean score.
- **Property-ID ledger checks** (`make verify-ledger`, FizzBee plan §5.3):
  mechanical diff of the assertion/oracle/conformance mapping — the
  drift gate for the model layer.
- **Spec-inference as a bootstrap** (SpecPylot-style):
  LLM-proposed properties validated by CrossHair counterexamples, compared
  against hand-written sets — with the documented rejection path when bounded
  search cannot refute false positives.
- **Clover/airtight-ai cross-consistency** as the packaged form of the same
  idea (six-way intent/spec/code checks across *different* models) — the
  mechanical answer to same-model circularity at the intent layer.

### 3.9a L9 — LLM-output contract corpus: the mechanizable T1.5 slice (first September 2026 amendment)

The T1/T2 split is binary, but between "machinery fails on no input" (T1)
and "the design is good" (T2, unmechanizable) sits a third, genuinely
mechanical class: **deterministic structural invariants over LLM output**.
A generated design is either well-formed and internally consistent or it is
not — no semantic judgment required. No pre-existing layer owned this class:
L0–L6 test the wrapper, L8 tests intent drift on *annotated* code, and T2
review only samples the output by reading.

**Mechanism.** A recorded corpus under `tests/eval/` of
`(requirements, domain)` → expected structural profile, covering the pattern
catalogue's major domains. Each corpus entry runs through the real pipeline
(opt-in via the existing `ARCH_BENCH_LLM` marker — never in default CI) and
the output is asserted against structural invariants:

- every cited pattern name exists in the catalogue;
- every component reference resolves (no dangling dependencies);
- every event contract names both a producer and a consumer;
- every API-contract endpoint referenced by a component is defined;
- score fields fall within their declared ranges;
- required sections/fields of `ArchitectureDesign` are present and non-empty.

**Purpose: drift detection.** The invariants are regression oracles for the
*product*: a prompt edit, model swap, or pipeline change that silently drops
section completeness or breaks reference closure fails the corpus. The
tracked structural pass-rate (advisory, recorded per run) is the drift signal;
structural failures block the triggering change until triaged (prompt bug vs.
corpus staleness). Cross-LLM advisory scoring over the same corpus can be
layered later without changing the invariant set.

**The boundary sentence (part of the layer's claim template).** This layer
certifies **well-formedness and internal consistency** — never whether the
design is *good*. It is the cheap mechanical precursor to the FizzBee
`design_meta.fizz` experiment (FizzBee plan §3.6, F3), not a substitute for
T2 rubrics or human review. Cost: minutes per run (LLM API), on prompt/model
changes and on demand; baseline recorded at Phase 0 (§6).

### 3.10 L10 — Human review and canaries

Humans remain the oracle for T2 (is the design good?) and for the judgment
calls the mechanical layers cannot make: vacuity triage, bound justification,
fairness assumptions, readability budgets, No-Go decisions. Programmed
elements: required review for critical paths (`jobs.py` transitions,
`pipeline.py` control flow, any `verify/` artifact that
changes a property claim), post-merge canaries for the decision-module paths
(coarse benchmark smoke, formal_verification.md §4.5 — proofs guarantee
functional correctness, not performance), and the nightly TCB canaries (L3
gardens against pinned verifier versions).

## 4. Cross-Cutting Principles (applied, not aspirational)

1. **Decorrelation check per new layer.** Before adopting a tool, name the
   bug class it owns that no existing layer owns (the "discriminating
   dimension" of a Go/No-Go decision). A layer without a unique class is
   cost without margin.
2. **Vacuity is the default failure.** Oracles accrete toward tautology;
   every layer here has a mechanical counter (gardens, prune passes, ledger
   diffs, could-fail reviews).
3. **One green.** All layers are `make` targets; hooks and CI delegate; no
   layer is defined twice.
4. **Advisory→blocking is a promotion, not a launch state.** New layers start
   advisory with a stated promotion trigger and date (async linters, ledger
   check, cross-consistency, pip-audit all follow this lifecycle).
5. **Claims are bounded and worded.** Each layer's §2 row is also its claim
   template; documents that overclaim (unbounded model claims, "verified"
   meaning "tested") are defects.

## 5. CI Wiring and Duty Matrix

| Stage | Checks | Cost | Scope |
|---|---|---|---|
| pre-commit (local) | ruff check/format, mypy `--strict` hook | seconds | changed files |
| pre-push (local) | vulture, deptry, `pytest tests/unit/`, `verify-fizz` (path-filtered) | ~1–5 min | whole project |
| CI (every push/PR) | everything above, unconditional + Hypothesis oracles/trace-replay, boundary fuzzing (L1b), ledger check, async linters (from Phase 1), cross-consistency (advisory) | minutes | server-side, authoritative |
| nightly | both gardens (TCB canary), FizzBee seeded simulation, mutmut (optional), pip-audit (when adopted), performance smoke | ~30 min | scheduled |
| manual | `mutation-tests`, garden authoring, spec-inference experiments, L9 output-contract corpus (on prompt/model changes) | on demand | per task |

**Duty matrix — what triggers what (agent- and human-facing):**

| What changed | Layers due |
|---|---|
| `src/text_validation.py`, `src/design_normalization.py` (decision modules) | L1 unit + L2 Hypothesis oracle update + ledger row |
| `verify/fizz/*.fizz` | full FizzBee loop + garden re-run + ledger row |
| `src/tools/jobs.py`, `src/pipeline.py` control flow | matching `.fizz` spec in the same PR (AGENTS.md rule); DST experiment objects when adopted |
| tool signature or schema (`src/tools/*.py`, `src/schemas/*`) | L1b payload-generator update + boundary-fuzzing run (first amendment) |
| prompt or model config (`src/prompts/`, `src/reasoning/`) | L9 output-contract corpus re-run — advisory drift gate (first amendment); **`src/reasoning/client.py` also triggers the L2 timeout/retry oracle (E5, second amendment)** |
| any other `src/` file | standard gates (L0/L1/L7) — nothing extra |
| `tests/**` | standard gates + mutmut spot-check on the touched module |
| dependency bumps | deptry, lock diff review, nightly gardens re-run before merge |

## 6. Rollout Alignment

| Program phase | Testing layers activated |
|---|---|
| Today | L0 (ruff, mypy), L1 (unit), L7 (deptry, pinning) |
| **Week 0** (first amendment — before Phase 0) | **guarded-transition bug fix in `src/tools/jobs.py` + unit tests** (the fix-before-proof sequencing correction: `J-1`/`J-2` become true of the implementation before any `.fizz` model or DST experiment claims them — formal_verification.md §4.5). **Second amendment (E6/E4):** the same Week-0 window adds the constructor-injectable `JobsStore` lock (E6) and the E4-extended secret canary (W0-3) — the full task list with acceptance criteria is [`week-0-task-breakdown.md`](week-0-task-breakdown.md) |
| Phase 0 (both plans, weeks 1–2) | L2 (Hypothesis oracles), L3 (gardens + Go/No-Go), L4 pilot (FizzBee F0, in-spec A/B flip), L1b boundary fuzzing advisory, L9 corpus baseline, async linters advisory, L6 experiment, L8 advisory (ledger, cross-consistency) |
| Phases F1–F2 (FizzBee) | L4 gate (`verify-fizz` blocking), L1b blocking (from Phase 1), L8 ledger blocking, async linters blocking |
| Continuous | nightly set complete (gardens, simulation, canaries, smoke), L10 cadence, L9 corpus on prompt/model changes |

The falsifiable gate remains the Phase-0 Go/No-Go (bug garden,
discriminating dimension, numeric thresholds) plus the FizzBee F0 reproduction
experiment — both programs are *measured* before they are trusted, and this
stack document inherits their numbers rather than inventing new ones. **The
two gates are independent decision units (E2, second September 2026
amendment):** a No-Go in one program does not rescope the other; each
program's descope path leaves the other's ledgers, oracles, and CI targets
intact (FizzBee plan §6.3).

## 7. Anti-Patterns and Risks

1. **Coverage vanity** — 90% coverage with tautological assertions; countered
   by L3 (mutation) and the could-fail review.
2. **Gate inflation** — promoting every layer to blocking immediately;
   countered by the advisory→blocking lifecycle (P4 of §4) with explicit
   triggers.
3. **Flaky oracles** — time-, network-, or scheduler-dependent tests erode
   trust in the whole stack; determinism rules (§3.2) and seeded everything.
4. **Tool-TCB regressions** — verifier/tester upgrades silently weaken
   oracles; countered by pinned versions + nightly garden canaries.
5. **Same-model circularity re-entering through the side door** — the agent
   writes code, tests, *and* the spec review; countered by the cross-LLM
   gates (L8) and the untrusted-agent CI rule (P4).
6. **Stack sprawl** — nine layers is a maintenance surface; every layer has a
   named Make target, an owner (this document + the two program plans), and a
   descope path (any layer can be demoted with a recorded decision, as the
   DST rejection path shows).
7. **Boundary trust by proxy** (first amendment) — assuming Pydantic schema
   validation equals boundary robustness. A schema constrains types; it does
   not constrain the *composition* of transport framing with validation
   (nested-shape misuse, oversized payloads, arity errors). Countered by L1b
   fuzzing end-to-end (§3.2a) and anti-pattern-1's decorrelation check, which
   is how L1b earned its slot.

## 8. Framework Catalog

One profile per framework named in this document — *the tool*, not the layer
(layer logic lives in §3). Uniform template: documentation links → maturity
note → pros/cons → usage pattern in this repo → adoption in the wild →
AI-trust contribution (which LLM failure-mode class it counters, with
evidence). Maturity notes are load-bearing: v0.x / single-maintainer entries
are exactly why the advisory→blocking lifecycle (§4.4) and the pinned-tool
nightly canaries (§7.4) exist.

| Layer | § | Frameworks |
|---|---|---|
| L0 | 8.1–8.4 | ruff, mypy, flake8-async, blockpath |
| L1 | 8.5 | pytest (+ pytest-asyncio) |
| L1b | 8.6 | Hypothesis (schema-derived boundary strategies) |
| L2 | 8.6–8.7 | Hypothesis, CrossHair |
| L3 | 8.8–8.9 | mutmut, crucible |
| L4 | 8.10 | FizzBee |
| L5 | — | (retired — see §3.6) |
| L6 | 8.12–8.13 | simloom, frontrun |
| L7 | 8.14–8.16 | deptry, pip-audit, uv |
| L8 | 8.17 | airtight-ai (Clover lineage) |
| L9 | — | in-repo `tests/eval/` corpus harness (`ARCH_BENCH_LLM`; no external framework) |
| wiring | 8.18–8.19 | vulture, pre-commit |

### 8.1 ruff — linting and formatting (L0)

Docs: <https://docs.astral.sh/ruff/> · Repo: <https://github.com/astral-sh/ruff>

| Pros | Cons |
|---|---|
| 10–100× faster than flake8/pylint in published benchmarks; 900+ rules replacing flake8 + isort + Black + pyupgrade in one tool; safe autofixes; single `[tool.ruff]` config; official pre-commit hook and GitHub Action | Not a type checker — no type-level or cross-module reasoning; shallower than Pylint's semantic checks (return-type consistency, None paths); per-file AST analysis only |

**Usage in this repo:** `make lint` / `make lint-fix`; config in
`pyproject.toml` (`[tool.ruff]`, 120 cols, py312, extended rule set);
mandatory gate per AGENTS.md.

**In the wild:** FastAPI, pandas, SciPy, Hugging Face Transformers, Apache
Airflow, Zulip, Dagster, Bokeh (ruff README:
<https://github.com/astral-sh/ruff>); third-party benchmark:
<https://pynions.com/ruff-python>.

**AI-trust contribution:** F821 (undefined names), F401 (unused imports) and
unreachable-code rules catch the easy end of agent bugs mechanically and in
milliseconds. Its *boundary* — hallucinated attributes, wrong argument
types — is owned by mypy (§8.2): a study of LLM library hallucinations
measured type checkers detecting ~70–77% of hallucinated-kwargs/attribute
bugs (<https://arxiv.org/html/2604.07755>).

### 8.2 mypy — static typing (L0)

Docs: <https://mypy.readthedocs.io/en/stable/> · Repo: <https://github.com/python/mypy>

| Pros | Cons |
|---|---|
| Reference PEP-484 checker with the widest plugin ecosystem; catches wrong argument types, None misuse, missing returns; enables confident large refactors; `--strict` maximizes coverage of the fragment | Annotation burden is real (Instagram: ~8 months to 50% coverage of 1M LOC, <https://eightfold.ai/engineering-blog/static-type-checking-large-scale-python-codebase/>); slower than Rust-based rivals; untyped deps degrade to `Any`; plugins unsupported by zuban — forbidden here (AGENTS.md) |

**Usage in this repo:** `make static-typing` (`uv run mypy --strict`,
`files = ["src"]`); AGENTS.md makes strict typing mandatory; zuban LSP must
show zero diagnostics in touched files (known accepted divergence recorded
in AGENTS.md).

**In the wild:** Spring (strict, full coverage,
<https://notes.crmarsh.com/using-mypy-in-production-at-spring>); Sentry
(strong-typing default,
<https://github.com/getsentry/sentry/commit/5cfc9f1fcbaab1f8e958a52d687e50c3ac0089ac>);
SignalWire (`--strict`).

**AI-trust contribution:** the cheapest effective filter against
hallucinated APIs (~70–77% detection, arXiv 2604.07755 above), and the
prerequisite substrate for the higher layer mutmut's mutant filtering
(§8.8).

### 8.3 flake8-async — async-safety linting (L0)

Docs: <https://flake8-async.readthedocs.io/> · Repo: <https://github.com/python-trio/flake8-async> (python-trio org, actively released)

| Pros | Cons |
|---|---|
| The most complete ASYNC rule set (blocking sync calls, cancellation/checkpoint semantics, timeout misuse) for trio/anyio/asyncio; some autofixes; user-configurable blocking-call patterns | Per-file analysis only — cannot follow cross-module call chains (that gap is §8.4's job); opinionated/noisy; flake8≥6 config quirks for 4-letter codes |

**Usage in this repo:** planned `make verify-async-lint`;
advisory Phase 0 → blocking Phase 1 (§3.1).

**In the wild:** its rule set is partially ported into ruff's ASYNC rules
(<https://docs.astral.sh/ruff/rules/blocking-path-method-in-async-function/>)
— both an endorsement and the reason ruff alone is insufficient here.

**AI-trust contribution:** LLMs mix sync and async idioms freely;
direct-call blocking detection is the cheapest owner of that bug class at
call depth 1.

### 8.4 blockpath — cross-module blocking-call analysis (L0)

Repo: <https://github.com/iraettae/blockpath> · PyPI: <https://pypi.org/project/blockpath/>

| Pros | Cons |
|---|---|
| Cross-module AST call-graph analysis (BFS passes): finds blocking calls 3–5 frames deep with full witness paths and fix hints; measured 98.2% precision; runtime recall verifier via `sys.monitoring` | **v0.1.0, single maintainer, no third-party adoption evidence**; slower than ruff; deliberately ignores callback-passed blocking calls; unproven at scale |

**Usage in this repo:** planned alongside flake8-async behind
`make verify-async-lint`; advisory-first with pinned version — the nightly
garden canary (§3.4) covers exactly this tool-TCB risk.

**In the wild:** none found beyond its own benchmarks — an honest adoption
gap the advisory→blocking lifecycle is designed to absorb.

**AI-trust contribution:** 51% of real blocking calls sit at depth ≥ 2 where
ruff flagged 0/81 — precisely where per-file linters (including the one the
agent runs locally) are blind; the `jobs.py` check-then-act class lived
behind helper chains.

### 8.5 pytest + pytest-asyncio — unit oracle (L1)

Docs: <https://docs.pytest.org/en/stable/how-to/fixtures.html> · <https://pytest-asyncio.readthedocs.io/en/stable/concepts.html>

| Pros | Cons |
|---|---|
| Fixture DI with scopes/autouse/yield-teardown; three parametrization levels; enormous plugin ecosystem; pytest-asyncio is the de-facto async runner; `asyncio_mode = "auto"` keeps annotations minimal | Loop-scope mismatch is the classic flakiness source (session fixture on function loop → "Event loop is closed", <https://qaskills.sh/blog/pytest-asyncio-event-loop-is-closed-fix>); async tests *silently pass* if the plugin/marker is missing; deprecated `event_loop` recipes still circulate |

**Usage in this repo:** `make unit-tests` (`pytest tests/unit/ -v`);
`asyncio_mode = "auto"` in pyproject; per-test tmp SQLite +
`JobsStore.reset_for_test()` (conftest) so jobs never bleed between tests;
perf/llm markers opt-in via `RUN_PERF`/`ARCH_BENCH_LLM`.

**In the wild:** the Python default — async-service testing guides
standardize on it (<https://dev.to/peytongreen_dev/testing-async-python-without-losing-your-mind-5344>,
<https://qaskills.sh/blog/pytest-asyncio-async-testing-guide>).

**AI-trust contribution:** the behavioural oracle that defines "no runtime
change" for every refactor in both verification programs; autouse config
mocks and tmp-path stores make green mean *reproducible*, not
"passed once".

### 8.6 Hypothesis — property-based testing (L2)

Docs: <https://hypothesis.readthedocs.io/en/latest/> (settings/profiles: <https://hypothesis.readthedocs.io/en/latest/settings.html>) · Repo: <https://github.com/HypothesisWorks/hypothesis>

| Pros | Cons |
|---|---|
| Shrinking reduces any failure to a minimal input; example database replays known failures first; built-in `ci` profile auto-activates under `CI` (derandomized, `deadline=None`, `print_blob`); `st.from_type` derives strategies from Pydantic models | Runtime cost at default 100 examples; `DeadlineExceeded` flakiness on noisy CI machines; heavy `filter`/`assume` starves generation; seed/database handling in CI must be explicit |

**Usage in this repo:** hand-written strategies already exist
(`tests/schemas/test_schemas.py`); L2 oracle home `tests/verification/`
keyed by shared property IDs (§3.3); gate
`make verify-hypothesis-oracles`.

**In the wild:** SymPy (novel bugs "after several million examples",
Hypothesis docs); Django (first-class integration); NumPy/SciPy/pandas
exercised by Anthropic's agentic PBT study
(<https://www.anthropic.com/research/property-based-testing>,
<https://arxiv.org/html/2510.09907v1>).

**AI-trust contribution:** decorrelates oracle from generator — LLM example
tests overfit chosen inputs; generated inputs explore boundaries. Evidence:
Anthropic agent study (56% of reports valid bugs, 86% of top-priority);
counter-evidence for skipping it: StarCoder solutions with Pass@10 ≈ 0.588
showed only 52% full PBT compliance — "unit tests alone may overestimate
correctness" (<https://vtechworks.lib.vt.edu/server/api/core/bitstreams/fb20964d-1ae5-4904-ae8f-1b60cdcf6764/content>).

### 8.7 CrossHair — symbolic execution peer (L2)

Repo: <https://github.com/pschanely/CrossHair> · Hypothesis backend: <https://github.com/pschanely/hypothesis-crosshair>

| Pros | Cons |
|---|---|
| Z3-driven path exploration — a *systematic* peer to random sampling; the most complete Python concolic implementation; drop-in via `@settings(backend="crosshair")` or a profile | Bounded search — never a proof; path explosion; historically weak on strings and floats; early-integration roughness |

**Usage in this repo:** `hypothesis[crosshair]`; same properties, second
backend (§3.3); refutes LLM-proposed specs in the SpecPylot-style bootstrap
(§3.9).

**In the wild:** no named adopters surfaced; presence is via the Hypothesis
backend API itself.

**AI-trust contribution:** a differently-blind sampler over the same
properties (P1): random search misses deep paths, symbolic search misses
wide value spaces. CrossHair findings are *hints* — never treated as proof
(§P5 wording rule).

### 8.8 mutmut — mutation testing (L3)

Docs: <https://mutmut.readthedocs.io/en/latest/> · Repo: <https://github.com/boxed/mutmut>

| Pros | Cons |
|---|---|
| Fork-based mutation schemata (parallel, fast); incremental re-runs cover only changed functions; optional mypy-based mutant filtering; interactive `browse` UI + HTML report; mature (~700+ downstream projects) | Runtime blowup (a 10 s suite → 43 min at 513 mutants, <https://nedbatchelder.com/blog/201903/mutmut>); equivalent mutants persist as false positives; the mypy filter can hide valid mutants — survivors are hints, not verdicts (§3.4); fork-only, no native Windows |

**Usage in this repo:** `make mutation-tests` over Tier A/B/C modules +
`tests/verification/` (§3.4); the standard affordability
pattern is incremental PR-scoped runs + nightly full sweeps — matches the
§5 wiring.

**In the wild:** coverage.py ecosystem dogfooding
(<https://nedbatchelder.com/blog/201903/mutmut>); tool comparison with
alternatives: <https://pytest-gremlins.readthedocs.io/en/latest/guide/comparison/>.

**AI-trust contribution:** the oracle-on-oracles audit. Quantified need:
DeepSeek-V3.1 detects only **36% of mutants** (SWE-Mutation,
<https://aclanthology.org/2026.findings-acl.1976/>) — AI suites look green
while most mutations survive. Mutation score is the mechanical answer to
the 68% circularity finding (§1).

### 8.9 crucible — LLM tester/critic mutation loop (L3, optional)

Repo: <https://github.com/Jott2121/crucible> · Paper: <https://arxiv.org/abs/2607.23002>

| Pros | Cons |
|---|---|
| Demo: mutation score 65% → 99% at constant 97% coverage; pre-registered causal estimate: critic rounds kill 78% [0.59, 0.94] of frozen-suite survivors; `$0` score mode; GitHub Action | Research-grade: single author, 4–5 subjects; LLM cost per harden; found a mutmut cache-staleness bug (silent 34-point flattering) — pin versions; equivalent mutants remain |

**Usage in this repo:** optional later stage over mutmut survivor lists
(§3.4); never a launch-blocking gate.

**In the wild:** self-dogfooded only (1,130 mutants,
<https://github.com/Jott2121/crucible/pull/13>).

**AI-trust contribution:** "no model ever grades model output" — the LLM
proposes test hardening, the mutation kill verdict *disposes* mechanically.
That acyclic property is exactly what same-model circularity demands
(<https://arxiv.org/abs/2607.23002>).

### 8.10 FizzBee — model checking (L4)

Docs: <https://fizzbee.io/> (design/testing guides) · Repo: <https://github.com/fizzbee-io/fizzbee>

| Pros | Cons |
|---|---|
| Exhaustive interleaving exploration up to stated bounds; implicit fault injection (crash at yield points, message loss, partitions); Python-like `.fizz` specs (low learning curve vs TLA+); safety + liveness (+ fairness) invariants; seeded, reproducible runs; model-based-testing adapters against real code | State-space explosion (8 nodes → 65,536 states in ~4 min); bounded ≠ proof — exhaustive claims weaken beyond the concurrency-2 non-atomic regime; error traces hard to read; model-vs-code drift (adapters mitigate, add glue) |

**Usage in this repo:** `verify/fizz/*.fizz`; `verify-fizz` gate (blocking
from F1); seeded nightly simulation (§3.5); owned by the FizzBee plan.

**In the wild:** Jack Vanlightly's independent evaluation
(<https://jack-vanlightly.com/blog/2024/12/6/to-be-atomic-or-non-atomic-that-is-the-question-fizzbee>);
SlateDB testimonial (found a real concurrency bug, fizzbee.io); weekend
pilot finding correctness bugs in a streaming platform (fizzbee.io).

**AI-trust contribution:** concurrency bugs (check-then-act, missing locks)
are characteristic LLM failure modes invisible to per-file review and to
sampling; "no interleaving up to bounds violates the assertions" is
evidence no other layer here can produce (§P5 wording).

### 8.11 Deductive verification — retired (2026-09)

The deductive-verification (Viper/Z3) profile formerly occupying this slot
was removed with the L5 layer in September 2026 — see `docs/verification.md`
L5 for the removal summary and the property-by-property hand-off to the
L1/L2 oracles.

### 8.12 simloom — deterministic simulation (L6)

PyPI: <https://pypi.org/project/simloom/> · Repo: <https://github.com/mandipadk/simloom>

| Pros | Cons |
|---|---|
| Runs *unmodified* asyncio code (real httpx/aiohttp in-sim) under a seeded scheduler + virtual clock; `systematic=True` = exhaustive delay-bounded exploration (a bounded proof); Elle-style serializability/linearizability checkers; pytest plugin; byte-exact seed replay | **Alpha, single author, pre-1.0 API**; harness-authoring cost (invariants + fault hooks must be written); no third-party adopters found |

**Usage in this repo:** Phase-0 DST head-to-head candidate (§3.7);
adoption only through that experiment's acceptance numbers.

**In the wild:** none surfaced — precedents are the DST school below (§8.13).

**AI-trust contribution:** exercises the *real implementation* — no model
drift, no twin divergence; replayable seeds make every failure
CI-reproducible.

### 8.13 frontrun — DPOR schedule exploration (L6)

Docs: <https://lucaswiman.github.io/frontrun/> · Repo: <https://github.com/lucaswiman/frontrun>

| Pros | Cons |
|---|---|
| DPOR (Rust/PyO3, vector clocks) explores every *meaningfully different* interleaving — no seed sampling needed; bytecode-level conflict detection with causal explanations; tri-state verdicts (certified/counterexample/inconclusive); virtual clock; cross-process SQL/Redis DPOR | Coarse `host:port` socket detection explodes the schedule space without refinement; C-extension state (NumPy) invisible; raw `call_later` stays wall-clock; repeated breaking API changes pre-1.0 |

**Usage in this repo:** the other Phase-0 DST candidate — the two tools
have orthogonal blind spots (delay-bounding vs partial-order reduction),
which is exactly why the head-to-head is run with numbers (§3.7).

**In the wild:** none surfaced; active through 2026. DST-school precedents:
FoundationDB (<https://apple.github.io/foundationdb/testing.html>),
TigerBeetle VOPR (<https://github.com/tigerbeetle/tigerbeetle/blob/main/docs/internals/vopr.md>,
<https://tigerbeetle.com/blog/2026-08-20-protocol-aware-dst/>).

**AI-trust contribution:** same as §8.12 — real-implementation schedules,
deterministically replayable; DPOR additionally gives a
certified-exhaustive claim over *meaningful* interleavings.

### 8.14 deptry — dependency hygiene (L7)

Docs: <https://deptry.com/> · Repo: <https://github.com/osprey-oss/deptry>

| Pros | Cons |
|---|---|
| Rust-powered AST scan for unused (DEP002), missing (DEP001) and transitive (DEP003) dependencies; PEP 621 / Poetry / PDM / uv support; ~8.8M downloads/month | Name→module mapping false positives (needs `package_module_name_map` — this repo has one); must run inside the project venv; group/exclusion config noise |

**Usage in this repo:** `make depcheck`; per-rule ignores for
transitively-provided imports (litellm/workflows/mcp) in pyproject — each
with a justification comment.

**In the wild:** broad OSS adoption by download volume
(<https://skillfed.io/packages/deptry>); no named companies surfaced.

**AI-trust contribution:** DEP001 is the direct mechanical detector of
hallucinated imports — first filter against the 19.7% slopsquatting
statistic (§3.8, USENIX '25 primary link in §9).

### 8.15 pip-audit — vulnerability scanning (L7, candidate)

Repo: <https://github.com/pypa/pip-audit> · Action: <https://github.com/pypa/gh-action-pip-audit>

| Pros | Cons |
|---|---|
| PyPA / Trail of Bits maintained; OSV + PyPI advisory DBs; PEP 751 `pylock.toml` support (`--locked`); official GitHub Action | Advisory latency — fresh typosquats/malware have *no advisories yet* (the allowlist remains the structural defense, §3.8); no reachability analysis; network-dependent |

**Usage in this repo:** candidate advisory at pre-push/CI (§3.8 priority 2),
promotable per the standard lifecycle.

**In the wild:** PyPA/Trail of Bits/Google-backed
(<https://cve.optibot.re/blog/pip-audit-safety-cli-python-security-2026>).

**AI-trust contribution:** covers the *second-order* supply-chain risk
(agent pins a known-vulnerable version of a real package); first-order
defense stays structural — import diff, allowlist, lockfile review.

### 8.16 uv — lockfile discipline (L7)

Docs: <https://docs.astral.sh/uv/> (concepts: <https://docs.astral.sh/uv/concepts/projects/layout/>)

| Pros | Cons |
|---|---|
| 10–100× faster than pip; universal cross-platform `uv.lock` (all OS/arch/Python markers); `uv sync --frozen` / `uv lock --check` guarantee CI resolves exactly the committed lock; preview OSV malware scan during sync | Fast-moving — lockfile schema churn across releases (pin uv itself in CI); single-vendor stewardship |

**Usage in this repo:** `make install` (`uv sync`); the fully pinned
`uv.lock` is an L7 gate; dependency bumps trigger the nightly garden
re-run *before* merge (§5 duty matrix) — that pairs the lock-diff review
with a tool-TCB regression check.

**In the wild:** `astral-sh/setup-uv` org workflows; modern-uv workflow
write-ups (<https://tenthirtyam.org/dispatches/2026/05/21/a-modern-python-workflow-with-astral-uv/>).

**AI-trust contribution:** the lock diff turns "agent added a dependency"
from an implicit side effect into an explicit, human-reviewed PR change —
slopsquatting defense in depth (CSA note:
<https://labs.cloudsecurityalliance.org/research/csa-research-note-slopsquatting-ai-supply-chain-20260419-csa/>).

### 8.17 airtight-ai — cross-LLM consistency (L8, Clover lineage)

PyPI: <https://pypi.org/project/airtight-ai/> · Repo: <https://github.com/chempotharun/airtight-ai/> · Research: Clover, <https://arxiv.org/abs/2310.17807> (<https://github.com/stanford-centaur/Clover>)

| Pros | Cons |
|---|---|
| Implements Clover's cross-consistency paradigm (intent/spec/code checks + reconstruction); verifier deliberately uses a *different* LLM than the generator; deterministic AST + property gates are mathematically sound | **v0.1.0, single author; the cross-LLM gate is planned for v0.2 — verify what ships before relying on it (§3.9 implies more than the package currently delivers)**; LLM gates add cost/latency/nondeterminism; Clover's docstring-equivalence checker "skews towards acceptance" |

**Usage in this repo:** L8 packaged form (§3.9); advisory only; the
NL-Doc cross-consistency gate (`make verify-cross-consistency`) is the
in-repo implementation of the same idea.

**In the wild:** Clover itself: 87% acceptance of correct programs,
**zero false positives** on adversarially incorrect ones; found 6 bugs in
human-written MBPP-DFY-50 (arXiv 2310.17807).

**AI-trust contribution:** a different-model checker does not share the
generator's blind spot — the mechanical counter to the 68% same-model
circularity finding at the *intent* layer, where every other layer is
blind.

### 8.18 vulture — dead-code detection (wiring)

Repo: <https://github.com/jendrikseipp/vulture>

| Pros | Cons |
|---|---|
| Fast AST scan with confidence scores (60–100%); `--min-confidence` tiers; `--sort-by-size` prioritizes cleanup; whitelist files preferred over noqa | False positives on framework-registered / dynamic code — needs `--ignore-decorators` + whitelist (this repo has both); dead code referenced *only by tests* resolves as "used" |

**Usage in this repo:** `make deadcode` (`--min-confidence 80`,
`--ignore-decorators` for `@step`, `@field_validator`, `@*.resource`,
`@*.prompt`; `whitelist.py`), scanning `src examples` — aligned with
AGENTS.md's quality gates.

**In the wild:** Django dead-code cleanup recipe
(<https://adamj.eu/tech/2023/07/12/django-clean-up-unused-code-vulture/>).

**AI-trust contribution:** LLM agents accumulate superseded variants and
orphaned helpers; unreferenced code is unreviewed maintenance and attack
surface. A deterministic floor beneath agent churn.

### 8.19 pre-commit — hook management (wiring)

Docs: <https://pre-commit.com/>

| Pros | Cons |
|---|---|
| Managed, pinned (`rev`) hook environments — no global pollution; polyglot (Python/Node/Go/Rust/Docker); committed config = identical hooks per clone; `pre-commit run --all-files` is the CI catch-all; `repo: local` hooks can delegate to any command | First-run env builds are slow (30–90 s; Airflow's config: 187 s / ~1.6 GB, <https://blog.qstars.nl/posts/pre-commit-vs-prek/>); hook-env drift vs local tooling; local hooks are honor-system — CI must re-run everything (P4) |

**Usage in this repo:** ruff + mypy hooks at pre-commit (changed files);
deeper gates delegated to Make targets (P3 one-green);
`pre-commit autoupdate` on schedule.

**In the wild:** CPython, Apache Airflow, FastAPI, ruff itself, Home
Assistant (qstars.nl above).

**AI-trust contribution:** mechanical enforcement that fires on every
commit even when the LLM "forgets" the rules — the *local* half of the
untrusted-agent control pair; unconditional CI (P4) is the other half.

## 9. References

**AI-code failure and testing evidence:**
- Veracode AI security study (45% OWASP failures): <https://www.you-source.com/blogs/test-ai-generated-code> (synthesis)
- Slopsquatting / hallucinated packages (USENIX Security '25): <https://bugbrain.tech/blog/testing-ai-generated-code>
- DORA 2025 (adoption vs distrust): <https://contextqa.com/blog/what-is-ai-generated-code-testing-checklist/>
- crucible (mutation testing of AI tests, 65% → 99%): <https://github.com/Jott2121/crucible>
- Augment guides (mutation testing & reviewing AI code; consensus stack): <https://www.augmentcode.com/guides/mutation-testing-ai-generated-code>, <https://www.augmentcode.com/guides/reviewing-ai-generated-code>
- Socratopia (PBT + mutation chapter): <https://www.socratopia.app/library/software-engineering-craft-en/chapter-6>

**Layer-specific primary sources:**
- Hypothesis: <https://hypothesis.readthedocs.io/en/latest/>; Anthropic PBT agent: <https://arxiv.org/abs/2510.09907>
- mutmut (incl. mypy-filter caveat): <https://mutmut.readthedocs.io/en/latest/>
- FizzBee (exhaustive + simulation): <https://fizzbee.io/>, [`fizzbee-verification-plan.md`](fizzbee-verification-plan.md) §5–§6
- DST: simloom <https://pypi.org/project/simloom/>, frontrun <https://pypi.org/project/frontrun/>; FoundationDB <https://apple.github.io/foundationdb/testing.html>; SlateDB DST field report: <https://rng.md/posts/deterministic-simulation-testing-is-really-hard/>
- flake8-async: <https://flake8-async.readthedocs.io/>; blockpath: <https://pypi.org/project/blockpath/>
- VLP / NL-Doc: <https://arxiv.org/abs/2607.02333>; SpecPylot: <https://arxiv.org/abs/2604.16560>; Clover: <https://arxiv.org/abs/2310.17807>; airtight-ai: <https://pypi.org/project/airtight-ai/>
- NL2VC-60 (vacuous verification): <https://arxiv.org/pdf/2604.22601>

**Companion documents:**
- Rationale and tool landscape: [`formal_verification.md`](formal_verification.md)
- Model-checking program: [`fizzbee-verification-plan.md`](fizzbee-verification-plan.md)
