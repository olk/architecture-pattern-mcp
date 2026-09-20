# Plan: Design Integrity Gate — runtime cross-reference enforcement

## Motivation

The GENERATE phase's most common defect class is cross-reference breakage. The
prompts themselves say so (`src/pipeline.py:258, 284-286, 1560-1561` label
unresolved component references "the most common rejection cause"), and the
repo measures it (`tests/benchmark/runner.py:166-170` `dangling_references`,
gated "must not regress") and tests it (`tests/eval/invariants.py` INV-2/3/4/5).
Yet nothing in `src/` enforces it at runtime: integrity discipline is
prompt-only; the Pydantic schemas (`src/schemas/design.py`,
`src/schemas/architecture.py`, `src/schemas/contracts.py`) validate shapes, not
the reference graph.

This plan promotes the graph-integrity family from offline oracle to a runtime
gate that rides the existing self-healing retry mechanism — capturing the
determinism benefit a rule engine was considered for, at plain-typed-Python
cost, with zero new dependencies.

**Explicitly rejected alternative:** integrating `durable_rules` (jruizgit/rules).
Rationale recorded in the session verdict: (1) semantic mismatch — no decision
in this pipeline needs fact chaining, working-memory accumulation, temporal
correlation, or conflict resolution; every check is a one-shot pure function
over one design payload, below the engine's own complexity gate; (2) dependency
abandonment risk — last release 2.0.28 on 2020-06-07, sdist-only C extension,
classifiers stop at Python 3.7, no type stubs, vs this repo's `>=3.12` +
mypy `--strict` + Docker multi-stage constraints; (3) verification-program tax
(mutmut/fizz/baseline surface) disproportionate to a wrapper over ~60 lines of
set-membership checks.

## Changes

### 1. New module `src/design_validation.py` (house pattern: `src/text_validation.py`)

Pure, typed, synchronous, no LLM, no I/O. Public surface:

```python
@dataclass(frozen=True)
class IntegrityViolation:
    rule_id: str          # "DIV-2" | "DIV-3" | "DIV-4" | "DIV-5"
    path: str             # stable locator, e.g. "relationships[3].target"
    message: str

@dataclass(frozen=True)
class DesignIntegrityVerdict:
    violations: tuple[IntegrityViolation, ...]   # sorted by (rule_id, path)

def evaluate_design_integrity(
    components: Sequence[Component],
    relationships: Sequence[Relationship],
    api_contracts: Sequence[ApiContract] = (),
    event_contracts: Sequence[EventContract] = (),
) -> DesignIntegrityVerdict: ...
```

Rules (IDs aligned with the eval-layer INV numbering they promote):

- **DIV-2** duplicate `Component.id` (regex well-formedness stays in the schema).
- **DIV-3** every `relationship.source`/`.target` ∈ component ids.
- **DIV-4** every `EventContract.published_by` and each `consumed_by` entry ∈
  component ids; at least one consumer.
- **DIV-5** every top-level `ApiContract.component_id` ∈ component ids.

Out of scope: INV-1 completeness (schema-level `min_length` where applicable),
INV-6 catalogue membership of cited style, INV-7 score ranges (already Pydantic
`Field` constraints). Deterministic violation ordering is mandatory — mutmut
stability and corpus diffing depend on it.

### 2. Wire-schema enforcement (self-healing, zero new plumbing)

`model_validator(mode="after")` on `ArchitectureDesignResponse` **and**
`ArchitectureDesignResponseWire` calling `evaluate_design_integrity` with the
fields each schema carries. `ValueError` listing the violations → Pydantic
`ValidationError` → `src/validation.py::validate_with_retries` already formats
it into the correction prompt and retries (`src/agent.py:176-183`). Lean mode
omits contract lists → DIV-4/DIV-5 are vacuously true there; DIV-2/DIV-3 still
gate. `ArchitectureDesign` (internal + tool-input schema) gets **no**
validator — see (3).

Pydantic policy per AGENTS.md: `Field(default=...)` keyword form only, no
positional defaults, no plugins; validators are plain `@model_validator`.

### 3. External input: soft findings, not hard reject

`submit_architecture_design` receives caller-authored designs. Hard-rejecting
them on DIV violations would be a breaking tool-contract change. Instead the
tool adapter (`src/tools/_adapters.py` layer, matching existing soft-check
placement) runs `evaluate_design_integrity` and surfaces violations as
structured findings in the evaluation payload (analogous to the warn-only
`_warn_on_external_migration_refs` precedent in `src/schemas/patterns.py:133`).

### 4. Deliberate non-delegation of `tests/eval/invariants.py`

The eval layer stays the independent dict-based oracle — that independence is
its documented purpose ("regression oracles for the product"). The ~40 lines of
logic duplication are the cost of oracle independence; document this in the
module docstring of both files. Tradeoff accepted: a divergence between the two
implementations shows up as a corpus failure on one side, which is the desired
alarm, not a bug.

### 5. Verification program (per AGENTS.md, non-negotiable)

- `tests/unit/test_design_validation_internals.py` — direct kill oracle for
  mutations (mirrors `test_text_validation_internals.py`): one test family per
  DIV rule, each with a kill-case (mutating the rule's predicate must flip a
  verdict), plus ordering determinism.
- Mutmut: add `src/design_validation.py` to `[tool.mutmut]` scope →
  `make regen-mutmut-baseline` → update the `verify/mutmut-scope.md` ledger row
  in the same PR → `make test-mutations` green against the new baseline.
- FizzBee: the generate-phase gate changes pipeline control flow (new
  rejection path inside wire-schema validation feeding the existing retry
  budget). Update `verify/fizz/design_loop.fizz` (and `pipeline_control.fizz`
  if its edge set covers generate-time validation outcomes), run
  `make verify-fizz`, then `make regen-fizz-traces` (no `require` inside
  `any`/`oneof`; check `^FAILED`; re-run once on seed flakiness).
- Benchmark: `tests/benchmark/` before/after on the same fixtures — acceptance
  gates are its own documented ones: `dangling_references` must not regress
  (expected: drops toward 0 for the relationship family), `attempts` must not
  regress, `validation_success` must not regress.

## Sequencing

1. Land `src/design_validation.py` + internals tests first, validator dormant
   (observer mode): run it over the existing unit corpus
   (`tests/unit/test_design.py`, `test_submit_architecture_design.py`,
   regression fixtures) and count violations. If curated fixtures are dirty,
   fix fixtures or narrow rules before enforcing — the gate must not turn the
   existing green suite red on day one.
2. Wire the two response-schema validators (self-healing live for GENERATE).
3. Add the submit-tool soft-findings path.
4. Mutmut scope + baseline + ledger; fizz spec updates + trace regen.
5. Benchmark before/after run; record metrics in the PR description.

## Acceptance criteria

- `make check-all` green (ruff, mypy --strict incl. zuban parity, unit,
  deadcode, depcheck); `make test-mutations`, `make verify-fizz`,
  `make regen-fizz-traces` green.
- A design with a dangling `relationship.target` produced in GENERATE is
  rejected by the schema, retried with a correction prompt naming
  `relationships[i].target`, and either heals or surfaces the existing
  exhausted-retry failure — never silently returned.
- `submit_architecture_design` with a dangling reference still succeeds at the
  transport level and reports the violation as a finding.
- Benchmark: no regression on `attempts`/`validation_success`;
  `dangling_references` strictly improved or unchanged.

## Risks

- Self-healing retries consume the shared retry budget → possible small
  `attempts` increase on dirty generations; mitigated by the correction prompt
  being precise (path-level), and measured by the benchmark gate.
- Fixture rot: observer-mode step (Sequencing 1) exists to surface it before
  enforcement flips on.
- Oracle duplication drift (eval vs src): accepted by design, alarmed by the
  corpus tests on either side.
