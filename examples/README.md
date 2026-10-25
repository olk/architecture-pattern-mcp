# Architecture Pattern MCP — Client Demo

A standalone Python script that connects to a running MCP server over HTTP and
calls one tool with a pipes-and-filter requirements string, then pretty-prints
the JSON result:

- `analyze_architecture` (default) — ANALYZE phase only: recommended style,
  selected patterns with scores, matched domains. Fast; no design generated.
- `design_architecture` (`--tool design`) — full design artifact: analyze →
  generate → evaluate → refine. Long-running (5–10 minutes).

## Quick Start

**Terminal 1 — start the server:**

```bash
python -m src.main
# Server listens on http://0.0.0.0:8050/mcp
```

**Terminal 2 — run the client:**

```bash
uv run python examples/architecture_client.py                  # analyze (fast)
uv run python examples/architecture_client.py --tool design    # full design

# or via make (server on http://localhost:8820/mcp):
make client-analyze
make client-design
```

## Output

### analyze (default)

The script prints a single JSON object to stdout containing:

| Key | Description |
|---|---|
| `recommended_style` | Style derived from the top-scoring pattern (or `layered-monolith` below the style threshold) |
| `selected_patterns` | Ranked catalogue patterns with `analysis_score`, `fusion_score`, `fusion_score_normalized` and `blended_score` |
| `quality_metrics` | Aggregated quality metrics from the analysis |
| `strengths` / `weaknesses` / `recommendations` | Deterministic narrative for this selection |
| `matched_domains` | Top retrieved domain slugs with fusion/rerank scores |
| `is_fallback` | `true` when no real domain match was found |

The exact ranking depends on the requirement weights the server extracts, but
the ETL text above targets the data-pipeline family (e.g. `pipe-and-filter`,
`batch-processing`); no components, relationships or API contracts are
generated.

### design (`--tool design`)

The full `PipelineResult`:

| Key | Description |
|---|---|
| `design` | `ArchitectureDesign`: overview, components, relationships, API/data/event contracts, quality attributes |
| `evaluation` | `ArchitectureEvaluation`: summary, metrics, recommendations |
| `attempts` | Generate attempts performed (initial + retries) |
| `final_style` | Delivered architecture style |
| `final_quality_score` | Best-attempt quality score |
| `quality_metrics` | Aggregated analysis metrics |
| `alternative_styles` | Runner-up patterns from the analyze phase |
| `matched_domains` / `is_fallback` | Retrieval provenance and fallback flag |

## Customising

Edit these constants at the top of `examples/architecture_client.py`:

```python
SERVER_URL = "http://localhost:8050/mcp"
PIPES_AND_FILTERS_REQUIREMENTS = "..."     # your own requirements text
DOMAIN = "data-processing"                 # a catalogue suitable_domains slug
```

`domain` must be a slug the catalogue indexes (e.g. `data-processing`,
`data-pipelines`, `stream-processing`); an unknown slug yields weak matches.

## Server LLM configuration

The demo requires a running server whose generator LLM is configured in the
**LlamaIndex LiteLLM** format — a LiteLLM model string of the form
`<provider>/<model>` (e.g. `openai/gpt-4o-mini`), set via `GENERATOR_PROVIDER`
and `GENERATOR_MODEL`. For the provider/model syntax reference see the
[LiteLLM Providers documentation](https://docs.litellm.ai/docs/providers);
for full configuration options see the main README's
[Generator LLM section](../README.md#generator-llm-llamaindex-litellm).

## Tips

Pipe the output to `jq` to inspect parts of the result:

```bash
# analyze (default)
uv run python examples/architecture_client.py 2>/dev/null | jq '.recommended_style'
uv run python examples/architecture_client.py 2>/dev/null | jq '.selected_patterns[].name'
uv run python examples/architecture_client.py 2>/dev/null | jq '.matched_domains'

# design
uv run python examples/architecture_client.py --tool design 2>/dev/null | jq '.design.overview'
uv run python examples/architecture_client.py --tool design 2>/dev/null | jq '.design.components[].id'
uv run python examples/architecture_client.py --tool design 2>/dev/null | jq '.evaluation.summary'
```
