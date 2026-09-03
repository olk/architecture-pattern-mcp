# Fusion Modes for Stage-1 Hybrid Domain-Slug Retrieval

Stage-1 of the recall pipeline fuses the BM25 leg with the dense embedding
leg via llama-index's `QueryFusionRetriever`. Stage-1 fusion **mode** is
**locked to `FUSION_MODES.RELATIVE_SCORE`** (per-leg min-max
normalization), and the slug-cut strategy is **locked to the Vespa-style
reciprocal-rank blend** `RR(fused_rank) + RR(ce_rank)` with k=60. The
**leg weights** (dense / BM25) are operator-tunable since the
`dense_weight` / `bm25_weight` config fields landed: defaults
0.7 / 0.3, validated to sum to 1.0 (±1e-3), extreme ratios (< 0.05)
log a startup warning. This document records the arithmetic, the
rationale for the choices, and the surface area, so the decisions stay
revisitable.

> **State & anchor note.** This document describes the post-migration
> state (relative_score stage-1 fusion, default leg weights dense 0.7 /
> BM25 0.3, locked rank_fusion slug-cut, `min_fusion_score` default 0.0
> operating on the blend scale [0, 2/60]). Authored in the same change
> set as the migration. Project-code anchors are symbol-level by design
> (durable); upstream code is cited by module path + function, pinned by
> `uv.lock`.

## The three upstream modes (for context)

Defined in `llama_index/core/retrievers/fusion_retriever.py` as
`FUSION_MODES`:

- **`reciprocal_rerank`** — Reciprocal Rank Fusion (Cormack et al.,
  SIGIR 2009), k=60. Per leg, rank every node (rank0 starts at 0) and
  score it `1 / (rank0 + 60)`; sum across legs. Output range with two
  legs: ~0.008–0.033. Purely rank-based — raw leg scores are discarded.
- **`relative_score`** — per leg, min-max normalize raw scores to [0, 1]
  (leg top → 1.0, worst → 0.0; equal scores → 1.0 if max > 0 else 0.0),
  multiply by the retriever weight, divide by `num_queries`, sum across
  legs for nodes retrieved by both. Output range: [0, 1] per query.
- **`dist_based_score`** — `relative_score` with the min/max anchors
  replaced by mean ± 3·std per leg; outlier-robust variant.

With the default leg weights `(dense=0.7, bm25=0.3)` (upstream normalizes
to sum 1, `num_queries=1`; any validated weight pair shifts these caps
proportionally):

- best possible consensus: 0.7 + 0.3 = **1.0**
- dense-only hit: **0.7** (the dense weight)
- BM25-only hit: **0.3** (the BM25 weight)

## Why relative_score wins for this system

1. **Fixed embedder** (TEI-sidecar Qwen3-embedding via LiteLLM). RRF's
   scale-free rank fusion removes a classic cross-provider concern that
   doesn't apply here.
2. **The slug-cut blend is rank-reciprocal** (`RR(fused) + RR(ce)` with
   k=60). Choosing score-based stage-1 lets the blend accumulate
   meaningful per-leg magnitudes (dense 0.7 vs BM25 0.3 with the default
   weights) before the rank transform. (Choosing RRF stage-1 would still
   combine cleanly; the choice here is driven by point 4.)
3. **Dense rank-1 confidence is preserved.** RRF's k=60 flattening
   treats rank 1 vs rank 5 as nearly identical (1/60 vs 1/64); on a
   ~213-slug corpus of one-line documents the cosine gap is real signal.
4. **Retriever weights are honored.** In the pinned llama-index-core
   0.14.x, `_reciprocal_rerank_fusion` iterates `results.values()` and
   silently ignores `retriever_weights` (upstream issue
   run-llama/llama_index#21444); `_relative_score_fusion` honors them.
   The dense-favoring weighting (0.7/0.3 with the defaults) is only
   meaningful in relative_score.

### What relative_score does NOT give you

Scores are **query-relative, not absolute**. The min-max 0-anchor is the
worst slug of that query's leg results — a 0.6 for "e-commerce" and a
0.6 for "TODO app" do not mean the same thing. Two corollaries:

- Because min-max sends each leg's top node to 1.0, **any non-empty
  recall scores ≥ max leg weight** (0.7 with dense hits; 0.3 for
  BM25-only, with the default weights — generally, the larger of the
  two configured weights). The `min_fusion_score` gate therefore fires
  only on degenerate (all-zero) recall.
- A single extreme outlier can pin one leg's max at 1.0 and compress
  the rest toward 0. If dashboards show that, switch candidates:
  `dist_based_score` is the drop-in variant.

## Why the slug-cut is locked to the reciprocal-rank blend

The CE reranker alone is the llama-index convention (`"rerank"`
selection: CE-only ordering, reported score = stage-1 relative_score).
The reciprocal-rank blend (`"rank_fusion"`: `RR(fused_rank) +
RR(ce_rank)` with k=60) is a Vespa-style consensus protector against
CE outliers on short inputs. We lock the blend because:

- The domain-slug corpus has very short documents (one slug per node) —
  exactly the regime where CE outliers are most likely to be wrong and
  consensus with stage-1 is most informative.
- Removing the `"rerank"` alternative eliminates the
  selection-mode × `min_fusion_score`-scale interaction that previously
  caused 100% fallback to layered-monolith on default values
  (deployment caught it: `min_fusion_score=0.25` with `rank_fusion`
  reports blend ≈0.029, gate rejects).

### What the blend reports

`reported_fusion_score = reciprocal_rank_score(fused_rank) +
reciprocal_rank_score(ce_rank)` where `reciprocal_rank_score(rank) =
1 / (rank + 60 - 1)` and rank starts at 1.

- Theoretical max: RR(1) + RR(1) = 2/60 ≈ **0.0333**.
- Pool under `rerank_top_n` makes the cut a no-op equivalent: all
  positions map to the same reciprocal value, so ordering is CE-only.
- The `min_fusion_score` gate operates on this scale and so the field
  is constrained to `[0, 2/60]`. A startup `ServerConfig` validator
  rejects any operator-set floor above the blend maximum.

## How much the mode matters

With the mandatory TEI cross-encoder rerank and `rerank_top_n=10`, the CE
still decides the survivor cut — stage-1 fusion affects *which*
candidates reach it plus the reported scores. The blend orders by
consensus strength but the CE logit is the actual cut. Don't attribute
retrieval-quality changes to the blend without checking the rerank stage.

## Pitfalls of operating QueryFusionRetriever here

- `llm=MockLLM()` is **required**: with a falsy `llm`, upstream `__init__`
  evaluates `Settings.llm` → `resolve_llm("default")` → tries to construct
  an OpenAI client → `ImportError` (no `llama-index-llms-openai`).
- `num_queries=1` disables LLM query generation (no extra LLM calls);
  `use_async=False` keeps the sync path used by `asyncio.to_thread`.
- `similarity_top_k` must be lossless (`dense_k + bm25_k` from warmup,
  fallback 2048) — upstream default 2 would silently truncate.

See `src/patterns/retriever.py :: _ensure_fusion_retriever`.

## Downstream consumers of fusion_score (shape unchanged by the swap)

- **Fused order → survivors.** Cut by the locked rank_fusion blend.
- **`rank_fusion` CE-blend** uses `reciprocal_rank_score` over list
  positions (independent of the stage-1 mode).
- **Pattern tuple score → `blended_score`.** `_score_patterns`
  re-normalizes fusion scores (min-max) within the recall set before
  blending (`0.7·analysis + 0.3·fusion`).
- **`min_fusion_score` gate** (default 0.0, range `[0, 2/60]`) →
  `layered-monolith` fallback tagged `is_fallback=True`. Guarded against
  impossible floors by `ServerConfig._check_fusion_floor_scale`.
- **`matched_domains` transparency** — values now reflect the blend
  scale ([0, 0.033]).

## What's locked vs what's tunable

| Knob | Value / constraint |
|---|---|
| `RETRIEVAL_FUSION_MODE` | `FUSION_MODES.RELATIVE_SCORE` (module constant, locked) |
| `RetrievalConfig.dense_weight` / `bm25_weight` | Stage-1 leg weights, defaults `(0.7, 0.3)`; each `> 0`, `≤ 1.0`, must sum to 1.0 (±1e-3, model validator); either `< 0.05` logs a startup WARNING; env `RETRIEVAL_DENSE_WEIGHT` / `RETRIEVAL_BM25_WEIGHT` |
| `RETRIEVAL_RETRIEVER_WEIGHTS` | module constant holding the DEFAULTS `(0.7, 0.3)` — (dense, BM25); config values take precedence via the pipeline wiring |
| `HybridPatternRetriever(..., retriever_weights=...)` | ctor override; two positive numbers, upstream-normalized |
| Slug-cut strategy | locked to `RR(fused) + RR(ce)` (k=60) |
| `RetrievalConfig.min_fusion_score` | default 0.0, validated `[0, 2/60]` (`le=RANK_FUSION_BLEND_MAX`) |
| Stage-1 mode via config.json / env | **removed** — legacy `retrieval.mode` keys fail startup (`extra="forbid"`), intentional |

The earlier `"simple"` rank-union mode was removed in a prior revision;
see git history for its retirement notes.

## Files and symbols (quick navigation)

| Concern | Location |
|---|---|
| Fusion orchestration + mode/weights constants | `src/patterns/retriever.py :: _ensure_fusion_retriever`, `RETRIEVAL_FUSION_MODE`, `RETRIEVAL_RETRIEVER_WEIGHTS` |
| Retriever entry point (QueryBundle split) | `src/patterns/retriever.py :: HybridPatternRetriever.retrieve` |
| Relevance-floor fallback + WARNING | `src/patterns/retriever.py :: retrieve`, `_fallback` |
| Adapter-layer fallback WARNING | `src/tools/_adapters.py :: analysis_to_pydantic` |
| Pipeline wiring | `src/pipeline.py :: analyze` |
| Stage-1 fusion shape + weight norm | `src/config.py :: RetrievalConfig` |
| Blend-max constant + floor validator | `src/config.py :: RANK_FUSION_BLEND_MAX`, `ServerConfig._check_fusion_floor_scale` |
| Regression tests | `tests/unit/test_fusion_rrf.py` (`TestQueryFusionRRF`, `TestRelativeScoreWeightedFusion`, `TestRetrievalFusionModeConstant`) |

## Operator notes

- `fusion_score` / `matched_domains` log spans are in the blend scale
  ([0, 0.033]); update any dashboards or monitors that previously keyed
  on RRF-band or relative_score values.
- `min_fusion_score` defaults to 0.0 (gate disabled). Setting a positive
  value within `[0, 0.033]` enforces a relevance trim; anything above
  0.033 fails the `ServerConfig` validator at startup.
- Embedder swap: re-check the score distribution shape. If outliers
  compress the normalized range, `dist_based_score` is the drop-in
  variant (single-constant change in `RETRIEVAL_FUSION_MODE`).
- Re-tune leg weighting via `RETRIEVAL_DENSE_WEIGHT` /
  `RETRIEVAL_BM25_WEIGHT` (sum to 1.0, ±1e-3) or
  `retriever_weights=(dense, bm25)` on `HybridPatternRetriever` —
  honored in score-based modes only under the pinned core.
- Changing the leg weights shifts the relative_score scale: the
  dense-only cap becomes the dense weight and the BM25-only floor the
  BM25 weight. The rank-based slug-cut blend and the `min_fusion_score`
  gate ([0, 2/60]) are unaffected — both operate on ranks, not scores.

## References

- `llama-index-core` (pinned by `uv.lock`):
  `llama_index/core/retrievers/fusion_retriever.py` — `QueryFusionRetriever`,
  `FUSION_MODES`, `_relative_score_fusion`, `_reciprocal_rerank_fusion`.
- Cormack, Clarke, Buettcher — "Reciprocal Rank Fusion outperforms Condorcet
  and individual Rank Learning Methods", SIGIR 2009.
- "An Analysis of Fusion Functions for Hybrid Retrieval", ACM TOIS 2023
  (Bruch et al.) — RRF vs score-based fusion under different score
  distributions.
- Upstream issue run-llama/llama_index#21444 — RRF ignores
  `retriever_weights` in the pinned core version.
- Internal issue #3 — `min_fusion_score` fragility under RRF (see
  `tests/unit/test_two_stage_fixes.py :: TestT7MinFusionScoreGateDisabled`).
