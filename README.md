# architecture-pattern-mcp

[![CI](https://img.shields.io/github/actions/workflow/status/olk/architecture-pattern-mcp/ci.yml?branch=main)](https://github.com/olk/architecture-pattern-mcp/actions)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![M8ven Score](https://m8ven.ai/badge/mcp/olk-architecture-pattern-mcp-1x6yt9)](https://m8ven.ai/mcp/olk-architecture-pattern-mcp-1x6yt9)

An MCP (Model Context Protocol) server that provides architecture design expertise to AI coding agents. Given a requirements string and a domain, it analyses the problem, selects matching architecture patterns (from 40 built-in patterns), generates a concrete architecture design with components, relationships, API contracts, data models, and event contracts, and evaluates it against quality attributes (maintainability, scalability, reliability, security, performance).

---

## Table of Contents

- [⚡ Quickstart](#-quickstart)
- [🔌 Connect Your Agent](#-connect-your-agent)
  - [Claude Code](#claude-code)
  - [OpenCode](#opencode)
  - [Codex CLI](#codex-cli)
- [🧑‍🏫 SKILL for AI Agents](#-skill-for-ai-agents)
- [🧪 Use the Tools](#-use-the-tools)
  - [Design your first architecture](#design-your-first-architecture)
  - [Explore the pattern catalog](#explore-the-pattern-catalog)
- [🛠️ Tools at a Glance](#️-tools-at-a-glance)
- [📖 Pattern Catalog](#-pattern-catalog)
- [Install Alternatives](#install-alternatives)
  - [Docker (manual)](#docker-manual)
  - [Local Development (uv)](#local-development-uv)
- [Configuration](#configuration)
- [Structured Reasoning (shannonthinking / code-reasoning)](#structured-reasoning-shannonthinking--code-reasoning)
- [Extending with Custom Patterns](#extending-with-custom-patterns)
- [Long-running tools & timeouts](#long-running-tools--timeouts)
- [Troubleshooting](#troubleshooting)
- [Building & Development](#building--development)
- [Publishing](#publishing)
- [systemd Service (Linux)](#systemd-service-linux)
- [License](#license)

---

## ⚡ Quickstart

```bash
# 1. Clone
git clone https://github.com/architecture-pattern/architecture-pattern-mcp.git
cd architecture-pattern-mcp

# 2. Add your API key
export GENERATOR_API_KEY=your_key_here

# 3. Start (Docker builds + starts everything)
docker compose -f docker/docker-compose.yml up --build

# 4. Demo
make client
```

Server starts on **streamable-http** at `http://localhost:8060/mcp` (dev compose host port; systemd uses 8050). Then connect your agent below.

---

## 🔌 Connect Your Agent

### Claude Code

```bash
# Install (one-time)
uv pip install -e .

# Run as stdio subprocess — pass API key via env
claude mcp add architecture-pattern \
  -e GENERATOR_API_KEY=your_key \
  -e GENERATOR_PROVIDER=openai \
  -- architecture-pattern-mcp --transport stdio
```

Or add to your project for the whole team:

```bash
claude mcp add --scope project architecture-pattern \
  -e GENERATOR_API_KEY=your_key \
  -- architecture-pattern-mcp --transport stdio
```

### OpenCode

OpenCode uses HTTP transport. Start the server first, then configure opencode:

```bash
# Terminal 1: start the server
docker compose -f docker/docker-compose.yml up --build
# or locally:
uv run python -m src.main --port 8050

# Terminal 2: add to ~/.config/opencode/opencode.json
```

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "architecture-pattern": {
      "type": "remote",
      "url": "http://localhost:8060/mcp"
    }
  }
}
```

> **Note:** `GENERATOR_API_KEY` is read from the server's config file (`~/.config/architecture-pattern-mcp/config.json`), not from opencode's environment.

### Codex CLI

```bash
# Install (one-time)
uv pip install -e .
```

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.architecture-pattern]
command = "architecture-pattern-mcp"
args = ["--transport", "stdio"]

[mcp_servers.architecture-pattern.env]
GENERATOR_API_KEY = "your_key"
GENERATOR_PROVIDER = "openai"
```

Or via CLI:

```bash
codex mcp add architecture-pattern \
  -e GENERATOR_API_KEY=your_key \
  -- architecture-pattern-mcp --transport stdio
```

---

## 🧑‍🏫 SKILL for AI Agents

AI coding agents (Claude Code, OpenCode, Codex CLI) can load a SKILL that teaches them how and when to use this server's tools — including timeout-aware entry-point selection, output interpretation, and the full workflow recipe.

The SKILL lives in `skills/architecture-pattern-mcp/`:

```
skills/architecture-pattern-mcp/
├── SKILL.md                 # Discovery, critical rules, decision guide
└── references/
    ├── tools.md             # All 9 tool signatures and output schemas
    └── workflows.md         # 4 worked examples, 4 prompts, best practices
```

**For agents that support file-based skills** (OpenCode, Claude Code): point the agent's skill loader at `skills/architecture-pattern-mcp/SKILL.md`. The skill tells the agent:

- Which tool to use based on client type and timeout budget
- How to phrase `requirements`, `domain`, and `style` as separate structured arguments
- How to interpret `final_quality_score`, `attempts > 1`, and `evaluation.recommendations`
- When to use the async job trio vs `design_architecture` directly

---

## Use the Tools

All tools accept `requirements` (free text) and `domain` (e.g. `data-processing`, `microservices`, `e-commerce`) as arguments. The examples below show the exact tool call shape so you can use them in any MCP client or API consumer.

### Try each tool

In Claude Code (or any MCP client), paste the natural-language instruction:

```
Build a scalable ETL pipeline for IoT sensor data: ingest 10k events/sec
from Kafka, parse JSON, enrich with geolocation from Redis, write to InfluxDB
and S3.
```

Your agent calls `design_architecture` internally. The server returns a full architecture design: components (Kafka source, JSON parser filter, geolocation enricher, InfluxDB sink, S3 sink), quality attribute scores (scalability: 9.1, maintainability: 8.2, …), and specific recommendations.

**Or call tools directly** from your agent:

```
Call analyze_architecture with:
  requirements: "Real-time data processing pipeline for 10k events/sec IoT sensor data"
  domain: "data-processing"

Call generate_architecture with:
  requirements: "ETL pipeline: Kafka → JSON parse → Redis geo-enrich → InfluxDB + S3"
  domain: "data-processing"
  selected_patterns: ["pipe-and-filter"]

Call evaluate_architecture with:
  architecture: { ... paste a design dict here ... }
  criteria: "scalability, reliability"

Call list_architecture_patterns()  # all 40 patterns
Call list_architecture_patterns(category="messaging")  # filter by category
Call get_architecture_pattern(name="event-driven")   # full pattern JSON
```

### Async job pattern: `submit_architecture_design_job` + `get_architecture_design_status`

ONLY for clients with short request timeouts (Cursor, Claude Desktop, TS-SDK). The default is `design_architecture` with heartbeat defence. `submit_architecture_design_job` returns a `job_id` immediately; poll `get_architecture_design_status` until done:

```
# Step 1: start the job
Call submit_architecture_design_job with:
  requirements: "ETL pipeline for IoT: Kafka → JSON → Redis geo-enrich → InfluxDB + S3"
  domain: "data-processing"

# Step 2: poll every 10-30 seconds
Call get_architecture_design_status with:
  job_id: "<job_id from step 1>"

# → status is "pending" | "running" | "completed" | "failed" | "cancelled"
# When status is "completed", the full design is in result.design
# When status is "failed", the error is in result.error
```

In Python (via the MCP HTTP API directly — see `examples/architecture_client_async.py`):

```python
import asyncio, aiohttp

SERVER = "http://localhost:8060/mcp"
POLL_EVERY = 15  # seconds

async def main():
    async with aiohttp.ClientSession() as sess:
        # Start
        async with sess.post(SERVER, json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "submit_architecture_design_job",
                "arguments": {
                    "requirements": "ETL pipeline for IoT: Kafka → JSON → Redis → InfluxDB + S3",
                    "domain": "data-processing",
                }
            },
            "id": 1
        }) as resp:
            job_id = (await resp.json())["result"]["content"][0]["data"]["job_id"]

        print(f"Job started: {job_id}")

        # Poll
        while True:
            await asyncio.sleep(POLL_EVERY)
            async with sess.post(SERVER, json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "get_architecture_design_status", "arguments": {"job_id": job_id}},
                "id": 2
            }) as resp:
                result = (await resp.json())["result"]["content"][0]["data"]
                print(f"  status={result['status']}")
                if result["status"] in ("completed", "failed", "cancelled"):
                    break

        print(result.get("result", result))  # full design when completed
```

See `examples/architecture_client_async.py` for the complete runnable example. Run it with:

```bash
docker compose -f docker/docker-compose.yml up --build   # Terminal 1
make client-async                                      # Terminal 2
```

### Explore the pattern catalog

```
Call list_architecture_patterns() with no filters to see all patterns.
```

Or get details on a specific pattern:

```
Show me details about the event-driven architecture pattern.
```

---

## 🛠️ Tools at a Glance

| Tool | Description |
|---|---|
| `analyze_architecture` | Analyse requirements and domain → recommended style, patterns, quality metrics. *Long-running (LLM call). Not idempotent.* |
| `generate_architecture` | Generate an architecture design from requirements and selected patterns. *Long-running (LLM call). Not idempotent.* |
| `evaluate_architecture` | Score an existing design against quality attributes. *Long-running (LLM call). Not idempotent.* |
| `design_architecture` | Default tool for full architecture design (analyse → generate → evaluate → refine, up to 3 attempts). *Long-running (5–10 min); use this unless your client has a short request timeout.* |
| `submit_architecture_design_job` | Start a background design job and return a `job_id` immediately. **ONLY for clients with short request timeouts** (Cursor, Claude Desktop, TS-SDK). For other clients use `design_architecture`. Poll `get_architecture_design_status` every 10–30 s. |
| `get_architecture_design_status` | Poll job status. Returns the current status, progress message, and the full design output when `completed`. |
| `cancel_architecture_design` | Cancel a running job (best-effort; takes effect at the next pipeline stage boundary; may take up to one LLM call). |
| `list_architecture_patterns` | List all 40 patterns; filter by `category` and/or `domain` |
| `get_architecture_pattern` | Get full JSON for a specific pattern by name |


**Domain and Style are structured parameters** — pass them as separate tool arguments, not embedded in the requirements text.

Example prompts:

```
Build a scalable distributed system for processing IoT sensor data with
100k events per second throughput, written in Python, deployed on Kubernetes.
```

```
Design an architecture for an e-commerce platform handling flash-sales events.
Domain: e-commerce. Style: microservices.
```

```
Show me details about the blackboard pattern.
```

```
Call design_architecture with:
  requirements: "ETL pipeline for IoT: Kafka → JSON → Redis geo-enrich → InfluxDB + S3"
  domain: "data-processing"
```

---

## 💬 Prompts

This server also exposes four user-invoked workflow prompts (slash commands
in MCP clients). Unlike tools, the LLM does not autonomously invoke prompts —
the user selects one and fills in its arguments. Each prompt encodes a tested
tool-orchestration recipe.

| Prompt | Args | What it does |
|---|---|---|
| `/design_architecture_workflow` | requirements\* | Full analyze → generate → evaluate pipeline |
| `/explore_pattern_catalog` | `domain`, `category` | Live catalog discovery with embedded pattern names |
| `/evaluate_my_architecture` | `focus` | Guide evaluation criteria + finding prioritisation |
| `/compare_architecture_styles` | style_a\*, style_b\*, requirements\* | Two designs side-by-side; ~2× token cost |

\* = required argument

### Tool-only clients

Clients that only support the tools protocol (no native `prompts/list` or `prompts/get`) can access all four workflow prompts via the generated `list_prompts` and `get_prompt` tools, which route through the server's middleware chain exactly as native prompt calls do.

---

## 📖 Pattern Catalog

### Via MCP tools (recommended — works in all clients)

```
list_architecture_patterns()                                  # all 40 patterns
list_architecture_patterns(category="messaging")               # filter by category
list_architecture_patterns(domain="microservices")            # filter by domain
get_architecture_pattern(name="event-driven")                 # full pattern JSON
```

Valid `category` values: `messaging`, `structural`, `cloud`, `data`, `ai_cognitive`, `specialized`, `api_gateway`, `coordination`, `dataflow`, `presentation`.

### Via MCP resources

```
mcp_list_resources(server="architecture-pattern")
mcp_read_resource(server="architecture-pattern", uri="pattern://microservices")
```

### Pattern JSON structure

Each pattern includes: `name`, `category`, `context`, `benefits`, `tradeoffs`, `quality_attributes` (scalability/maintainability/reliability/security/performance/simplicity, scores 1–10), `suitable_domains`, `component_types`, `technology_stack`, `design_principles`, `best_practices`.

---

## Install Alternatives

### Docker (manual)

```bash
# Build the image
make docker-build

# Run with your API key
MINIMAXAI_API_KEY=your_key docker compose -f docker/docker-compose.yml up -d
```

### Local Development (uv)

**Prerequisites:** Python 3.12+, [uv](https://github.com/astral-sh/uv)

```bash
# Install
make install

# Configure
cp config/config.json ~/.config/architecture-pattern-mcp/config.json
# Edit ~/.config/architecture-pattern-mcp/config.json and set your GENERATOR_API_KEY

# Run the server
uv run python -m src.main --transport stdio              # for Claude Code / Codex
uv run python -m src.main --port 8050                    # for OpenCode (HTTP, default)
```

Or use the installed console script (after `make install`):

```bash
architecture-pattern-mcp --transport stdio
```

The TEI embedder (Qwen3-Embedding-0.6B) is required for domain-scoped pattern retrieval. Without it, the server falls back to the default pattern. Docker compose starts it automatically; local users must run it separately on port 8080.

The retrieval indexes (FAISS + BM25) are built at server startup so a misconfigured or unreachable TEI sidecar prevents startup (fail-fast) rather than breaking the user's first design request. Docker compose's `service_healthy` dependency ordering guarantees TEI is ready before the app starts.

---

## Configuration

### config.json

The server reads `~/.config/architecture-pattern-mcp/config.json` (override with `--config-path`):

```json
{
  "generator": {
    "provider": "openai",
    "config": {
      "model": "gpt-4o-mini",
      "base_url": "https://api.openai.com/v1",
      "api_key": "{env:GENERATOR_API_KEY}",
      "temperature": 0.1,
      "top_p": 1.0,
      "top_k": 20
    }
  },
  "embedder": {
    "provider": "tei",
    "config": {
      "base_url": "http://127.0.0.1:8080"
    }
  },
  "retrieval": {
    "bm25_top_k": 0,
    "dense_top_k": 0,
    "top_k_patterns": 5,
    "min_quality_score": 50.0
  },
  "pattern_directory": "~/.config/architecture-pattern-mcp/pattern",
  "transport": "streamable-http",
  "host": "0.0.0.0",
  "port": 8050,
  "logging_level": "INFO",
  "logging_format": "json"
}
```

`{env:VAR:-default}` syntax expands environment variables at load time.

### Generator LLM (LlamaIndex LiteLLM)

The generator LLM is accessed through the **LlamaIndex LiteLLM integration** ([`llama-index-llms-litellm`](https://docs.llamaindex.ai/en/stable/examples/llm/litellm/)). All provider settings therefore follow **LiteLLM's model syntax**: `<provider>/<model>` (e.g. `openai/gpt-4o-mini`, `anthropic/claude-sonnet-4-5`, `openrouter/minimax/minimax-m2`).

The server composes the LiteLLM model string from your configuration as `generator.provider` + `generator.config.model`:

| Config / env | Example | Resulting LiteLLM model string |
|---|---|---|
| `provider: "openai"`, `model: "gpt-4o-mini"` | `GENERATOR_PROVIDER=openai`, `GENERATOR_MODEL=gpt-4o-mini` | `openai/gpt-4o-mini` |
| `provider: "anthropic"`, `model: "claude-sonnet-4-5"` | `GENERATOR_PROVIDER=anthropic`, `GENERATOR_MODEL=claude-sonnet-4-5` | `anthropic/claude-sonnet-4-5` |
| `provider: "openrouter"`, `model: "minimax/minimax-m2"` | `GENERATOR_PROVIDER=openrouter`, `GENERATOR_MODEL=minimax/minimax-m2` | `openrouter/minimax/minimax-m2` |

If the configured model already contains a provider prefix (e.g. `openai/gpt-4o-mini`), that prefix is stripped and replaced by the configured `provider`.

- **Provider list, model names, and the exact `<provider>/<model>` syntax:** [LiteLLM Providers documentation](https://docs.litellm.ai/docs/providers)
- Custom/OpenAI-compatible endpoints (proxies, vLLM, Ollama, …): set `GENERATOR_BASE_URL` (`generator.config.base_url`) — it is passed as the LiteLLM `api_base`
- `GENERATOR_API_KEY` is passed as the LiteLLM `api_key`; `temperature`, `top_p`, `top_k`, and `stream` map to the corresponding LiteLLM parameters

### Key environment variables

| Variable | Default | Description |
|---|---|---|
| `GENERATOR_API_KEY` | *(required)* | API key for your LLM provider (passed to LiteLLM as `api_key`) |
| `GENERATOR_PROVIDER` | `openai` | LiteLLM provider prefix: `openai`, `anthropic`, `openrouter`, … — see [LiteLLM Providers](https://docs.litellm.ai/docs/providers) |
| `GENERATOR_BASE_URL` | `https://api.openai.com/v1` | API base URL (passed to LiteLLM as `api_base`) |
| `GENERATOR_MODEL` | `gpt-4o-mini` | Model name; final model string is `<GENERATOR_PROVIDER>/<GENERATOR_MODEL>` (LiteLLM syntax) |
| `GENERATOR_TEMPERATURE` | `0.1` | Sampling temperature |
| `GENERATOR_TOP_P` | `1.0` | Top-p sampling |
| `GENERATOR_TOP_K` | `20` | Top-k sampling |
| `GENERATOR_STREAM` | `false` | Enable streaming responses |
| `EMBEDDER_PROVIDER` | `tei` | Embedder provider |
| `EMBEDDER_BASE_URL` | `http://127.0.0.1:8080` | TEI embedder URL |
| `EMBEDDER_BATCH_SIZE` | `16` | Embedding batch size |
| `EMBEDDER_QUERY_INSTRUCTION` | *(empty)* | Query instruction prefix |
| `EMBEDDER_TEXT_INSTRUCTION` | *(empty)* | Text instruction prefix |
| `RETRIEVAL_BM25_TOP_K` | `0` | BM25 stage-1 recall cap (0=full corpus) |
| `RETRIEVAL_DENSE_TOP_K` | `0` | Dense stage-1 recall cap (0=full corpus) |
| `RETRIEVAL_TOP_K_PATTERNS` | `5` | Number of patterns to select |
| `RETRIEVAL_MIN_FUSION_SCORE` | `0.0` | Relevance floor on the rank_fusion blend value (range [0, 2/60] ≈ [0, 0.033]). Default 0.0 (gate disabled). Values above the blend maximum are rejected at startup. |
| `RETRIEVAL_RERANK_TOP_N` | `10` | Rerank top N (slug-cut after CE) |
| `RETRIEVAL_USE_LEAN_WIRE_SCHEMA` | `false` | Use lean response schema |
| `RETRIEVAL_STYLE_SCORE_THRESHOLD` | `50.0` | Min analysis score for style recommendation |
| `REASONING_ENABLED` | `true` | Server-side reasoning MCP integration (see [Structured Reasoning](#structured-reasoning-shannonthinking--code-reasoning)) |
| `REASONING_SPAWN_TIMEOUT_SECONDS` | `10` | Subprocess spawn timeout per reasoning tool |
| `REASONING_STEP_TIMEOUT_SECONDS` | `20` | Per-thought tool-call timeout |
| `REASONING_MAX_TOTAL_STEPS` | `8` | Hard cap on reasoning steps per phase |
| `REASONING_QUIET_STDERR` | `true` | Silence reasoning-subprocess stderr (ASCII progress boxes, `[info]` banners); set `false` to debug spawn failures |
| `REASONING_FAIL_FAST` | `false` | Fail server startup when a reasoning tool is unreachable |
| `REASONING_SHANNONTHINKING_CMD` | *(embedded)* | JSON list command for shannonthinking (e.g. `["npx","-y","server-shannon-thinking@latest"]`) |
| `REASONING_CODE_REASONING_CMD` | *(embedded)* | JSON list command for code-reasoning |
| `RETRIEVAL_ANALYSIS_BLEND_WEIGHT` | `0.7` | Weight on analysis score in blend |
| `RETRIEVAL_FUSION_BLEND_WEIGHT` | `0.3` | Weight on fusion score in blend |
| `RETRIEVAL_WEIGHT_SMOOTHING_ALPHA` | `0.7` | Weight smoothing alpha |
| `RETRIEVAL_VERBOSE_TIMING` | `false` | Log phase timings at INFO level |
| `RETRIEVAL_MAX_TRIES` | `3` | Max design loop attempts |
| `RETRIEVAL_MIN_QUALITY_SCORE` | `50.0` | Early-stop quality threshold |
| `RERANKER_BASE_URL` | *(default reranker URL)* | TEI reranker endpoint (host:port); model is fixed to `gte-reranker-modernbert-base` |
| `RERANKER_TIMEOUT` | `30.0` | Reranker timeout (seconds) |
| `RERANKER_MAX_BATCH_SIZE` | `48` | Max texts per TEI /rerank request; must be ≤ min(MAX_CLIENT_BATCH_SIZE, MAX_CONCURRENT_REQUESTS) of the reranker sidecar. HybridPatternRetriever chunks large pools automatically. |
| `PATTERN_DIRECTORY` | `~/.config/architecture-pattern-mcp/pattern` | Pattern files directory |
| `VALIDATION_MAX_RETRIES` | `2` | Max self-healing retry attempts |
| `VALIDATION_RETRY_ON_FAIL` | `true` | Retry on validation failure |

---

## Structured Reasoning (shannonthinking / code-reasoning)

Before each LLM phase call (ANALYZE / GENERATE / EVALUATE / RETRY), the server
optionally runs a bounded **ThoughtGenerator loop**: it authors each reasoning
step with the generator's own LLM (LlamaIndex LiteLLM; one completion per
step) and submits it to the
[shannonthinking](https://github.com/olaservo/shannon-thinking) and/or
[code-reasoning](https://github.com/mettamatt/code-reasoning) MCP servers —
structured thinking scratchpads that validate, number, and record each step.
The resulting trace is injected into the phase prompt as a
`<reasoning_context>` block. Contract: **each thought = 1 LLM completion + 1
MCP tool call**, capped by `REASONING_MAX_TOTAL_STEPS` (default 8).

Key properties:

- **Embedded in Docker** — the `build-mcps` stage bakes both npm packages
  (`server-shannon-thinking@0.1.1`, `@mettamatt/code-reasoning@0.8.1`) into
  the image at `/usr/local/lib/node_modules/...`; the runtime invokes them
  directly via `node` (no network, no npx).
- **Auto-fallback to npx** outside Docker — when the embedded entry points
  are missing, the client falls back to `npx -y <pkg>` (first call downloads).
- **Process-per-call isolation** — each tool call runs in a fresh subprocess
  (`keep_alive=False`); nothing persists between calls.
- **Silent per-call degradation** — any spawn/timeout/tool failure logs a
  WARNING and the phase proceeds with a degraded in-prompt thinking scaffold
  (decompose → classify → calibrate → resolve → verify); it never raises.
- **Loud startup** — the lifespan health-check probes both tools and logs an
  ERROR (with resolution hints) if one is unreachable; set
  `REASONING_FAIL_FAST=true` to make startup fail instead.
- **Trace caching** — ANALYZE and GENERATE traces are computed once per
  design request and reused across design-loop attempts.

### Opting out / tuning

```bash
export REASONING_ENABLED=false          # disable entirely
export REASONING_FAIL_FAST=true         # refuse to start with broken MCPs
```

Local (non-Docker) development needs Node.js; either install the packages
globally (`npm install -g server-shannon-thinking @mettamatt/code-reasoning`)
or let the npx fallback download them on first use.

Latency note: expect roughly +1–6 s per reasoning step. Worst case adds a
couple of minutes per design run; the trace cache keeps typical overhead
well below that.

Set `LOGGING_LEVEL=DEBUG` to capture the authored `thought` and tool response
for every per-step reasoning call. Docker/systemd stacks default to INFO;
export `LOGGING_LEVEL=DEBUG` before `make docker-up`.
| `ARCHITECTURE_PATTERN_JOBS_DB` | `~/.config/architecture-pattern-mcp/jobs.db` | SQLite path for async job trio. Override for test isolation |
| `TASKS_HEARTBEAT_ENABLED` | `true` | Emit progress notifications during long tool calls |
| `TASKS_HEARTBEAT_INTERVAL_SECONDS` | `30` | Heartbeat interval in seconds (keep below client idle timeout) |
| `TRANSPORT` | `streamable-http` | Transport mode: `stdio`, `streamable-http` |
| `HOST` | `0.0.0.0` | HTTP bind host |
| `PORT` | `8050` | HTTP bind port |
| `LOGGING_LEVEL` | `INFO` | Logging level |
| `LOGGING_FORMAT` | `json` | Logging format: `json`, `text` |
| `CONFIG_PATH` | `~/.config/architecture-pattern-mcp/config.json` | Config file path |

### CLI flags

| Flag | Description |
|---|---|
| `--transport {stdio,streamable-http}` | Override transport mode |
| `--host` | Override HTTP bind host (default: 0.0.0.0) |
| `--port` | Override HTTP port (default: 8050) |
| `--config-path` | Path to config file |
| `--health` | Run health check and exit |

---

## Extending with Custom Patterns

Pattern files are loaded from `~/.config/architecture-pattern-mcp/pattern/` (configurable via `PATTERN_DIRECTORY`). Drop a JSON file alongside the 40 built-in patterns.

**Minimal pattern structure:**

```json
{
  "category": "structural",
  "name": "my-custom-pattern",
  "context": "Describe when this pattern applies.",
  "benefits": ["Benefit 1", "Benefit 2"],
  "tradeoffs": ["Tradeoff 1"],
  "quality_attributes": {
    "scalability": 7,
    "maintainability": 8,
    "reliability": 7,
    "security": 6,
    "performance": 7,
    "simplicity": 5
  }
}
```

Required fields: `category`, `name`, `context`, `benefits`, `tradeoffs`, `quality_attributes`.

Valid `category` values: `messaging`, `structural`, `cloud`, `data`, `ai_cognitive`, `specialized`, `api_gateway`, `coordination`, `dataflow`, `presentation`.

Full JSON Schema with all enums: `docs/pattern-schema.json`

---

## Long-running tools & timeouts

`design_architecture` (and to a lesser extent `analyze_architecture`, `generate_architecture`, `evaluate_architecture`) run multi-stage LLM pipelines that **can take 5–10 minutes per call**. This is inherent to the workload, not a bug: the generator LLM must process a large input payload — the selected pattern definitions from the 36-pattern catalog, your requirements, and the full output of every previous stage — and produce a large, strictly structured JSON document (components, relationships, API contracts, data models, event contracts, quality scores) one token at a time. The `design_architecture` pipeline repeats generate → evaluate up to three times, so a single call can comprise 9+ LLM round trips.

### The timeout problem

MCP clients (AI coding agents, MCP SDKs) sit between the server and the LLM. Many of them implement a **client-side idle timeout**: if no data is received on the HTTP connection for some period (typically 30–120 seconds), the client aborts the request. The server is still working — the LLM is still generating — but the client closes the connection and reports a timeout error to the agent.

This is a client-side behaviour, not a server-side one. The server processes the full request correctly; the client simply gives up before the response arrives.

**Affected clients (hardcoded short timeouts):**

| Client | Timeout | Notes |
|---|---|---|
| Claude Desktop (TS-SDK) | 60 s | Hardcoded; does not reset on progress notifications |
| Cursor (TS-SDK) | 60 s | Same as Claude Desktop |
| Other TS-SDK based agents | varies | Most cap at 60–120 s |

These clients cannot be reconfigured to accept longer timeouts — the timeout is baked into the SDK.

**Clients covered by the heartbeat defence:**

| Client | Timeout | Defence |
|---|---|---|
| Claude Code | ~300 s | Heartbeat every 30 s resets idle timer |
| OpenCode | ~300 s | Heartbeat every 30 s resets idle timer |
| Codex CLI | ~300 s | Heartbeat every 30 s resets idle timer |
| Other HTTP-transport agents | varies | Most reset on any received data |

Works for these because their idle timers are reset by any incoming data — the heartbeat `progress` notifications sent from a parallel async task on the server are received by the client, resetting its clock.

### The heartbeat defence (applied by default)

Every long-running tool emits `progress` notifications from a parallel coroutine every 30 seconds (configurable via `TASKS_HEARTBEAT_INTERVAL_SECONDS`). As long as the client resets its idle timer on any received data, the request stays alive for the full duration of the pipeline.

> **TS-SDK clients (Claude Desktop, Cursor, etc.) do not reset their timeout on progress notifications.**

### The async job trio (for timeout-constrained clients)

For full control and compatibility with timeout-limited clients, three tools provide a durable job handle:

```
submit_architecture_design_job(requirements, domain, override_style)  → job_id
get_architecture_design_status(job_id)                                  → {status, result, error}
cancel_architecture_design(job_id)                                      → {cancelled, status}
```

`submit_architecture_design_job` returns a `job_id` in milliseconds. The pipeline runs in a background task. Poll `get_architecture_design_status(job_id)` every 10–30 seconds. When status is `completed`, the full design is in the `result` field. Cancellation is best-effort — the job exits at the next pipeline stage boundary.

**This is the only fix that works for TS-SDK clients (Claude Desktop, Cursor).**

The job store is SQLite at `~/.config/architecture-pattern-mcp/jobs.db` (configurable via `ARCHITECTURE_PATTERN_JOBS_DB`).

### Bypassing client timeouts entirely: `make client`

The example client in `examples/architecture_client.py` is a **direct Python HTTP client** — it is not an MCP agent. It calls the server over HTTP without any MCP SDK, and therefore has **no client-side idle timeout**. It makes a single blocking request and waits for the full response, regardless of how long it takes.

```bash
# Start the server (from project root)
docker compose -f docker/docker-compose.yml up --build

# In another terminal, run the example client
make client
```

`make client` is a development/demo tool. It demonstrates that the server **correctly completes** long requests — the timeout issue is purely a client-side problem. For production use with MCP agents, covers the majority of clients; async job trio is the universal fallback.

## Troubleshooting

### Server starts but tools are not visible

1. Check the agent's MCP connection: Claude Code `/mcp`, OpenCode `opencode mcp list`, Codex `codex mcp list`
2. Verify the server process started: compose logs should show `MCPArchitectServer initialized`
3. Confirm the TEI embedder is healthy: `curl http://127.0.0.1:8080/health` inside the container

### "Connection refused" or timeout errors

The server waits for the TEI embedder to become healthy:

```bash
docker compose -f docker/docker-compose.yml logs pattern-tei
```

### LLM provider errors (502 / 401)

- Confirm `GENERATOR_API_KEY` is set and not expired
- Verify `GENERATOR_BASE_URL` matches your provider's endpoint
- If using a proxy, check reachability from inside the container

### Pattern JSON files not loading

- Files must have `.json` extension
- Required fields: `category`, `name`, `context`, `benefits`, `tradeoffs`, `quality_attributes`
- Validate against `docs/pattern-schema.json`

---

## Building & Development

**Common make targets:**

| Target | Description |
|---|---|
| `make install` | Install package in editable mode with dev dependencies |
| `make lint` | Run ruff linting |
| `make lint-fix` | Auto-fix lint issues and format |
| `make typecheck` | Run pyright type checking |
| `make unit-tests` | Run unit tests with uv (tests/unit/) |
| `make client` | Run the example MCP client demo (requires server running) |
| `make docker-build` | Build the MCP server Docker image |
| `make docker-build-all` | Build MCP server + TEI embedder images |
| `make docker-publish` | Push image to Docker Hub + GHCR (version + latest) |
| `make docker-up` | Build and start all services |
| `make docker-down` | Stop all services |
**Development workflow:**

```bash
make install                      # First-time setup
make lint typecheck              # Before pushing
make docker-build-all             # Build both images (first time and after code changes)
make docker-up   # Start services
make docker-logs-follow          # Watch logs
make docker-down                 # Stop
```

---

## Publishing

All three images are published to two registries simultaneously:

| Image | Docker Hub | GHCR | Tags |
|---|---|---|---|
| MCP server | `olkowa/architecture-pattern-mcp` | `ghcr.io/olk/architecture-pattern-mcp` | `$(DOCKER_TAG)`, `latest` |
| TEI embedder | `olkowa/pattern-tei-embed` | `ghcr.io/olk/pattern-tei-embed` | `$(DOCKER_TAG)`, `latest` |
| TEI reranker | `olkowa/pattern-tei-rerank` | `ghcr.io/olk/pattern-tei-rerank` | `$(DOCKER_TAG)`, `latest` |

All three images share the same `$(DOCKER_TAG)` (the version from `pyproject.toml`), so `tei:1.0.3` always ships with `mcp:1.0.3`. Blob deduplication keeps re-tagging unchanged TEI images cheap.

> **Bandwidth note:** the TEI embedder image is ~5 GB (ONNX fp32 weights baked in). First push to each registry is ~5 GB upload. Subsequent pushes are incremental — only changed layers are transferred.

### Prerequisites

**Docker Hub** — already authenticated locally (`docker login`).

**GitHub Container Registry** — requires a [classic PAT](https://github.com/settings/tokens/new?scopes=write:packages) with `write:packages` scope. 2FA is not an issue — PATs bypass it. After login the token is discarded; the credential persists in `~/.docker/config.json` until you log out.

### Publish (one-time setup + per-session)

```bash
# 1. Login to GHCR (interactive — paste token at the password prompt)
docker login ghcr.io -u olk

# 2. Build and push all three images (MCP + TEI embedder + TEI reranker)
#    The umbrella target builds the MCP image, tags it, pushes it, creates the git tag,
#    then builds and pushes each TEI image in sequence.
make docker-publish-all

# 3. Logout from GHCR immediately after publishing
#    (removes the ghcr.io credential from ~/.docker/config.json)
docker logout ghcr.io
```

On subsequent publishes repeat steps 1–3. If your PAT has expired, generate a new one at the link above.

### First push — set packages public (GHCR only)

GHCR packages default to **private**. After the first `make docker-publish-all`, flip all three packages to public:

| Package | Settings URL |
|---|---|
| MCP server | `https://github.com/users/olk/packages/container/architecture-pattern-mcp/settings` |
| TEI embedder | `https://github.com/users/olk/packages/container/pattern-tei-embed/settings` |
| TEI reranker | `https://github.com/users/olk/packages/container/pattern-tei-rerank/settings` |

Set each to **Public** and save.

### Partial failure recovery

If the push fails mid-way (e.g., GHCR auth was not configured), Docker Hub layers are already uploaded. After fixing auth, re-running `make docker-publish-all` is safe — each registry reports a cache hit for already-uploaded layers and completes the remaining push. For targeted retries, individual images can be pushed with `make docker-publish-tei` or `make docker-publish-tei-rerank`.

---

## systemd Service (Linux)

The server can run as a systemd service on any systemd-based Linux host. It
starts the Docker Compose stack automatically at boot.

### File layout

The `systemd/` directory contains three files:

| File | Purpose |
|---|---|
| `systemd/architecture-pattern-mcp.service` | The systemd unit |
| `systemd/docker-compose.yml` | Production compose variant (no `build:`, absolute paths) |
| `systemd/README.md` | Full runbook with install, verify, and troubleshooting |

The production compose file is a deployment variant of `docker/docker-compose.yml`:
it has no `build:` sections (images must be pre-built), uses absolute paths, and
lives under `/etc/architecture-pattern-mcp/` on the host. The systemd-managed
project uses the distinct name `apmcp-systemd` so it can coexist with the dev
compose if needed.

> **TEI sidecars are NOT defined in this stack** — the `pattern-tei-embed` embedder
> and `pattern-tei-rerank` reranker containers live in the shared
> [`pattern-tei-infra`](https://github.com/olk/pattern-tei-infra) stack.  This
> stack owns the `pattern-tei-shared` Docker network and exposes the sidecars at
> `http://pattern-tei-embed:8080/v1` (embedder) and `http://pattern-tei-rerank:8080`
> (reranker).  The systemd MCP stack joins that network and reaches them by
> those DNS names.
>
> **Prerequisite — one-time TEI infra setup:**
>
> ```bash
> # Clone the infra stack (if not already on the host)
> git clone https://github.com/olk/pattern-tei-infra.git ~/pattern-tei-infra
>
> # Install and enable the pattern-tei-infra systemd unit
> sudo install -m 644 ~/pattern-tei-infra/pattern-tei-infra.service \
>                 /etc/systemd/system/
> sudo systemctl daemon-reload
> sudo systemctl enable --now pattern-tei-infra.service
> # Wait ~2 min for the TEI sidecars to become healthy
> ```
>
> **Start `architecture-pattern-mcp.service` only AFTER** `pattern-tei-infra.service`
> is `active (running)`. See
> [`pattern-tei-infra/README.md`](https://github.com/olk/pattern-tei-infra/README.md)
> for full details.

### Prerequisites

- systemd-based Linux host with Docker (`docker compose version`).
- `<user>` is in the `docker` group.
- Both images pre-built locally (`make docker-build-all` from the repo).
- **Shared TEI infra stack installed and enabled** (see tei-infra README).

### Install

```bash
# 0. Install + enable shared TEI infra (once)
sudo install -m 644 {HOME}/pattern-tei-infra/pattern-tei-infra.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pattern-tei-infra.service

# 1. Build images (once)
make docker-build-all

# 2. Deploy /etc/architecture-pattern-mcp/
sudo install -d /etc/architecture-pattern-mcp/config
sudo install -m 644 systemd/docker-compose.yml /etc/architecture-pattern-mcp/
sudo install -m 644 ~/.config/architecture-pattern-mcp/config.json /etc/architecture-pattern-mcp/config/

# 3. Create the .env file (root:docker 640) and edit it.
#     640 root:docker — not 600 root:root — so the systemd service
#     running as User=graemer (a member of the `docker` group) can read this
#     file when docker compose auto-loads it.  The `docker` group is
#     effectively privileged; this is the standard trade-off for non-root
#     systemd services that manage Docker containers.
sudo install -o root -g docker -m 640 /dev/null /etc/architecture-pattern-mcp/.env
sudo $EDITOR /etc/architecture-pattern-mcp/.env
# Contents:
#   MINIMAXAI_API_KEY=sk-...
#   COMPOSE_PROJECT_NAME=apmcp-systemd
#   MCP_HOST_PORT=8050          # change to avoid port conflicts with other MCP servers

# 4. Install and enable the service.
sudo install -m 644 systemd/architecture-pattern-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now architecture-pattern-mcp.service
```

### Verify

`systemctl status` shows `active (exited)` within seconds, but the containers
take **up to ~2 minutes** to become healthy (TEI embedder `start_period: 120s`).
The unit does not wait for healthchecks.

```bash
systemctl status architecture-pattern-mcp
journalctl -u architecture-pattern-mcp -n 50
docker compose -p apmcp-systemd -f /etc/architecture-pattern-mcp/docker-compose.yml ps
curl -fsS http://localhost:${MCP_HOST_PORT:-8050}/health
```

### Day-to-day

```bash
sudo systemctl start|stop|restart|reload architecture-pattern-mcp
journalctl -u architecture-pattern-mcp -n 200 -f
docker compose -p apmcp-systemd -f /etc/architecture-pattern-mcp/docker-compose.yml logs -f
```

### Updating the stack

```bash
make docker-build-all                     # rebuild both images
sudo systemctl reload architecture-pattern-mcp   # recreate containers
```

### Uninstall

```bash
sudo systemctl disable --now architecture-pattern-mcp.service
sudo rm /etc/systemd/system/architecture-pattern-mcp.service
sudo systemctl daemon-reload
sudo rm -rf /etc/architecture-pattern-mcp
```

For full troubleshooting, networking details, and the coexistence guide, see
`systemd/README.md`.

---

## License

MIT License. See [LICENSE](LICENSE).
