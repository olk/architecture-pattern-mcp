# architecture-pattern-mcp

[![CI](https://img.shields.io/github/actions/workflow/status/olk/architecture-pattern-mcp/ci.yml?branch=main)](https://github.com/olk/architecture-pattern-mcp/actions)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

An MCP (Model Context Protocol) server that provides architecture design expertise to AI coding agents. Given a requirements string and a domain, it analyses the problem, selects matching architecture patterns (from 36 built-in patterns), generates a concrete architecture design with components, relationships, API contracts, data models, and event contracts, and evaluates it against quality attributes (maintainability, scalability, reliability, security, performance).

---

## Table of Contents

- [⚡ Quickstart](#-quickstart)
- [🔌 Connect Your Agent](#-connect-your-agent)
  - [Claude Code](#claude-code)
  - [OpenCode](#opencode)
  - [Codex CLI](#codex-cli)
- [🧪 Use the Tools](#-use-the-tools)
  - [Design your first architecture](#design-your-first-architecture)
  - [Explore the pattern catalog](#explore-the-pattern-catalog)
- [🛠️ Tools at a Glance](#️-tools-at-a-glance)
- [📖 Pattern Catalog](#-pattern-catalog)
- [Install Alternatives](#install-alternatives)
  - [Docker (manual)](#docker-manual)
  - [Local Development (uv)](#local-development-uv)
- [Configuration](#configuration)
- [Extending with Custom Patterns](#extending-with-custom-patterns)
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

Server starts on **streamable-http** at `http://localhost:8050/mcp`. Then connect your agent below.

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
      "url": "http://localhost:8050/mcp"
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

## Use the Tools

### Design your first architecture

In Claude Code (or your agent), try:

```
Build a scalable ETL pipeline for IoT sensor data: ingest 10k events/sec
from Kafka, parse JSON, enrich with geolocation from Redis, write to InfluxDB
and S3.
```

Then call the `design_architecture` tool with:
- `requirements`: "ETL pipeline for IoT sensor data: ingest 10k events/sec from Kafka, parse JSON, enrich with geolocation from Redis, write to InfluxDB and S3"
- `domain`: "data-processing"
- `style`: "pipe-and-filter"

The server returns a full architecture design: components (Kafka source, JSON parser filter, geolocation enricher, InfluxDB sink, S3 sink), quality attribute scores (scalability: 9.1, maintainability: 8.2, …), and specific recommendations.

### Explore the pattern catalog

Ask your agent to list all available patterns:

```
Call list_architecture_patterns() with no filters to see all patterns.
```

Or get details on a specific pattern:

```
Show me the event-driven architecture pattern.
```

---

## 🛠️ Tools at a Glance

| Tool | Description |
|---|---|
| `analyze_architecture` | Analyse requirements and domain → recommended style, patterns, quality metrics |
| `generate_architecture` | Generate an architecture design from requirements and selected patterns |
| `evaluate_architecture` | Score an existing design against quality attributes |
| `design_architecture` | Full pipeline: analyse → generate → evaluate → refine (up to 3 attempts) |
| `list_architecture_patterns` | List all 36 patterns; filter by `category` and/or `domain` |
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

---

## 📖 Pattern Catalog

### Via MCP tools (recommended — works in all clients)

```
list_architecture_patterns()                                  # all 36 patterns
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
      "api_key": "{env:GENERATOR_API_KEY}"
    }
  },
  "embedder": {
    "provider": "tei",
    "config": {
      "model": "data/qwen3-embedding-0.6b",
      "base_url": "http://127.0.0.1:8080/v1",
      "embedding_dim": 1024
    }
  },
  "retrieval": {
    "bm25_top_k": 0,
    "dense_top_k": 0,
    "top_k_patterns": 5,
    "mode": "reciprocal_rerank",
    "min_quality_score": 50.0
  },
  "pattern_directory": "~/.config/architecture-pattern-mcp/pattern"
}
```

`{env:VAR:-default}` syntax expands environment variables at load time.

### Key environment variables

| Variable | Default | Description |
|---|---|---|
| `GENERATOR_API_KEY` | *(required)* | API key for your LLM provider |
| `GENERATOR_PROVIDER` | `openai` | Provider: `openai`, `minimax`, `anthropic`, … |
| `GENERATOR_BASE_URL` | `https://api.openai.com/v1` | API base URL |
| `GENERATOR_MODEL` | `gpt-4o-mini` | Model name |
| `EMBEDDER_BASE_URL` | `http://127.0.0.1:8080/v1` | TEI embedder URL |
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

Pattern files are loaded from `~/.config/architecture-pattern-mcp/pattern/` (configurable via `PATTERN_DIRECTORY`). Drop a JSON file alongside the 36 built-in patterns.

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

## Troubleshooting

### Server starts but tools are not visible

1. Check the agent's MCP connection: Claude Code `/mcp`, OpenCode `opencode mcp list`, Codex `codex mcp list`
2. Verify the server process started: compose logs should show `MCPArchitectServer initialized`
3. Confirm the TEI embedder is healthy: `curl http://127.0.0.1:8080/health` inside the container

### "Connection refused" or timeout errors

The server waits for the TEI embedder to become healthy:

```bash
docker compose -f docker/docker-compose.yml logs architecture-pattern-tei
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

The MCP server image is published to two registries simultaneously:

| Registry | Namespace | Image tags |
|---|---|---|
| Docker Hub | `olkowa/architecture-pattern-mcp` | `1.0.1`, `latest` |
| GitHub Container Registry | `ghcr.io/olk/architecture-pattern-mcp` | `1.0.1`, `latest` |

Both registries receive the same local image; the Makefile handles tagging and pushing for each in one invocation.

Each `make docker-publish` also creates and pushes an annotated git tag `v<version>` (e.g., `v1.0.2`) marking the released commit; the target requires a clean worktree.

### Prerequisites

**Docker Hub** — already authenticated locally (`docker login`).

**GitHub Container Registry** — requires a [classic PAT](https://github.com/settings/tokens/new?scopes=write:packages) with `write:packages` scope. 2FA is not an issue — PATs bypass it. After login the token is discarded; the credential persists in `~/.docker/config.json` until you log out.

### Publish (one-time setup + per-session)

```bash
# 1. Login to GHCR (interactive — paste token at the password prompt)
docker login ghcr.io -u olk

# 2. Build and push to both registries
make docker-publish

# 3. Logout from GHCR immediately after publishing
#    (removes the ghcr.io credential from ~/.docker/config.json)
docker logout ghcr.io
```

On subsequent publishes repeat steps 1–3. If your PAT has expired, generate a new one at the link above.

### First push — set package public (GHCR only)

GHCR packages default to **private**. After the first `make docker-publish`, flip the package to public:

`https://github.com/users/olk/packages/container/architecture-pattern-mcp/settings`

Set visibility to **Public** and save.

### Partial failure recovery

If the push fails mid-way (e.g., GHCR auth was not configured), Docker Hub layers are already uploaded. After fixing auth, re-running `make docker-publish` is safe — each registry reports a cache hit for already-uploaded layers and completes the remaining push.

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

### Prerequisites

- systemd-based Linux host with Docker (`docker compose version`).
- `<user>` is in the `docker` group.
- Both images pre-built locally (`make docker-build-all` from the repo).

### Install

```bash
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
