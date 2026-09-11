# Formal Verification of LLM-Generated Code — FizzBee, DST, and the Layered Verification Stack

> In-depth analysis (Shannon methodology: problem definition → constraints → model →
> proof/validation → implementation). Sources:
> [fizzbee.io](https://fizzbee.io/),
> [FizzBee GitHub](https://github.com/fizzbee-io/FizzBee).
>
> This document provides the deeper rationale for the layered verification
> stack: where each layer procures trust within this project, where its hard
> limits lie, which methods other projects employ, and which verification and
> testing plan fits the AI-generated nature of the repository.
>
> Structure: problem statement → **1.** deductive verification (retired) →
> **2.** FizzBee → **3.** methods of other projects → **4.** verification plan
> → **5.** testing → **6.** synthesis and recommendation → **Appendix** tool
> landscape.
>
> **September 2026 amendment:** the L5 deductive-verification layer
> (Viper/Z3 over `Requires`/`Ensures`/`Invariant` contracts on the decision
> cores) has been removed.  The decision-module properties it certified are
> pinned by the L1/L2 behavioral oracles
> (`tests/unit/test_text_validation.py`, `tests/unit/test_normalization.py`,
> `tests/verification/test_normalization_idempotence.py`) — see
> [`verification.md`](verification.md) L5 for the removal summary and the
> property-by-property hand-off table.  This document's tier model, evidence
> base, and layered-stack synthesis remain valid; verifier-specific sections
> are trimmed or marked historical.  The FizzBee program and the DST
> experiment are standalone decision units (E2).

## Problem Statement: Decomposing the Repository's Trust Problem

"Is the generated code correct and does the application fulfill its purpose?" are
here **two fundamentally different questions**:

| | T1: Trust in the machinery | T2: Trust in the product |
|---|---|---|
| Meaning | The deterministic scaffolding fails on **no** input: no crashes, no state corruption, termination | Are the architecture designs substantively correct/sensible? |
| Affected | `validation.py`, `text_validation.py`, `design_normalization.py`, `tools/jobs.py`, `patterns/retriever.py`, `config_expansion.py` | LLM output, prompt quality, substantive judgments of the evaluation logic |
| Formally verifiable? | **Partially — bounded model checking, DST, and property oracles** | **No — not in principle** (semantic quality is not a theorem) |

Key claim: the layered stack makes the **class of errors** that typically
kills LLM code (unguarded index accesses, None dereferences, wrong shape
assumptions about data, infinite loops, race conditions) implausible to
survive — but it cannot prove that a proposed microservices design is
"good". Presenting formal verification as a solution for T2 misrepresents
its applicability.

## 1. Deductive Verification — Retired (2026-09)

> **Historical.** Until September 2026 this section described a modular
> static verifier for Python 3 (ETH Zürich, CAV 2018; Viper/Silver + Z3)
> whose contract idiom (`Requires`/`Ensures`/`Invariant`,
> separation-logic permissions, pure functions) verified the two decision
> cores.  The layer was removed: see [`verification.md`](verification.md)
> L5 for the rationale, the removal summary, and the property hand-off to
> the L1/L2 oracles.  The hard limits that motivated the layered approach
> still hold and are restated below because they shape the surviving stack.

### 1.1 Hard Limits — What Deductive Verification Cannot Do Here

1. **`pipeline.py` (asyncio) is not verifiable as-written**: static
   verifiers of this class support threads, not asyncio.  The control logic
   (attempt loop ≤ 3, cancellation between stages) is instead checked by the
   FizzBee `.fizz` model (§2.3) and the DST experiment (§2.7).
2. **Third-party opacity**: Pydantic metaprogramming, `aiosqlite`, `LiteLLM`,
   `httpx` are black boxes for static verifiers. Only self-written contracts
   about their behavior are acceptable — unproven oracle assumptions that must be
   reviewed like code.
3. **LLM responses remain unverifiable in content**: only **structural**
   properties of the interaction (permitted operation sequences, progress)
   can be checked, never the semantic quality of a response.
4. **Effort**: writing specifications is expert work with superlinear effort
   for stateful code. Realistic: the critical 5–10% of modules, not all of
   the tree (measured 2026-09-09: ~13,400 raw lines, ~10,200 excluding
   blanks and comments).
5. **Vacuous specs**: a too-weak contract verifies trivially — specs need
   review like code. (The documented pitfalls apply: subtype quantification,
   trigger inference with nested quantifiers, function-modular reasoning
   requiring sufficiently strong postconditions on the callee.)

## 2. FizzBee — Model Checking at the Design/Protocol Level

> Research status: September 2026 ([fizzbee.io](https://fizzbee.io/) +
> [GitHub](https://github.com/fizzbee-io/FizzBee), Shannon analysis).

### 2.1 What FizzBee Is

FizzBee (active, Apache-2.0) is a **model checker rather than a code verifier**: a
formal specification language `.fizz` (Python-like syntax, positioned as the
"easiest-ever formal methods language" against TLA+) plus an exhaustive
state-space explorer for distributed systems (Go/Bazel). Core features: `always`
assertions and liveness/fairness, **implicit fault injection**, symmetry
reduction, probabilistic and performance modelling, actors/roles/channels.
**Built AI-native**: skills for Claude Code/Cursor/Gemini CLI (`fizz-spec`,
`fizz-check`, `fizz-debug`, `fizz-mbt`; Agent Skills standard) —
generate-verify-repair as a product principle. Externally validated: SlateDB
concurrency bug (DoorDash), streaming ingestion bugs (Shopify), endorsement from
Jack Vanlightly (Confluent; "upholds the rigor of TLA+"). Sources: [fizzbee.io](https://fizzbee.io/),
[GitHub](https://github.com/fizzbee-io/FizzBee),
[online playground](https://fizzbee.io/play),
[TLA+ quickstart](https://github.com/fizzbee-io/fizzbee/blob/main/docs/fizzbee-quick-start-for-tlaplus-users.md).

### 2.2 Taxonomy: The Two Exploration Cells

The formal methods map has two orthogonal axes — *what* is checked (implementation
code vs. design/protocol model) and *how* it is checked (deductively vs. explicit
state exploration):

| | Implementation (code) | Design/protocol (model) |
|---|---|---|
| **Deductive** (SMT proof, ∀ inputs, unbounded) | (retired — §1) | — |
| **Model checking** (all interleavings, bounded, counterexample traces) | DST — all schedules of the real implementation (§2.7) | FizzBee — `.fizz` specs |

The complementarity: FizzBee checks **temporal**
properties (liveness, deadlock freedom, consistency invariants) over **all
interleavings** of a finite model (global, bounded); DST explores the *real
implementation's* interleavings (§2.7). No tool covers the other cell —
treating both as substitutes repeats the false dichotomy of section 6.

### 2.3 Where FizzBee Fills the Deductive Gap

1. **`pipeline.py` control logic (asyncio)**: a `.fizz` model of the control
   logic: attempt loop ≤ 3, cancellation between stages,
   `ANALYZE → GENERATE → EVALUATE → REFINE`. Checkable properties:
   boundedness, liveness ("no job stays in `RUNNING` forever"), deadlock
   freedom. **Implicit fault injection** is the natural abstraction of the
   unreliable LLM environment ("LLM call fails/times out at any stage").
   Counterexample traces (instead of abstract proof failures) feed directly into
   the LLM repair loop — the structured-feedback finding from §3.1 (JetBrains).
2. **`jobs.py` interleavings (Tier B, duplication)**: submit/get_status/cancel
   from multiple clients × crash points — classic model-checking territory.
   Division of labor: **FizzBee checks the protocol, the DST experiment
   explores the implementation's actual schedules** (including crash-recovery
   scenarios that tests never exhaustively cover).

### 2.4 Adoption Advantages and Limits

**Adoption advantages for this repository:** no JVM (standalone Go binary; Docker
`ghcr.io/fizzbee-io/fizzbee`), online playground = pilot in hours instead of
days. Probabilistic modelling (PRISM heritage) fits retry mathematics under
real LLM error rates.

**Limits:** FizzBee model-based testing ("Specify how the design maps to your
code") requires adapters in one of FizzBee's shipped target languages —
Go/Java/Rust/TypeScript as of September 2026, **no Python adapter** →
unusable for the Python implementation; only the design verification side is
usable. The model≠code gap remains — `.fizz` models are subject to the same
review discipline as any spec (vacuity analog: a too-weak model proves
nothing about the implementation).

### 2.5 Concrete Use in This Repo

`.fizz` models for (a) the `pipeline.py` control logic (attempt loop,
cancellation) and (b) the `jobs.py` protocol (client interleavings × fault
injection × crash recovery) — details in 2.3. `fizz` as a CI gate (Docker
`ghcr.io/fizzbee-io/fizzbee`) — the fizz-spec/fizz-check skills are installed
for the agent loop. Pilot effort: hours (online playground); success criterion
following the SlateDB pattern: one real bug within days. The F0 pilot is the
**in-spec A/B flip** around the Week-0 guarded transitions — the spec
defaults to the guarded semantics and reproduces the historical `J-1`
violation by flipping the guard off, so one artifact demonstrates both
finding and fix-confirmation (see the FizzBee plan §3.5).
Sources: [fizzbee.io](https://fizzbee.io/),
[GitHub](https://github.com/fizzbee-io/FizzBee),
[SlateDB testimonial](https://fizzbee.io/).

### 2.6 Meta Angle (T2, Speculative)

This server *generates* architecture designs (T2). The only lever visible today
to partially mechanize T2: structurally model-check generated event-driven/
microservices designs in the EVALUATE step (deadlocks in event flows,
consistency invariants over component interactions) — FizzBee as an evaluation
upgrade within the server's own pipeline.

### 2.7 DST Frameworks for asyncio — the Implementation-Level Exploration Cell

> Research status: September 2026 (Exa web search; PyPI project pages and
> repositories). This sub-section explains the tool category behind the
> L6 deterministic-simulation layer.

**What deterministic simulation testing (DST) is.** A DST framework replaces
the asyncio event loop with a fully controlled one: a *seeded* scheduler owns
every interleaving decision, a virtual clock makes time a scheduled quantity,
and an in-memory network injects latency, loss, reordering, partitions, and
crashes — all driven by the same seed. One seed ⇒ one exact universe; a
failure *is* its reproduction. This is the FoundationDB / TigerBeetle /
Antithesis school of reliability testing, which until 2026 existed only in
Rust, C++, and Java.

**Why it is a third cell, not a duplicate.** The taxonomy of §2.2 gets a
refinement: the existing cells check either a model of the design (FizzBee,
all interleavings but of an abstraction) or sample the implementation
(Hypothesis). DST explores **all interleavings of the
real implementation** — no twin, no conformance coupling, no model-drift risk.
Asyncio is structurally ideal for this: every interleaving decision happens
at an `await`, under a **replaceable event loop** — no forked interpreter, no
hypervisor, no recompilation — and because the ecosystem (aiohttp, httpx,
redis, streams) bottoms out in loop primitives, real unmodified libraries run
inside the simulation. Properties are asserted with safety/liveness oracles
(`world.always(...)` = invariant at every step, `world.eventually(...,
within=T)` = bounded liveness, `world.leads_to(...)`), and the strongest
variant — exhaustive systematic search over bounded delays — **passes as a
bounded proof of correctness**, or fails with a replayable seed. An
Elle-style serializability checker additionally catches *wrong answers*
(stale reads, lost updates) that plain crash-freedom tests miss.

**The four frameworks (links to primary sources):**

| Tool | Ver | Cell | Maturity |
|---|---|---|---|
| [simloom](https://pypi.org/project/simloom/) | 0.5.0 (2026-08) | `systematic=True` gives bounded proof; safety/liveness oracles (`world.always/eventually/leads_to`); Elle-style serializability checker for lost updates; virtual clock | Alpha, CI torture 10k seeds |
| [seedloop](https://github.com/klimavojtech2002/seedloop) | 0.3.2 (2026-07) | FoundationDB/TigerBeetle style DST; sans-I/O required; `world.always` invariants | Beta, 245 tests |
| [askew](https://github.com/cqlsh/askew) | early | Same DST approach; in-memory network with partitions/loss/reordering | Alpha |
| [frontrun](https://pypi.org/project/frontrun/) ([GitHub](https://github.com/lucaswiman/frontrun)) | 0.7.0 | DPOR-driven, sync+async, virtual clock, deadlock detection | Beta |

Category nuances worth knowing before choosing:

- **simloom** is the most property-rich (liveness oracles, serializability +
  linearizability checkers, causal-trace CLI, `pct:auto` scheduler for
  deep-ordering bugs) and the most self-skeptical: every CI run runs a
  10,000-seed determinism torture on the harness itself, differentially
  validates its own consistency checkers against brute-force references, and
  raises loud errors at the determinism boundary (blocking C-extension I/O
  cannot run in-sim).
- **seedloop** requires the sans-I/O style (protocol logic behind an abstract
  transport) and is explicit that it tests *algorithms*, not database
  drivers; its non-determinism auditor turns any uncontrolled entropy source
  into a reproducible failure.
- **askew** is the minimal-core entry (Python 3.11+, zero dependencies):
  virtual clock, PRNG-permuted ready queue, in-memory links; reports deadlock
  when no callback and no timer is pending instead of hanging the suite.
- **frontrun** is the outlier in the family: DPOR (dynamic partial order
  reduction with vector clocks, Rust engine) instead of random/systematic
  schedule exploration — it prunes *equivalent* interleavings rather than
  sampling schedules, covers **threads and OS processes as well as asyncio**,
  and detects shared-memory conflicts at the bytecode level (plus Redis/SQL
  interceptors and a `LD_PRELOAD` hook for C extensions). Its virtual-clock
  mode covers timeout/TTL/retry races; its random strategy can find races
  DPOR cannot see (C-level mutations invisible to bytecode tracking).

**Use in this repository.** The application target is exactly the Tier B gap
(§4.1): `tools/jobs.py` interleavings (submit/get_status/cancel × crash
points) and the `pipeline.py` attempt loop — checked **on the implementation
directly**, complementing the FizzBee protocol view (§2.5). Phase 0 runs a
head-to-head sub-experiment with explicit acceptance numbers: simloom (or
frontrun on rejection) must prove ≥ 2 of `J-1`–`J-4` on the real `jobs.py`
within a bounded exploration budget — **including at least one of the
discriminating pair `J-1`/`J-2`** (E1: without this, the threshold is
gameable by the near-trivial `J-3`/`J-4`). **Caveats:** all four are pre-1.0
(pin exact versions, wrap in a thin adapter under `tests/verification/`);
C-extension boundaries (psycopg, grpcio) and real threads are outside every
determinism guarantee — the boundary is disclosed per tool, not hidden.

Sources: [simloom (PyPI)](https://pypi.org/project/simloom/),
[seedloop](https://github.com/klimavojtech2002/seedloop),
[askew](https://github.com/cqlsh/askew),
[frontrun (PyPI)](https://pypi.org/project/frontrun/),
[frontrun (GitHub)](https://github.com/lucaswiman/frontrun);
category lineage: [FoundationDB simulation testing](https://apple.github.io/foundationdb/testing.html),
[TigerBeetle VOPR](https://github.com/tigerbeetle/tigerbeetle),
[madsim (Rust)](https://github.com/madsim-rs/madsim).

## 3. Methods of Other Projects (External Evidence)

> Research status: September 2026 (Exa web search; project repositories and
> documentation). This section complements the preceding analysis with independent evidence;
> all claims are linked, multiple sources per point allowed. The full tool landscape is
> catalogued in the **Appendix**.

### 3.1 The Formal Verification Camp

- **VeriGuard (Google, 2025)** — an LLM generates policy code **plus formal
  contracts**, a three-stage repair loop (intent validation → pytest →
  **Hoare-triple proof**) refines both, after which the verified policy runs
  as a runtime monitor (enforcement strategies: task termination, action
  blocking, re-planning). Result: attack success rate ≈ 0 on ASB/EICU-AC/
  Mind2Web-SC while preserving task success. Google deliberately verifies
  only the small policy layer, **not** the entire agent — exactly the tier
  model of this document. The limitation Google itself names: the NL→spec
  translation remains the insecure step; generated contracts need human
  validation.
   Sources: [arXiv 2510.05156](https://arxiv.org/abs/2510.05156),
   [Google Research page](https://research.google/pubs/veriguard-enhancing-llm-agent-safety-via-verified-code-generation/),
   [EmergentMind summary](https://www.emergentmind.com/papers/2510.05156).
- **VLP — Verifiable Literate Programming (Yuan et al., July 2026)** — the
  missing intermediate-review layer between prompts and proofs: (1) an
  NL-Doc intermediate (unambiguous, mostly deterministic code-to-doc
  translation) that humans validate instead of the code, (2) LLM-based
  mismatch detection over trace links between prompt fragments and
  documentation lines, (3) bounded model checking of API-usage and
  Hoare-style properties derived from the *validated* documentation.
  Result: pass@1 28.7–73.2% → 65.4–93.5% at reasonable user effort.
  Independently corroborated: validating an intermediate artifact beat
  direct code review 84% vs 40% with lower cognitive load (Fakhoury et
  al., 2024); 81.7–83.3% of studied LLM-code failures were expressible as
  concrete intent-level behaviors — meaning the spec surface is finite and
  enumerable. This repo's docstring-discipline is a micro-version of the
  same pattern. Sources: [arXiv 2607.02333](https://arxiv.org/abs/2607.02333).
- **JetBrains Research: "Can LLMs Enable Verification in Mainstream Programming?"
  (Shefer et al., 2025)** — evaluates LLMs on verified code generation in
  Dafny and Verus (HumanEval derivatives). Finding: verify-repair
  loops work; verifier-specific syntax errors of the models are fixed with
  **cheap deterministic preprocessors** instead of more expensive model
  calls. Source: [arXiv 2503.14183](https://arxiv.org/abs/2503.14183).
- **AxDafny (2026)** — verifier-guided repair with a proposer/reviewer/memory
  architecture: 92.7% on DafnyBench, 56.4% vs. 11.6% baseline on
  LiveCodeBench-Pro-Dafny. Critical finding: verified programs still fail on
  resource limits — **proofs guarantee functional correctness, not performance
  or intent** (confirms the T1/T2 split from the problem statement).
  Sources: [arXiv 2606.32007](https://arxiv.org/html/2606.32007v1),
  [code + benchmark](https://github.com/Axiomatic-AI/ax-dafny).
- **NL2VC-60 (2026)** — demonstrates **vacuous verification** as a demonstrated
  failure mode: models satisfy verifiers with trivial specs; context-free
  prompting fails almost always, signature prompts + self-healing feedback turn
  success rates to 80–90% (Gemma 4-31B: 90.9%, GPT-OSS 120B: 0% → 81.8%).
  Confirms the vacuity-control rule. Functional validation via uDebug test
  suites combines SMT proof with a test oracle. Source: [arXiv 2604.22601](https://arxiv.org/pdf/2604.22601).
- **Dafny as an opaque intermediate language (2025)** — alternative
  architecture: an LLM generates Dafny + proof, compiles to Python; the user
  never sees Dafny. Unsuitable for this repository (contracts should be
  runtime no-ops **in the same source code**), but methodologically
  instructive: spec agreement via natural language, consistency checks,
  Dafny-generated unit tests. Source: [arXiv 2501.06283](https://arxiv.org/abs/2501.06283).
- **AutoProv** — neuro-symbolic CI/CD pipeline (specifier agent → coder agent →
  Dafny-SMT sandbox → repair agent → transpiler) in a zero-trust Docker sandbox;
  it uses **LiteLLM, as does this repository**. Source:
  [GitHub](https://github.com/DimitriosThomaidis/AutoProv).
- **Nightjar (2026)** — productized proof of the tiered model: 6-stage
  cheapest-first pipeline (preflight → dependency audit → Pydantic schema →
  CrossHair negation proof → Hypothesis PBT → Dafny/CEGIS) with graceful
  degradation without Dafny; routing by cyclomatic complexity, behavioral
  safety gate against silent invariant drops. Found 74 bugs in 34 packages,
  zero false positives. Sources:
  [GitHub](https://github.com/j4ngzzz/Nightjar).
- **The LLM-aided verification loop as a maturing category (2026)** — three
  independent results extend the repair loop from *code+contract generation*
  to *spec inference* and *cross-model validation*:
  [SpecPylot](https://arxiv.org/abs/2604.16560) (FSE 2026,
  [tool](https://github.com/ragibayon/specpylot)) proposes icontract
  annotations via LLM, validates with CrossHair, refines on counterexamples —
  the documented failure mode (bounded symbolic search missing violations
  beyond its bounds) is exactly why its outputs feed a *review* pipeline, not
  an unsupervised gate; Anthropic's property-based-testing agent
  ([arXiv 2510.09907](https://arxiv.org/abs/2510.09907)) autonomously wrote
  Hypothesis properties for numpy/scipy/pandas with 86% of top-priority bug
  reports valid;
  [airtight-ai](https://pypi.org/project/airtight-ai/) packages Clover-style
  cross-consistency (six-way checks between intent/spec/code using a
  *different* LLM than the generator) into a four-gate pipeline. Direct
  consequences for this repo: spec inference as a bootstrap task, and a
  cross-LLM consistency gate against the 68% same-model circularity finding
  of §5.2.

## 4. Plan: Layered Verification of the Project Code

### 4.1 Verifiability Tiering of the Codebase

#### Tier A — Decision logic (highest value)

- **`text_validation.py` / `design_normalization.py`**: everything LLMs
  output flows through these modules. Properties: **totality** (no
  IndexError/KeyError/AttributeError on **any** input — precisely the bug
  class that LLMs produce) and **idempotence** (`normalize(normalize(x)) ==
  normalize(x)` — prevents corruption from double normalization). Pinned by
  the L1 behavioral oracles and the L2 Hypothesis oracle (N-1..N-4);
  previously verified deductively (retired — §1).
- **`patterns/retriever.py` scoring mathematics**: monotonicity (higher score ⇒
  never a worse rank), stability of the top-k selection.
- **`config_expansion.py`**: pure expansion rules, determinism provable.

#### Tier B — Stateful job store (`tools/jobs.py`)

The 5-state automaton `PENDING → RUNNING → {COMPLETED, FAILED, CANCELLED}` is a
textbook verification target — checked by FizzBee at the protocol view (§2.3)
and by the DST experiment at the implementation view (§2.7). Properties:

- **Terminal states are immutable** (`J-1`, no transition back out of
  `COMPLETED`).
- **Correct cancellation** (`J-2`): cancellation only takes effect from
  `PENDING`/`RUNNING` — exactly the property the `cancel_architecture_design`
  tool promises.
- **Monotonicity**: `created_at <= updated_at` as an invariant (`J-3`).
- **At most one RUNNING per job_id** (`J-4`).

**Implementation status (September 2026):** the automaton is enforced by
guarded transition setters — the Week-0 bug-fix PR converted the
unconditional `UPDATE`s to `WHERE id = ? AND status IN (...)` guards, so a
cancel/completion race can no longer move a job out of `COMPLETED`. The
properties are therefore *true of the implementation* — fix first, prove
after; the FizzBee F0 pilot re-runs the historical violation via the in-spec
A/B flip (§2.5), the L2 shadow-automaton oracle and the L6 DST suite pin the
implementation directly, and the frozen traces replay the counterexamples.

#### Tier C — Retry loop in `validation.py` (self-healing)

The provable contract shape: the retry loop **is guaranteed to terminate**
(no infinite self-healing spin on degenerate LLM responses) and has a total
error signature. Pinned by the L1 unit tests.

#### Tier D — Data contracts of the Pydantic schemas (`src/schemas/`)

Field constraints (e.g., `score ∈ [0, 10]`, non-empty `name`) are enforced at
the Pydantic boundary. Effect: downstream code (e.g., aggregations in
`pipeline.py`, `get_architecture_design_status`) may **rely on the invariants**
instead of defensively re-checking — eliminates a redundancy bug class.

#### Tier E — Secure information flow (secret canary)

The *secret-canary test* — distinctive fake key, mock LLM transport capturing
outbound payloads, `caplog` assertion of absence, extended (E4) to persisted
job state (`jobs.result`/`jobs.error` rows and the raw DB file) — proves the
practical assurance that **API keys never flow into LLM prompts, log output,
or persisted state** at ~1% of the cost of information-flow analysis.

#### Not verifiable (Tier F)

`reasoning/client.py` internals, embedder integration, prompt contents,
semantic design quality.

### 4.2 Meta-Synthesis: Generate-Check-Repair Loop

Since this repository **is written by LLMs**, the highest-leverage approach is
not after-the-fact specification but the installation of a **generate-check
repair loop**:

```
LLM writes code
        ↓
mechanical gates check it (types, linters, unit oracles, .fizz models, DST)
        ↓ error messages (position + violated property)
LLM repairs ←────┘
```

Arguments for feasibility:

- This repository's `mypy --strict` discipline is a significant head start:
  verifiers require PEP 484-typed code, and it already exists here in full.
- The FizzBee skills (`fizz-spec`/`fizz-check`/`fizz-debug`) and the
  structured-feedback finding (JetBrains, §3.1) make counterexample-driven
  repair native to the agent loop.

### 4.3 Recommended Roadmap

| Phase | Goal | Effort | Payoff |
|---|---|---|---|
| **0 — Pilot** | Week-0 guarded-transition fix (landed) + `.fizz` F0 in-spec A/B flip; **mutation test**: planted bugs (off-by-one, None deref, infinite loop) must be caught by the oracle layers; **numeric Go/No-Go thresholds** | days | Empirical cost/benefit proof — the falsifiable experiment |
| **F1** | `jobs.py` state automaton: `.fizz` model + L2 shadow automaton + DST head-to-head (§2.7 acceptance numbers) | ~1–2 weeks | Proven job integrity, correct cancellation — true of the implementation |
| **F2** | `pipeline.py` control-logic model (attempt loop, cancellation points): FizzBee `.fizz` model with fault injection | days–1 week | Checked boundedness + cancellation property |
| **continuous** | LLM changes only with gates green; Hypothesis PBT for non-verified modules as a cheaper fuzzing layer beneath | process | Verification as a system property, not a one-off act |

### 4.4 Review Amendments (September 2026)

1. **Numeric Phase-0 Go/No-Go thresholds** — garden ≥ 20 planted mutants
   across the four classes (off-by-one, None-deref, unbounded loop,
   shape/KeyError); oracle kill ≥ 90% of the garden with the
   Hypothesis-only baseline kill rate recorded alongside; the readability
   review passes. Any miss ⇒ No-Go or descope — the affected property moves
   down to the Hypothesis/CrossHair layers.
2. **Model–implementation conformance discipline** — the weakest link of
   model-based verification is drift, and the September 2026 review found it
   is not hypothetical: the `jobs.py` transition setters issued unconditional
   `UPDATE`s, so terminal-state immutability was **false of the
   implementation**. Countermeasures: properties get stable IDs (`J-1`…`J-4`,
   `P-1`) shared by the `.fizz` models, the Hypothesis oracles, and the DST
   suite; the **Week-0** guarded `UPDATE`s are a documented bug-fix exemption
   landed before the program began; frozen counterexamples replay against the
   real store.
3. **Nightly verifier canary (TCB guard)** — the verifier toolchains are part
   of the trusted computing base; a scheduled CI job re-runs the bug garden
   against the pinned versions, and a garden mutant that survives a
   `uv.lock` bump blocks the bump until triaged.
4. **CrossHair as a standing layer** — zero annotation cost and the shared
   `hypothesis[crosshair]` backend justify running it over pure modules from
   Phase 0 on; the demonstrated false-`verified` report (issue #354,
   Appendix A.1) confirms the "weak but useful peer of Hypothesis"
   classification — never a proof.
5. **ESBMC-Python landscape note** — bounded and fragment-restricted, but its
   `--generate-pytest-testcase` (pytest generation from counterexamples) is a
   candidate for the repair loop; on the watch list.
6. **Performance smoke gate** — proofs guarantee functional correctness, not
   performance (AxDafny finding, §3.1): the decision modules get a coarse
   benchmark smoke so refactors cannot silently regress latency.
7. **mutmut filter caveat** — mutmut's own docs warn the mypy/pyrefly type
   filter can hide valid mutants; the planted-bug garden, not filter survivor
   counts, stays the vacuity authority.

## 5. Testing: Mutation Testing, Property-Based Testing & Co.

### 5.1 AI Code Error Statistics

(Synthesis sources): 45% OWASP security failures across 150+ models (Veracode),
19.7% hallucinated packages → slopsquatting (USENIX Security '25), ~1.7× issue
rate in AI-co-authored PRs (CodeRabbit), 90% adoption with 30% distrust
(DORA 2025), Google: >25% of new code AI-generated "then reviewed and accepted
by engineers". Sources: [you-source synthesis](https://www.you-source.com/blogs/test-ai-generated-code),
[BugBrain](https://bugbrain.tech/blog/testing-ai-generated-code),
[ContextQA checklist](https://contextqa.com/blog/what-is-ai-generated-code-testing-checklist/).

### 5.2 Mutation Testing as the "Who Tests the Tests?" Oracle

crucible (tester/critic LLM loop over mutmut, add-only operation, kills must be
earned) raises the mutation score 65% → 99%; study finding: up to **68% of
AI-generated test suites validated bugs** instead of catching them
(same-model circularity — the same blind spots shape code and tests).
Sources: [crucible](https://github.com/Jott2121/crucible),
[Augment: Mutation Testing for AI-Generated Code](https://www.augmentcode.com/guides/mutation-testing-ai-generated-code),
[mutmut docs](https://mutmut.readthedocs.io/en/latest/) (mypy integration
filters type-invalid mutants — synergy with `mypy --strict`).

**Use in this repository:** `mutmut` as the `make test-mutations` gate over
Tier A/B/C + `tests/verification/`: audits the Hypothesis oracles themselves
and kills the same-model circularity (68% finding). Synergy: mutmut uses mypy
for mutant filtering — with the documented caveat that the filter can hide
*valid* mutants; the planted-bug garden (§4.4), not filter survivor counts,
remains the vacuity authority. Optional later: a crucible-style tester/critic
loop over the survivors.

### 5.3 Property-Based Testing

Carlini/Anthropic — agentic PBT with LLM-inferred Hypothesis properties found
real numpy/pandas bugs (56% of reports valid, 86% of the top priorities).
Sources: [arXiv 2510.09907](https://arxiv.org/abs/2510.09907),
[Hypothesis docs](https://hypothesis.readthedocs.io/en/latest/).

### 5.4 Consensus Verification Stack

lint → typecheck → unit (85–90% coverage for AI code vs. 70–80% for human) →
mutation → PBT → SAST → dependency check → human review for critical paths;
test-first sequencing against tautological tests; post-merge canaries. Sources:
[Augment: Reviewing AI-Generated Code](https://www.augmentcode.com/guides/reviewing-ai-generated-code),
[Socratopia: Property-Based & Mutation Testing](https://www.socratopia.app/library/software-engineering-craft-en/chapter-6).

## 6. Synthesis and Recommendation

### 6.1 Verdict: Verification as a Layered Stack

The question of whether formal verification is the best approach constitutes a
false dichotomy. Consistent with the evidence is a **composition model**
(defense in depth): the layers' blind spots are decorrelated, so the
residuals multiply; each layer's marginal benefit depends on what the others
already cover:

- **Yes for T1, as a layered stack**: mypy-strict + Pydantic + unit tests
  already exist here; FizzBee adds bounded-universal interleaving coverage,
  DST adds bounded proof **on the real implementation**, mutation auditing
  keeps the oracles honest, and the L2 Hypothesis oracles pin the decision
  properties across generated inputs.
- **No as a total strategy**: vacuous specs verify trivially (NL2VC-60);
  whole-program verification is illusory at seL4/CompCert cost (11
  person-years, 3× code size); asyncio/Pydantic internals remain black
  boxes; no existing tool proves T2 (design quality); it remains the domain
  of evaluation rubrics and human review.
- **Layer evidence**: VeriGuard (proof + tests + enforcement), Nightjar (6
  stages with degradation), crucible (mutation audits AI tests), industry
  consensus stack (§5.4) — no successful project uses one technique *alone*;
  all combine.
- **The model-checking cell (FizzBee, section 2)**: temporal properties
  (liveness, deadlock freedom) over **all interleavings** of a finite model,
  with fault injection — addresses exactly the asyncio and interleaving
  gaps.
- **The DST cell (§2.7)**: simloom (`systematic=True` = exhaustive
  delay-bounded model checking of unmodified asyncio code), frontrun
  (DPOR-based, Rust engine), seedloop, askew — bounded proof *on the
  implementation itself*, complementing (not replacing) the FizzBee model
  view.
- **VLP-style intermediate-artifact review** — the docstring-as-NL-Doc
  discipline promoted to a machine-checked consistency gate, on
  84%-vs-40% evidence.
- **Cross-LLM consistency** (Clover, airtight-ai) — mechanical enforcement
  against the same-model circularity of §5.2.
- **Governance sharpenings (E1–E8):** (a) **gate-gameability control (E1)** —
  the DST acceptance requires ≥ 1 of `J-1`/`J-2`; (b) **program independence
  (E2)** — the FizzBee program and the DST program are independent decision
  units; (c) **model-identity pinning (E3)** — the cross-LLM consistency gate
  records the second model's identity and version per run; (d) **leak-surface
  extension (E4)** — the secret canary covers persisted job state; (e)
  **reasoning-client oracle (E5)** — timeout/retry behaviour gets a
  Hypothesis property; (f) **lock injectability (E6)** — the `JobsStore`
  singleton lock is constructor-injectable; (g) **evidence self-audit (E7)**
  — the citations this document builds on get a quarterly existence/version
  re-check; (h) **pipeline-model sequencing (E8)** — FizzBee F2 first.

### 6.2 Conclusion

No single tool fully secures this project — asyncio, Pydantic internals, and
the semantic quality of the architecture designs remain out of reach of any
single technique. But the layered stack can establish, for the deterministic
core (validation, normalization, job management, scoring), what tests alone
only show by sampling: bounded-universal and property-based assurance with
every oracle independently auditable. Precisely because the code originates
from LLMs, the combination of mypy-strict (existing) + behavioral oracles +
model checking + DST + mutation auditing is the most consistent trust
strategy. The external evidence (section 3) confirms this pattern: VeriGuard
(Google), Nightjar, and the industry consensus stack deploy verification
exclusively as the tip of a layered stack — never as a sole solution.

## Appendix — Tool Landscape: Verification Alternatives

> Research status: September 2026 (Exa web search; project repositories and
> documentation). Answers the question *"what verification tools exist and
> where do they fit?"* — separately for Python (A.1), for other languages
> (A.2), and with the consequence for this repository (A.3). Classification
> follows the two axes of section 2.2 (*what* is checked: implementation vs.
> design model; *how*: deductive proof vs. bounded exploration), extended by
> soundness and by the same-source-contracts criterion (contracts must be
> runtime no-ops in the shipped Python).

### A.1 Python — Alternatives and Complements

| Tool | Cell / approach | Soundness / guarantee | Contracts in same source? | Maturity | Assessment for this repo |
|---|---|---|---|---|---|
| **CrossHair** | Symbolic execution (Z3), counterexample search | **Not sound** — bounded path exploration; assumes termination, closed class hierarchies, single-threaded, determinism ([own soundness discussion](https://github.com/pschanely/CrossHair/discussions/156)) | Yes — plain `assert`, PEP-316 docstrings, icontract/deal; no new imports, no JVM | Mature ([GitHub](https://github.com/pschanely/CrossHair)) | Standing bounded layer: peer of Hypothesis, not of a deductive verifier |
| **ESBMC-Python** | Bounded model checking (SMT over GOTO IR; CPython 3.10 parser) | **Not sound ∀-inputs** — bounded unwinding; restricted fragment (only `range()`-`for` loops; partial list/str/dict support) | No — `assert`/`assume` harnesses | Active research tool ([ISSTA 2024](https://doi.org/10.1145/3650212.3685304), generator support merged 2026) | `--generate-pytest-testcase` (pytest from counterexamples) is a repair-loop candidate; fragment too narrow for this codebase |
| **icontract / deal / beartype** | Runtime Design-by-Contract | Checked per call at runtime — enforcement, not proof | Yes | Mature ([icontract](https://github.com/Parquery/icontract), [deal](https://github.com/life4/deal)) | Cheap optional runtime layer beneath the static ones |
| **Dafny** | Deductive (Boogie/Z3), own language | Sound; best SMT automation and best LLM tooling (DafnyBench, AxDafny — 3.1) | No — extraction to Python; contracts are not no-ops in shipped source | Very mature ([dafny.org](https://dafny.org)) | Rejected as opaque intermediate (§3.1); backend of choice for the Python front-ends below |
| **veripy** (ZJU-PL, 2025) | Auto-active VC generation, Dafny/Verus-style | Self-declared **"not sound for full Python"** — restricted fragment (side-effect-free int/bool/mathematical arrays; aliasing/exceptions approximated) | Yes (decorators) | Early ([GitHub](https://github.com/ZJU-PL/veripy), [PyPI](https://pypi.org/project/py-veripy/)) | Fragment does not cover this codebase (state, exceptions, aliasing) |
| **lemmapy** (v0.1.0a1, M0–M2 complete) | `#@` comment specs on production Python → runtime contracts (CrossHair-executable) + Dafny SMT proofs, plus conformance checker, boundary guards, island integrity, translation validation vs. CPython | Careful **layered** soundness (four independent mechanisms) under explicit assumptions A1–A7; continuous `difftest` differential testing | Yes — `#@` comments, ignored by CPython | Alpha but fast-moving (2026-08-15 release: LSP, `lemmapy repair` proof-repair loop, 16/16 corpus proven, 81% mutant kill; [PyPI](https://pypi.org/project/lemmapy/)) | **Watch list → Phase-0 co-evaluation candidate**; nearest architectural successor to the retired deductive layer |
| **Strata-Python** (AWS) | Python → Laurel IVL → SMT | Sound for its fragment; machine-oriented serialized specs | Partially | Early | Watch list |
| **dafny-of-python** | Deductive verification of a Python subset via Dafny | Sound on the subset | Yes-ish | Research ([GitHub](https://github.com/arsalan0c/dafny-of-python)) | Instructive only |
| **PyExZ3** | Symbolic execution (academic predecessor) | Bounded | n/a | Unmaintained | Superseded by CrossHair as the practical implementation |
| **2vyper** | Deductive (Viper) for the Vyper smart-contract language | Sound | n/a | ETH, active-ish | Different domain (smart contracts) |
| **Pyre/Pysa · mypy · pyright** | Type systems + taint analysis | Sound only w.r.t. the checked type properties — no functional correctness | n/a | Mature | Already present: `mypy --strict` |
| **Nightjar** | Orchestrator: Pydantic → CrossHair → Hypothesis → Dafny/CEGIS | Layered, degrades gracefully without Dafny | `.card.md` spec sidecars | New ([GitHub](https://github.com/j4ngzzz/Nightjar)) | Pattern reference, not a component (§3.1) |

**Verdict (Python):** no production-grade, same-source, sound deductive
verifier occupies the retired cell today — every alternative either gives up
soundness (CrossHair, PyExZ3, ESBMC-Python), restricts the language fragment
(veripy, Strata-Python, dafny-of-python), uses another prover language with
extraction (Dafny, lemmapy, Nightjar — the route rejected in §3.1 for this
repo), or checks something weaker (runtime DbC, types).  That is precisely
why the decision-module properties moved to the L1/L2 oracle layers
(verification.md L5).

**CrossHair deserves the closer look** because it pays off regardless of the
deductive decision: zero annotation-language barrier (plain `assert`s),
pure-Python install without JVM, counterexample output, usable as a
[Hypothesis
backend](https://hypothesis.readthedocs.io/en/latest/strategies.html#alternative-backends),
and productively deployed as the "negation proof" stage in Nightjar (§3.1).
Its documented unsoundness conditions (termination assumed, closed type
hierarchies, single-threadedness) mean a "confirmed over all paths" from
CrossHair is a much weaker statement than a proof — it slots into the stack
*next to Hypothesis* (§5.3) — a weakness demonstrated in practice by
[issue #354](https://github.com/pschanely/CrossHair/issues/354) (2025:
CrossHair reported `verified` on a failing property; **since fixed** in
`hypothesis-crosshair` v0.0.30 — so the headline false-`verified` failure
mode is mitigated, while the structural weakness — bounded search is not
proof — remains and keeps the classification: peer of Hypothesis).

**Watch list:** veripy (now with a Lean backend and automatic invariant
inference), Strata-Python (PySpec pipeline landing), ESBMC-Python (fragment
coverage may grow — currently too narrow for this codebase), lemmapy
(2026-08-15 M2 release: `#@` specs compile to runtime contracts that
CrossHair searches for counterexamples **and** translate to Dafny for SMT
proofs; all four soundness layers built; the agent layer is live with LSP
and `lemmapy repair`). None of these is far enough along for a bet; reassess
at the Phase-0 Go/No-Go.

### A.2 Other Languages — The Same Cells Elsewhere

The two-axis taxonomy of 2.2 generalizes: every mature ecosystem has bounded/
symbolic layers and design-level checkers, with sound same-language deductive
verifiers as the tip where they exist:

| Ecosystem | Tool(s) | Cell | Notes |
|---|---|---|---|
| Java | [OpenJML](https://www.openjml.org) (JML contracts), VeriFast, KeY | Deductive, same-language contracts | OpenJML is the JML-contract verifier of Java — JML annotations are comments in Java source |
| C | [Frama-C/ACSL](https://frama-c.com) (WP plugin + Alt-Ergo/Why3), [CBMC](https://www.cprover.org/cbmc/), [ESBMC](https://esbmc.org) | Deductive + bounded model checking | CBMC/ESBMC are bounded (like the FizzBee cell, but at code level); Python support exists via **ESBMC-Python** (A.1) — bounded and fragment-restricted |
| Rust | [Prusti](https://github.com/viperproject/prusti-dev) (Viper-based), [Verus](https://github.com/verus-lang/verus) (SMT verification conditions), [Kani](https://github.com/model-checking/kani) (BMC, AWS) | Deductive + BMC | Verus covered by the JetBrains benchmark (§3.1); Kani is the bounded layer |
| Own-language ecosystems | [Dafny](https://dafny.org) (.NET/Go/Java/Python extraction), [F*](https://www.fstar-lang.org) (dependent types; Vale, EverParse), [Why3](https://why3.lri.fr)/WhyML | Deductive | Dafny optimizes automation for humans/LLMs; F* optimizes expressiveness at proof cost |
| Interactive proof assistants | Coq (CompCert), Lean, Isabelle/HOL (seL4) | Manual proof, code extraction | The 11-person-year cost class referenced in 6.1 — not automation, categorically different effort model |
| Design level (language-agnostic) | [TLA+](https://lamport.azurewebsites.net/tla/tla.html)/TLC/TLAPS, Alloy, [Stateright](https://github.com/stateright/stateright) (state machines), FizzBee (section 2) | Model checking of specs | TLA+ is the incumbent FizzBee positions against; Stateright checks API/protocol state machines |
| Smart contracts | 2vyper (A.1) | Deductive | Vyper, not Python runtime code |

Two observations transfer back to this repository:

1. **The convergent architecture**: no ecosystem relies on a single tool —
   the sound deductive verifier, where it exists, is always the *tip* over
   bounded layers (Kani/CBMC ≈ CrossHair/Hypothesis) and design-level
   checkers (TLA+ ≈ FizzBee). This independently reproduces the
   layered-stack thesis of section 6 from the tooling side.
2. **Why porting is not an option here**: Dafny/Verus/F*/Prusti all assume
   their host language's runtime and contracts-in-source model; using them
   for this Python codebase means extraction or translation — the opaque-
   intermediate route already rejected in §3.1 (contracts must be no-ops in
   the *same* shipped source, and `tests/unit/` must remain the behavioural
   oracle).

### A.3 Consequence for This Repository

- **L1/L2 oracles own the decision-module properties** (the retired
  deductive cell — verification.md L5).
- **CrossHair is a standing bounded layer** next to Hypothesis (peer
  level, not proof level) — zero annotation cost, shared
  `hypothesis[crosshair]` backend; the Phase-0 bug garden remains the honest
  referee that measures whether any heavier tool's annotation cost buys a
  real delta over the cheaper layers (§4.4).
- **Lemmapy co-evaluation at the Phase-0 Go/No-Go** (promoted from the
  watch list, third September 2026 amendment — full protocol in §A.1):
  head-to-head proof of the decision modules against the same bug garden,
  with explicit promotion/rejection criteria. The remaining watch list
  (veripy, Strata-Python, ESBMC-Python) is reassessed at the Phase-0
  Go/No-Go — the field is moving quickly.
- The appendix's finding **strengthens section 6**: the alternative landscape
  itself shows tools being *combined* into layered stacks, never substituted
  one-for-one.

### A.4 Sources (Appendix)

- CrossHair: [GitHub](https://github.com/pschanely/CrossHair),
  [soundness discussion #156](https://github.com/pschanely/CrossHair/discussions/156),
  [false-`verified` report #354](https://github.com/pschanely/CrossHair/issues/354),
  [kinds of contracts](https://crosshair.readthedocs.io/en/latest/kinds_of_contracts.html),
  [Nightjar vs. CrossHair](https://nightjarcode.dev/compare/nightjar-vs-crosshair)
- ESBMC-Python: [Python frontend docs](http://esbmc.github.io/docs/python/),
  [GitHub (esbmc/esbmc)](https://github.com/esbmc/esbmc),
  [ISSTA 2024 paper](https://doi.org/10.1145/3650212.3685304)
- veripy: [GitHub (ZJU-PL)](https://github.com/ZJU-PL/veripy),
  [PyPI](https://pypi.org/project/py-veripy/)
- lemmapy: [PyPI](https://pypi.org/project/lemmapy/) (architecture, soundness
  layers in project description; v0.1.0a1 2026-08-15 release notes — M0–M2
  status, 16/16 corpus, 81% mutant kill, LSP, `lemmapy repair`)
- Strata-Python / dafny-of-python: referenced from lemmapy's project
  description; [dafny-of-python](https://github.com/arsalan0c/dafny-of-python)
- Nightjar: [GitHub](https://github.com/j4ngzzz/Nightjar)

**Third September 2026 amendment sources:**

- hypothesis-crosshair (fix for CrossHair #354):
  [PyPI v0.0.30 changelog](https://pypi.org/project/hypothesis-crosshair/),
  [GitHub](https://github.com/pschanely/hypothesis-crosshair)
- VLP (Verifiable Literate Programming):
  [arXiv 2607.02333](https://arxiv.org/abs/2607.02333) (Yuan et al., July
  2026; Fakhoury et al. 2024 intermediate-artifact finding cited therein)
- SpecPylot: [arXiv 2604.16560](https://arxiv.org/abs/2604.16560) (FSE 2026),
  [GitHub](https://github.com/ragibayon/specpylot)
- airtight-ai: [PyPI](https://pypi.org/project/airtight-ai/) (Clover-style
  four-gate verification gate)
- Clover (cross-consistency origin):
  [arXiv 2310.17807](https://arxiv.org/abs/2310.17807)
- Anthropic property-based-testing agent:
  [arXiv 2510.09907](https://arxiv.org/abs/2510.09907)
- simloom: [PyPI](https://pypi.org/project/simloom/) (v0.5.0, 2026-08;
  `systematic=True` bounded proof, safety/liveness oracles, serializability
  checker, determinism boundary docs)
- frontrun: [PyPI](https://pypi.org/project/frontrun/),
  [GitHub](https://github.com/lucaswiman/frontrun) (v0.7.0; DPOR, virtual
  clock, sync+async)
- seedloop: [GitHub](https://github.com/klimavojtech2002/seedloop) (v0.3.2;
  FoundationDB/TigerBeetle-style DST, sans-I/O)
- askew: [GitHub](https://github.com/cqlsh/askew) (DST for asyncio, Python
  3.11+, virtual clock + seeded scheduler)
- flake8-async: <https://flake8-async.readthedocs.io/>
- blockpath: [PyPI](https://pypi.org/project/blockpath/) (cross-module
  blocking-call reachability; preregistered depth/precision benchmark)
- Dafny: <https://dafny.org>; Verus: <https://github.com/verus-lang/verus>;
  Prusti: <https://github.com/viperproject/prusti-dev>;
  Kani: <https://github.com/model-checking/kani>
- Frama-C: <https://frama-c.com>; CBMC: <https://www.cprover.org/cbmc/>;
  ESBMC: <https://esbmc.org>; Why3: <https://why3.lri.fr>;
  F*: <https://www.fstar-lang.org>; OpenJML: <https://www.openjml.org>
- TLA+: <https://lamport.azurewebsites.net/tla/tla.html>;
  Stateright: <https://github.com/stateright/stateright>;
  Alloy: <https://alloytools.org>
- icontract: <https://github.com/Parquery/icontract>;
  deal: <https://github.com/life4/deal>;
  beartype: <https://github.com/beartype/beartype>
