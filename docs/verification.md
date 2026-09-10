# Verification — architecture-pattern-mcp

> **Status:** summary of the implemented verification and testing program
> (September 2026). This document summarizes the layered stack: which layer
> exists, which frameworks it uses, what it tests/verifies, and where its
> gate lives. It summarizes; it does not replace the owning documents:
> [`testing-strategies.md`](testing-strategies.md) (the stack),
> [`nagini-verification-plan.md`](nagini-verification-plan.md) (L5/L6),
> [`fizzbee-verification-plan.md`](fizzbee-verification-plan.md) (L4),
> [`formal_verification.md`](formal_verification.md) (rationale),
> [`phase-0-decisions.md`](phase-0-decisions.md) (run outcomes and
> provisioning notes), [`review-checklist.md`](review-checklist.md) (L10).

## The trust model in one paragraph

The server's code is LLM-generated and nobody reads all of it. The program
splits trust into decorrelated layers so their blind spots multiply instead of
add: cheap layers (types, unit tests) run always; expensive layers
(model checking, deductive proof) are opt-in and scoped to the critical
~5–10% of modules. Two boundaries are absolute:

- **T1 vs T2:** mechanical layers verify that the *machinery* fails on no
  input (T1). No layer judges whether a generated *design* is good (T2) —
  that stays with evaluation rubrics and human review (L10).
- **Vacuity control:** every oracle must be able to fail. Assertions and
  contracts are accepted only if they kill garden mutants (L3) or carry a
  justification (`# spec-explains:`).

## The stack at a glance

| Layer | Framework(s) | What it tests / verifies | Gate | Status |
|---|---|---|---|---|
| L0 | ruff, mypy `--strict` (zuban), vulture, deptry | style, type errors, dead code, dependency hygiene | pre-commit + CI (`make check-lint check-static-typing check-deadcode check-depcheck`) | active |
| L1 | pytest | chosen-input behaviour, regressions; secret canary (no key leakage into prompts/logs/persisted state) | `make test-unit`, `make test-oracles` | active |
| L1b | Hypothesis (payload strategies) | MCP tool-call boundary robustness: malformed/nested/oversized payloads — structured errors only, no tracebacks | collected by `make test-oracles` (advisory → blocking Phase 1) | harness active, generators expanding |
| L2 | Hypothesis | input-space properties: job-lifecycle interleavings vs shadow automaton (J-1..J-4), LLM-boundary timeout/retry discipline (E5), normalization idempotence/dedup (N-1..N-4) | `make test-oracles` | active |
| L3 | mutmut + planted-bug gardens | tests-the-tests: tautological oracles, vacuous contracts/assertions; the garden is the vacuity authority | `make test-mutations` (manual/nightly) | garden active; mutmut nightly |
| L4 | FizzBee (`.fizz` models) | **all interleavings up to bounds**: races, crash windows, guard gaps, deadlock freedom, fault injection; 7 models over the job protocol, the background-task lifecycle + cancel tool, the pipeline stage machine, design-loop triage, reasoning-client deadline/retry/cache, TEI rerank verdicts, retrieval resolution | `make verify-fizz` (CI-authoritative) | active (7 specs, 31 garden mutants) |
| L5 | Nagini (Viper/Z3) | **active** — the pure decision cores (text_validation_core, design_normalization_core) carry explicit Requires/Ensures/Invariant contracts and verify with the Nagini CLI (`make verify-nagini`, dedicated `.venv-nagini` venv) and the MCP server (`nagini_verify_file`); Unicode facts and Pydantic object graphs are trusted adapter precomputations | `make verify-nagini` / `make verify-coverage` | active |
| L6 | deterministic simulation (native now; simloom/frontrun on provisioning) | real asyncio schedules of the **real implementation**: bounded, seeded, replayable proof of J-1/J-2 under all race schedules | `tests/verification/test_jobs_dst.py` (always on) | active (native), proven |
| L7 | deptry, uv.lock pinning, pip-audit, import-inventory diff | supply chain: hallucinated/unused/vulnerable deps; slopsquatting defence (new package names need human decision) | `make check-depcheck`, `make verify-import-inventory` | active |
| L8 | ledger checker, NL-Doc cross-consistency | intent drift: code ≠ docstring ≠ contract ≠ model; property-ID mapping mechanically checked | `make verify-ledger`, `make verify-cross-consistency` (advisory) | active (mechanical subset) |
| L9 | in-repo corpus + structural invariants (`tests/eval/`) | well-formedness and internal consistency of LLM output: section completeness, reference closure, producer+consumer pairs, catalogue existence, score ranges | `llm` marker + `ARCH_BENCH_LLM=1` (live); offline vacuity guard always on | active |
| L10 | human review, perf smoke, nightly canaries | T2 (design quality), vacuity triage, bound/fairness justification, verified-core latency budgets, TCB regressions | PR review (required paths) + `.github/workflows/verification.yml` | active |

## Layer details

### L1 — Unit testing (`pytest`)
The behavioural oracle that defines "no runtime behaviour change" for every
refactor. `tests/unit/` (900+ tests) plus the Week-0 deliverable
`tests/verification/test_secret_canary.py`: a distinctive fake API key is set
through the real configuration boundary and asserted absent from outbound LLM
payloads, every log record, and — E4 extension — persisted job state
(`jobs.result`/`jobs.error` columns and the raw DB file bytes). Negative
controls prove every capture surface works.

### L1b — MCP boundary fuzzing (Hypothesis)
The tool-call surface is attacked with schema-derived plus malformed-payload
strategies; for every generated payload: no unhandled exception escapes, every
error matches the structured error shape, no traceback leaks. Rides the same
collection target as L2; payload generators widen with the tool surface.

### L2 — Property-based testing (`Hypothesis`)
Generated inputs instead of chosen ones, keyed by the shared property IDs:

- `test_jobs_properties.py` — generated operation sequences replayed against
  the real `JobsStore`; a shadow model of the guarded automaton predicts every
  accepted/rejected transition (J-1 terminal immutability, J-2 cancel scope,
  J-3 timestamp monotonicity, J-4 one row per job).
- E5 reasoning-client oracle — failure schedules over the self-healing retry
  loop: structured errors retried, attempts bounded by `max_retries + 1`,
  raw transport failures surface as structured `LLMError`, never a hang.
- `test_normalization_idempotence.py` — N-1 idempotence and N-2..N-4 dedup
  invariants over generated designs.

### L3 — Mutation testing (`mutmut` + gardens)
The oracle-on-oracles audit, answering the same-model circularity finding
(AI test suites validate bugs instead of catching them). Two mechanisms:

1. `tests/verification/gardens/bug_garden.py` — 21 planted mutants across the
   four documented classes (off-by-one, None-deref, unbounded-loop,
   shape/KeyError); `test_bug_garden.py` asserts every kill oracle passes on
   the reference and fails on the mutant.
2. `mutmut` over the Tier A/B/C modules (`make test-mutations`); its mypy
   filter caveat is documented — the garden, not survivor counts, is the
   vacuity authority.

Later oracle layers (Nagini contracts, `.fizz` assertions) must kill the same
mutant IDs or are rejected as vacuous (AGENTS.md rule).

### L4 — Model checking (`FizzBee`)
Exhaustive exploration of **all interleavings up to stated bounds** with
implicit fault injection (crash at yield points, message loss) — the
protocol-level view no other layer can produce. Artifacts:

- `specs/fizz/jobs_protocol.fizz` — job store (durable, atomic guarded
  transitions) × symmetric clients (crash-on-yield); the `GUARDED` constant
  is the F0 A/B flip: `False` reproduces the historical J-1 violation
  trace, `True` (current implementation) must hold. Also carries the two
  liveness rows: FC-1 (every RUNNING job of an alive client eventually
  leaves RUNNING) and FC-2 (an acknowledged cancel ends CANCELLED).
- `specs/fizz/jobs_runner.fizz` — the background task lifecycle
  (`_run_job`) and the cancel tool against the store: W0-1 checkpoints,
  the terminal-write race, the done-callback task-map cleanup (RUN-1/3/4,
  C-1); J-1's kill authority lives here (the terminal-write race is the
  genuine second-write path).
- `specs/fizz/pipeline_control.fizz` — pipeline stage machine
  (ANALYZE→GENERATE→EVALUATE→REFINE, attempts ≤ 3) with an unreliable LLM
  environment (`oneof` respond/fail) and a bounded fair retry tick;
  FP-2..FP-7 including the FP-5 liveness row (every run eventually ends).
- `specs/fizz/design_loop.fizz` — `design_loop` triage decisions: guarded
  best-score update, early stop, cancel checkpoint, malformed-continue
  (DL-2..DL-5).
- `specs/fizz/reasoning_retry.fizz` — the reasoning client's `wait_for`
  deadline (E5F-1/2) and the trace cache's LRU + single-flight discipline
  (E5F-3/4).
- `specs/fizz/tei_fallback.fizz` — TEI reranker verdict discipline
  (TEI-1) and the no-partial-result-on-rerank-error rule (RET-1).
- `specs/fizz/retrieval_fusion.fizz` — the retrieval resolution tail:
  real outcomes carry patterns and passed the floor (FUS-1/2); fallbacks
  are tagged (FUS-3).
- `specs/fizz/README.md` — the property-ID ledger coupling every assertion
  to its twin contract, Hypothesis oracle, and conformance test, plus the
  spec garden (FG-01..FG-31, each re-validated on the toolchain
  2026-09-10) and run-stats table.

Frozen counterexamples are replayed against the real store in
`tests/verification/test_fizz_traces.py`, independent of tool availability.

### L5 — Deductive verification (`Nagini` / Viper-Z3) — active via MCP
The only layer whose verdict is universal over inputs, scoped to the critical
5–10% (`NAGINI_FILES`, reported by `make verify-coverage`).

Verification runs with the Nagini CLI (`make verify-nagini`, which provisions
a dedicated `.venv-nagini` venv because the CLI pins `mypy==1.5.0`) and with
the Nagini MCP server tools (`nagini_verify_file`) over the two pure decision
cores:

- `src/text_validation_core.py` — the printable-text decision engine.
  Nagini cannot translate the Unicode operations (`unicodedata.category`,
  `str.isspace`, `ord`, `strip`), so the Pydantic adapter
  (`src/text_validation.py`) precomputes per-character facts (category codes,
  strip-whitespace flags, allowed-whitespace flags) and the core decides over
  plain lists. Verified properties: totality (no crash on any input), verdict
  well-formedness, the first-disallowed-character scan, the maximal strip
  window, the length check, and the letter/digit presence check.
- `src/design_normalization_core.py` — the denormalization decision core.
  The Pydantic object graphs and `typing.Protocol` are outside Nagini's
  subset, so the adapter (`src/design_normalization.py`) extracts plain keys
  (component_ids, (name, is_shared) tuples, event names) and maps the core's
  key lists back onto the original objects with a first-occurrence scan.
  Verified properties: N-2 dedup (no duplicate keys), coverage (no loss) and
  subset (no hallucinated keys) for all three promotion rules.

The contract vocabulary is provided by a local, typed, runtime-inert stub
package (`nagini_contracts/`) — Nagini recognises contract calls by name and
ignores that module; the real `nagini-contracts` distribution cannot be
installed here (it pins `mypy==1.5.0`, conflicting with the dev group).
Quantifier results that feed runtime decisions (the membership tests in the
promotion loops) evaluate for real in the stub; contract-position quantifiers
are inert, so the contracts cost nothing at runtime.

The honest-claims boundary stands: the verified fragments are correct on all
inputs, assuming the adapter precomputations (Unicode oracles, key
extraction) are correct — those are pinned by the L1/L2 behavioral oracles
(`tests/unit/test_text_validation.py`, `tests/unit/test_normalization.py`,
`tests/verification/test_normalization_idempotence.py`).

#### Why not the whole tree

`make verify-nagini` deliberately covers only the annotated cores. Nagini
verifies the target file **and all transitive imports** (CAV'18), so a module
can enter the set only if its entire import graph is inside the supported
subset. Empirically (nagini MCP server, per module):

| src/ module class | Verdict | Reason |
|---|---|---|
| `text_validation_core`, `design_normalization_core` | verifies | pure decision logic, annotated |
| `errors.py` | untranslatable | module-level constants violate the static-field subset |
| `schemas/enums.py` | untranslatable | `class X(str, Enum)` — subclassing a builtin type unsupported |
| `prompts/style_guidance.py` | untranslatable | 300-line module-level dict constant overflows the prover |
| `config_expansion.py` | untranslatable | `re` module, `Any`-typed recursion |
| everything else (`tools/*`, `schemas/*`, `pipeline.py`, `agent.py`, `patterns/*`, `server.py`, ...) | untranslatable | imports pydantic / fastmcp / llama_index / litellm / httpx / aiosqlite / numpy / faiss / click / dotenv |

Scope discipline adds a second reason: the documented L5 decision (critical
5–10%, never the tree). Every verified fragment costs prover time and every
contract must be non-vacuous (AGENTS.md); verifying error constants or enums
would add minutes without adding decision-logic assurance. The critical
decision logic in this codebase is exactly the two cores — the rest is
LLM/Pydantic/FastMCP plumbing whose behavior is pinned by the L1/L2/L4/L6
layers instead.

### L6 — Deterministic simulation (DST)
Exercises the **real implementation's actual schedules** — no model, no twin,
no drift. `tests/verification/test_jobs_dst.py` runs two deterministic modes:
exhaustive micro-step interleaving of the cancel/completion race (all 6
order-preserving schedules) and seeded real-asyncio races; both prove J-1 and
J-2 on the real store with a can-fail oracle (the guard must reject the
historical race schedule). Written so the scenarios map 1:1 onto simloom
(`systematic=True`) / frontrun (DPOR) when provisioned.

### L7 — Dependency & supply chain (`deptry`, `pip-audit`, inventory diff)
AI code hallucinates dependencies (19.7% in the USENIX '25 study →
slopsquatting). Defences: full `uv.lock` pinning, `deptry` hygiene
(`make check-depcheck`) and the import-inventory drift gate
(`make verify-import-inventory` — a new third-party root fails the build
until a human reviews it).

### L8 — Spec & doc-level testing (intent layer)
Aimed above the code: intent drift between prompt, docstring, contract,
model, and implementation.

- `make verify-ledger` — every property ID referenced in an artifact must
  have a `specs/fizz/README.md` ledger row, and every row must reference an
  existing artifact or be explicitly deferred.
- `make verify-cross-consistency` — the NL-Doc gate (VLP evidence: validating
  an intermediate artifact beats direct code review 84% vs 40%). Mechanical
  subset now (every public function in `NAGINI_FILES` carries a docstring);
  the LLM comparison activates via `ARCH_CONSISTENCY_MODEL`, with the checker
  model identity pinned per run (E3).

### L9 — LLM-output contract corpus (`tests/eval/`)
The mechanizable slice between T1 and T2: deterministic structural invariants
over generated designs — INV-1 section completeness, INV-2 component-id
uniqueness, INV-3 relationship closure, INV-4 event producer+consumer
closure, INV-5 api-contract resolution, INV-6 cited pattern exists in the
catalogue, INV-7 score ranges. The corpus (five catalogue families) runs
through the real pipeline under `ARCH_BENCH_LLM`; the tracked pass-rate is
the drift gate for prompt/model changes. Offline tests prove every invariant
fails on its bug class. Boundary sentence: certifies well-formedness and
internal consistency — never design quality.

### L10 — Human review + canaries
Humans judge T2 and the calls machines cannot make: vacuity triage, bound
justification, fairness assumptions, No-Go decisions. Programmed elements:
`docs/review-checklist.md` (required-review paths), the perf smoke canary
(`tests/verification/test_perf_smoke.py`, RUN_PERF — proofs guarantee
functional correctness, not performance), and the nightly TCB canary workflow
(`.github/workflows/verification.yml`: gardens, oracle suites, ledger,
inventory, perf smoke blocking; mutmut/Nagini/FizzBee/pip-audit advisory).

## Shared property vocabulary

One ID per property across all layers (drift is reviewable 1:1 via the
`specs/fizz/README.md` ledger):

| ID | Property | Layers |
|---|---|---|
| `J-1` | terminal job states immutable | L2, L3, L4, L5, L6, frozen traces |
| `J-2` | cancel effective only from pending/running | L2, L4, L5, L6 |
| `J-3` | `created_at <= updated_at` always | L2, L4, L5 |
| `J-4` | one running row per job_id | L2, L4, L5 |
| `P-1` | pipeline attempt loop bounded (≤ 3) | L4, L5 |
| `FP-2..FP-7`, `FC-1`, `FC-2` | pipeline/order/liveness (FizzBee-only) | L4 |
| `RUN-1`, `RUN-3`, `RUN-4`, `C-1` | background-task lifecycle + cancel-tool triage (FizzBee-only) | L4 |
| `E5F-1..E5F-4` | reasoning-client deadline/retry/cache discipline (FizzBee view of E5) | L4 |
| `TEI-1`, `RET-1`, `FUS-1..FUS-3` | reranker verdict + retrieval resolution/fallback | L4 |
| `DL-2..DL-5` | design-loop triage decisions | L4 |
| `N-1..N-4` | normalization idempotence + dedup | L2, L5 |
| `E5` | LLM-boundary timeout/retry discipline | L2 |
| `INV-1..INV-7` | LLM-output structural invariants | L9 |
| `M-*` / `FG-*` | garden mutants (Python / `.fizz`) | L3 |

## Running the gates

| Target | Layer(s) | When |
|---|---|---|
| `make check-lint` / `make check-static-typing` / `make check-deadcode` / `make check-depcheck` | L0 | every commit (pre-commit + CI); `make check-all` runs all four |
| `make test-unit` | L1 | every commit |
| `make test-oracles` | L1b, L2, plus L4 traces / L5 conformance / L6 DST / L1 canary | pre-push + CI |
| `make test-mutations` | L3 | manual / nightly |
| `make verify-fizz` / `make verify-fizz-simulation` | L4 | CI authoritative |
| `make verify-nagini` / `nagini_verify_file` (MCP server) / `make verify-coverage` | L5 | agent-run per change; CI authoritative |
| `make verify-import-inventory` | L7 | commit / nightly |
| `make verify-ledger` / `make verify-cross-consistency` | L8 | commit (advisory) |
| `ARCH_BENCH_LLM=1 pytest tests/eval/ -m llm` | L9 | prompt/model changes |
| `RUN_PERF=1 pytest tests/verification/test_perf_smoke.py` | L10 | nightly canary |

## Honest claims (what green means per layer)

| Layer | A green run licenses |
|---|---|
| L0–L1 | observed behaviour on the tested inputs is correct |
| L2 | properties hold on generated samples (shrunk to minimal counterexamples on failure) |
| L3 | the oracles themselves catch every planted bug class |
| L4 | no interleaving **up to the stated bounds** violates the assertions |
| L5 | the annotated fragment is correct on **all inputs** (stubs assumed correct) |
| L6 | the real implementation holds J-1/J-2 under **all explored schedules** |
| L7 | no known-vulnerable or unreviewed dependency entered |
| L8 | spec, docstring, and artifact mapping agree |
| L9 | output is well-formed and internally consistent (never that it is *good*) |
| L10 | a human accepted the judgment calls; latency budgets hold |
