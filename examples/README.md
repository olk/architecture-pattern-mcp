# Architecture Pattern MCP — Client Demo

A standalone Python script that connects to a running MCP server over HTTP,
calls `design_architecture` with a pipes-and-filter requirements string,
and pretty-prints the full JSON result to stdout.

## Quick Start

**Terminal 1 — start the server:**

```bash
python -m src.main
# Server listens on http://0.0.0.0:8050/mcp
```

**Terminal 2 — run the client:**

```bash
uv run python examples/architecture_client.py
```

## Output

The script prints a single JSON object to stdout containing:

| Key | Description |
|---|---|
| `design` | Full `ArchitectureDesign` (overview, components, relationships, patterns, api_contracts, shared_data_models, event_contracts, quality_attributes) |
| `evaluation` | `ArchitectureEvaluation` (summary, metrics, recommendations) |
| `iterations` | Number of refine cycles performed |
| `final_style` | Resolved architecture style |
| `final_quality_score` | Quality score after refinement |
| `quality_metrics` | Aggregated quality metrics from analysis |
| `applied_best_practices` | Best practices applied during refinement |

The `design.overview.style` will be `"pipe-and-filter"` and the components will
decompose into source → filter → filter → … → sink stages.

## Customising

Edit these constants at the top of `examples/architecture_client.py`:

```python
SERVER_URL = "http://localhost:8050/mcp"
PIPES_AND_FILTERS_REQUIREMENTS = "..."     # your own requirements text
DOMAIN = "data-processing"                # e.g. "etl", "log-analysis"
```

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
uv run python examples/architecture_client.py 2>/dev/null | jq '.design.overview'
uv run python examples/architecture_client.py 2>/dev/null | jq '.design.components[].id'
uv run python examples/architecture_client.py 2>/dev/null | jq '.evaluation.summary'
```
