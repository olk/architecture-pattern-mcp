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
- `make lint` (ruff), `make static-typing` (mypy), `make unit-tests`,
  `make deadcode`, `make depcheck` — all must pass before task completion.
- Runtime behavior of existing code must not change while fixing type errors;
  `tests/unit/` is the behavioral oracle.
