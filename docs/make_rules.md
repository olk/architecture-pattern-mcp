# Makefile rule reference

A detailed explanation of every `make` rule in this repository. For a quick
overview run `make help`.

> **Authority note:** if anything in this document disagrees with the
> `Makefile`, the `Makefile` is authoritative. This doc is a convenience, not
> a gate.

## Conventions

**Prefix families.** Targets that belong to one purpose share a stem, so
tab completion (`make check-<TAB>`) surfaces them as a unit:

| Family | Purpose | Members |
|---|---|---|
| `check-*` | static analysis quality gates (side-effect free) | `check-lint`, `check-static-typing`, `check-deadcode`, `check-depcheck` |
| `test-*` | runs pytest (unit + executable oracles) or mutmut | `test-unit`, `test-oracles`, `test-mutations` |
| `verify-*` | formal-model / external-tool audits | `verify-fizz`, `verify-fizz-simulation`, `verify-nagini`, `verify-coverage`, `verify-import-inventory`, `verify-deps-audit`, `verify-ledger`, `verify-cross-consistency` |
| `docker-*` | container build / publish / lifecycle | see below |
| `install*`, `client*`, `help`, `clean` | singletons / small pairs, no family | — |

**Aggregators.** Each family has a one-command entry point: `check-all`,
`test-all`, `verify-all` (and `docker-build-all` / `docker-publish-all`).
Aggregators **echo a `==> [n/m] <target>` banner before each step** and run
their members strictly sequentially via recursive `make` — fail-fast by
cost (cheap checks first), and a failing step is identifiable from its
banner. Aggregators are **side-effect free**: `check-lint-fix`-style
auto-fixing targets must never join a gate (a gate must not mutate the
working tree). `test-mutations` is deliberately outside `test-all` — mutmut
is a manual/nightly gate (ephemeral toolchain, long runtime), not a PR-time
one.

**Opt-in gating.** Heavy toolchains self-skip so local environments without
them never break the standard gate set:

| Variable | Targets | Without it |
|---|---|---|
| `RUN_VERIFY=1` | `verify-fizz`, `verify-fizz-simulation`, `verify-nagini` | prints a one-line "opt-in via RUN_VERIFY=1" note, exits 0 |
| `STRICT=1` | `verify-deps-audit`, `verify-cross-consistency` (promotion trigger) | advisory: findings are leads to triage, not failures |

CI sets these unconditionally (`.github/workflows/verification.yml`); a
pushed branch can never skip verification.

**Removed targets.** `lint-fix` (and its `check-lint-fix` successor idea) was
removed from the project. To auto-fix, run the tools directly:
`uv run ruff check --fix .` and `uv run ruff format .`.

---

## Setup

### `install`
`uv sync` — syncs the locked dependency set into `.venv` (the `dev` group is
included by default). Implicit prerequisite of every target that needs the
toolchain (`check-static-typing`, `test-unit`, `test-oracles`).

### `install-mcps`
`npm install -g server-shannon-thinking@0.1.1 @mettamatt/code-reasoning@0.8.1`
— installs the two reasoning MCP servers for local development. Docker images
embed them at build time, so this is only needed for local non-container runs.

### `help`
Default goal. Renders the target list grouped by the `##@` section banners.

---

## Quality (`##@ Quality`)

All `check-*` gates are read-only over the working tree. CI runs them on
every push/PR; `make check-all` is the one-liner for local use.

### `check-lint`
`uv run ruff check .` — style and lint rules over the whole repo.

### `check-static-typing`
`uv run mypy --strict` — strict static typing, scoped to `src/` only
(`tests/`, `examples/` currently unchecked). `--strict` is redundant with
`[tool.mypy] strict=true` but kept explicit so the gate survives future
config edits. AGENTS.md: must exit 0 before finishing any task.

### `check-deadcode`
`uv run vulture src examples whitelist.py --min-confidence 80` — dead-code
scan. Decorators that register callables with a framework (llama-index
Workflow `@step`, pydantic `@field_validator`/`@model_validator`, FastMCP
`@*.resource`/`@*.prompt`) are excluded via `VULTURE_IGNORE_DECORATORS`
(the decorated symbol is live without a static call site). `whitelist.py`
holds accepted false positives — keep it in sync.

### `check-depcheck`
`uv run deptry .` — dependency hygiene: declared-but-unused, imported-but-
undeclared (DEP001), and transitive-leak detection. Known intentional
exemptions live in `[tool.deptry.per_rule_ignores]` (pyproject.toml):
`litellm`/`workflows`/`mcp` arrive transitively, `mutmut` is installed
ephemerally by `test-mutations`.

### `check-all`
Aggregator: `check-lint`, `check-static-typing`, `check-deadcode`,
`check-depcheck`. The standard pre-push and CI quality gate.

---

## Tests (`##@ Tests`)

Two sub-families: `test-*` executes the test suite (pytest or mutmut);
`verify-*` runs formal-model tools and external audits.

### `test-unit`
`uv run pytest tests/unit/ -v` — the 900+ unit tests in `tests/unit/`. This
is the behavioural oracle that defines "no runtime behaviour change" for
every refactor (layer L1 in docs/verification.md).

### `test-oracles`
`uv run pytest tests/verification/ -v` — the executable-oracle suite in
`tests/verification/`: L1 secret canary, L2 Hypothesis property oracles,
L3 bug-garden kill checks, L4 frozen-trace replay, L5 conformance, L6
deterministic simulation. Designed to pass regardless of whether the heavy
verification toolchains (fizz, nagini) are installed.

### `test-mutations`
L3 mutation testing via mutmut over the Tier A/B/C modules, plus the
planted-bug gardens (the vacuity authority). Runs mutmut ephemerally
(`uv run --with mutmut` — deliberately not a project dependency) through
`verify/mutmut_compat.py`, which patches mutmut 3.x for this repo's
`src.*` package layout. **Manual/nightly only** — heavy; CI runs it as a
separate advisory job (`.github/workflows/verification.yml#mutmut-sweep`).

### `test-all`
Aggregator: `test-unit` + `test-oracles`. The PR-time test entry point.
`test-mutations` stays outside on purpose (see Conventions).

### `verify-fizz` — L4
Runs `fizz` exhaustively over every `specs/fizz/*.fizz` model (bounds per
`fizz.yaml`). Gate: `RUN_VERIFY=1`; requires the `fizz` binary (or
`FIZZ=scripts/fizz-docker.sh`). CI-authoritative for control-flow claims
(J-1/J-2, P-1, FP-2..FP-5, FC-1/FC-2). fizz v0.5.3 exits 0 even on
invariant failure (only panics exit non-zero), so the gate captures each
run's output and requires the `PASSED: Model checker completed
successfully` verdict line in addition to a zero exit — `|| exit 1` alone
would be vacuous. Verified non-vacuous: the FG-01 `GUARDED=False` flip
fails the gate (first provisioning run, 2026-09-10).

### `verify-fizz-simulation` — L4
Seeded parallel FizzBee simulation (`fizz -x --seed $(date +%s) --parallel
$(nproc)`) over all specs — the nightly statistical relief valve for the
exhaustive checks. Gate: `RUN_VERIFY=1`. Simulation mode prints no PASSED
verdict on success, so the gate fails on any `FAILED` line or non-zero
exit; a lucky seed can miss a violation (statistical by design — the
exhaustive target is the authority).

### `verify-nagini` — L5
Deductive verification (`nagini --counterexample`) over `NAGINI_FILES` — the
file set reported by `scripts/verify_coverage.py --files` (pure cores + sync
twins). Proves totality, no undeclared exceptions, and Requires/Ensures
contracts for all inputs. Gate: `RUN_VERIFY=1`; needs Java 11+ with
`JAVA_HOME` set and `nagini[mcp,lsp,server]` installed.

### `verify-coverage` — L5
`scripts/verify_coverage.py` — reports which modules are covered by the
Nagini verification set (target: 5–10% of lines). Companion to
`verify-nagini`.

### `verify-import-inventory` — L7
`scripts/import_inventory.py --check tests/verification/snapshots/import_inventory.txt`
— slopsquatting defence: diffs the actual third-party import roots against a
checked-in snapshot; a new package name fails the build until a human
reviews and updates the snapshot.

### `verify-deps-audit` — L7
`pip-audit` vulnerability scan over the project environment. Advisory by
default (skips with a hint if pip-audit isn't installed); `STRICT=1`
enforces. CI runs it nightly with `STRICT: "1"` in a `continue-on-error` job.

### `verify-ledger` — L8
`scripts/verify_ledger.py` — property-ID ledger consistency: every property
ID referenced in an artifact must have a `specs/fizz/README.md` ledger row,
and every row must reference an existing artifact or be explicitly deferred.

### `verify-cross-consistency` — L8
`scripts/cross_consistency.py` — NL-Doc/docstring cross-consistency over
`NAGINI_FILES` (mechanical subset always on; the LLM comparison activates
via `ARCH_CONSISTENCY_MODEL`, checker identity pinned per run). Advisory;
`STRICT=1` enforces the >10% divergence promotion trigger.

### `verify-all`
Aggregator over the eight `verify-*` targets. Nightly entry point — safe on
toolchain-less boxes because the gated members self-skip (see Conventions).

---

## Demo (`##@ Demo`)

### `client`
Runs the pipes-and-filters MCP client demo
(`examples/architecture_client.py`) against `http://localhost:8060/mcp` —
synchronous `design_architecture`. Development tool proving the server
completes long requests; the timeout issue it demonstrates is client-side.

### `client-async`
Runs the async job trio demo (`examples/architecture_client_async.py`) —
`submit_architecture_design_job` + `get_architecture_design_status`
polling, the production-safe pattern for long requests.

---

## Docker (`##@ Docker`)

Images: the MCP server (`architecture-pattern-mcp`) plus the TEI sidecars
(`pattern-tei-embed`, `pattern-tei-rerank`). Version tag is derived from
`pyproject.toml`. Registries: Docker Hub (`olkowa/*`) and GHCR
(`ghcr.io/olk/*`).

### `docker-build`
Builds the MCP server image (production target), tagged with the project
version and `latest`.

### `docker-build-tei`
Builds both TEI images (embedder + reranker) from their Dockerfiles.

### `docker-build-all`
Aggregator: `docker-build` + `docker-build-tei`.

### `docker-publish`
`docker-build`, then refuses on a dirty git tree, pushes the server image to
Docker Hub + GHCR (version + latest tags), creates annotated git tag
`v<version>` if absent, and pushes the tag.

### `docker-publish-tei`
`docker-build-tei`, then pushes both TEI images to both registries.

### `docker-publish-all`
Aggregator: `docker-publish` + `docker-publish-tei`. Re-running after a
failed push is safe — already-uploaded layers are cache hits.

### `docker-up` / `docker-down`
Start (`up -d --build`) / stop the compose stack
(`docker/docker-compose.yml`); serves on :8060.

### `docker-logs` / `docker-logs-follow`
One-time / following logs of the MCP server service.

### `docker-rm`
Removes the local server image (version tag).

---

## Maintenance (`##@ Maintenance`)

### `clean`
Removes `.pytest_cache`, `.ruff_cache`, `dist/`, `build/`, and all
`__pycache__/` outside `.venv/`. (Does not remove `mutants/` — that is
regenerated wholesale by `test-mutations` and gitignored.)

---

## CI matrix

| Target(s) | Workflow | When |
|---|---|---|
| `check-lint` (as `uv run ruff check .`), `check-static-typing` (as `uv run mypy --strict`) | `ci.yml` #Lint & Type Check | every push/PR |
| `check-deadcode`, `check-depcheck` | `ci.yml` #Dead Code & Dependency Hygiene | every push/PR |
| `test-unit` (as `uv run pytest tests/unit/`) | `ci.yml` #Unit Tests | every push/PR |
| oracle suite (as `uv run pytest tests/verification/`), `verify-ledger`, `verify-cross-consistency`, `verify-import-inventory` | `verification.yml` #bug-gardens | nightly + manual dispatch |
| `test-mutations` | `verification.yml` #mutmut-sweep | nightly (advisory) |
| `verify-coverage`, `verify-nagini` (`RUN_VERIFY=1`) | `verification.yml` #verify-nagini | nightly (advisory) |
| `verify-fizz` (`RUN_VERIFY=1`) | `verification.yml` #verify-fizz | nightly (advisory) |
| `verify-deps-audit` (`STRICT=1`) | `verification.yml` #deps-audit | nightly (advisory) |
| `check-all`, `test-all`, `verify-all`, demo/docker targets | — | local / release use |

---

## Local workflow cheat sheet

```bash
make install                    # first time
make check-lint                 # while iterating (fast)
make check-all                  # before pushing (lint + types + dead code + deps)
make test-unit                  # every commit
make test-oracles               # pre-push
make test-mutations             # occasionally / before risky merges (slow)
RUN_VERIFY=1 make verify-fizz   # after control-flow changes (needs fizz)
make docker-build-all           # before first docker-up or after dep changes
make docker-up                  # serve on :8060
make docker-logs-follow         # tail logs
make docker-down                # stop
make clean                      # clear caches
```
