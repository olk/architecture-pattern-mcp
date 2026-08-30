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
