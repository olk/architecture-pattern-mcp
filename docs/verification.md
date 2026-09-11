# Verification — architecture-pattern-mcp

> **Status:** summary of the implemented verification and testing program
> (September 2026). This document summarizes the layered stack: which layer
> exists, which frameworks it uses, what it tests/verifies, and where its
> gate lives. It summarizes; it does not replace the owning documents:
> [`testing-strategies.md`](testing-strategies.md) (the stack),
> [`formal_verification.md`](formal_verification.md) (rationale),
> [`review-checklist.md`](review-checklist.md) (L10).

## The trust model in one paragraph

The server's code is LLM-generated and nobody reads all of it. The program
splits trust into decorrelated layers so their blind spots multiply instead of
add: cheap layers (types, unit tests) run always; expensive layers
(model checking) are opt-in and scoped to the critical
~5–10% of modules. Two boundaries are absolute:

- **T1 vs T2:** mechanical layers verify that the *machinery* fails on no
  input (T1). No layer judges whether a generated *design* is good (T2) —
  that stays with evaluation rubrics and human review (L10).
- **Vacuity control:** every oracle must be able to fail. Assertions and
  `.fizz` models are accepted only if they kill garden mutants (L3) or carry a
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
| L5 | deductive verification (Viper/Z3) | **retired 2026-09** — the decision modules (`text_validation`, `design_normalization`) previously carried Requires/Ensures/Invariant contracts; their properties are now pinned by the L1/L2 behavioral oracles (`tests/unit/test_text_validation.py`, `tests/unit/test_normalization.py`, `tests/verification/test_normalization_idempotence.py`) | — | retired |
| L6 | deterministic simulation (native now; simloom/frontrun on provisioning) | real asyncio schedules of the **real implementation**: bounded, seeded, replayable proof of J-1/J-2 under all race schedules | `tests/verification/test_jobs_dst.py` (always on) | active (native), proven |
| L7 | deptry, uv.lock pinning, import-inventory listing | supply chain: hallucinated/unused deps; slopsquatting defence (new package names need human decision) | `make check-depcheck` | active |
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

Later oracle layers (`.fizz` assertions) must kill the same
mutant IDs or are rejected as vacuous (AGENTS.md rule).

### L4 — Model checking (`FizzBee`)
Exhaustive exploration of **all interleavings up to stated bounds** with
implicit fault injection (crash at yield points, message loss) — the
protocol-level view no other layer can produce. Artifacts:

- `verify/fizz/jobs_protocol.fizz` — job store (durable, atomic guarded
  transitions) × symmetric clients (crash-on-yield); the `GUARDED` constant
  is the F0 A/B flip: `False` reproduces the historical J-1 violation
  trace, `True` (current implementation) must hold. Also carries the two
  liveness rows: FC-1 (every RUNNING job of an alive client eventually
  leaves RUNNING) and FC-2 (an acknowledged cancel ends CANCELLED).
- `verify/fizz/jobs_runner.fizz` — the background task lifecycle
  (`_run_job`) and the cancel tool against the store: W0-1 checkpoints,
  the terminal-write race, the done-callback task-map cleanup (RUN-1/3/4,
  C-1); J-1's kill authority lives here (the terminal-write race is the
  genuine second-write path).
- `verify/fizz/pipeline_control.fizz` — pipeline stage machine
  (ANALYZE→GENERATE→EVALUATE→REFINE, attempts ≤ 3) with an unreliable LLM
  environment (`oneof` respond/fail) and a bounded fair retry tick;
  FP-2..FP-7 including the FP-5 liveness row (every run eventually ends).
- `verify/fizz/design_loop.fizz` — `design_loop` triage decisions: guarded
  best-score update, early stop, cancel checkpoint, malformed-continue
  (DL-2..DL-5).
- `verify/fizz/reasoning_retry.fizz` — the reasoning client's `wait_for`
  deadline (E5F-1/2) and the trace cache's LRU + single-flight discipline
  (E5F-3/4).
- `verify/fizz/tei_fallback.fizz` — TEI reranker verdict discipline
  (TEI-1) and the no-partial-result-on-rerank-error rule (RET-1).
- `verify/fizz/retrieval_fusion.fizz` — the retrieval resolution tail:
  real outcomes carry patterns and passed the floor (FUS-1/2); fallbacks
  are tagged (FUS-3).
- `verify/fizz/README.md` — the property-ID ledger coupling every assertion
  to its Hypothesis oracle and conformance test, plus the
  spec garden (FG-01..FG-31, each re-validated on the toolchain
  2026-09-10) and run-stats table.

Frozen counterexamples are replayed against the real store in
`tests/verification/test_fizz_traces.py`, independent of tool availability.

### L5 — Deductive verification — retired (2026-09)

The L5 layer (deductive verification over Viper/Z3) has been removed from
the stack.  The two decision modules that carried the Requires/Ensures/
Invariant contracts — `src/text_validation.py` and
`src/design_normalization.py` (formerly split into `*_core.py` + Pydantic
adapter) — retain their decision properties, now pinned by the L1 behavioral
oracles (`tests/unit/test_text_validation.py`,
`tests/unit/test_normalization.py`) and the L2 Hypothesis oracle
(`tests/verification/test_normalization_idempotence.py`, N-1..N-4).  The
character-level Unicode facts and Pydantic object graphs that deductive
verification could not model remain trusted precomputations, unchanged.

Removal summary: the contract-vocabulary stub package, the dedicated
verification make target and its venv, the coverage-report script, the
corresponding CI job, and the agent rules in AGENTS.md were deleted in a
single PR.  The
honest-claims boundary they encoded stands in equivalent form: the decision
logic is correct on the tested/pinned input space, assuming the Unicode
oracles and key extraction are correct — those assumptions are pinned by the
L1/L2 behavioral oracles named above.

#### Why the layer was removed

Deductively verifying only the two cores cost a dedicated toolchain (JVM +
Viper backend, a pinned `mypy==1.5.0` venv), a runtime-inert contract-vocabulary
stub package shipped with the wheel, and an agent workflow around the
verifier's MCP server — for properties that the L1/L2/L4 layers already pin
with lower total cost.  The surviving stack covers the same bug classes:

| Former L5 claim | Now pinned by |
|---|---|
| text-verdict well-formedness / strip-window maximality | `tests/unit/test_text_validation.py` (behavioral oracle) |
| normalization dedup / coverage / subset / idempotence (N-1..N-4) | `tests/unit/test_normalization.py` + `tests/verification/test_normalization_idempotence.py` (Hypothesis) |
| job-lifecycle and pipeline interleavings | FizzBee L4 + DST L6 (unchanged) |

### L6 — Deterministic simulation (DST)
Exercises the **real implementation's actual schedules** — no model, no twin,
no drift. `tests/verification/test_jobs_dst.py` runs two deterministic modes:
exhaustive micro-step interleaving of the cancel/completion race (all 6
order-preserving schedules) and seeded real-asyncio races; both prove J-1 and
J-2 on the real store with a can-fail oracle (the guard must reject the
historical race schedule). Written so the scenarios map 1:1 onto simloom
(`systematic=True`) / frontrun (DPOR) when provisioned.

### L7 — Dependency & supply chain (`deptry`, inventory listing)
AI code hallucinates dependencies (19.7% in the USENIX '25 study →
slopsquatting). Defences: full `uv.lock` pinning, `deptry` hygiene
(`make check-depcheck`), and the import-inventory listing
(`scripts/import_inventory.py`) — the drift gate that diffs the listing
against a checked-in snapshot is planned but not yet wired as a make
target.

### L8 — Spec & doc-level testing (intent layer)
Aimed above the code: intent drift between prompt, docstring, contract,
model, and implementation.

- `make verify-ledger` — every property ID referenced in an artifact must
  have a `verify/fizz/README.md` ledger row, and every row must reference an
  existing artifact or be explicitly deferred (range rows like
  `` `N-1..N-4` `` supported).
- `make verify-cross-consistency` — the NL-Doc gate (VLP evidence: validating
  an intermediate artifact beats direct code review 84% vs 40%). Mechanical
  subset now (every public function in the decision modules carries a
  docstring); the LLM comparison activates via `ARCH_CONSISTENCY_MODEL`, with
  the checker model identity pinned per run (E3).

Both run in the nightly canary workflow (`verification.yml` #bug-gardens).

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
(`tests/verification/test_perf_smoke.py`, RUN_PERF — the decision modules'
latency budgets are the canary), and the nightly TCB canary workflow
(`.github/workflows/verification.yml`: unit suite, oracle suites, gardens,
ledger, NL-Doc, perf smoke blocking; mutmut/FizzBee advisory).

## Shared property vocabulary

One ID per property across all layers (drift is reviewable 1:1 via the
`verify/fizz/README.md` ledger):

| ID | Property | Layers |
|---|---|---|
| `J-1` | terminal job states immutable | L2, L3, L4, L6, frozen traces |
| `J-2` | cancel effective only from pending/running | L2, L4, L6 |
| `J-3` | `created_at <= updated_at` always | L2, L4 |
| `J-4` | one running row per job_id | L2, L4 |
| `P-1` | pipeline attempt loop bounded (≤ 3) | L4 |
| `FP-2..FP-7`, `FC-1`, `FC-2` | pipeline/order/liveness (FizzBee-only) | L4 |
| `RUN-1`, `RUN-3`, `RUN-4`, `C-1` | background-task lifecycle + cancel-tool triage (FizzBee-only) | L4 |
| `E5F-1..E5F-4` | reasoning-client deadline/retry/cache discipline (FizzBee view of E5) | L4 |
| `TEI-1`, `RET-1`, `FUS-1..FUS-3` | reranker verdict + retrieval resolution/fallback | L4 |
| `DL-2..DL-5` | design-loop triage decisions | L4 |
| `N-1..N-4` | normalization idempotence + dedup | L2 |
| `E5` | LLM-boundary timeout/retry discipline | L2 |
| `INV-1..INV-7` | LLM-output structural invariants | L9 |
| `M-*` / `FG-*` | garden mutants (Python / `.fizz`) | L3 |

## Running the gates

| Target | Layer(s) | When |
|---|---|---|
| `make check-lint` / `make check-static-typing` / `make check-deadcode` / `make check-depcheck` | L0 | every commit (pre-commit + CI); `make check-all` runs all four |
| `make test-unit` | L1 | every commit + nightly canary (`verification.yml` #unit-suite) |
| `make test-oracles` | L1b, L2, plus L4 traces / L6 DST / L1 canary | pre-push + CI + nightly canary (`verification.yml` #bug-gardens) |
| `make test-mutations` | L3 | manual / nightly |
| `make verify-fizz` / `make verify-fizz-simulation` | L4 | CI authoritative |
| `make verify-ledger` / `make verify-cross-consistency` | L8 | commit (advisory) + nightly canary (`verification.yml` #bug-gardens) |
| `ARCH_BENCH_LLM=1 pytest tests/eval/ -m llm` | L9 | prompt/model changes |
| `RUN_PERF=1 pytest tests/verification/test_perf_smoke.py` | L10 | nightly canary |

## Honest claims (what green means per layer)

| Layer | A green run licenses |
|---|---|
| L0–L1 | observed behaviour on the tested inputs is correct |
| L2 | properties hold on generated samples (shrunk to minimal counterexamples on failure) |
| L3 | the oracles themselves catch every planted bug class |
| L4 | no interleaving **up to the stated bounds** violates the assertions |
| L5 | *(retired)* — decision properties pinned by the L1/L2 oracles |
| L6 | the real implementation holds J-1/J-2 under **all explored schedules** |
| L7 | no known-vulnerable or unreviewed dependency entered |
| L8 | spec, docstring, and artifact mapping agree |
| L9 | output is well-formed and internally consistent (never that it is *good*) |
| L10 | a human accepted the judgment calls; latency budgets hold |
