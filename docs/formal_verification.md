# Formal Verification of LLM-Generated Code — Nagini, FizzBee, and the Layered Verification Stack

> In-depth analysis (Shannon methodology: problem definition → constraints → model →
> proof/validation → implementation). Sources:
> [Nagini Wiki](https://github.com/marcoeilers/nagini/wiki),
> [ETH PM group research page](https://www.pm.inf.ethz.ch/research/nagini.html),
> [fizzbee.io](https://fizzbee.io/),
> [FizzBee GitHub](https://github.com/fizzbee-io/FizzBee).
>
> Complements, does not replace:
> [`nagini-verification-plan.md`](nagini-verification-plan.md) (the concrete
> verification roadmap).
>
> This document provides the deeper rationale:
> what Nagini and FizzBee are, where they procure trust within this project,
> where their hard limits lie, which methods other projects employ, which
> verification and testing plan fits the AI-generated nature of the repository —
> and the synthesis derived from it.
>
> Structure: problem statement → **1.** Nagini → **2.** FizzBee → **3.** methods of
> other projects → **4.** verification plan → **5.** testing → **6.** synthesis and
> recommendation → **Appendix** tool landscape (Python alternatives + other
> languages). External evidence research as of September 2026 (Exa web search,
> Nagini/FizzBee repositories/documentation, Context7); restructured September 2026
> without information loss; amended after the September 2026 review (Tier A/B
> corrections, ESBMC-Python landscape fix, Go/No-Go thresholds — see §4.5);
> third September 2026 amendment after a fresh Exa evidence pass: CrossHair
> #354 fix status (§A.1), lemmapy promoted from watch list to Phase-0
> co-evaluation (§A.1/§A.3), VLP entry (§3.1), LLM-verification-loop
> category entry (§3.1), new-evidence synthesis bullet (§6.1), DST
> frameworks sub-section (§2.7 — the tool category behind the plan's §3.6
> amendment) — the
> plan-side counterparts live in the plan's third amendment (§3.3, §3.6,
> §5.3, §5.4, §6.2, §6.3). **Fourth September 2026 amendment** (plan review
> E1–E9, 2026-09-09): fix-first sequencing — the `jobs.py` guarded transitions
> move from Phase-4 entry criterion to a **Week-0 bug-fix PR** (§4.1/§4.3);
> FizzBee F0 re-scoped as the in-spec A/B flip (§2.5); secret-canary precursor
> for Tier E (§4.1); MBT landscape correction (§2.4 — adapters now
> Go/Java/Rust/TypeScript, still no Python); LOC reconciliation (§1.2).
> **Fifth September 2026 amendment** (E1–E8 review pass, 2026-09-09; the
> countermeasures are numbered E1–E8 in the companion plans, the
> Week-0 delivery in
> [`week-0-task-breakdown.md`](week-0-task-breakdown.md)): DST acceptance
> sharpened — at least one of the discriminating pair `J-1`/`J-2` must be
> proven (§2.7, E1); the secret canary extends to persisted job fields
> (§4.1, E4); the FizzBee `.fizz` model is the primary pipeline-control
> artifact, the Nagini sync twin demoted behind the phase-gate
> continuation rule (§4.3 phase 2, E8); the FizzBee program is declared
> independent of the Nagini Phase-0 Go/No-Go (§6.1, E2); a quarterly
> evidence audit of this document's own citations joins the tool-vitality
> discipline (§6.1, E7).

## Problem Statement: Decomposing the Repository's Trust Problem

"Is the generated code correct and does the application fulfill its purpose?" are
here **two fundamentally different questions**:

| | T1: Trust in the machinery | T2: Trust in the product |
|---|---|---|
| Meaning | The deterministic scaffolding fails on **no** input: no crashes, no state corruption, termination | Are the architecture designs substantively correct/sensible? |
| Affected | `validation.py`, `text_validation.py`, `design_normalization.py`, `tools/jobs.py`, `patterns/retriever.py`, `config_expansion.py` | LLM output, prompt quality, substantive judgments of the evaluation logic |
| Formally verifiable? | **Yes — Nagini's core domain** | **No — not in principle** (semantic quality is not a theorem) |

Key claim: Nagini makes the **class of errors** that typically kills LLM code
(unguarded index accesses, None dereferences, wrong shape assumptions about data,
infinite loops, race conditions) mathematically impossible — but it cannot prove
that a proposed microservices design is "good". Presenting formal verification
as a solution for T2 misrepresents its applicability.

## 1. Nagini — Deductive Verification of Implementation Code

### 1.1 What Nagini Is

Nagini (ETH Zürich, Programming Methodology Group: Marco Eilers, Peter Müller;
originally CAV 2018, actively developed through ISoLA/CAV 2026 — including
cross-language verification Python/C, object-relations reasoning) is an
**automatic, modular static verifier for Python 3**, built on the
[Viper infrastructure](https://www.pm.inf.ethz.ch/research/viper.html) (Silver IR + Z3).
It emerged from the VerifiedSCION project; available via PyPI and as a VS Code
extension.

Core concepts:

- **Function-modular verification via contracts**: `Requires()`, `Ensures()`,
  `Exsures()` (exceptional postconditions), `Invariant()` for loops. When a
  function is called, only its specification is used, not its implementation.
- **Separation-logic access permissions**: `Acc(field)`, fractional permissions
  (`Acc(o.f, 1/2)`), `MayCreate`/`MaySet`, `Fold`/`Unfold` of predicates — proves
  absence of aliasing errors and data races; built-in predicates exist for
  lists/dicts/sets (`list_pred`, `dict_pred`, `set_pred`).
- **Ghost code / ghost types** (`PSeq`, `PSet`, `PMultiset`, `GInt`, …): code
  serving exclusively verification. Nagini checks that ghost code does **not**
  influence program behavior — it is provably deletable (`--extraction`).
- **Pure functions & predicates**: `@Pure` (usable in contracts), `@Opaque` +
  `Reveal`, `@Predicate` (families under inheritance), `Decreases()` for
  termination of recursive pure functions.
- **Obligation contracts**: `MustTerminate(n)` proves termination of methods and
  loops, lock-release obligations; obligations must not "leak".
- **Threads & locks**: dedicated `Thread` and `Lock` classes with level ordering
  against deadlocks; `Joinable(t)`, `ThreadPost(t)`, lock invariants.
- **IO contracts as Petri nets**: `@IOOperation`, `token(place)`; programs may
  only perform permitted IO operations in permitted order (based on
  Penninckx et al., extended with liveness).
- **Secure information flow**: `--sif` / `--sif=poss` / `--sif=prob` with `Low(e)`,
  `LowVal(e)`, `LowEvent()` proves non-interference (including termination- and
  probabilistically sensitive variants). Encoding via modular product programs
  (TOPLAS 2020).

Decisive for this repository: **contracts are runtime no-ops** — the same source code
is verified and shipped; `--extraction` removes ghost code and contracts.
Verification therefore does not violate the project rule that the runtime
behavior of existing code must not change.

### 1.2 Hard Limits — What Nagini Cannot Do Here

1. **`pipeline.py` (2,367 LOC, the centerpiece) is not verifiable as-written**:
   Nagini supports threads (`nagini_contracts.thread`), **not asyncio**. Remedy:
   a **verified synchronous twin model** of the control logic (attempt loop ≤ 3,
   cancellation flag checked between stages — provable as a progress/liveness
   property), coupled to the implementation via review (the VerifiedSCION
   approach from which Nagini emerged). **Alternative or preliminary stage**:
   a FizzBee `.fizz` model of the control logic — model checking with fault
   injection instead of deductive proof, a much flatter learning curve (see
   section 2).
2. **Third-party opacity**: Pydantic metaprogramming, `aiosqlite`, `LiteLLM`,
   `httpx`, `chromadb` are black boxes for Nagini. Only self-written contracts
   about their behavior are acceptable — unproven oracle assumptions that must be
   reviewed like code.
3. **LLM responses remain unverifiable in content**: IO contracts (Petri nets)
   can only prove **structural** properties of the interaction (permitted
   operation sequences, progress), never the semantic quality of a response.
4. **Effort**: writing specifications (permissions, fold/unfold, triggers) is
   expert work with superlinear effort for stateful code. Realistic: the critical
   5–10% of modules, not all of the tree (measured 2026-09-09: ~13,400 raw
   lines, ~10,200 excluding blanks and comments — the earlier "~8,800 LOC"
   figure is superseded; the 5–10% decision is module-based and unaffected).
5. **Vacuous contracts**: a too-weak contract verifies trivially — contracts need
   review like code. (The documented wiki pitfalls apply: subtype quantification in
   `Forall(type, ...)`, trigger inference with nested quantifiers,
   function-modular reasoning requires sufficiently strong postconditions on the
   callee.)

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
Jack Vanlightly (Confluent; "upholds the rigor of TLA+"). **Complement to Nagini,
not a competitor** — classified in 2.2. Sources: [fizzbee.io](https://fizzbee.io/),
[GitHub](https://github.com/fizzbee-io/FizzBee),
[online playground](https://fizzbee.io/play),
[TLA+ quickstart](https://github.com/fizzbee-io/fizzbee/blob/main/docs/fizzbee-quick-start-for-tlaplus-users.md).

### 2.2 Taxonomy: The Missing Model-Checking Cell

The formal methods map has two orthogonal axes — *what* is checked (implementation
code vs. design/protocol model) and *how* it is checked (deductively vs. explicit
state exploration). Nagini and FizzBee occupy different cells:

| | Implementation (code) | Design/protocol (model) |
|---|---|---|
| **Deductive** (SMT proof, ∀ inputs, unbounded) | Nagini — contracts in `src/*.py` | — |
| **Model checking** (all interleavings, bounded, counterexample traces) | — | FizzBee — `.fizz` specs |

The complementarity is mathematical: Nagini proves functional correctness of a
function over **all inputs** (local, unbounded); FizzBee checks **temporal**
properties (liveness, deadlock freedom, consistency invariants) over **all
interleavings** of a finite model (global, bounded). No tool covers the other
cell — treating both as substitutes repeats the false dichotomy of section 6.
(Third September 2026 amendment: a further refinement — exploration of the
*real implementation's* interleavings rather than a model's — is covered by
the DST frameworks of §2.7.)

### 2.3 Where FizzBee Fills Nagini's Hardest Gaps

1. **`pipeline.py` control logic (gap 1.2.1, asyncio)**: instead of — or as a
   precursor to — the expensive Nagini sync twin (roadmap 4.3, phase 2), a
   `.fizz` model of the control logic: attempt loop ≤ 3, cancellation between
   stages, `ANALYZE → GENERATE → EVALUATE → REFINE`. Checkable properties:
   boundedness, liveness ("no job stays in `RUNNING` forever" — the obligation
   property from Tier B), deadlock freedom. **Implicit fault injection** is the
   natural abstraction of the unreliable LLM environment ("LLM call fails/times
   out at any stage"), which Nagini can only capture coarsely via IO Petri nets.
   Counterexample traces (instead of abstract proof failures) feed directly into
   the LLM repair loop — the structured-feedback finding from 3.1 (JetBrains).
2. **`jobs.py` interleavings (Tier B, duplication)**: submit/get_status/cancel
   from multiple clients × crash points — classic model-checking territory that
   Nagini only laboriously reaches via threads/locks. Division of labor:
   **Nagini proves the implementation, FizzBee checks the protocol** (including
   crash-recovery scenarios that tests never exhaustively cover).

### 2.4 Adoption Advantages and Limits

**Adoption advantages for this repository:** no JVM (standalone Go binary; Docker
`ghcr.io/fizzbee-io/fizzbee`), online playground = pilot in hours instead of
days, flatter learning curve than separation logic (section 1.2.4: zero Nagini
experience on the team). fizz skills in Claude Code/opencode = same integration
logic as `nagini_mcp` (4.4). Probabilistic modelling (PRISM heritage) fits retry
mathematics under real LLM error rates.

**Limits:** FizzBee model-based testing ("Specify how the design maps to your
code") requires adapters in one of FizzBee's shipped target languages —
Go/Java/Rust/TypeScript as of September 2026, **no Python adapter** (fourth
September 2026 correction: the earlier "Go-only" phrasing undersold upstream
progress while the material fact is unchanged) → unusable for the Python
implementation; only the design verification side is usable. The model≠code gap
remains — `.fizz` models are subject to the same review discipline as contracts
(vacuity analog: a too-weak model proves nothing about the implementation).
No replacement for Tier A function proofs.

### 2.5 Concrete Use in This Repo (Amendment 4)

`.fizz` models for (a) the `pipeline.py` control logic (attempt loop,
cancellation — precursor or complement to the Nagini sync twin from phase 2) and
(b) the `jobs.py` protocol (client interleavings × fault injection × crash
recovery) — details in 2.3. `fizz` as a separate CI gate (Docker
`ghcr.io/fizzbee-io/fizzbee`) alongside `make verify-nagini` — same opt-in logic
as `RUN_VERIFY`; the fizz-spec/fizz-check skills are to be installed for the
agent loop. Pilot effort: hours (online playground); success criterion
following the SlateDB pattern: one real bug within days. (Fourth September
2026 amendment: F0 is re-scoped as the **in-spec A/B flip** around the Week-0
guarded transitions — the spec defaults to the guarded semantics and
reproduces the historical `J-1` violation by flipping the guard off, so one
artifact demonstrates both finding and fix-confirmation; see the FizzBee plan
§3.5.)
Sources: [fizzbee.io](https://fizzbee.io/),
[GitHub](https://github.com/fizzbee-io/FizzBee),
[SlateDB testimonial](https://fizzbee.io/).

### 2.6 Meta Angle (T2, Speculative)

This server *generates* architecture designs (T2). The only lever visible today
to partially mechanize T2: structurally model-check generated event-driven/
microservices designs in the EVALUATE step (deadlocks in event flows,
consistency invariants over component interactions) — FizzBee as an evaluation
upgrade within the server's own pipeline.

### 2.7 DST Frameworks for asyncio — the Implementation-Level Exploration Cell (Third September 2026 Amendment)

> Research status: September 2026 (Exa web search; PyPI project pages and
> repositories). This sub-section explains the tool category identified as
> review finding **G1** and folded into the roadmap as the plan's §3.6
> amendment (DST head-to-head sub-experiment).

**What deterministic simulation testing (DST) is.** A DST framework replaces
the asyncio event loop with a fully controlled one: a *seeded* scheduler owns
every interleaving decision, a virtual clock makes time a scheduled quantity,
and an in-memory network injects latency, loss, reordering, partitions, and
crashes — all driven by the same seed. One seed ⇒ one exact universe; a
failure *is* its reproduction. This is the FoundationDB / TigerBeetle /
Antithesis school of reliability testing, which until 2026 existed only in
Rust, C++, and Java.

**Why it is a third cell, not a duplicate.** The taxonomy of §2.2 (deductive
vs. model checking × implementation vs. design) gets a refinement: the
existing cells check either a proof about the implementation (Nagini, ∀
inputs but no interleavings) or a model of the design (FizzBee, all
interleavings but of an abstraction). DST explores **all interleavings of the
real implementation** — no twin, no conformance coupling, no model-drift risk
(the drift the §4.1/Tier B review found to be a live bug in `jobs.py`).
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
directly**, complementing the FizzBee protocol view (§2.5) and the Nagini
twin rather than replacing either (Nagini proves the twin ∀-inputs; FizzBee
checks the protocol; DST explores the implementation's actual schedules).
Phase 0 runs a head-to-head sub-experiment with explicit acceptance numbers:
simloom (or frontrun on rejection) must prove ≥ 2 of `J-1`–`J-4` on the real
`jobs.py` within a bounded exploration budget — **including at least one of
the discriminating pair `J-1`/`J-2`** (E1, fifth September 2026 amendment:
without this, the threshold is gameable by the near-trivial `J-3`/`J-4`) —
see plan §3.6 amendment and §6.2 thresholds. **Caveats:** all four are pre-1.0 (pin exact versions, wrap
in a thin adapter under `tests/verification/`); C-extension boundaries
(psycopg, grpcio) and real threads are outside every determinism guarantee —
the boundary is disclosed per tool, not hidden.

Sources: [simloom (PyPI)](https://pypi.org/project/simloom/),
[seedloop](https://github.com/klimavojtech2002/seedloop),
[askew](https://github.com/cqlsh/askew),
[frontrun (PyPI)](https://pypi.org/project/frontrun/),
[frontrun (GitHub)](https://github.com/lucaswiman/frontrun);
category lineage: [FoundationDB simulation testing](https://apple.github.io/foundationdb/testing.html),
[TigerBeetle VOPR](https://github.com/tigerbeetle/tigerbeetle),
[madsim (Rust)](https://github.com/madsim-rs/madsim).

## 3. Methods of Other Projects (External Evidence)

> Research status: September 2026 (Exa web search, Nagini repository/documentation,
> Context7). This section complements the preceding analysis with independent evidence;
> all claims are linked, multiple sources per point allowed. The full tool landscape —
> Python alternatives to Nagini and other-language verifiers — is catalogued in the
> **Appendix**.

### 3.1 The Formal Verification Camp — Nagini Is Built Exactly for This Purpose

- **VeriGuard (Google, 2025)** — the most direct precedent for this plan:
  An LLM generates policy code **plus formal contracts**, a three-stage
  repair loop (intent validation → pytest → **Nagini Hoare-triple proof**)
  refines both, after which the verified policy runs as a runtime monitor
  (enforcement strategies: task termination, action blocking, re-planning).
  Result: attack success rate ≈ 0 on ASB/EICU-AC/Mind2Web-SC while preserving
  task success. Google deliberately verifies only the small policy layer,
  **not** the entire agent — exactly the tier model of this document. The
  limitation Google itself names mirrors section 1.2.5: the NL→spec translation
  remains the insecure step; generated contracts need human validation.
   Sources: [arXiv 2510.05156](https://arxiv.org/abs/2510.05156),
   [Google Research page](https://research.google/pubs/veriguard-enhancing-llm-agent-safety-via-verified-code-generation/),
   [EmergentMind summary](https://www.emergentmind.com/papers/2510.05156);
   listed as a reference in the [Nagini README](https://github.com/marcoeilers/nagini).
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
  enumerable. This repo's docstring-discipline (§4.1 review caveats, plan
  §3.3) is a micro-version of the same pattern. Sources:
  [arXiv 2607.02333](https://arxiv.org/abs/2607.02333).
- **JetBrains Research: "Can LLMs Enable Verification in Mainstream Programming?"
  (Shefer et al., 2025)** — evaluates LLMs on verified code generation in
  Dafny, Nagini, and Verus (HumanEval derivatives). Finding: verify-repair
  loops work; Nagini-specific syntax errors of the models (e.g., illegal
  `a < b < c` chains, which are legal in Python) are fixed with **cheap
  deterministic preprocessors** instead of more expensive model calls.
  Confirms section 4.2 (loop feasibility) and motivates the MCP integration
  (4.4). Source: [arXiv 2503.14183](https://arxiv.org/abs/2503.14183).
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
  Confirms section 1.2.5 (vacuous contracts) and motivates the vacuity review
  (4.4). Functional validation via uDebug test suites combines SMT proof with a
  test oracle. Source: [arXiv 2604.22601](https://arxiv.org/pdf/2604.22601).
- **Dafny as an opaque intermediate language (2025)** — alternative
  architecture: an LLM generates Dafny + proof, compiles to Python; the user
  never sees Dafny. Unsuitable for this repository (contracts should be runtime
  no-ops **in the same source code**), but methodologically instructive: spec
  agreement via natural language, consistency checks, Dafny-generated unit
  tests. Source: [arXiv 2501.06283](https://arxiv.org/abs/2501.06283).
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
  independent results extend the §4.2 loop from *code+contract generation*
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
  consequences for this repo: spec inference as a Phase-0 bootstrap task
  (plan §5.3 amendment), and a cross-LLM consistency gate against the 68%
  same-model circularity finding of §5.2 (plan §5.4 amendment).

## 4. Plan: Formal Verification of the Project Code

### 4.1 Verifiability Tiering of the Codebase

#### Tier A — Pure leaf logic (directly verifiable, highest value)

- **`text_validation.py` (165 LOC) / `design_normalization.py` (92 LOC)**:
  Everything LLMs output flows through these modules.
  - **Totality**: `Ensures` + static bounds checks on every index access prove:
    no `IndexError`/`KeyError`/`AttributeError` on **any** input — precisely
    the bug class that LLMs produce.
  - **Idempotence**: `Ensures(normalize(normalize(x)) == normalize(x))` —
    prevents corruption from double normalization.

  Review caveat (September 2026): `design_normalization.py` is **not**
  Pydantic-free — it imports `ArchitectureDesign` & co. from `src/schemas` and
  flattens via `model_copy(update=..., deep=True)`. Its idempotence proof
  therefore targets a `*_core.py` split over plain data with the Pydantic
  adapter kept at the boundary (plan §3.4/§3.8), mirroring the
  `text_validation` split.
- **`patterns/retriever.py` scoring mathematics**: monotonicity (higher score ⇒
  never a worse rank), stability of the top-k selection.
- **`config_expansion.py`**: pure expansion rules, determinism provable.

#### Tier B — Stateful job store (`tools/jobs.py`, 196 LOC)

The 5-state automaton `PENDING → RUNNING → {COMPLETED, FAILED, CANCELLED}` is a
textbook verification target — but **not directly**: the store is asyncio
(`aiosqlite`), so Nagini reaches it only via the synchronous twin
([`nagini-verification-plan.md` §3.6](nagini-verification-plan.md)); FizzBee
checks the protocol view (§2.3). Properties (proven in the twin, not inline):

- **Terminal states are immutable** (`J-1`, no transition back out of
  `COMPLETED`) — provable as an invariant with `Acc()`/predicate permissions
  in the twin.
- **Correct cancellation** (`J-2`): cancellation only takes effect from
  `PENDING`/`RUNNING` — exactly the property the `cancel_architecture_design`
  tool promises.
- **Monotonicity**: `created_at <= updated_at` as an invariant (`J-3`).
- **At most one RUNNING per job_id** (`J-4`): permission discipline on the store.
- **Eventual termination**: obligation contracts prove that no job stays stuck
  in `RUNNING` forever (database layer modeled as an IO operation or assumed
  via an abstract model).

**Implementation status (September 2026 review; sequencing fixed by the
fourth September 2026 amendment):** the automaton currently
exists by convention only — the transition setters in `src/tools/jobs.py` issue
unconditional `UPDATE`s (no `WHERE id = ? AND status IN (...)` guard) and
callers check-then-act under asyncio, so a cancel/completion race can move a
job out of `COMPLETED`. Rather than deferring the fix behind weeks of
contract work (the earlier Phase-4-entry-criterion shape), the guard fix is
now a **Week-0 standalone bug-fix PR** — one day, zero verification
infrastructure, under the documented unit-tested exemption from the
no-runtime-change rule (plan §3.6/§3.9). The properties are therefore *true
of the implementation before* the twin proofs, the `.fizz` model, and the
DST experiment claim them — fix first, prove after; the FizzBee F0 pilot
re-runs the historical violation via the in-spec A/B flip (§2.5, FizzBee plan
§3.5), and executable conformance tests couple twin and implementation
(§4.5, plan §3.6).

#### Tier C — Retry loop in `validation.py` (self-healing, 153 LOC)

Form of the provable contract:

```python
#   Invariant(MustTerminate(max_retries - attempt))
#   Ensures(IsValid(Result()) or Exsures(ValidationError, ...))
```

This proves that the retry loop **is guaranteed to terminate** (no infinite
self-healing spin on degenerate LLM responses) and that it has a total error
signature.

#### Tier D — Data contracts of the Pydantic schemas (`src/schemas/`)

Field constraints (e.g., `score ∈ [0, 10]`, non-empty `name`) can be mirrored as
`Ensures` clauses. Effect: downstream code (e.g., aggregations in
`pipeline.py`, `get_architecture_design_status`) may **rely on the invariants**
instead of defensively re-checking — eliminates a redundancy bug class.

#### Tier E — Secure information flow (bonus, experimental)

With `--sif` and `Low()` assertions one could prove that **API keys and
environment configuration never flow into LLM prompts or log output** — a real,
checkable information-flow property at the `reasoning/` boundary. Effort:
medium; performance penalty only during verification (SIF is a compile-time
option). **Precursor (fourth September 2026 amendment):** a *secret-canary
test* — distinctive fake key, mock LLM transport capturing outbound payloads,
`caplog` assertion of absence — buys the practical assurance at ~1% of the
cost from day one ([testing-strategies.md §3.2](testing-strategies.md));
**extended by E4 (fifth September 2026 amendment)** to assert the key value
never appears in *persisted* job state either — `jobs.result`/`jobs.error`
rows and the raw DB file — closing a leak path the prompt/log-only version
missed (a failed or cancelled job persists its `error` text to SQLite);
`--sif` proceeds only where the canary or review demonstrates residual risk.

#### Not verifiable (Tier F)

`reasoning/client.py` internals, embedder integration, prompt contents,
semantic design quality.

### 4.2 Meta-Synthesis: Verified-Code-Generation Loop

Since this repository **is written by LLMs**, the highest-leverage approach is
not after-the-fact specification but the installation of a **generate-verify
repair loop**:

```
LLM writes code + Nagini contracts
        ↓
Nagini verifies (CI gate on the annotated subset)
        ↓ error messages (position + violated contract)
LLM repairs ←────┘
```

Arguments for feasibility:

- The Nagini wiki explicitly calls its pitfalls "worth keeping in mind when
  writing specifications, **including with the help of an AI agent**" — the
  maintainers anticipate exactly this workflow.
- This repository's `mypy --strict` discipline is a significant head start: Nagini
  requires PEP 484-typed code, and it already exists here in full.
- Contracts are runtime no-ops ⇒ no violation of the rule "runtime behavior
  must not change". AGENTS.md forbids mypy plugins (zuban compatibility) —
  Nagini therefore runs as a **separate CI gate** alongside
  `make static-typing`, not integrated.

### 4.3 Recommended Roadmap

| Phase | Goal | Effort | Payoff |
|---|---|---|---|
| **0 — Pilot** | `text_validation.py` split + contracts (`design_normalization` core split follows the same pattern, §4.1); **mutation test**: planted bugs (off-by-one, None deref, infinite loop) must be caught by Nagini; **numeric Go/No-Go thresholds (§4.5)** | days | Empirical cost/benefit proof — the falsifiable experiment |
| **1** | `jobs.py` state automaton — guard fix already landed Week 0 (fourth amendment), then twin with permissions + invariants + conformance tests (§4.5) | ~1–2 weeks | Proven job integrity, correct cancellation — true of the implementation, not just the twin |
| **2** | `pipeline.py` control-logic model (attempt loop, cancellation points): FizzBee `.fizz` model (cheaper, counterexample traces, fault injection) or Nagini sync twin — see 2.3/2.5 | FizzBee: days–1 week; Nagini: ~1–2 weeks | Checked/proven boundedness + cancellation property |

Sequencing note (E8, fifth September 2026 amendment): the FizzBee F2 model
([fizzbee-verification-plan.md](fizzbee-verification-plan.md) §6.2) is the
**primary** pipeline artifact — 3–5 days, fault injection, counterexample
traces. The Nagini `pipeline_control_twin` (phase 7 of
[nagini-verification-plan.md](nagini-verification-plan.md)) is the **secondary**
artifact and proceeds only under that plan's phase-gate continuation rule —
its 2–4 week estimate is the single riskiest item in the roadmap (2,367-LOC
async source, zero team Nagini experience).
| **3** | Mirror Pydantic constraints as `Ensures`; optional SIF check of the secrets→prompt flow | ongoing | Invariant-based simplification downstream |
| **continuous** | LLM changes only with contracts; `nagini` as CI gate; Hypothesis PBT for non-verified modules as a cheaper fuzzing layer beneath | process | Verification as a system property, not a one-off act |

### 4.4 Evidence-Based Nagini Amendments (Fold into Phase 0)

The four evidence-based amendments are distributed thematically: #1 and #3 here,
#2 (mutmut gate) in 5.2, #4 (FizzBee models) in 2.5 — the items below therefore
carry the canonical numbers 1 and 3; #2/#4 are not missing here, they live in
their own sections.

1. **Adoption of `nagini_mcp` as the agent interface (new)**: Nagini now ships its own
   **MCP server** (`pip install "nagini[mcp]"`; tools `verify_file`,
   `verify_method`, `verify_snippet`, `configure`, `cancel`, `flush_cache`;
   in-process ViperServer backend; structured diagnostics including
   counterexamples). The project's agents already speak MCP — the integration
   and expertise friction (section 1.2.4) largely disappears; verify-repair runs
   natively in the agent loop (JetBrains finding: structured feedback
   diagnostics is the lever). Phase-0 effort: a single configuration line, with
   no workflow rewrite. Sources:
   [Nagini README (MCP section)](https://github.com/marcoeilers/nagini),
   [Docker image bigtalk-org/docker-nagini](https://github.com/bigtalk-org/docker-nagini)
   (Silicon and Carbon backend images for CI without a local Java installation),
   [JetBrains arXiv 2503.14183](https://arxiv.org/abs/2503.14183).
3. **Contract vacuity review as a process rule**: one AGENTS.md line — every
   `Requires`/`Ensures` must survive the phase-0 mutation set; a contract that
   planted bugs survive must be rejected ("non-trivial contracts only").
   Sources: [NL2VC-60, arXiv 2604.22601](https://arxiv.org/pdf/2604.22601),
   [VeriGuard, arXiv 2510.05156](https://arxiv.org/abs/2510.05156) (Google
   flags the same limitation).

**The decision procedure remains phase 0** (days, not weeks): plant a bug
garden and measure Nagini against Hypothesis. The measured delta *is* the
empirical added value of FV — this falsifiable experiment cannot be replaced by
further literature research. Acceptance is now numeric (§4.5.1).

### 4.5 Review Amendments (September 2026)

Findings from the post-plan review of both documents, folded into the roadmap
(plan-side counterparts: §3.4–3.6, §5.2, §5.5, §6.2–6.3 of
[`nagini-verification-plan.md`](nagini-verification-plan.md)):

1. **Numeric Phase-0 Go/No-Go thresholds** — "measure the delta" previously
   had no acceptance numbers: garden ≥ 20 planted mutants across the four
   classes (off-by-one, None-deref, unbounded loop, shape/KeyError); Nagini
   kills ≥ 90% of the garden with the Hypothesis-only baseline kill rate
   recorded alongside; contract overhead ≤ ~30% additional LOC in
   `*_core.py`; `verify_file` ≤ 60 s and `make verify-nagini` ≤ 3 min on CI
   hardware; the readability review (plan §3.1, principle 5) passes. Any
   miss ⇒ No-Go or descope — the affected property moves down to the
   Hypothesis/CrossHair layers (Appendix A.1). *(Third September 2026
   amendment: the plan-side §6.2 table is now canonical and extended with
   the discriminating dimension, garden bias control, DST head-to-head,
   lemmapy co-evaluation, spec inference, cross-LLM, async-linter, spec-
   coverage, and cost dimensions — the numbers above are its subset.)*
2. **Twin–implementation conformance discipline** — the weakest link of the
   twin concept is model drift, and this review found it is not hypothetical:
   the `jobs.py` transition setters currently issue unconditional `UPDATE`s,
   so terminal-state immutability is **false of the implementation today**.
   Countermeasures: properties get stable IDs (`J-1`…`J-4`, `P-1`) shared by
   twin contracts, the `.fizz` model, the Hypothesis oracles and the
   conformance tests; `tests/verification/test_jobs_conformance.py` drives
   twin and real `JobsStore` through identical Hypothesis-generated
   interleavings; the **Week-0** guarded `UPDATE`s (fourth September 2026
   amendment — pulled forward from the Phase-4 entry criterion) are a
   documented bug-fix exemption landed before the program begins
   (plan §3.6/§3.9).
3. **Nightly verifier canary (TCB guard)** — Nagini/Z3/Viper are part of the
   trusted computing base; a scheduled CI job re-runs the bug garden against
   the pinned versions, and a garden mutant that survives a `uv.lock` bump
   blocks the bump until triaged (plan §6.3).
4. **CrossHair promoted to a standing layer** — zero annotation cost and the
   shared `hypothesis[crosshair]` backend justify running it over pure
   modules from Phase 0 on (A.3); the demonstrated false-`verified` report
   (issue #354, Appendix A.1) confirms the "weak but useful peer of
   Hypothesis" classification — never a proof.
5. **ESBMC-Python landscape correction** — the appendix previously reported
   Python support for ESBMC as effectively nonexistent; wrong since ISSTA
   2024. Bounded and fragment-restricted (no displacement of Nagini), but its
   `--generate-pytest-testcase` (pytest generation from counterexamples) is a
   candidate for the repair loop; on the watch list (A.1/A.2).
6. **Contract-coverage report** — `make verify-coverage` lists functions in
   `NAGINI_FILES` with explicit contracts vs. default-safety-only, keeping
   the 5–10% scope decision visible in CI (plan §6.3).
7. **Performance smoke gate** — proofs guarantee functional correctness, not
   performance (AxDafny finding, 3.1): verified core functions get a coarse
   benchmark smoke so refactors cannot silently regress latency (plan §5.5).
8. **mutmut filter caveat** — mutmut's own docs warn the mypy/pyrefly type
   filter can hide valid mutants; the planted-bug garden, not filter survivor
   counts, stays the vacuity authority (5.2).

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
earned)
raises the mutation score 65% → 99%; study finding: up to **68% of AI-generated
test suites validated bugs** instead of catching them (same-model circularity —
the same blind spots shape code and tests). Sources:
[crucible](https://github.com/Jott2121/crucible),
[Augment: Mutation Testing for AI-Generated Code](https://www.augmentcode.com/guides/mutation-testing-ai-generated-code),
[mutmut docs](https://mutmut.readthedocs.io/en/latest/) (mypy integration
filters type-invalid mutants — synergy with `mypy --strict`).

**Use in this repository (Amendment 2)**: `mutmut` as a `make mutation-tests` gate
over Tier A/B/C + `tests/verification/`: audits the Hypothesis oracles
themselves and kills the same-model circularity (68% finding). Synergy: mutmut
uses mypy for mutant filtering — with the documented caveat that the filter can
hide *valid* mutants; the planted-bug garden (§4.5), not filter survivor
counts, remains the vacuity authority. Optional later: a crucible-style
tester/critic loop over the survivors.

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

### 6.1 Verdict: Formal Verification as the Tip of a Layered Stack

The question of whether FV is the best approach constitutes a false dichotomy.
Consistent with the evidence is a **composition model** (defense in depth): the
layers' blind spots are decorrelated, so the residuals multiply; each layer's
marginal benefit depends on what the others already cover:

- **Yes for T1, as the tip**: FV is the only technique that upgrades "tested on
  samples" to "proven on all inputs" — precisely suited to code that no one
  reads in full. mypy-strict + Pydantic + unit tests already exist here ⇒ their
  residual (unguarded index/None, non-termination, state corruption, aliasing)
  is precisely Nagini's core competence on Tier A/B/C — maximum marginal
  benefit.
- **No as a total strategy**: vacuous specs verify trivially (NL2VC-60);
  whole-program verification is illusory at seL4/CompCert cost (11 person-years,
  3× code size) — this document's 5–10% scoping decision is correct;
  asyncio/Pydantic internals remain black boxes; no existing tool proves T2
  (design quality); it remains the domain of evaluation rubrics and human
  review.
- **Layer evidence**: VeriGuard (FV + tests + enforcement), Nightjar (6 stages
  with degradation), crucible (mutation audits AI tests), industry consensus
  stack (5.4) — no successful project uses FV *alone*; all combine.
- **Extension by the model-checking cell (FizzBee, section 2)**: the stack
  above is deductive at the code level; FizzBee adds model checking at the
  design level — temporal properties (liveness, deadlock freedom) over **all
  interleavings** of a finite model, with fault injection — addresses exactly
  the asyncio and interleaving gaps from section 1.2 that Nagini leaves open.
- **What the third September 2026 evidence pass adds (three new categories,
  folded into the plan as amendments):** (a) **deterministic simulation
  testing for asyncio** — simloom (`systematic=True` = exhaustive
  delay-bounded model checking of unmodified asyncio code, with
  safety/liveness oracles and a serializability checker), frontrun
  (DPOR-based, Rust engine), seedloop, askew — a category that did not exist
  for asyncio in early 2026 and now provides *bounded proof on the
  implementation itself*, complementing (not replacing) the FizzBee
  model view and the Nagini twin (§2.7; plan §3.6 amendment); (b)
  **VLP-style intermediate-artifact review** — the docstring-as-NL-Doc
  discipline promoted to a machine-checked consistency gate, on 84%-vs-40%
  evidence (plan §3.3/§5.4 amendments); (c) **cross-LLM consistency**
  (Clover, airtight-ai) — mechanical enforcement against the same-model
  circularity of §5.2   (plan §5.4 amendment). The §6.1 conclusion — FV as
  the tip of a layered stack — is unchanged; the stack simply has more
  layers with stronger mechanistic guarantees than when this document was
  first drafted.
- **What the fifth September 2026 review pass adds (E1–E8, governance
  sharpenings):** (a) **gate-gameability control (E1)** — the DST
  acceptance now requires ≥ 1 of `J-1`/`J-2`, because a criterion
  satisfiable by the near-trivial `J-3`/`J-4` measures nothing; (b)
  **program independence (E2)** — the FizzBee program and the Nagini
  program are independent decision units: either Phase-0 gate can stop its
  own program without stopping the other (the docs previously stated only
  the FizzBee→Nagini direction); (c) **model-identity pinning (E3)** — the
  cross-LLM consistency gate records the second model's identity and
  version per run, so a weak checker cannot silently inflate a "clean"
  score; (d) **leak-surface extension (E4)** — the secret canary now covers
  persisted job state, not just prompts and logs; (e) **reasoning-client
  oracle (E5)** — timeout/retry behaviour of the LiteLLM boundary gets a
  Hypothesis property (timeout → structured error, bounded retries), the
  one wrapper surface previously owned by no layer; (f) **lock
  injectability (E6)** — the `JobsStore` singleton lock becomes
  constructor-injectable in Week 0, unlocking parallel state-machine
  testing; (g) **evidence self-audit (E7)** — the citations this document
  builds on are themselves part of the TCB and get a quarterly
  existence/version re-check beside the tool-vitality table; (h)
  **pipeline-twin sequencing (E8)** — FizzBee F2 first, Nagini twin
  demoted behind the continuation rule.

### 6.2 Conclusion

Nagini cannot fully secure this project — asyncio (now partially addressable
via FizzBee models, see section 2), Pydantic internals, and the semantic
quality of the architecture designs remain out of reach. But it can prove, for
the deterministic core (validation, normalization, job management, scoring),
what tests only show by sampling: **correct on all inputs, terminating,
state-consistent**. Precisely because the code originates from LLMs, the
combination of mypy-strict (existing) + contracts as a CI gate + a
verify-repair loop is the most consistent trust strategy. The external evidence
(section 3) confirms this pattern: VeriGuard (Google), Nightjar, and the
industry consensus stack deploy formal verification exclusively as the tip of a
layered stack — never as a sole solution; FizzBee complements as the
model-checking cell exactly the interleaving and asyncio gaps (section 2). The
four amendments further reduce adoption costs: `nagini_mcp` + vacuity review
(4.4), mutmut gate (5.2), FizzBee models (2.5); the review amendments (4.5)
harden the twin-coupling, tool-trust, and scope-visibility story. Phase 0
costs days and delivers the data for the Go/No-Go decision — now against
numeric thresholds (4.5).

## Appendix — Tool Landscape: Alternatives to Nagini

> Research status: September 2026 (Exa web search; project repositories and
> documentation). Answers the question *"are there better alternatives than
> Nagini?"* — separately for Python (A.1), for other languages (A.2), and with
> the consequence for this repository (A.3). Classification follows the two
> axes of section 2.2 (*what* is checked: implementation vs. design model;
> *how*: deductive proof vs. bounded exploration), extended by soundness and
> by the same-source-contracts criterion (contracts must be runtime no-ops in
> the shipped Python — section 1.1).

### A.1 Python — Direct Alternatives and Complements

| Tool | Cell / approach | Soundness / guarantee | Contracts in same source? | Maturity | Assessment for this repo |
|---|---|---|---|---|---|
| **Nagini** | Deductive, modular (Viper/Z3, separation-logic permissions) | Sound ∀-inputs proof; termination, race freedom, IO/permission discipline | Yes (`nagini_contracts`, runtime no-ops) | 8 yrs, active (v1.3.1: MCP/LSP servers, ViperServer) | **The choice** (sections 1, 4) |
| **CrossHair** | Symbolic execution (Z3), counterexample search | **Not sound** — bounded path exploration; assumes termination, closed class hierarchies, single-threaded, determinism ([own soundness discussion](https://github.com/pschanely/CrossHair/discussions/156)) | Yes — plain `assert`, PEP-316 docstrings, icontract/deal; no new imports, no JVM | Mature ([GitHub](https://github.com/pschanely/CrossHair)) | Strongest **complement**, not replacement: peer of Hypothesis, not of the verifier |
| **ESBMC-Python** | Bounded model checking (SMT over GOTO IR; CPython 3.10 parser) | **Not sound ∀-inputs** — bounded unwinding; restricted fragment (only `range()`-`for` loops; partial list/str/dict support) | No — `assert`/`assume` harnesses | Active research tool ([ISSTA 2024](https://doi.org/10.1145/3650212.3685304), generator support merged 2026) | Landscape correction (September 2026 review: previously mis-reported as nonexistent — §A.2); `--generate-pytest-testcase` (pytest from counterexamples) is a repair-loop candidate; fragment too narrow for this codebase |
| **icontract / deal / beartype** | Runtime Design-by-Contract | Checked per call at runtime — enforcement, not proof | Yes | Mature ([icontract](https://github.com/Parquery/icontract), [deal](https://github.com/life4/deal)) | Cheap optional runtime layer beneath the static ones |
| **Dafny** | Deductive (Boogie/Z3), own language | Sound; best SMT automation and best LLM tooling (DafnyBench, AxDafny — 3.1) | No — extraction to Python; contracts are not no-ops in shipped source | Very mature ([dafny.org](https://dafny.org)) | Rejected as opaque intermediate (3.1); backend of choice for the new Python front-ends below |
| **veripy** (ZJU-PL, 2025) | Auto-active VC generation, Dafny/Verus-style | Self-declared **"not sound for full Python"** — restricted fragment (side-effect-free int/bool/mathematical arrays; aliasing/exceptions approximated) | Yes (decorators) | Early ([GitHub](https://github.com/ZJU-PL/veripy), [PyPI](https://pypi.org/project/py-veripy/)) | Fragment does not cover this codebase (state, exceptions, aliasing) |
| **lemmapy** (v0.1.0a1, M0–M2 complete) | `#@` comment specs on production Python → runtime contracts (CrossHair-executable) + Dafny SMT proofs, plus conformance checker, boundary guards, island integrity, translation validation vs. CPython | Careful **layered** soundness (four independent mechanisms) under explicit assumptions A1–A7; continuous `difftest` differential testing | Yes — `#@` comments, ignored by CPython | Alpha but fast-moving (2026-08-15 release: LSP, `lemmapy repair` proof-repair loop, 16/16 corpus proven, 81% mutant kill; [PyPI](https://pypi.org/project/lemmapy/)) | **Phase-0 co-evaluation** (promoted from watch list, September 2026 third amendment — see §A.3); nearest architectural competitor to Nagini |
| **Strata-Python** (AWS) | Python → Laurel IVL → SMT | Sound for its fragment; machine-oriented serialized specs | Partially | Early | Watch list |
| **dafny-of-python** | Deductive verification of a Python subset via Dafny | Sound on the subset | Yes-ish | Research ([GitHub](https://github.com/arsalan0c/dafny-of-python)) | Instructive only |
| **PyExZ3** | Symbolic execution (academic predecessor) | Bounded | n/a | Unmaintained | Superseded by CrossHair as the practical implementation |
| **2vyper** | Deductive (Viper) for the Vyper smart-contract language | Sound | n/a | ETH, active-ish | Different domain (Nagini's sibling for EVM contracts) |
| **Pyre/Pysa · mypy · pyright** | Type systems + taint analysis | Sound only w.r.t. the checked type properties — no functional correctness | n/a | Mature | Already present: `mypy --strict` (and a Nagini prerequisite, 4.2) |
| **Nightjar** | Orchestrator: Pydantic → CrossHair → Hypothesis → Dafny/CEGIS | Layered, degrades gracefully without Dafny | `.card.md` spec sidecars | New ([GitHub](https://github.com/j4ngzzz/Nightjar)) | Pattern reference, not a component (3.1) |

**Verdict (Python):** for the target cell — *sound, modular, ∀-inputs proof of
implementation-level Python with contracts as runtime no-ops in the same
source* — Nagini remains the only production-grade occupant in 2026. Every
alternative either gives up soundness (CrossHair, PyExZ3, ESBMC-Python), restricts the
language fragment (veripy, Strata-Python, dafny-of-python), uses another
prover language with extraction (Dafny, lemmapy, Nightjar — the route
rejected in 3.1 for this repo, though lemmapy's translation-validation and
agent layers earned it the §A.1 Phase-0 co-evaluation below), or checks
something weaker (runtime DbC, types).
Independent confirmation: VeriGuard (Google) surveyed the field and chose
Nagini "as a black box" precisely because it "can handle more complex
properties than other available Python verifiers" (3.1).

**CrossHair deserves the closer look** because it is the one addition that
pays off regardless of the Nagini decision: zero annotation-language barrier
(plain `assert`s), pure-Python install without JVM, counterexample output,
usable as a [Hypothesis
backend](https://hypothesis.readthedocs.io/en/latest/strategies.html#alternative-backends),
and productively deployed as the "negation proof" stage in Nightjar (3.1).
Its documented unsoundness conditions (termination assumed, closed type
hierarchies, single-threadedness) mean a "confirmed over all paths" from
CrossHair is a much weaker statement than a Nagini proof — it slots into the
stack *next to Hypothesis* (5.3), one layer beneath the deductive tip — a
weakness demonstrated in practice by [issue
#354](https://github.com/pschanely/CrossHair/issues/354) (2025: CrossHair
reported `verified` on a failing property; **since fixed** in
`hypothesis-crosshair` v0.0.30 — "prevent an incorrect verified claim under
SMT-heavy analysis" — so the headline false-`verified` failure mode is
mitigated, while the structural weakness — bounded search is not proof —
remains and keeps the classification: peer of Hypothesis, never of the
deductive verifier). The Phase-0 bug garden (4.4) runs
as a three-way experiment Nagini vs. CrossHair vs. Hypothesis; given its zero
annotation cost, the September 2026 review promotes CrossHair from experiment
to a **standing CI layer** over pure modules (A.3, 4.5).

**Watch list → Phase-0 co-evaluation:** lemmapy is **promoted from the watch
list to a Phase-0 co-evaluation** (September 2026 third amendment). The
2026-08-15 M2 release crossed the threshold where "watch" undersells the
evidence: `#@` specs compile to *runtime contracts* that CrossHair searches
for counterexamples **and** translate to Dafny for SMT proofs; all four
soundness layers are built (conformance checker, boundary guards, island
integrity A1–A7, continuous translation validation via Dafny's Python
backend — differential testing against CPython, the most honest treatment
of the "model ≠ CPython" gap any tool in this table attempts); the agent
layer is live (LSP at two speeds, `lemmapy repair` proof-repair loop,
structured `--json` failures); 16/16 corpus functions proven with 81% of
mutants refuted by the specs. Its own positioning against the incumbent:
*"Nagini proves the front-end shape works (typed Python, shallowly encoded
into an IVL); this project trades its Viper permission logic for SMT/LLM
automation and adds the boundary-guard and translation-validation layers."*

**Head-to-head protocol (executes in Phase 0, alongside the bug garden):**
both tools attempt the identical end-to-end proof of
`src/text_validation_core.py` against the identical Phase-0 garden.
*Promotion criteria (all must hold):* annotation overhead < 2× Nagini's
(plan §6.2 telemetry); MCP/LSP parity for the agent loop; `difftest`
false-positive rate ≤ 5% on the garden; the typed fragment admits the full
file without carve-outs. *Rejection:* any criterion fails — recorded with
the specific number in `docs/phase-0-decisions.md`. Either outcome leaves
Nagini's Phase-0 gates unchanged; this is a falsifiable upgrade path, not a
strategic pivot.

**Remaining watch list:** veripy (now with a Lean backend and automatic
invariant inference), Strata-Python (PySpec pipeline landing), ESBMC-Python
(fragment coverage may grow — currently too narrow for this codebase).
None of these is far enough along for a bet; reassess at the Phase-0
Go/No-Go.

### A.2 Other Languages — The Same Cells Elsewhere

The two-axis taxonomy of 2.2 generalizes: every mature ecosystem has (at most)
one sound, same-language deductive verifier, plus bounded/symbolic layers
beneath it and design-level checkers above it:

| Ecosystem | Tool(s) | Cell | Notes |
|---|---|---|---|
| Java | [OpenJML](https://www.openjml.org) (JML contracts), VeriFast, KeY | Deductive, same-language contracts | OpenJML is "the Nagini of Java" — JML annotations are comments in Java source |
| C | [Frama-C/ACSL](https://frama-c.com) (WP plugin + Alt-Ergo/Why3), [CBMC](https://www.cprover.org/cbmc/), [ESBMC](https://esbmc.org) | Deductive + bounded model checking | CBMC/ESBMC are bounded (like the FizzBee cell, but at code level); Python support exists via **ESBMC-Python** (A.1) — bounded and fragment-restricted (corrected September 2026) |
| Rust | [Prusti](https://github.com/viperproject/prusti-dev) (Viper-based — Nagini's sibling), [Verus](https://github.com/verus-lang/verus) (SMT verification conditions), [Kani](https://github.com/model-checking/kani) (BMC, AWS) | Deductive + BMC | Verus covered by the JetBrains benchmark (3.1); Kani is the bounded layer |
| Own-language ecosystems | [Dafny](https://dafny.org) (.NET/Go/Java/Python extraction), [F*](https://www.fstar-lang.org) (dependent types; Vale, EverParse), [Why3](https://why3.lri.fr)/WhyML | Deductive | Dafny optimizes automation for humans/LLMs; F* optimizes expressiveness at proof cost |
| Interactive proof assistants | Coq (CompCert), Lean, Isabelle/HOL (seL4) | Manual proof, code extraction | The 11-person-year cost class referenced in 6.1 — not automation, categorically different effort model |
| Design level (language-agnostic) | [TLA+](https://lamport.azurewebsites.net/tla/tla.html)/TLC/TLAPS, Alloy, [Stateright](https://github.com/stateright/stateright) (state machines), FizzBee (section 2) | Model checking of specs | TLA+ is the incumbent FizzBee positions against; Stateright checks API/protocol state machines |
| Smart contracts | 2vyper (A.1) | Deductive | Vyper, not Python runtime code |

Two observations transfer back to this repository:

1. **The convergent architecture**: no ecosystem relies on a single tool —
   the sound deductive verifier is always the *tip* over bounded layers
   (Kani/CBMC ≈ CrossHair/Hypothesis) and design-level checkers (TLA+ ≈
   FizzBee). This independently reproduces the layered-stack thesis of
   section 6 from the tooling side.
2. **Why porting is not an option here**: Dafny/Verus/F*/Prusti all assume
   their host language's runtime and contracts-in-source model; using them
   for this Python codebase means extraction or translation — the opaque-
   intermediate route already rejected in 3.1 (contracts must be no-ops in
   the *same* shipped source, and `tests/unit/` must remain the behavioural
   oracle).

### A.3 Consequence for This Repository

- **Keep Nagini** for the deductive tip (T1, Tier A/B/C) — no better tool
  occupies its cell for Python in 2026.
- **Add CrossHair as a standing bounded layer** next to Hypothesis (peer
  level, not proof level) — zero annotation cost, shared
  `hypothesis[crosshair]` backend; the Phase-0 bug garden remains the honest
  referee that measures whether Nagini's annotation cost buys a real delta
  over the cheaper layers (4.4, 4.5).
- **Lemmapy co-evaluation at the Phase-0 Go/No-Go** (promoted from the
  watch list, third September 2026 amendment — full protocol in §A.1):
  head-to-head proof of `text_validation_core.py` against the same bug
  garden, with explicit promotion/rejection criteria. The remaining watch
  list (veripy, Strata-Python, ESBMC-Python) is reassessed at the Phase-0
  Go/No-Go and again after phase 2 — the field is moving quickly.
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
  layers, Nagini comparison in project description; v0.1.0a1 2026-08-15
  release notes — M0–M2 status, 16/16 corpus, 81% mutant kill, LSP,
  `lemmapy repair`)
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
