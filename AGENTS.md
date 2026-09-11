# Agent Rules — architecture-pattern-mcp

## Static typing (MANDATORY)
- `src/` is mypy strict. `uv run mypy --strict` MUST exit 0 before finishing any task.
- Clear all zuban LSP diagnostics (mypy mode) in files you touch. Known, accepted
  divergence: zuban reports a few errors stock mypy does not (e.g. some
  `pipeline.py` slice/misc findings) and vice versa; stock mypy is authoritative
  for CI — fix both sets where possible, never introduce zuban-only constructs.
- Annotate every function signature; parameterize all generics (`dict[str, X]`,
  not `dict`; `re.Match[str]`, not `Match`).
- No bare `Any` in public signatures.
- NO mypy plugins (zuban cannot run them). Pydantic: use `Field(default=...)`
  keyword form, never positional defaults; `default_factory` gets a named,
  return-annotated factory function.
- `# type: ignore[<code>]` ONLY where third-party stubs are provably wrong;
  always with a justification comment. No bare `type: ignore`, no blanket ignores.
- New third-party imports: prefer typed libs / `tests-*` stubs (`types-*`); otherwise
  add a per-module override in `[tool.mypy]` with a comment.
- Scope: `src/` only (`tests/`, `examples/` currently unchecked).

## Quality gates
- `make check-lint` (ruff), `make check-static-typing` (mypy), `make test-unit`,
  `make check-deadcode`, `make check-depcheck` — all must pass before task
  completion (`make check-all` runs the four check-* gates in one go).
- Runtime behavior of existing code must not change while fixing type errors;
  `tests/unit/` is the behavioral oracle.

## Verification program
- Changing job/pipeline control flow: update the matching `.fizz` model in
  `verify/fizz/` in the same PR, prove it with `make verify-fizz`; CI re-checks
  all specs on every push regardless of what the agent did; every assertion
  must kill at least one spec-garden mutant and appear in the
  `verify/fizz/README.md` ledger.
- Every `.fizz` `always` / `always eventually` assertion must kill at least one
  spec-garden mutant or carry a `# spec-explains:` justification — vacuous
  assertions are rejected.
- The executable layers (L1 unit tests, L2 Hypothesis oracles, L3 gardens,
  L4 FizzBee, L6 DST) are the verification authority; a change to the decision
  modules (`src/text_validation.py`, `src/design_normalization.py`) must keep
  `tests/unit/` and `tests/verification/` green.
- L3 scope changes (any edit to `[tool.mutmut]` in `pyproject.toml`) must
  update the `verify/mutmut-scope.md` ledger row in the same PR. The Python
  garden (`tests/verification/gardens/bug_garden.py`) now declares SIX bug
  classes; `make test-mutations` enforces a ratchet against the committed
  `verify/mutmut-baseline.json` (new survivors and kill-ratio drops fail the
  gate; deliberate refresh via `make regen-mutmut-baseline`; acknowledged
  equivalents go to `verify/mutmut-equivalents.md`). The mutation-scope
  modules and their oracles are listed there; `tests/unit/` internals tests
  (`test_text_validation_internals.py`,
  `test_design_normalization_internals.py`) are the direct kill oracles for
  the decision-engine primitives.
