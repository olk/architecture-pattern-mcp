# Plan: `stage0-benchmark-port` — port the Stage-0 selection benchmark harness into architecture-pattern-mcp

## Context

`../design-pattern-mcp-local` @ `25cbfba` has a Stage-0 benchmark harness (`tests/benchmark/harness/`, 11 modules + `scenarios/seed.json` + compose override + `benchmark-*` Make targets) that measures pattern-selection quality (hit rate, recall@K, primary F1, calibration, risk-coverage) with per-stage latency attribution and a pre-registered A/B decision rule. This repo (B) has only the prompt-A/B suite (`tests/benchmark/runner.py` + `compare.py` + `requirements.jsonl`, script mode). Goal: port the harness so B gets the same selection-quality instrument, adapted to B's pipeline, with **zero `src/` edits** and **no new dependencies** (`jsonschema` is transitively present via `litellm`/`mcp` — verified in `uv.lock`).

Verified A→B substitutions this plan is built on:

| A (design-pattern-mcp-local) | B (this repo) |
|---|---|
| `DesignPipeline(config, catalog, index, llm, guard, reasoning)` | `ArchitecturePipeline(agent, pattern_loader, embedder_config, retrieval_config, reranker_config, reasoning_client)` — `src/pipeline.py:539-547`; entry `.run_design(requirements, domain, style, evaluate_criteria, cancellation)` :631-664 |
| `PipelineResult.final_pattern` | `PipelineResult.final_style` (= `best_design.overview.style.value`, :1146) |
| `selections[].candidates[].fit_score(/100)` | `AnalysisResult.selected_patterns[*]` dicts with `analysis_score`(0-100), `fusion_score_normalized`, `blended_score`(0-100) (`_score_patterns` :1666-1714) |
| `PartSelection` primary/supporting/veto | none — dropped, with their metrics |
| `DESIGN_PATTERN_*` env | section-scoped env: `GENERATOR_*, EMBEDDER_*, RERANKER_*, RETRIEVAL_*, REASONING_*, VALIDATION_*, TASKS_*` + `PATTERN_DIRECTORY`, `MINIMAXAI_API_KEY` (config/config.json) |
| `DESIGN_PATTERN_CONFIG_PATH` | `CONFIG_PATH` (`ConfigManager.load_config`, `src/config.py:459-513`) |
| e2e tool `select_design_patterns` @8062 | `design_architecture` @8050, client env `ARCHITECTURE_CLIENT_URL` (examples/architecture_client.py:57) |
| `OfflineHashEmbedder`/`LexicalReranker`/`tests/unit/fakes.py` | none — offline doubles live inside the harness |
| catalog `### subgroups` families | `category` (PatternCategory, 10 values; 40 patterns; enum values == pattern names, verified 40/40) |

Key B behaviors the harness must respect:

- **Style selection chain** (offline must exercise it end-to-end): stub legs → fusion+rerank blend → `_score_patterns` (weights × `quality_attributes`) → `_select_recommended_style` (top `analysis_score` ≥ `style_score_threshold` 50.0 else `layered-monolith`, :1721-1747) → generate prompt literally contains `Design a {style} architecture for the {domain} domain` (:1525) → `final_style` = generated `overview.style.value`. Config defaults: `analysis_blend_weight=0.7`, `fusion_blend_weight=0.3`, `weight_smoothing_alpha=0.7`, `max_tries=3`.
- **Rerank is not separately attributable**: `SafeTEIReranker` is built inside `HybridPatternRetriever._ensure_reranker` (`src/patterns/retriever.py:311-332`) from config; rerank latency lands in `residual_ms` (documented deviation).
- **Retrieval legs are swappable**: `analyze()` reads `pipeline._dense_retriever`/`_bm25_retriever` per call and only calls `_build_retrievers()` when either is `None` (:696-700) — same trick `create_test_pipeline` uses (`tests/unit/test_pipeline.py:370-388`).
- **Agent seam**: exactly 3 `generate_structured` call sites — `RequirementWeights` (:1644), `ArchitectureDesign` (:856), `ArchitectureEvaluation` (:953). Reasoning seam: `.enabled` + `run_pre_llm(phase, …)` with phases analyze/generate/evaluate/retry (:754/844/940/984; `src/reasoning/client.py:190-279`).

## Approach

Deliverable tree (all new files except Makefile/.gitignore/README edits):

```
tests/benchmark/__init__.py            (empty — makes the package importable; does NOT affect
                                        script-mode `uv run python tests/benchmark/runner.py`)
tests/benchmark/harness/__init__.py    (docstring only)
tests/benchmark/harness/{config,probes,scoring,runner,offline,e2e,compare,draft,selfcheck,main}.py
tests/benchmark/scenarios/scenario.schema.json
tests/benchmark/scenarios/seed.json
docker/docker-compose.benchmark.yml
Makefile                               (##@ Benchmark section + .PHONY additions)
.gitignore                             (+ data/benchmark-runs/)
tests/benchmark/README.md              (append Stage-0 section)
```

No `test_*.py`, no `conftest.py` under `tests/benchmark/harness/` → pytest still collects nothing there (`testpaths=["tests"]` finds no test files).

### 1. Scaffolding + seed corpus (`config.py`, schema, `seed.json`)

- `Scenario` dataclass: `scenario_id`, `family` (PatternCategory value), `description` (40–10000 chars), `split` (train|holdout), `style` (always `null` in seed — no hints), `expected{primary, acceptable_primary}` (≥2 unique names), optional `weights` (dict of the 6 quality attributes — drives offline scripted ranking; B-specific addition), `notes`. `Scenario.primary` property = `acceptable_primary[0]`. **Drop** A's `decision_statement/category/language/paradigm/focus/acceptable_supporting` (B has no language, no decision parts, no supporting concept — supporting-F1 is gone with it).
- Corpus loader: `jsonschema.Draft7Validator` over `scenarios/scenario.schema.json`, unique ids, split coverage, catalog resolvability via `PatternLoader().get_by_name(name) is not None` (`src/patterns/loader.py:300`).
- `load_run_config()`: `CONFIG_PATH` env → default **repo** `config/config.json` (never the `~/.config` default — it carries a legacy schema ServerConfig rejects) → `ConfigManager.load_config` → raw dict validated by `ServerConfig.model_validate`. Offline override: `retrieval.min_fusion_score = 0.0` only (B has no `selection` section — A's `primary/supporting_score_threshold` override is dropped).
- Env snapshot for the manifest: prefixes `GENERATOR_, EMBEDDER_, RERANKER_, RETRIEVAL_, REASONING_, VALIDATION_, TASKS_` + extras `PATTERN_DIRECTORY`, `MINIMAXAI_API_KEY`, `ARCHITECTURE_CLIENT_URL`. Never writes config files.
- `seed.json`: **16 scenarios = 2 per category** for the 8 categories with ≥2 patterns (messaging 5, structural 10, coordination 7, data 5, cloud 3, ai_cognitive 4, api_gateway 2, dataflow 2); `presentation`/`specialized` dropped (single pattern → sibling near-miss vacuous). Hand-authored; do NOT recycle `requirements.jsonl` (different protocol: prompt-quality vs selection-quality). Near-miss siblings chosen from the verified domain-overlap pairs, e.g. `hexagonal`~`clean-architecture` (3 shared domains), `microservices`~`clean-architecture`, `model-view-controller`~`client-server`, `broker`~`enterprise-service-bus`, `event-driven`~`reactive-architecture`, `cqrs`~`data-mesh`, `saga`~`blockchain-based`, `hybrid-cloud`~`multi-cloud`, `blackboard`~`rule-based-system`, plus the two api_gateway and two dataflow patterns. Split family-disjoint ≈ 11 train / 5 holdout (holdout spread across sizes). Each description must make `primary` the natural winner; `weights` set explicitly where uniform weights would let a sibling win (offline gate enforces, see step 3).

### 2. Pure-math layer (`scoring.py`) + probes + selfcheck

- Metrics (adapted from A): acceptable-primary **hit** (`not is_fallback and final_style ∈ acceptable_primary`); **recall@K** (K=3,5) over `selected_patterns` names ∪ `alternative_styles` names; **primary precision/recall/F1**; **calibration** `score = clip01(blended_score/100)` from the top `selected_patterns` entry (B's selection confidence; `alternative_styles[].score` is the same scale), Brier + ECE(10 bins) + risk-coverage curve; **Wilson** interval; **sign test** + **Newcombe** CI. Dropped vs A: supporting-F1, veto-conflict count (no observables). `statistics`/`math` only.
- `probes.py`: `LLMTimingProxy` wrapping the agent — wraps `generate_structured`, buckets by `response_schema` class → `llm.weights|generate|evaluate`; `ReasoningTimingProxy` wrapping `ReasoningClient` — forwards `.enabled`, wraps `run_pre_llm` → `reasoning.<phase>`; leg proxies wrapping the dense/BM25 retrievers (forward sync `retrieve` — `QueryFusionRetriever` is built with `use_async=False` — and `aretrieve` for safety) → `retrieval.dense|retrieval.bm25`. Stage table keys: `build.embed` (warmup), `retrieval.dense`, `retrieval.bm25`, `llm.weights|generate|evaluate`, `reasoning.analyze|generate|evaluate|retry`, e2e-only `e2e.total/http/overhead`, and `residual_ms = total − Σ(attributed) ≥ 0` (rerank lands here — documented).
- `selfcheck.py`: A's checks minus `check_veto_conflicts`, with `check_recall_and_f1` primary-only → 10 checks, all numeric anchors unchanged (percentiles, stage_table, wilson, sign_test, newcombe, recall_and_f1, hit_and_score, calibration, risk_coverage, proxies). `python -m tests.benchmark.harness.selfcheck`, exit 0 on all-pass.

### 3. Offline mode (`offline.py`) — deterministic, no network, <60 s

Mirrors `create_test_pipeline` + `test_analyze_phase`'s reranker patch:

- Stub legs: return `NodeWithScore(TextNode(text=slug, metadata={"slug": slug}))` per expected pattern, slugs drawn from **each expected pattern's own `suitable_domains`** (so `filter_by_domain` resolves them), descending scores in `acceptable_primary` order (primary first). Both legs identical; `--flip <scenario_id>` swaps the top two (decoy).
- Reranker: `unittest.mock.patch("src.patterns.retriever.SafeTEIReranker", return_value=_DummyReranker())` — identity `postprocess_nodes`, `top_n` attr — **scoped to the offline executor process** (documented deviation from A's zero-monkeypatch stance; same mechanism as `tests/unit/test_pipeline.py:427-435`).
- Pipeline: `ArchitecturePipeline(agent=ScriptedAgent, pattern_loader=PatternLoader() (real catalog), embedder_config=EmbedderConfig(provider="none", config=EmbedderInnerConfig()), retrieval_config=RetrievalConfig(min_fusion_score=0.0, …defaults), reranker_config=RerankerConfig())`; pre-inject `pipeline._dense_retriever/_bm25_retriever = stubs` so `_build_retrievers()`/embedder never runs; never call `warmup_indexes()`.
- `ScriptedAgent.generate_structured`: `RequirementWeights` → scenario `weights` (or uniform); `ArchitectureDesign` → minimal valid instance with `overview.style` parsed from the user prompt via `r"Design a ([a-z0-9-]+) architecture"` (exact wording verified at :1525) — this makes offline `final_style` reflect the **real** deterministic chain (real fusion → real `_score_patterns` → real `_select_recommended_style`) so `--flip` flips the hit; `ArchitectureEvaluation` → minimal valid instance (`overall_score` 80, empty lists). Only required fields populated; optionals default.
- **Fixture-integrity gate**: with no `FLIP`, every scenario must hit (`final_style == primary`); with `FLIP=<id>`, exactly that scenario misses. A scenario failing the gate ⇒ adjust its `weights`/description or swap the sibling choice (overlap table), never the harness.

### 4. Runner + main (`runner.py`, `main.py`)

- `RunOptions`: mode, scenarios path, out dir, run_id, limit, split, repeat, flip, no_warmup, url (e2e), call-timeout. `main.py` = argparse dispatcher for offline/live/e2e.
- Live executor: `load_run_config()` → real `SoftwareArchitectAgent` (wrapped) → `ReasoningClient(reasoning_cfg, agent)` (wrapped; optional `health_check()` recorded as `reasoning_health`) → `ArchitecturePipeline(...)` → `warmup_indexes()` (timed as `build.embed`) → replace `_dense_retriever`/`_bm25_retriever` with leg proxies → `run_design(requirements, domain)`. No `pipeline.validate()` (A-only).
- Per-run record: `scenario_id, split, repeat_idx, hit, primary_f1, recall@3/@5, calibration{score,hit,miss}, latency_ms, stage_ms{…}, final_style, is_fallback, selected_pattern_names, alt_style_names, error/aborted flags`. Run dir `data/benchmark-runs/<run_id>/`: `manifest.json` (`run_id, mode, corpus_sha (sha256 of scenarios file), config_hash, env snapshot, created_at, scenarios_file, reasoning_health`), `records.jsonl`, `summary.json` (per-split aggregates: hit rate + Wilson, p50/p95 latency, mean F1, Brier, ECE, risk-coverage AUC, per-stage p50s), `report.txt`.

### 5. e2e (`e2e.py`) + compose override

- `fastmcp.Client(url)` → `call_tool("design_architecture", {requirements, domain})` (`style` only when scenario sets it) → wire `DesignArchitectureOutput`: `final_style`, `final_quality_score`, `is_fallback`, `alternative_styles`. e2e observables subset: hit + recall over `{final_style} ∪ alternative_styles` names; `selected_patterns`/calibration are wire-unobservable → nulls (documented). URL env `ARCHITECTURE_CLIENT_URL`, default `http://localhost:8050/mcp`; split `e2e.total` into `e2e.http` vs `e2e.overhead`.
- `docker/docker-compose.benchmark.yml` (additive override; base services at docker/docker-compose.yml:97/:121 publish nothing):

```yaml
services:
  pattern-tei-embed:
    ports: ["127.0.0.1:${BENCH_EMBED_PORT:-18081}:8080"]
  pattern-tei-rerank:
    ports: ["127.0.0.1:${BENCH_RERANK_PORT:-18082}:8080"]
```

### 6. Compare (`compare.py`) — pre-registered rule, verbatim semantics from A

Refusal (exit 2): `corpus_sha`/mode mismatch (`--allow-mismatch` escape), unpaired scenario ids, aborted records in either arm. Verdict: candidate **wins** iff holdout p95 e2e (or mode-matching total) latency improves ≥15% AND candidate holdout hit rate ≥ baseline Wilson lower bound; <4 holdout pairs → `inconclusive`. Exit 0 win/inconclusive, 1 candidate-loss. Reports paired sign test + Newcombe CI. Never edits run dirs.

### 7. Makefile + `.gitignore` + README

- `##@ Benchmark` section (B has none today; add targets to the `.PHONY` line): `benchmark-selfcheck/offline/live/e2e/compare/sidecars-up/draft` with `BENCH_RUNS/BENCH_SCENARIOS/BENCH_COMPOSE/BENCH_EMBED_URL/BENCH_RUN_ARGS` mirroring A. `benchmark-sidecars-up` = `$(BENCH_COMPOSE) up -d pattern-tei-embed pattern-tei-rerank`. `benchmark-live` recipe (single `sh -c`, A's pattern to dodge the GNU make `$(if)` comma trap): npm-root discovery for `REASONING_SHANNONTHINKING_CMD`/`REASONING_CODE_REASONING_CMD`, then `GENERATOR_PROVIDER/MODEL/BASE_URL/API_KEY` minimax defaults (`MINIMAXAI_API_KEY` fallback), `EMBEDDER_BASE_URL=http://127.0.0.1:18081/v1`, `EMBEDDER_API_KEY=tei-noauth`, `RERANKER_BASE_URL=http://127.0.0.1:18082` (no `DENSE_CACHE_PATH`/`GENERATOR_TIMEOUT_SECONDS` — not B env vars). `benchmark-compare A=<dir> B=<dir>` usage guard.
- `.gitignore`: append `data/benchmark-runs/` with a comment (regenerable run artifacts).
- `tests/benchmark/README.md`: append a "Stage-0 selection benchmark" section — mode matrix, metric definitions, decision rule, stage-attribution table **with the two documented deviations** (rerank in residual; offline `SafeTEIReranker` patch), seed-corpus authoring rules, and the old suite untouched. Existing content unchanged.

## Critical files & anchors

1. `src/pipeline.py` — ctor :539-547; legs read :696-700; analyze :666-808; reasoning call sites :754/844/940/984; agent call sites :856/953/1644; design_loop → `final_style`/`alternative_styles` :1146/:1155; generate prompt "Design a {style} architecture" :1525; `_score_patterns` :1666-1714; `_select_recommended_style` :1721-1747.
2. `src/patterns/retriever.py` — `_ensure_reranker` :311-332; retrieve/rerank-blend :353-540.
3. `src/config.py` — `ConfigManager.load_config` :459-513 (`CONFIG_PATH`); `RetrievalConfig` :159-292; `RerankerConfig` :119-140.
4. `tests/benchmark/runner.py` — script-mode bootstrap :107-111 (coexistence anchor); `build_pipeline` :139-158.
5. `tests/unit/test_pipeline.py` — `create_test_pipeline` :370-388 and `test_analyze_phase` reranker patch :427-435 (offline doubles recipe).

## Verification

Build order with acceptance criteria (each step's gate must pass before the next):

1. **Scaffold + corpus**: `uv run python -c` loads seed.json through the schema validator; every label resolves via `get_by_name`.
2. **Pure math**: `make benchmark-selfcheck` → exit 0, "all 10 checks passed".
3. **Offline**: `make benchmark-offline` → fixture-integrity (all-hit), populated stage table incl. `retrieval.dense/bm25`, `llm.weights/generate/evaluate`, `residual_ms ≥ 0`, <60 s, no network. Then `make benchmark-offline FLIP=<scenario_id>` → exactly that scenario misses.
4. **Compare dry-run**: compare the two offline dirs → verdict line executes, exit semantics correct (tiny holdout ⇒ `inconclusive`); corrupt one `corpus_sha` → exit 2.
5. **e2e + targets**: `make -n benchmark-live benchmark-e2e benchmark-sidecars-up` recipes well-formed; compose override validates (`docker compose -f docker/docker-compose.yml -f docker/docker-compose.benchmark.yml config -q`).
6. **Draft**: `make benchmark-draft DRY_RUN=1` prints the prompt, writes nothing.
7. **Repo gates**: `make check-lint check-deadcode check-depcheck` green (deptry needs one `DEP003 = […, "jsonschema"]` addition with a comment: imported in tests, transitively provided via litellm/mcp — verified in uv.lock); `make check-static-typing test-unit` unchanged-green; `uv run pytest tests/benchmark --collect-only -q` collects 0 tests; old suite still runs: `uv run python tests/benchmark/runner.py --src . --out /tmp/x --limit 1` smoke.

User-gated (not part of implementation): `make benchmark-sidecars-up && make benchmark-live LIMIT=2` → stage table shows real `reasoning.*` and leg timings; `make benchmark-e2e` against the running stack. No baseline arm is committed.

## Assumptions & contingencies

- **`jsonschema` availability**: present via litellm+mcp in `uv.lock` (dev sync includes them); if CI deptry still objects beyond the DEP003 ignore, fallback = replace Draft-07 validation with a pydantic mirror model (no new import).
- **Offline style echo**: the regex targets the exact prompt string at :1525; if the wording ever changes, the offline fixture gate fails loudly → update the regex.
- **`final_style` ∈ pattern names**: guaranteed today (ArchitectureStyle enum values == catalog names, 40/40 verified); if that drifts, map via `get_by_name(final_style)` before comparing to labels.
- **Seed ranking failures**: scenario `weights` field exists precisely so a sibling that outscores primary under uniform weights can be corrected without touching harness code; last resort = swap sibling per the overlap table.
- **Rerank attribution / offline reranker patch**: deliberate, documented deviations forced by the zero-`src/`-edit constraint; both called out in README.
- **typing/lint scope**: harness is `tests/` — mypy strict does not apply (src/-only), vulture scans src/+examples only; ruff applies repo-wide, so the harness is written ruff-clean under the existing ignore list (no new per-file-ignores).
