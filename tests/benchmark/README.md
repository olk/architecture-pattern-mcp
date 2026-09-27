# Prompt A/B Benchmark Suite

Measures whether a change to the GENERATE-phase system prompt
(`_generate_system_prompt_cached` in `src/pipeline.py`) actually improves design
quality, before the change merges.

The runner is **version-agnostic**: it imports the pipeline from whatever source
tree `--src` points at. There is no `prompt_version` config flag — the baseline
and candidate are two checkouts (branches/worktrees) run through the same runner
and case list.

## Prerequisites

1. `uv sync` (dev environment)
2. A valid `config/config.json` with LLM credentials (the pipeline runs live LLM
   calls — this suite is **not** part of CI's default unit run).
3. TEI embedding sidecar and reranker sidecar running. The hybrid retriever's
   dense leg fails without them:
   `docker compose -f docker/docker-compose.yml up -d`
4. Judge temperature `0` in `config/config.json` (recommended, see RUBRIC.md).

Cost estimate for a full run: ~150-400 LLM calls, roughly 3-6 hours wall clock
for 37 cases x up to 3 design_loop attempts x (generate + evaluate).

## Two-branch procedure

```bash
# 1. Baseline arm (main, before the prompt change merges)
git worktree add ../apm-v1 main
uv run python tests/benchmark/runner.py --src ../apm-v1 --out results_baseline.json

# 2. Candidate arm (the branch with the prompt change)
uv run python tests/benchmark/runner.py --src . --out results_candidate.json

# 3. Compare and gate
uv run python tests/benchmark/compare.py results_baseline.json results_candidate.json
```

`compare.py` exit codes: `0` gate passed, `1` gate failed, `2` inputs unusable
(case sets unaligned or empty results).

Useful subset runs (smoke tests, judge-variance checks):

```bash
uv run python tests/benchmark/runner.py --src . --out smoke.json --limit 3
uv run python tests/benchmark/runner.py --src . --out subset.json --only ec-001 iot-040 lg-080
```

## Case list

`requirements.jsonl` holds 37 curated cases spanning e-commerce, fintech,
healthcare, IoT, data pipelines, AI, internal tools, gaming and legacy
modernization. It forces most styles explicitly — including `blackboard`,
`strangler-fig`, `clean-architecture`, `client-server` and `master-slave`,
which the pre-fix prompt forbade — and leaves 2 cases style-free to exercise
the analyze-phase recommendation path. The file lives next to the runner and is
used unchanged for both arms; do not edit it between arms.

## Metrics

Deterministic (immune to judge noise):

- `dangling_references` — relationship source/target ids missing from components
- `generic_technologies` — technology_stack entries matching a generic stopword
  list ("web framework", "database", ...)
- `qa_format_valid` — every `quality_attributes` value matches `"N/10"`
- `field_population` — presence of api/data/event contracts and config requirements
- `component_count`, `attempts`, `validation_success`

Judge-based (see RUBRIC.md for anchors and bias caveats):

- `overall_quality` — final best-attempt score from the server's evaluate phase

## Merge gate

`compare.py` passes only when, over >= 30 paired cases:

1. `overall_quality` improved with p < 0.05 (paired permutation test),
2. `validation_success`, `dangling_references` and `attempts` did not regress,
3. `generic_technologies` did not regress (the -50% reduction target is
   reported but not gated).

A failed gate blocks merge; investigate per-case output before retrying.

---

# Stage-0 selection benchmark harness

Selection-quality benchmark for the architecture pipeline, ported from
`design-pattern-mcp-local@25cbfba` (`tests/benchmark/harness/`) and adapted to
`ArchitecturePipeline`. It never edits `src/`: the pipeline is constructor-injected, so the
runners wrap the seams they hand in (retrieval legs, agent, reasoning client).

## Modes

| mode     | module                    | seams                                                       | stage attribution | calibration score |
|----------|---------------------------|-------------------------------------------------------------|-------------------|-------------------|
| offline  | `harness/main.py`         | scripted legs + scripted LLM over the real catalog          | yes (scripted)    | yes (85.0 stub)   |
| live     | `harness/main.py`         | real TEI embedder/reranker, real generator, optional reasoning | yes           | yes               |
| e2e      | `harness/e2e.py`          | fastmcp Client → running stack (`design_architecture`)      | no                | no (wire carries none) |

- **offline** — deterministic plumbing proof (<60 s, no network). Every scenario's domain-slug
  pool is scripted so the primary pattern must win through the real fusion path; `--flip <id>`
  demotes the primary to last rank as a negative control (the run note asserts flipped = miss,
  non-flipped = hit).
- **live** — the shipped pipeline in-process with per-stage timing wraps
  (`retrieval.dense`, `retrieval.bm25`, `llm.weights`, `llm.generate`, `llm.evaluate`).
  Rerank/embed time shows up as the e2e residual (overlapping concurrent generate batches can
  make the residual negative — the record carries a `residual_note` explaining this).
  The loopback reranker sidecar is CPU-bound and rejects work when the machine is loaded
  (`HTTP 429 Model is overloaded`); that propagates out of `analyze` as
  `RuntimeError: TEI reranker … 429` and is recorded as a *failed scenario*
  (`provenance.error`, counted as a miss, `compare` refuses the arm) — so run one arm at a
  time and keep other CPU-heavy jobs, including ad-hoc retrieval probes, off the machine.
- **e2e** — black-box: what a real deployment costs *in total* and nothing else. Hit/recall are
  computed over `final_style ∪ alternative_styles[].name`; the tool error is recorded, never
  dropped. Calibration/risk-coverage are reported as `{"available": false}`.

## Metrics (see `harness/scoring.py`, pinned by `harness/selfcheck.py`)

- **hit** — `final_style` (analyze-only: `recommended_style`) is in the scenario's
  `expected.acceptable_primary` and the run is not a fallback; a fallback is an automatic miss.
- **recall@3 / recall@5** — the analyze selection set capped at K against `acceptable_primary`.
- **acceptable-primary F1** — hit ⇒ P=1, R=1/|A|; miss ⇒ 0/0.
- **Brier / ECE(10)** — monitoring-only diagnostics over `final_quality_score/100`.
- **risk-coverage** — within-arm ordering by score; AUC anchored at (0,0).
- Supporting-set F1 and veto-conflict violations (A's harness) are **dropped**: B exposes no
  supporting-set or veto-ledger observables.

## Pre-registered A/B decision rule (`harness/compare.py`)

> candidate wins iff holdout p95 e2e improves ≥ 15% AND the candidate holdout hit rate stays
> ≥ the baseline's Wilson 95% lower bound.

Anything else is `inconclusive` or `candidate-loss` (`make benchmark-compare` exits 1 on a
loss, 2 on a refusal). At this corpus size the rule usually resolves to `inconclusive` — that
is reported, never hidden. Compare refuses corpora whose scenario-file sha256 or mode differs
(`--allow-mismatch` overrides with a warning).

## Usage

```sh
make benchmark-selfcheck                       # metric formulas vs hand-computed anchors
make benchmark-offline                         # 16 deterministic scenarios
make benchmark-offline FLIP=coordination-robot-orchestration   # negative control
make benchmark-sidecars-up                     # publish TEI sidecars on 127.0.0.1:18081/18082
make benchmark-live LIMIT=2                    # real in-process pipeline (needs DEEPSEEK_API_KEY)
make benchmark-live LIMIT=1 LOG_LEVEL=info     # + per-phase logs: candidate pool, fusion summary, scores
make benchmark-e2e LIMIT=2                     # black-box vs the running compose stack
make benchmark-draft DRY_RUN=1                 # print the corpus-drafting prompt
make benchmark-compare A=<dir> B=<dir>         # paired comparison + verdict
```

Run directories land in `data/benchmark-runs/<run-id>/` (gitignored): `manifest.json`
(git/env/config provenance), `summary.json`, `report.txt`, `scenarios/*.json`. A crashed run
(e.g. executor-creation failure, `--fail-fast` set, or Ctrl-C) writes `aborted.json` instead of
a summary and `compare` refuses it. By default a *scenario* failure (e.g. the provider returning
malformed JSON that survives `VALIDATION_MAX_RETRIES` repair attempts) is recorded instead:
the scenario's record carries `provenance.error`, counts as a miss in every rate, appears in
`summary.failures` and the report's "Failed scenario runs" table, and the arm completes —
one stochastic LLM glitch does not burn a ~50-minute live arm. `compare` refuses completed
arms that contain failed scenario runs (`--allow-mismatch` overrides, at your own risk).
The offline mode's fixture-integrity gate ignores failed records for the same reason:
their integrity is expressed by `summary.failures`, not the scripted hit gate.

Console output: `--log-level` (default `warning`) is applied to the root logger, its handlers
*and* the `bm25s` logger — bm25s re-pins itself to DEBUG at import time, after the harness has
configured logging, so the handler level is what holds it quiet. The harness also appends the
pipeline's `phase`/`attempt`/`error`/`errors` `extra` fields to rendered warning-and-worse
lines, so a self-healing GENERATE retry (`Attempt 1 failed with
MalformedArchitectureOverviewError`) prints the offending validation locator instead of a bare
message; the retry itself is counted in the record's `llm.generate` stage count.

### Structured-output contract (what a live `llm.*` stage measures)

Structured output travels through llama-index function calling (`as_structured_llm` →
`FunctionCallingProgram`, one tool named after the response schema), so every prompt that
feeds `generate_structured` must ask for that *function call*: wording that asks for "a JSON
object" as the reply text invites a plain-text answer the transport discards and heals by
retry. Measured 2026-09-27 (DeepSeek V4.1 Flash, live arm plus prompt A/B on the real EVALUATE
system prompt): 6 of 12 sampled calls replied with text JSON and no tool call, ~20-30 s per
wasted call — that is what produced the `Self-healing repair call failed` warnings, the
inflated `llm.*` stage times, and the failed scenario records
(`ERR_009 … Expected at least one tool call, but got 0 tool calls`, then a cascaded
`design_loop produced no valid design`). The GENERATE/ANALYZE/EVALUATE/RETRY prompt builders
now carry the function-call clause (`tests/unit/test_pipeline.py::TestStructuredOutputContract`
pins it), so a live `llm.*` stage is one call per phase unless a provider faults again.

## Corpus

`scenarios/seed.json`: 16 scenarios, 2 per `PatternCategory` over 8 categories. The family is
the category, so the train/holdout split is category-disjoint: holdout = {api_gateway, cloud,
dataflow} (6 scenarios). `scenario.schema.json` pins the record shape (jsonschema-validated on
load). Expansion to a `full.json` corpus goes through `make benchmark-draft` and manual label
review — drafts are never committed.

Every scenario carries an authored `domain`. Both live retrieval legs index *catalogue domain
slugs* (one node per `suitable_domains` value, `src/patterns/nodes.py`) and the analyze phase
queries them with the domain string alone (`retriever.retrieve(user_domain=domain)`); the
requirements text only reaches the weights extraction. A domain the catalogue does not know
therefore measures slug-matching noise, not the pipeline's requirements-weighted ranking —
measured 2026-09-27, feeding the pattern `category` as the domain (`messaging`) ranked the
(dataflow) `kappa-architecture` first through its unrelated `notifications` slug, with the
labelled `event-driven` outside the top 5. The corpus rule:

- `domain` MUST be a `suitable_domains` value of the primary label (loader-enforced), so the
  labelled pattern is always retrievable and a typo fails on load;
- it SHOULD also be listed for an acceptable sibling, so the near miss competes for the same
  pool — 8 of the 16 seed scenarios share one, the other 8 name a primary-only domain (the
  sibling is then unreachable in live mode; its label still counts in hit/F1);
- it is passed verbatim to `analyze`, reaches the generate/evaluate prompts, and is echoed in
  every run record (`scenario.domain`).

The offline stub legs ignore the query entirely (scripted slug order), so the offline fixture
gate is unaffected by the domain value.

No `test_*.py` lives here: pytest never collects the harness; `selfcheck` is its own gate.
