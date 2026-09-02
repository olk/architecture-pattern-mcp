# Vespa-Style Blend Score

The system uses two distinct blend stages, both named for Vespa's [open-source search engine](https://github.com/vespa-engine/vespa) which popularized the reciprocal-rank approach to combining retrieval signals.

## Stage 1: Slug-Cut Blend (RR(fused) + RR(ce))

**Location:** `src/patterns/retriever.py` (locked, not operator-tunable)

After stage-1 hybrid fusion (dense + BM25 via `QueryFusionRetriever`) and cross-encoder reranking, the slug-cut stage selects the top-N candidates using a Vespa-style reciprocal-rank blend of two rank signals:

```
selection_score = RR(fused_rank) + RR(ce_rank)

RR(rank) = 1 / (rank + k - 1)
k        = 60  (RRF_K constant)
rank     = 1-based position in the respective list
```

**Example values:**

| fused_rank | ce_rank | RR(fused)      | RR(ce)        | blend        |
|------------|---------|----------------|---------------|--------------|
| 1          | 1       | 1/60 ≈ 0.0167  | 1/60 ≈ 0.0167| 0.0333 (max) |
| 1          | 3       | 1/60 ≈ 0.0167  | 1/62 ≈ 0.0161| 0.0328       |
| 3          | 1       | 1/62 ≈ 0.0161  | 1/60 ≈ 0.0167| 0.0328       |
| 5          | 5       | 1/64 ≈ 0.0156  | 1/64 ≈ 0.0156| 0.0312       |

**Scale:** `[0, 2/60] ≈ [0, 0.0333]`

**Properties:**
- Purely rank-based — raw scores from both stages are discarded
- k=60 is the same k used in Reciprocal Rank Fusion (Cormack et al., SIGIR 2009)
- When the candidate pool is ≤ `rerank_top_n`, all positions receive the same reciprocal, making the cut CE-only (no-op equivalent, logged at debug)
- Acts as a **consensus protector**: a slug must agree with both the retrieval fusion AND the reranker to survive

**Why it's locked:**
- The domain-slug corpus has very short documents (one slug per node) — exactly the regime where CE outliers are most likely to be wrong
- Removes the interaction between selection-mode × `min_fusion_score`-scale that previously caused 100% fallback to layered-monolith on defaults

**Config constraint:** `min_fusion_score` is validated to `[0, 2/60]` (`RANK_FUSION_BLEND_MAX = 2/60`). Any operator-set floor above the blend maximum fails `ServerConfig` validation at startup.

---

## Stage 2: Selection Blend (analysis_score + fusion_normalized)

**Location:** `src/pipeline.py :: _score_patterns`

After slug-cut survivors are resolved to full patterns, a second blend combines the **requirements-weighted analysis score** with a **min-max-normalized fusion score** to produce the final `blended_score` used for pattern ranking and `recommended_style` selection:

```
fusion_normalized = (fusion_score - f_min) / (f_max - f_min) * 100

blended_score = analysis_blend_weight * analysis_score
              + fusion_blend_weight * fusion_normalized
```

**Defaults (`RetrievalConfig`):**

| Parameter               | Default | Description                                           |
|-------------------------|---------|-------------------------------------------------------|
| `analysis_blend_weight` | 0.7     | Weight on requirements-weighted analysis_score         |
| `fusion_blend_weight`   | 0.3     | Weight on min-max-normalized fusion_score              |
| `weight_smoothing_alpha`| 0.7     | Smoothing on raw LLM requirement weights              |

**Constraint:** `analysis_blend_weight + fusion_blend_weight == 1.0` (validated)

**`analysis_score` computation:**
```
weighted_avg = sum(w[attr] * qa[attr]) / sum(w)  for attr in QUALITY_ATTRIBUTE_KEYS
analysis_score = weighted_avg * 10.0             → [0, 100]
```

Where `w` is the `RequirementWeights.as_dict()` per requirement (smoothed LLM-assigned weights summing to ~1.0), and `qa[attr]` is the per-pattern quality-attribute score (0–10).

**`fusion_normalized` computation:**
- Min-max normalized within the current recall set (not across queries)
- Scale: `[0, 100]` (multiplied by 100)
- When `fusion_score` is constant across the set, `fusion_normalized = 0`

**Example:**

| pattern           | analysis_score | fusion_score | fusion_normalized | blended_score (0.7/0.3) |
|-------------------|----------------|-------------|-------------------|--------------------------|
| microservices     | 90.0           | 0.0250      | 75.0              | 0.7×90 + 0.3×75 = 85.5  |
| pipe-and-filter   | 65.0           | 0.0300      | 100.0             | 0.7×65 + 0.3×100 = 75.5 |
| layered-monolith  | 50.0           | 0.0100      | 0.0               | 0.7×50 + 0.3×0 = 35.0   |

**Sort key:** `blended_score` when `fusion_blend_weight > 0`, else `analysis_score`

**Restore pre-change behavior:** Set `analysis_blend_weight=1.0, fusion_blend_weight=0.0`

---

## Relationship Between the Two Stages

```
[Query]
    │
    ▼
Stage-1: QueryFusionRetriever (relative_score, dense 0.7 / BM25 0.3)
    │
    ▼  fused_score ∈ [0, 1]  (per-query, per-leg min-max normalized)
    │
Cross-encoder rerank
    │
    ▼  ce_rank (1-based)
Slug-cut: RR(fused_rank) + RR(ce_rank) ∈ [0, 2/60]
    │
    ▼  fusion_score (blend value stored in DomainMatch.fusion_score)
Select top-N survivors → resolve to full patterns
    │
    ▼
Stage-2: analysis_score (requirements-weighted, [0, 100])
    │
Blend: 0.7·analysis_score + 0.3·fusion_normalized
    │
    ▼
blended_score ∈ [0, 100]
recommended_style = top-scoring pattern name (gated by style_score_threshold)
```

**Note on naming:** `DomainMatch.fusion_score` carries the **stage-1 slug-cut blend value** (`RR(fused) + RR(ce)`, scale `[0, 0.033]`), while `PatternTuple.blended_score` carries the **stage-2 selection blend value** (`0.7·analysis + 0.3·fusion_normalized`, scale `[0, 100]`). They are different metrics at different pipeline stages.

---

## Files

| Concern | Location |
|---------|----------|
| Stage-1 blend formula + `RRF_K` | `src/patterns/retriever.py:110–118` |
| Stage-1 blend application (slug-cut) | `src/patterns/retriever.py:449–477` |
| Stage-2 blend formula + weights | `src/pipeline.py:1655–1695` |
| Blend weight config fields | `src/config.py:223–238` |
| `RANK_FUSION_BLEND_MAX = 2/60` | `src/config.py:156` |
| Tests | `tests/unit/test_two_stage_fixes.py`, `tests/unit/test_blended_scoring.py` |
| Rationale doc | `docs/retrieval-fusion-modes.md` |
