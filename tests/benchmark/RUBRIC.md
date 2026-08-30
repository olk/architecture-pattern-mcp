# Benchmark Judge Rubric

This document fixes how design quality is measured during prompt A/B benchmarks so
that the only intended difference between arms is the GENERATE-phase system prompt.

## Judge setup

- The judge is the server's own EVALUATE phase (`ArchitecturePipeline.evaluate`),
  run inside `design_loop` — no external judge tool is used.
- The judge model, temperature, and evaluation criteria string MUST be identical
  across both arms. Only the checkout under `--src` differs.
- Recommended: set generator temperature to `0` in `config/config.json` for both
  arms to reduce judge variance.
- The judge sees the same criteria default (`quality,maintainability,scalability`)
  unless a case overrides it — this suite does not override it.

## Score anchors

The judge emits 0-100 scores per metric plus `overall_quality`. Anchor the
interpretation as follows when reading results:

| Score | Meaning |
|-------|---------|
| 90+   | Exceptional: design decisions are outstanding for the stated requirements and style; rare |
| 75-89 | Strong: production-ready with minor, clearly-identified gaps |
| 60-74 | Balanced: sound design with real trade-offs; typical good output |
| 40-59 | Weak: significant gaps (missing contracts, dangling references, vague technologies) |
| < 40  | Poor: does not address the requirements or is internally inconsistent |

A *healthy* design scores 6-7/10 per quality attribute (60-74 overall), not 9-10.
Inflated self-scores across BOTH arms indicate judge leniency, not improvement.

## Known judge biases (and mitigations)

1. **Self-evaluation bias** — the same configured model judges designs it generated.
   Mitigation: the judge is identical in both arms, so bias affects both arms
   equally; relative deltas remain meaningful. Absolute scores do not transfer
   across models.
2. **Verbosity bias** — judges tend to reward more components/contracts. The
   dangling-reference and generic-technology metrics are computed
   deterministically and are immune.
3. **Position/anchoring** — criteria are fixed in the server's evaluate prompt;
   do not reorder criteria between arms.

## Variance check (run before trusting a comparison)

LLM judges are noisy. Before gating on a full comparison:

1. Re-run a 10-case subset with the same `--src` into a `*_judgecheck.json` file:
   `uv run python tests/benchmark/runner.py --src . --out judgecheck.json --only ec-001 pay-010 fin-020 iot-040 dp-050 ai-061 web-071 lg-080 misc-122 any-130`
2. Compare `overall_quality` between the check run and the arm it duplicates.
3. If the per-case spread exceeds ~8 points on more than 3 of 10 cases, the
   signal is too noisy: increase the case count (or set judge temperature to 0)
   before drawing conclusions.

## Metrics recorded per case

| Metric | Source | Gated? |
|--------|--------|--------|
| `overall_quality` | judge (final best attempt) | must improve (p < alpha) |
| `attempts` | design_loop retry count | must not regress |
| `dangling_references` | deterministic (relationships vs component ids) | must not regress |
| `generic_technologies` | deterministic (stopword match) | must not regress; -50% target reported |
| `validation_success` | pipeline completed without exception | must not regress |
| `qa_format_valid` | deterministic (`"8/10"` string format) | reported |
| `field_population` | deterministic presence checks | reported |
| `component_count` | descriptive | reported |
