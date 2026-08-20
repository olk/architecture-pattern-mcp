# architecture-pattern-mcp

MCP server that gives any AI coding agent architecture-design expertise — 36 built-in patterns, 6 tools, 4 workflow prompts.

```
┌──────────────────────────────────────────────────────────────┐
│  OpenCode / Claude Code / VS Code / any MCP client           │
│        ────────── HTTP ──────────► :8050/mcp                 │
│                                                              │
│      ┌──────────────────────────────┐                        │
│      │   architecture-pattern-mcp   │                        │
│      └───────────────┬──────────────┘                        │
│                      │                                       │
│    ┌─────────────────┼─────────────────┐                     │
│    │   tei-embedder  │   tei-rerank    │ ← pattern-tei-infra │
│    │   :8080 (TEI)   │   :8080 (TEI)   │                     │
│    └─────────────────┴─────────────────┘                     │
└──────────────────────────────────────────────────────────────┘
```

## Architecture

This image is the **MCP server only**. The TEI embedder and TEI reranker are
separate infrastructure (see [pattern-tei-infra project](https://github.com/olk/pattern-tei-infra))
published as
[olkowa/pattern-tei](https://hub.docker.com/r/olkowa/pattern-tei) and
[olkowa/pattern-tei-rerank](https://hub.docker.com/r/olkowa/pattern-tei-rerank).

Start the pattern-tei-infra stack first, then this MCP server — they connect via Docker DNS
using the hostnames `tei-embedder` and `tei-rerank` on a shared Docker network.

## What you get

| Tool / Prompt | Description |
|---|---|
| `analyze_architecture` | Analyse requirements → recommended style, patterns, quality metrics |
| `generate_architecture` | Generate an architecture design from requirements + selected patterns |
| `evaluate_architecture` | Score an existing design against quality attributes |
| `design_architecture` | Full pipeline: analyse → generate → evaluate → refine (up to 3 attempts) |
| `list_architecture_patterns` | List all 36 patterns; filter by `category` and/or `domain` |
| `get_architecture_pattern` | Get full JSON for a specific pattern by name |
| `/design_architecture_workflow` | Guided analyse → generate → evaluate cycle |
| `/explore_pattern_catalog` | Interactive pattern discovery with live embedding search |
| `/evaluate_my_architecture` | Structured design evaluation with criteria guidance |
| `/compare_architecture_styles` | Side-by-side comparison of two architecture styles |

## Prerequisites

- **Docker** 24+ with compose plugin (`docker compose version`)
- **TEI sidecars running** — [pattern-tei-infra stack](https://github.com/olk/pattern-tei-infra) on a shared Docker network with hostnames `tei-embedder` and `tei-rerank`
- **An LLM API key** for any LiteLLM-compatible provider (OpenAI, Anthropic, MiniMax, DeepSeek, Ollama, vLLM, OpenRouter, or any OpenAI-compatible endpoint)

## Quick start

```bash
# 1. Start the TEI sidecars (separate pattern-tei-infra project)
git clone https://github.com/olk/pattern-tei-infra.git && cd pattern-tei-infra
docker compose up -d

# 2. Start the MCP server
cd ..
mkdir architecture-pattern-mcp && cd architecture-pattern-mcp
curl -fsSLo docker-compose.yml \
  https://raw.githubusercontent.com/olk/architecture-pattern-mcp/main/docker/docker-compose.hub.yml
curl -fsSLo config.json \
  https://raw.githubusercontent.com/olk/architecture-pattern-mcp/main/config/config.json
printf 'GENERATOR_API_KEY=sk-...\n' > .env
docker compose up -d
curl -fsS http://localhost:8050/health
```

The server starts on **streamable-http** at `http://localhost:8050/mcp`.

> **Reproducibility tip:** replace `main` in the curl URLs with a version tag
> (e.g. `refs/tags/v0.1.0`) to pin to a specific release.

## Bringing your own LLM

The compose defaults to **OpenAI** (`gpt-4o-mini`, `api.openai.com/v1`).
Override with any `.env` combination:

| Provider | `.env` additions |
|---|---|
| **OpenAI** *(default)* | `GENERATOR_API_KEY=sk-...` |
| **Anthropic** | `GENERATOR_PROVIDER=anthropic` · `GENERATOR_MODEL=claude-sonnet-4-5` · `GENERATOR_API_KEY=sk-ant-...` |
| **MiniMax** | `GENERATOR_PROVIDER=minimax` · `GENERATOR_MODEL=minimax/MiniMax-M2.7` · `GENERATOR_BASE_URL=https://api.minimax.io/v1` · `GENERATOR_API_KEY=...` |
| **DeepSeek** | `GENERATOR_PROVIDER=deepseek` · `GENERATOR_MODEL=deepseek-chat` · `GENERATOR_BASE_URL=https://api.deepseek.com/v1` · `GENERATOR_API_KEY=sk-...` |
| **Ollama / vLLM / OpenRouter / any OpenAI-compatible** | `GENERATOR_BASE_URL=http://host:11434/v1` · `GENERATOR_MODEL=...` · `GENERATOR_API_KEY=...` |

## TEI sidecar configuration

The MCP server connects to the TEI embedder at `http://tei-embedder:8080`
and the TEI reranker at `http://tei-rerank:8080` by default (Docker DNS names
from the pattern-tei-infra stack).  Override if your setup differs:

| Variable | Default | Description |
|---|---|---|
| `EMBEDDER_BASE_URL` | `http://tei-embedder:8080` | TEI embedder URL |
| `RERANKER_ENABLED` | `false` | Enable the reranker |
| `RERANKER_BASE_URL` | `http://tei-rerank:8080` | TEI reranker URL |

Full env var reference: [GitHub README → Configuration](https://github.com/olk/architecture-pattern-mcp#configuration)

## Verify in 30 seconds (no IDE needed)

```bash
npx -y @modelcontextprotocol/inspector \
  --server-url http://localhost:8050/mcp \
  --transport http
```

## Connect your agent

### OpenCode

Add to `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "architecture-pattern": {
      "type": "remote",
      "url": "http://localhost:8050/mcp"
    }
  }
}
```

### VS Code (MCP extension)

Add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "architecture-pattern": {
      "url": "http://localhost:8050/mcp",
      "type": "http"
    }
  }
}
```

### Claude Code / Codex CLI

```bash
# Install (one-time)
uv pip install -e .

# Add to your agent
claude mcp add architecture-pattern \
  -e GENERATOR_API_KEY=sk-... \
  -- architecture-pattern-mcp --transport stdio
```

Full client docs: [GitHub README → Connect Your Agent](https://github.com/olk/architecture-pattern-mcp#-connect-your-agent)

## Try it

Ask your agent (or use the Inspector):

> Build a scalable ETL pipeline for IoT sensor data: ingest 10k events/sec from Kafka, parse JSON, enrich with geolocation from Redis, write to InfluxDB and S3.

Then call `design_architecture` with:
- `requirements`: "ETL pipeline for IoT sensor data: ingest 10k events/sec from Kafka, parse JSON, enrich with geolocation from Redis, write to InfluxDB and S3"
- `domain`: "data-processing"
- `style`: "pipe-and-filter"

## Operations

```bash
# Upgrade to latest images
docker compose pull && docker compose up -d

# View logs
docker compose logs -f architecture-pattern-mcp

# Stop
docker compose down

# Pin a specific version
TAG=0.1.0 docker compose up -d
```

On Linux with a shared host, restrict your `.env` file:
```bash
chmod 600 .env
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `401 Unauthorized` from LLM | Check `GENERATOR_API_KEY` in `.env`; verify the key is active |
| `curl localhost:8050/health` returns non-200 | Wait ~40 s for MCP server startup; check `docker compose logs` |
| TEI connection errors | Ensure pattern-tei-infra stack is running; verify `tei-embedder` hostname resolves (`docker network inspect`); override `EMBEDDER_BASE_URL` if your network differs |
| Port 8050 already in use | `MCP_HOST_PORT=8051 docker compose up -d`, then update your client URL |

## Links

- **GitHub** (source, docs, issue tracker): [olk/architecture-pattern-mcp](https://github.com/olk/architecture-pattern-mcp)
- **TEI infrastructure** (embedder + reranker): [olk/pattern-tei-infra](https://github.com/olk/pattern-tei-infra) · [olkowa/pattern-tei](https://hub.docker.com/r/olkowa/pattern-tei) · [olkowa/pattern-tei-rerank](https://hub.docker.com/r/olkowa/pattern-tei-rerank)
- **License**: [MIT](https://github.com/olk/architecture-pattern-mcp/blob/main/LICENSE)
