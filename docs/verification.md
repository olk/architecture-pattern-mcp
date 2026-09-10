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
| L4 | FizzBee (`.fizz` models) | **all interleavings up to bounds**: races, crash windows, guard gaps, deadlock freedom, fault injection; protocol view of job lifecycle + pipeline control | `make verify-fizz` (`RUN_VERIFY=1`; CI-authoritative) | artifact-complete; tool-gated |
| L5 | Nagini (Viper/Z3) | **∀ inputs**: totality, no undeclared exceptions, termination, state invariants — over `NAGINI_FILES` (pure cores + sync twins) | `make verify-nagini` (`RUN_VERIFY=1`) + `make verify-coverage` | artifact-complete; tool-gated |
| L6 | deterministic simulation (native now; simloom/frontrun on provisioning) | real asyncio schedules of the **real implementation**: bounded, seeded, replayable proof of J-1/J-2 under all race schedules | `tests/verification/test_jobs_dst.py` (always on) | active (native), proven |
| L7 | deptry, uv.lock pinning, pip-audit, import-inventory diff | supply chain: hallucinated/unused/vulnerable deps; slopsquatting defence (new package names need human decision) | `make check-depcheck`, `make verify-import-inventory`, `make verify-deps-audit` (advisory) | active |
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
  transitions) × symmetric clients (crash-on-yield); the `GUARDED` constant is
  the F0 A/B flip: `False` reproduces the historical J-1 violation trace,
  `True` (current implementation) must hold.
- `specs/fizz/pipeline_control.fizz` — pipeline stage machine
  (ANALYZE→GENERATE→EVALUATE→REFINE, attempts ≤ 3) with an unreliable LLM
  environment (`oneof` respond/fail) and a fair retry tick.
- `specs/fizz/README.md` — the property-ID ledger coupling every assertion to
  its twin contract, Hypothesis oracle, and conformance test, plus the
  12-mutant spec garden (FG-01..FG-12) and run-stats table.

Frozen counterexamples are replayed against the real store in
`tests/verification/test_fizz_traces.py`, independent of tool availability.

### L5 — Deductive verification (`Nagini` / Viper-Z3)
The only layer whose verdict is universal over inputs, scoped to the critical
5–10% (`NAGINI_FILES`, reported by `make verify-coverage`):

- `src/text_validation_core.py` and `src/design_normalization_core.py` —
  pure, typed, stdlib-only cores (Pydantic is opaque to Nagini); adapters
  keep the public API and the single `model_copy`.
- `verify/twin/jobs_state_twin.py` — sync model of the guarded 5-state
  automaton (J-1..J-4, logical clock for J-3) with executable invariants.
- `verify/twin/pipeline_control_twin.py` — bounded attempt loop with
  cancellation checkpoints (P-1).
- `verify/stubs/` — annotated stubs declaring unproven oracle assumptions
  (reviewed like source, spot-checked where feasible).
- `verify/_contracts.py` — typed runtime no-op shim mirroring
  `nagini_contracts.contracts`; swapped for the real package when the
  toolchain is provisioned.

Coupling to the implementation is executable:
`tests/verification/test_jobs_conformance.py` drives twin and real store
through identical Hypothesis-generated interleavings
(`RuleBasedStateMachine` + per-test sync facade) and asserts agreement after
every step.

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
(`make check-depcheck`), the import-inventory drift gate
(`make verify-import-inventory` — a new third-party root fails the build
until a human reviews it), and an advisory vulnerability scan
(`make verify-deps-audit`).

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
| `FP-2..FP-5`, `FC-1`, `FC-2` | pipeline/order/liveness (FizzBee-only) | L4 |
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
| `make verify-fizz` / `make verify-fizz-simulation` | L4 | opt-in `RUN_VERIFY=1` locally; CI authoritative |
| `make verify-nagini` / `make verify-coverage` | L5 | opt-in `RUN_VERIFY=1` locally; CI authoritative |
| `make verify-import-inventory` / `make verify-deps-audit` | L7 | commit / nightly |
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
