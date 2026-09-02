# How Domain & Style Are Selected

Analysis of how the architecture-pattern-mcp server derives the target **domain** and the architectural **style** from a user's description (requirements + domain inputs).

## Two Different Vocabularies (`src/schemas/enums.py`)

- **`ArchitectureDomain`** (`src/schemas/enums.py:72`) — ~376 problem-space slugs (`e-commerce`, `high-frequency-trading`, ...) used only for pattern suitability filtering.
- **`ArchitectureStyle`** (`src/schemas/enums.py:469`) — ~40 canonical approach names (`microservices`, `hexagonal`, `event-driven`, ...) = the pattern names in `pattern/*.json`.

Domain answers *"which patterns apply?"*; style names *"which architecture was chosen?"*.

## Entry Point

User calls `design_architecture(requirements, domain, override_style=None)` — `src/tools/design.py:211-218`.

Domain is a **user-supplied parameter**, not LLM-classified. It flows into `run_design()` → Workflow `_orchestrate` step (`src/pipeline.py:809-849`), which runs ANALYZE then:

```python
design_loop(style=style or analysis_result.recommended_style)  # src/pipeline.py:841
```

So the style is either user-overridden or derived in ANALYZE.

## DOMAIN Selection = Hybrid Retrieval, Not Classification

In `analyze()` (`src/pipeline.py:377-507`):

1. **Normalize**: `domain.lower().replace(" ", "-")` — `src/pipeline.py:403` (IC-31)
2. **Index corpus**: all slugs from every pattern's `suitable_domains` build FAISS + BM25 indexes — `_build_vector_index` `src/pipeline.py:885-899`
3. **Two-leg retrieval** (`HybridPatternRetriever.retrieve`, `src/patterns/retriever.py:254-305`):
   - Dense leg embeds the *raw* domain string → FAISS (`src/patterns/retriever.py:304`)
   - BM25 leg matches the *normalized* slug tokens (`src/patterns/retriever.py:305`)
   - Different queries per leg is intentional (`src/patterns/retriever.py:141-147`)
4. **Fusion + rerank**: relative_score fusion (per-leg min-max normalization, dense 0.7 / BM25 0.3 weights — locked constant, see `docs/retrieval-fusion-modes.md`), then mandatory TEI cross-encoder rerank capped at `rerank_top_n=10` — `src/patterns/retriever.py` (`_ensure_fusion_retriever`, rerank block)
5. **Slug → patterns**: `filter_by_domain(slug)`, pattern score = max fusion score over matching slugs — `src/patterns/retriever.py:444-451`
6. **Fallback**: empty result or best score < `min_fusion_score` → `layered-monolith` tagged `is_fallback=True` — `src/patterns/retriever.py:456-469`, `495-516` (`DEFAULT_FALLBACK_PATTERN_NAME` at `src/patterns/retriever.py:78`)

The retrieval runs off the event loop via `asyncio.to_thread` — `src/pipeline.py:427-431`.

## STYLE Selection = Requirements-Weighted Scoring

Also in ANALYZE:

1. **LLM weight extraction** (`_extract_requirement_weights`, `src/pipeline.py:1193-1231`):
   - One small LLM call maps requirements → 6 quality-attribute weights 0–1 (prompt at `src/pipeline.py:1395-1442`)
   - All-zero result retries once, then unweighted mean (`src/pipeline.py:1207-1217`)
   - Convex smoothing `w' = α·w + (1−α)/n`, α=0.7 (`src/pipeline.py:1233-1248`)
2. **Deterministic scoring** (`_score_patterns`, `src/pipeline.py:1250-1301`):
   - `analysis_score = Σ(w·quality_attributes)/Σw × 10` (0–100 scale)
   - Fusion score min-max normalized to 0–100
   - `blended = 0.7·analysis + 0.3·fusion` (weights: `src/config.py:214-229`; validator `src/config.py:248-255`)
   - Top `top_k_patterns=5` kept **after** scoring — `src/pipeline.py:464-466`
3. **Style decision** (`_select_recommended_style`, `src/pipeline.py:1303-1331`):
   - Explicit `override_style` always wins (`src/pipeline.py:1315-1316`)
   - Else top pattern's **name** becomes `recommended_style` if its `analysis_score >= style_score_threshold=50` (`src/config.py:207-213`)
   - Else fallback to `layered-monolith`

## Style Drives Generation & Final Validation

- Cached system prompt: *"You are an expert software architect specializing in {style}"* plus hard enum constraints listing valid styles — `_generate_system_prompt_cached` `src/pipeline.py:204-271`
- User prompt embeds requirements/domain/style/pattern context — `src/pipeline.py:1080-1111`
- Output must parse into `ArchitectureDesign` whose `overview.style` is an `ArchitectureStyle` member
- `design_loop` retries up to `max_tries=2`, keeping the best `overall_quality` (`src/pipeline.py:660-803`)
- `final_style = best_design.overview.style.value` (`src/pipeline.py:795`)
- Runner-ups exposed as `alternative_styles` (`_style_candidates` `src/pipeline.py:1333-1370`)

## Summary

| Aspect | Mechanism | Where decided |
|---|---|---|
| Domain | Hybrid retrieval (BM25 + dense + cross-encoder rerank) over curated `ArchitectureDomain` slugs | `HybridPatternRetriever.retrieve` |
| Style | Requirements-weighted pattern ranking, threshold-gated, override-precedent | `_score_patterns` + `_select_recommended_style` in ANALYZE |

**Domain = retrieval problem; style = scored decision.**
