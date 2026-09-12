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
| `src/text_validation.py` | `compute_strip_window`, `evaluate_printable_text`, `_category_code`, `ensure_printable_text`, the three `AfterValidator`s | L1 `test_text_validation.py` (behavioral oracle) + L1 `test_text_validation_internals.py` (direct, kills index-arithmetic mutants the wrapper cannot see) **+ L2 `tests/verification/test_text_validation_properties.py` (V-1..V-6, 2026-09-12: totality, verdict well-formedness, strip-window maximality, TOO_LONG/NO_PRINTABLE iff-laws, first-disallowed index; Annotated wrappers pinned via TypeAdapter at Field boundaries; V-3 reference arithmetic corrected same day — the all-whitespace corner must assert the well-formed `(n, n)` half-open window, not the inverted `len(rstrip())` interval, mirroring the L1 pin `test_all_whitespace_window_is_empty_at_n`; V-6 reference scan corrected same day — `\n`/`\r` must be allowed only when `allow_line_breaks` (the unconditional `_ALLOWED_WHITESPACE` whitelist disagreed with the SUT on line-break-bearing draws; deterministic mode-matrix pin added)** | MCP input boundary; totality + verdict discipline (Tier A totality promise) | yes — wrapper-level error-message f-string mutants partially overlap (see equivalents ledger) |
| `src/design_normalization.py` | `promote_api_contract_ids`, `promote_shared_model_keys`, `dedupe_event_names`, `_select_first` | L2 `test_normalization_idempotence.py` (N-1..N-4) + L1 `test_design_normalization_internals.py` | §4.11 denormalization precedence/dedup — wrong dedup silently drops contracts | rare (kill ratio 0.96 at baseline) |
| `src/validation.py` | `format_validation_errors`, `validate_with_retries` | L1 `test_validation.py` + L2 E5 retry oracle (`test_jobs_properties.py`) | self-healing retry loop at the LLM boundary — unbounded retry = hang class | **yes — 50 of 80 at baseline; the weakest audited module, triage pending** |
| `src/config_expansion.py` | `expand_env`, `expand_env_in_obj` | L1 `test_config_expansion.py` **+ L2 `tests/verification/test_config_properties.py` (CE-1..CE-6, 2026-09-12: no-op/env-wins/default/empty-wins laws, idempotence, structural-recursion shadow walker, malformed-placeholder passthrough; + CV Field-bound properties)** | `{env:VAR}` expansion feeds every config secret/URL — silent mis-expansion is a config-injection class | none at baseline (30/30 killed) — L2 must hold the ratio |
| `src/tools/jobs.py` | `JobsStore` lifecycle + `_guarded_update` | L1 `test_jobs.py` (transition matrix) + L2 J-oracles + L4 `jobs_protocol`/`jobs_runner` conformance **+ L1b `test_boundary_fuzz.py` job-trio surfaces (2026-09-12)** | W0-1 guarded transitions (J-1/J-2); the single most safety-critical automaton in the server | yes — mostly SQL-string f-string mutants killed only via behavior; triage pending |
| `src/agent.py` *(R5)* | `_generate_structured_once`, `generate_structured` retry wiring | L2 E5 raw-transport mapping oracle + L1 `test_agent.py` | the raw-exception → `LLMError` mapping; an unmapped exception escapes into the pipeline | triage pending (new in R5) |
| `src/reasoning/client.py` *(R5)* | `_run_cached` (LRU + single-flight), `_generate_trace` (step bound), `_validate_draft` | L1 `test_reasoning_client.py` `TestCacheLRUEviction`/`TestSingleFlight` (E5F-3/E5F-4) + L4 `reasoning_retry.fizz` (FG-20..22) **+ L2 E5F-2/3/4 oracle extensions in `test_jobs_properties.py` (2026-09-12: step-loop bound, LRU bound incl. recency, single-flight over the REAL cache/loop)** | silent-degradation failure mode (E5F family); cache poisoning and unbounded generation are kill classes | triage pending (new in R5); `logger\.` lines are OBSERVATIONAL here (caplog tests) — no pattern exclusion |
| `src/patterns/safe_tei_rerank.py` *(R5)* | `_safe_tei_rerank_call`, `SafeTEIReranker._call_api` | L1 `test_retriever.py` HTTP-error tests + L4 `tei_fallback.fizz` (FG-23/24, TEI-1/RET-1) **+ L2 `tests/verification/test_tei_rerank_properties.py` (2026-09-12: generated status/body matrix, malformed-JSON branch added — the oracle found the empty-200-body raw-JSONDecodeError leak, fixed same PR; TEI-1 happy-path row strategy corrected same day: `score` now excludes ±inf, the one float strategy missing `allow_infinity=False` — non-finite scores are unrepresentable in strict JSON and crashed the mock `json=` encoder before the SUT ran)** | error verdicts must stay pure signals — a partial result masquerading as REAL is the RET-1 kill class | triage pending (new in R5) |
| `src/patterns/retriever.py` *(R5)* | `HybridPatternRetriever.retrieve` resolution/floor/fallback tail, `reciprocal_rank_score` | L1 `test_retriever.py`/`test_fusion_rrf.py` + L4 `retrieval_fusion.fizz` (FG-25..27, FUS-1..3) **+ L2 `tests/verification/test_retrieval_fusion_properties.py` (FUS-1/2/3 over generated leg orderings + floors, branch-steered via `target()`) and `test_scoring_properties.py` (S-1/S-2 RRF laws; 2026-09-12)** | the fallback decision decides whether users get real patterns or layered-monolith | triage pending (new in R5) |
| `src/errors.py` *(round 2)* | `JobStateError.__init__`, `MalformedArchitectureOverviewError.__init__` | L1 `test_jobs.py` (attribute asserts) + L1 `test_adapters.py` (locator/message) | error attribute contracts (`job_id`, `current_status`) are asserted by callers — attribute-drop mutants are killable | not expected (both attrs pinned) |
| `src/patterns/loader.py` *(round 2)* | `PatternLoader.load_all`, `filter_by_domain`, domain normalization | L1 `test_pattern_loader.py` (19 tests: discovery, lowercase/spaces→hyphens, alias, unsuitable filter) **+ L2 `tests/verification/test_loader_properties.py` (LD-1..LD-6, 2026-09-12: normalization idempotence/canonical-form laws, alias-map closure, real-catalogue filter equivalence under case/whitespace corruption, catalogue shape)** | pattern discovery + domain normalization decide which patterns a query can ever see | triage pending |
| `src/patterns/embedder.py` *(round 2)* | `_normalize` (L2 row normalisation, zero-vector guard) | L1 `test_pattern_embedder.py` (9 tests; zero-vector → NaN is the kill class) | NaN embeddings poison FAISS ranking silently — the guard IS the decision | not expected (`_normalize` fully pinned); wrapper classes may show no-tests rows |
| `src/reasoning/prompts.py` *(round 2)* | `build_step_user_prompt`, scaffold rendering, truncation caps | L1 `test_reasoning_prompts.py` (15 tests: per-phase scaffolds, injection points, truncation) | prompt construction decides what the reasoning LLM ever sees; truncation mutants flip context boundaries | triage pending |
| `src/reasoning/tools.py` *(round 2)* | `draft_to_params` adapters (shannon camelCase / code snake_case), phase-tag coercion | L1 `test_reasoning_client.py` `TestToolContracts`/`TestShannonPhaseTagCoercion`/adapters (already selected) | per-tool payload contracts — a casing/field mutant is a silent MCP protocol error | triage pending |
| `src/tools/_adapters.py` *(round 2)* | overview validation adapters, `MalformedArchitectureOverviewError` raising | L1 `test_adapters.py` (13 tests, both directions incl. "does not silently default") | the ERR_012 boundary between LLM output and tool responses | triage pending |
| `src/tools/submit_architecture_design.py` *(round 2)* | `_run_job` fate matching, task-map bookkeeping, cancel tool ack | L1 `test_submit_architecture_design.py` (15) + L6 DST + L4 `jobs_runner.fizz` (RUN-1/RUN-3/C-1) | the runner's triage outcome ↔ store state agreement; ack honesty | triage pending (async mutants may be noisy — DST/fizz are the kill authority) |
| `src/tools/cancel_architecture_design.py` *(round 2)* | cancel tool handler (ack-after-guarded-write) | L1 `test_submit_architecture_design.py` + L4 `jobs_runner.fizz` (C-1) | an ack without a landed write is the FG-15 bug class | triage pending |

## Deferred (excluded from mutmut scope)

> Drift countermeasure mirroring `verify/fizz/README.md`: a PR that changes
> `[tool.mutmut]` in `pyproject.toml` must change a row in this file in the
> same PR. Two exclusion rationales live here: modules that may move to scope
> (awaiting sign-off) and modules whose decisions other verification layers
> already own (model-checked).

### Awaiting scope sign-off — do NOT add without a ledger row

| Module | Candidate functions | Why deferred |
|---|---|---|
| `src/config.py` | the four `_check_*` model validators (weight-sum `1e-3`/`0.05` tolerances, floor ≤ `2/60`) | boundary logic is a good mutmut target, but the file is 564 lines of Pydantic models — mutating field defaults and `Field` wiring would flood the run with equivalents; needs `# pragma: no mutate` support verification first (3.7 pragma semantics unverified) and dedicated boundary tests. Boundary tolerance IS covered meanwhile by the garden's `boundary-tolerance` class (M-27..M-31). |
| `src/tools/analyze.py` / `src/tools/design.py` / `src/tools/evaluate.py` / `src/tools/generate.py` | tool handlers | dedicated test files exist (11/20/17/15 tests) and handlers carry real formatting/error-wrapping decisions, but the tests mock the pipeline — expect survivor noise; ~1 600 LOC would grow the mutant surface by ~4x. Add as a dedicated PR AFTER the first nightly run reports wall-clock for the current scope (job cap: 180 min). |
| `src/tools/get_architecture_design_status.py` | status mapping handler | its tests live in `test_server.py`, which is not in the mutation test selection (and pulling in all of test_server drags server wiring into every slice). Needs a dedicated handler test file first. |
| `src/tools/patterns.py` | list/get pattern handlers | thin loader delegation; loader.py itself is already in scope. |
| `src/reasoning/config.py` | `get_strategy`, command validation | mostly declarative pydantic; the tested decisions (defaults, override parsing) are pinned via `test_reasoning_client.py` but the model-default bulk would be equivalent noise. Revisit together with `src/config.py` pragma work. |

### Model-checked (L4) — decisions owned by the fizz/L1/L2 layers

> Excluded from mutmut because the decision surface is already pinned by
> layers whose authority does not degrade with survivor noise: FizzBee checks
> the state machine exhaustively up to bounds, and the L1/L2 oracles call the
> REAL pipeline methods. Mutating individual statements would re-test
> decisions these layers already enforce.

| Module | Decision functions | Why excluded | Coverage authority |
|---|---|---|---|
| `src/pipeline.py` *(Orchestration)* | `run_design`, `_orchestrate`, `design_loop`, `_build_retry_attempt_prompt` | heavily coupled Workflow-backed loop: shared mutable best-design state, cancel checkpoint between attempts, retry-with-feedback; single-statement mutants re-test what the model checker pins at state-machine level | L4 `design_loop.fizz` (DL-2..5) + `pipeline_control.fizz` (P-1, FP-2..7) + `jobs_runner.fizz` (RUN-1/RUN-3/C-1) **+ L2 `tests/verification/test_pipeline_properties.py` (`TestP1AttemptBound`, `TestDL2BestScoreGuard`, `TestDL3CancelFreezes`, `TestDL4MalformedContinues`, `TestDL5EarlyStopThreshold`, `TestFPTerminalDiscipline` — over the REAL `design_loop`, phases scripted)** |
| `src/pipeline.py` *(Analyze)* | `analyze`, `_extract_requirement_weights(._once)`, `_smooth_weights`, `_score_patterns`, `_select_recommended_style`, `_style_candidates`, `_selected_style_score`, `_calculate_quality_metrics`, `_analyze_strengths`, `_analyze_weaknesses`, `_generate_recommendations`, `AnalysisResult`, `_analyze_system_prompt_cached`, `_build_analyze_system_prompt`, `_build_analyze_user_prompt`, coercers (`_pattern_from_entry`, `_to_matched_domain`, `_effective_pattern_score`) | deterministic scoring is decision-dense but every branch has a direct pin; the LLM boundary is already mutated via `src/agent.py`; prompt builders are string-noise | L1 `test_pipeline.py` (`test_score_patterns_*`, `test_select_recommended_style_*`, `test_style_candidates_*`, `test_selected_style_score_*`, `test_calculate_quality_metrics_*`, `test_analyze_*`) **+ L2 `test_two_stage_properties.py` (TS-2..TS-6 over the REAL `_score_patterns`)** + L3 `src/agent.py` |
| `src/pipeline.py` *(Generate)* | `generate`, `_build_retrievers`, `_build_pattern_context`, `_pattern_context_key`, `_build_generate_system_prompt`, `_build_generate_user_prompt`, `_generate_system_prompt_cached`, `_select_refinement_pattern`, `_retry_prompt`, `_render_retry_pattern_section` | prompt construction = string-mutant noise; contract construction/denormalization and the lean-vs-full schema switch are pinned; retriever construction is exercised at warmup; LLM transport already mutated via `src/agent.py` | L1 `test_pipeline.py` (`test_generate_phase`, `test_generate_propagates_populated_contracts`, `test_generate_contracts_roundtrip`, `test_generate_denormalizes_*`, `test_patterns_flow_through_generate_metadata`) + L3 `src/agent.py` |
| `src/pipeline.py` *(Evaluate)* | `evaluate`, `_generate_evaluation_recommendations`, `_build_evaluate_system_prompt`, `_build_evaluate_user_prompt`, `_render_analysis_summary` | prompt construction = string-mutant noise; the deterministic recommendation merge and contract passing are pinned; LLM transport already mutated via `src/agent.py` | L1 `test_pipeline.py` (`test_evaluate_phase`, `test_evaluate_receives_populated_contracts`, `test_patterns_flow_through_evaluate_quality_benchmarking`) + L3 `src/agent.py` |
| `src/pipeline.py` *(Helpers)* | `CancellationToken`, `__init__`, `_reasoning_block`, `warmup_indexes`, `_phase_extra`, `_timed_phase` | cross-phase plumbing; cancellation is pinned by the L2 loop oracle (token injection seam); timing/log helpers are observational | L1 `test_pipeline.py` + L2 `test_pipeline_properties.py` (`TestDL3CancelFreezes`, `TestFPTerminalDiscipline` — `CancellationToken` exercised via the injection seam) |

## Permanent (excluded by design)

> Excluded for structural reasons (wiring / declarative / prompt text), not
> pending triage. A module leaves this section only by growing real decision
> density AND a dedicated kill oracle — same-PR ledger row required
> (AGENTS.md L3 rule). Cross-ref `pyproject.toml [tool.mutmut].do_not_mutate`
> for the canonical list.

| Module | Decision-density zones | Why permanently excluded | Coverage authority |
|---|---|---|---|
| `src/main.py` | `cli()` health-check branch; option dispatch | thin click CLI wrapping `server_main` — mutation surface is dispatcher noise | L0 (ruff/mypy) + server-lifecycle integration tests (outside the mutation selection) |
| `src/__main__.py` | — | one-line `python -m src` shim delegating to `src.main.cli` | L0 + import smoke at startup |
| `src/server.py` | `_with_prompts_as_tools_annotations`; transport validation (`stdio`/`streamable-http`); job-task cancel gather; JSON log-formatter branch | FastMCP wiring + lifespan management; the four decision zones are integration-tested but survivors would be framework noise (string literals, gather patterns, formatter construction) | L1 server-lifecycle integration tests (outside the mutation selection) + L0 |
| `src/mcp_prompts/*` | `register_prompts` dispatch | user-invoked workflow templates; prompt text = string-mutant noise bombs; registration is a dispatch table | L1 `test_server.py` + L0 |
| `src/patterns/nodes.py` | `build_bm25_retriever` `top_k <= 0 → full corpus` resolution | thin LlamaIndex leg factories over the shared domain-slug node set; the single top_k decision has a direct pin | L1 `test_bm25_retriever.py` (`test_zero_top_k_means_full_corpus`, node-shape tests) + L0 |
| `src/prompts/*` | `get_style_guidance` lookup | internal LLM prompt content + few-shot examples; string-mutant noise bombs; schema drift is caught at import time (examples instantiate against the Pydantic models) | L0 import-time schema validation (`examples.py`) |
| `src/reasoning/schemas.py` | `ReasoningTrace.render_lines` formatting | declarative Pydantic schemas for the reasoning integration; `render_lines` is pure formatting observed via caplog asserts | L1 `test_reasoning_client.py` + L0 |
| `src/reasoning/__init__.py` | `__getattr__` PEP 562 lazy import | re-exports + one lazy import breaking the `client → src.agent → src.config` cycle; pure wiring | L0 + import smoke |
| `src/resources/*` | resource-handler JSON dumps + slug→blueprint lookup | FastMCP resource registration wiring; handlers are format-and-lookup | L1 `test_resources.py` (loader-backed handlers, slugify, templates) + L0 |
| `src/schemas/*` | — | declarative Pydantic models + enums; unasserted defaults would flood equivalents (same rationale as `src/config.py`'s model bulk, without the boundary logic) | L0 (`mypy --strict` schema gate) + Pydantic validation at tool boundaries |
| `src/tools/__init__.py` | `create_all_tools` dispatch table | tool factory: maps tool keys to constructors; handler decisions live in the per-tool modules (rows above) | L0 + server-lifecycle integration tests |

## Gate mechanics (what `make test-mutations` now enforces)

1. mutmut is pinned `==3.7.*` in lockstep with `verify/mutmut/mutmut_compat.py`
   (source-string guards fail loudly on an upstream change — bump pin + shim
   together).
2. `also_copy = ["verify/", "scripts/", "pattern/"]`: the scratch tree must
   carry the shim, the scripts package the `tests/verification` meta-tests
   import (a missing copy aborts the run at stats collection — observed
   2026-09-11), and the real pattern catalogue (observed 2026-09-12: a
   missing `pattern/` copy fails the LD-6 real-data pin with "catalogue must
   not be empty" and silently vacuates LD-4, whose corruption pool collapses
   to the empty set).
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
   is unaffected). Done 2026-09-11 after the round-2 scope expansion,
   2026-09-12 after adding `pattern/` to `also_copy`, and 2026-09-12 after
   the consecutive-run cache warning ("pyproject.toml changed … cached
   results were kept").
8. Dependency-change policy: `on_dependency_change = "rerun"` +
   `cache_invalidation_files = ["pattern/*.json"]` (both keys verified
   present in the 3.7.0 `Config` dataclass). The default "warn" KEEPS cached
   mutant results when a watched non-Python file changes — for a manual
   nightly ratchet that means `scripts/mutmut_baseline.py --gate` could
   distill stale verdicts (observed 2026-09-12). "rerun" discards all
   results instead; the catalogue glob additionally re-tests the loader
   mutants when the `pattern/` data the LD-4/LD-6 oracles read changes.

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
