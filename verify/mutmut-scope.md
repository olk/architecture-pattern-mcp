# mutmut Scope Ledger — Tier A/B/C + R5 Decision Modules

> Owned by the L3 section of [`docs/verification.md`](../docs/verification.md)
> (drift countermeasure, mirroring `verify/fizz/README.md`: a PR that changes
> `[tool.mutmut]` in `pyproject.toml` must change a row here in the same PR).
> Run: `make test-mutations` · Enforcement: `scripts/mutmut_baseline.py --gate`
> · Baseline: `verify/mutmut-baseline.json` · Parameters:
> `verify/mutmut-thresholds.toml` · Equivalents: `verify/mutmut-equivalents.md`

## Why a narrow scope

The mutation surface is the decision logic — the code where a silent bug is a
kill-class bug — never the whole tree (testing-strategies §3.4: "the critical
5-10%, never the tree"). A module enters scope only when all four checklist
rows hold; it leaves scope only through a row edit here.

## Module ledger

| Module | Decision functions | Ownership (kill authority) | Why in scope | Expected survivors |
|---|---|---|---|---|
| `src/text_validation.py` | `compute_strip_window`, `evaluate_printable_text`, `_category_code`, `ensure_printable_text`, the three `AfterValidator`s | L1 `test_text_validation.py` (behavioral oracle) + L1 `test_text_validation_internals.py` (direct, kills index-arithmetic mutants the wrapper cannot see) **+ L2 `tests/verification/test_text_validation_properties.py` (V-1..V-6, 2026-09-12: totality, verdict well-formedness, strip-window maximality, TOO_LONG/NO_PRINTABLE iff-laws, first-disallowed index; Annotated wrappers pinned via TypeAdapter at Field boundaries)** | MCP input boundary; totality + verdict discipline (Tier A totality promise) | yes — wrapper-level error-message f-string mutants partially overlap (see equivalents ledger) |
| `src/design_normalization.py` | `promote_api_contract_ids`, `promote_shared_model_keys`, `dedupe_event_names`, `_select_first` | L2 `test_normalization_idempotence.py` (N-1..N-4) + L1 `test_design_normalization_internals.py` | §4.11 denormalization precedence/dedup — wrong dedup silently drops contracts | rare (kill ratio 0.96 at baseline) |
| `src/validation.py` | `format_validation_errors`, `validate_with_retries` | L1 `test_validation.py` + L2 E5 retry oracle (`test_jobs_properties.py`) | self-healing retry loop at the LLM boundary — unbounded retry = hang class | **yes — 50 of 80 at baseline; the weakest audited module, triage pending** |
| `src/config_expansion.py` | `expand_env`, `expand_env_in_obj` | L1 `test_config_expansion.py` | `{env:VAR}` expansion feeds every config secret/URL — silent mis-expansion is a config-injection class | none at baseline (30/30 killed) |
| `src/tools/jobs.py` | `JobsStore` lifecycle + `_guarded_update` | L1 `test_jobs.py` (transition matrix) + L2 J-oracles + L4 `jobs_protocol`/`jobs_runner` conformance **+ L1b `test_boundary_fuzz.py` job-trio surfaces (2026-09-12)** | W0-1 guarded transitions (J-1/J-2); the single most safety-critical automaton in the server | yes — mostly SQL-string f-string mutants killed only via behavior; triage pending |
| `src/agent.py` *(R5)* | `_generate_structured_once`, `generate_structured` retry wiring | L2 E5 raw-transport mapping oracle + L1 `test_agent.py` | the raw-exception → `LLMError` mapping; an unmapped exception escapes into the pipeline | triage pending (new in R5) |
| `src/reasoning/client.py` *(R5)* | `_run_cached` (LRU + single-flight), `_generate_trace` (step bound), `_validate_draft` | L1 `test_reasoning_client.py` `TestCacheLRUEviction`/`TestSingleFlight` (E5F-3/E5F-4) + L4 `reasoning_retry.fizz` (FG-20..22) **+ L2 E5F-2/3/4 oracle extensions in `test_jobs_properties.py` (2026-09-12: step-loop bound, LRU bound incl. recency, single-flight over the REAL cache/loop)** | silent-degradation failure mode (E5F family); cache poisoning and unbounded generation are kill classes | triage pending (new in R5); `logger\.` lines are OBSERVATIONAL here (caplog tests) — no pattern exclusion |
| `src/patterns/safe_tei_rerank.py` *(R5)* | `_safe_tei_rerank_call`, `SafeTEIReranker._call_api` | L1 `test_retriever.py` HTTP-error tests + L4 `tei_fallback.fizz` (FG-23/24, TEI-1/RET-1) **+ L2 `tests/verification/test_tei_rerank_properties.py` (2026-09-12: generated status/body matrix, malformed-JSON branch added — the oracle found the empty-200-body raw-JSONDecodeError leak, fixed same PR)** | error verdicts must stay pure signals — a partial result masquerading as REAL is the RET-1 kill class | triage pending (new in R5) |
| `src/patterns/retriever.py` *(R5)* | `HybridPatternRetriever.retrieve` resolution/floor/fallback tail, `reciprocal_rank_score` | L1 `test_retriever.py`/`test_fusion_rrf.py` + L4 `retrieval_fusion.fizz` (FG-25..27, FUS-1..3) **+ L2 `tests/verification/test_retrieval_fusion_properties.py` (FUS-1/2/3 over generated leg orderings + floors, branch-steered via `target()`) and `test_scoring_properties.py` (S-1/S-2 RRF laws; 2026-09-12)** | the fallback decision decides whether users get real patterns or layered-monolith | triage pending (new in R5) |
| `src/errors.py` *(round 2)* | `JobStateError.__init__`, `MalformedArchitectureOverviewError.__init__` | L1 `test_jobs.py` (attribute asserts) + L1 `test_adapters.py` (locator/message) | error attribute contracts (`job_id`, `current_status`) are asserted by callers — attribute-drop mutants are killable | not expected (both attrs pinned) |
| `src/patterns/loader.py` *(round 2)* | `PatternLoader.load_all`, `filter_by_domain`, domain normalization | L1 `test_pattern_loader.py` (19 tests: discovery, lowercase/spaces→hyphens, alias, unsuitable filter) | pattern discovery + domain normalization decide which patterns a query can ever see | triage pending |
| `src/patterns/embedder.py` *(round 2)* | `_normalize` (L2 row normalisation, zero-vector guard) | L1 `test_pattern_embedder.py` (9 tests; zero-vector → NaN is the kill class) | NaN embeddings poison FAISS ranking silently — the guard IS the decision | not expected (`_normalize` fully pinned); wrapper classes may show no-tests rows |
| `src/reasoning/prompts.py` *(round 2)* | `build_step_user_prompt`, scaffold rendering, truncation caps | L1 `test_reasoning_prompts.py` (15 tests: per-phase scaffolds, injection points, truncation) | prompt construction decides what the reasoning LLM ever sees; truncation mutants flip context boundaries | triage pending |
| `src/reasoning/tools.py` *(round 2)* | `draft_to_params` adapters (shannon camelCase / code snake_case), phase-tag coercion | L1 `test_reasoning_client.py` `TestToolContracts`/`TestShannonPhaseTagCoercion`/adapters (already selected) | per-tool payload contracts — a casing/field mutant is a silent MCP protocol error | triage pending |
| `src/tools/_adapters.py` *(round 2)* | overview validation adapters, `MalformedArchitectureOverviewError` raising | L1 `test_adapters.py` (13 tests, both directions incl. "does not silently default") | the ERR_012 boundary between LLM output and tool responses | triage pending |
| `src/tools/submit_architecture_design.py` *(round 2)* | `_run_job` fate matching, task-map bookkeeping, cancel tool ack | L1 `test_submit_architecture_design.py` (15) + L6 DST + L4 `jobs_runner.fizz` (RUN-1/RUN-3/C-1) | the runner's triage outcome ↔ store state agreement; ack honesty | triage pending (async mutants may be noisy — DST/fizz are the kill authority) |
| `src/tools/cancel_architecture_design.py` *(round 2)* | cancel tool handler (ack-after-guarded-write) | L1 `test_submit_architecture_design.py` + L4 `jobs_runner.fizz` (C-1) | an ack without a landed write is the FG-15 bug class | triage pending |

## Deferred (awaiting scope sign-off — do NOT add without a ledger row)

| Module | Candidate functions | Why deferred |
|---|---|---|
| `src/config.py` | the four `_check_*` model validators (weight-sum `1e-3`/`0.05` tolerances, floor ≤ `2/60`) | boundary logic is a good mutmut target, but the file is 564 lines of Pydantic models — mutating field defaults and `Field` wiring would flood the run with equivalents; needs `# pragma: no mutate` support verification first (3.7 pragma semantics unverified) and dedicated boundary tests. Boundary tolerance IS covered meanwhile by the garden's `boundary-tolerance` class (M-27..M-31). |
| `src/pipeline.py::design_loop` | triage decisions | heavily coupled; owned by `design_loop.fizz` (DL-2..5) — model-checked exhaustively instead |
| `src/tools/analyze.py` / `design.py` / `evaluate.py` / `generate.py` | tool handlers | dedicated test files exist (11/20/17/15 tests) and handlers carry real formatting/error-wrapping decisions, but the tests mock the pipeline — expect survivor noise; ~1 600 LOC would grow the mutant surface by ~4x. Add as a dedicated PR AFTER the first nightly run reports wall-clock for the current scope (job cap: 180 min). |
| `src/tools/get_architecture_design_status.py` | status mapping handler | its tests live in `test_server.py`, which is not in the mutation test selection (and pulling in all of test_server drags server wiring into every slice). Needs a dedicated handler test file first. |
| `src/tools/patterns.py` | list/get pattern handlers | thin loader delegation; loader.py itself is already in scope. |
| `src/reasoning/config.py` | `get_strategy`, command validation | mostly declarative pydantic; the tested decisions (defaults, override parsing) are pinned via `test_reasoning_client.py` but the model-default bulk would be equivalent noise. Revisit together with `src/config.py` pragma work. |
| `src/server.py`, `src/main.py`, `src/__main__.py`, `src/tools/__init__.py`, `src/patterns/nodes.py`, `src/resources/*` | — | framework wiring, near-zero decision density — permanently excluded unless they grow real logic. |
| `src/prompts/*`, `src/mcp_prompts/*`, `src/schemas/*` | — | prompt text = string-mutant noise bombs; schemas = declarative pydantic/enums with unasserted defaults. Permanently excluded. |

## Gate mechanics (what `make test-mutations` now enforces)

1. mutmut is pinned `==3.7.*` in lockstep with `verify/mutmut/mutmut_compat.py`
   (source-string guards fail loudly on an upstream change — bump pin + shim
   together).
2. `also_copy = ["verify/", "scripts/"]`: the scratch tree must carry the
   shim AND the scripts package the `tests/verification` meta-tests import
   (a missing copy aborts the run at stats collection — observed 2026-09-11).
3. Per-mutant budget: `timeout_constant = 5.0`, `timeout_multiplier = 6.0`
   (verified present in the 3.7.0 `Config` dataclass).
4. The recipe runs in one shell with an `EXIT` trap — the per-run Hypothesis
   database is cleaned up even on failure.
5. `scripts/mutmut_baseline.py --gate` distills the run and fails on: any new
   survivor key, any per-function kill-ratio drop beyond
   `ratio_tolerance` (0.02), any module that lost all its data, and any
   garden class without engine-side classified mutants (R7 bridge).
6. `do_not_mutate_patterns` is deliberately unset: logger lines became
   observational when `retriever.py` entered scope (caplog tests), so a
   global `logger\.` exclusion would delete live mutation targets
   (review finding P-02).
7. Scratch reset duty: a materially changed `[tool.mutmut]` (scope or
   selection) plus an interrupted run can leave `mutants/` with a stale
   config fingerprint and half-invalidated results — the documented reset is
   `rm -rf mutants/` (gitignored, fully regenerable; the committed baseline
   is unaffected). Done 2026-09-11 after the round-2 scope expansion.

## mutmut 4 migration note (R11)

The compat shim guards two upstream source strings verbatim
(`_TRAMPOLINE_GUARD`, `_NAMING_GUARD` in `verify/mutmut/mutmut_compat.py`) and
the Makefile pins the version. A mutmut 4 bump must, in one PR: update the
pin, re-derive both guarded strings from the new source, re-verify the
trampoline-hit module-name convention (the whole reason the shim exists is the
`src`-package layout), re-check `Config` field names for the timeout keys, run
one full `make test-mutations`, and `make regen-mutmut-baseline` (indices and
keys will shift wholesale).

## Survivor triage duty

Every NEW-SURVIVOR gate failure is either (a) a test-suite gap — write the
missing kill, or (b) a true equivalent — record it in
`verify/mutmut-equivalents.md` with its mutant key and a reason, then
`make regen-mutmut-baseline`. The baseline only ever moves deliberately.
Known weak spots at the 2026-09-11 baseline: `src/validation.py` (kill ratio
0.375) and `src/tools/jobs.py` (0.67) — their survivor lists are the first
triage candidates.
