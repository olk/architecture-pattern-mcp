# INSTALL — deployment runbook for AI agents

Step-by-step instructions for an AI agent (Claude Code, Codex, OpenCode, …)
to install **architecture-pattern-mcp** on the Linux host the agent runs on.
All steps are non-interactive: files are written with heredocs, every step has
a verification command with its expected output. Run commands from the repo
root unless noted. Requires a clone of this repo (this file lives in it).

Human-oriented background: [README.md](README.md) (configuration reference,
MCP client setup) and [systemd/README.md](systemd/README.md) (systemd
deep-dive, troubleshooting).

## What gets installed

| Component | Image (Docker Hub — public registry) | Role |
|---|---|---|
| MCP server | `olkowa/architecture-pattern-mcp` | Tool server, streamable-http on container port 8050 |
| TEI embedder | `olkowa/pattern-tei-embed` | Qwen3-Embedding-0.6B sidecar; required for retrieval |
| TEI reranker | `olkowa/pattern-tei-rerank` | Reranker sidecar; required for retrieval |

Tags: `latest` plus a pinned release tag per image — the MCP server releases
independently of the TEI sidecars (TEI images change rarely), so the pins
differ: MCP `1.1.3`, TEI embed/rerank `1.1.1`. GHCR mirrors of these images
are not anonymously pullable — use Docker Hub. Images are **linux/amd64
only**; on arm64 hosts build locally instead: `make docker-build-all`.

Pick exactly ONE path:

| | Path A — Compose stack | Path B — systemd stack |
|---|---|---|
| Use when | evaluating / developing; no sudo available | persistent host service, starts at boot |
| Needs root | no (Docker group membership only) | yes (`sudo`) |
| Host port | 8060 | 8050 |
| TEI sidecars | own copies inside the compose project | shared `pattern-tei-infra` stack |
| Survives reboot | no (manual `up -d`) | yes (systemd unit) |

Both paths can run concurrently (distinct container names and ports).

## 0. Preconditions (both paths)

```bash
test -f docker/docker-compose.yml && echo "repo clone: OK"
docker compose version                      # needs ≥ v2.20
id -nG | tr ' ' '\n' | grep -qx docker && echo "docker group: OK"
df -h /var/lib/docker                       # ≥ 5 GB free (MCP ≈ 0.3 GB, TEI ≈ 2–4 GB)
```

For Path B additionally:

```bash
systemctl is-system-running                 # expect "running" or "degraded"
```

The deployed stack defaults to **MiniMax** as generator LLM, so obtain a
`MINIMAXAI_API_KEY` (`sk-...`). To use another provider (OpenAI, DeepSeek,
Ollama, …) see [Switching the generator LLM](#switching-the-generator-llm) —
the install steps below stay the same.

## Path A — Compose stack (repo clone, no build, no root)

`docker/docker-compose.yml` has no `build:` sections; images are parameterized
(`${MCP_IMAGE}`, `${TEI_IMAGE}`, `${TEI_RERANK_IMAGE}`, `${MINIMAXAI_API_KEY}`,
`${MCP_HOST_PORT}`) and resolved from an env file.

```bash
# A1. Resolve the MCP release version and pull the images. TEI pins differ
#     from the MCP version (TEI images release rarely); check the tags table
#     at the top of this file for the current TEI pin.
VERSION=$(grep -m 1 '^version' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')
TEI_VERSION=1.1.1
docker pull "olkowa/architecture-pattern-mcp:${VERSION}"
docker pull "olkowa/pattern-tei-embed:${TEI_VERSION}"
docker pull "olkowa/pattern-tei-rerank:${TEI_VERSION}"
# If a pull fails (tag not published), list available tags and use latest:
#   curl -fsS 'https://hub.docker.com/v2/repositories/olkowa/architecture-pattern-mcp/tags'

# A2. Write the env file next to the compose file (compose interpolation source).
cat > docker/.env <<EOF
MCP_IMAGE=olkowa/architecture-pattern-mcp:${VERSION}
TEI_IMAGE=olkowa/pattern-tei-embed:${TEI_VERSION}
TEI_RERANK_IMAGE=olkowa/pattern-tei-rerank:${TEI_VERSION}
MINIMAXAI_API_KEY=sk-REPLACE-ME
MCP_HOST_PORT=8060
EOF

# A3. Sanity check: interpolation resolved to the Hub refs (each printed image:
#     olkowa/architecture-pattern-mcp:…, olkowa/pattern-tei-embed:…,
#     olkowa/pattern-tei-rerank:…). Empty MINIMAXAI_API_KEY warning is expected
#     only if you skipped the key.
docker compose --env-file docker/.env -f docker/docker-compose.yml config | grep 'image:'

# A4. Start. TEI sidecars cold-start model weights; first start takes ~2 min.
docker compose --env-file docker/.env -f docker/docker-compose.yml up -d

# A5. Wait until all three report "healthy" (poll if still "starting").
docker inspect -f '{{.Name}} {{.State.Health.Status}}' \
  pattern-tei-embed-dev pattern-tei-rerank-dev architecture-pattern-mcp-dev

# A6. Probe the MCP endpoint — must print 200.
#     (GET /health is 404 by design; the JSON-RPC initialize POST is the probe.)
curl -s -o /dev/null -w '%{http_code}\n' -X POST "http://localhost:8060/mcp" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"probe","version":"0.0.0"}},"id":1}'
```

Installed endpoint: `http://localhost:8060/mcp` (streamable-http).

Stop / remove the stack:

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml down
rm docker/.env   # contains the API key — remove or keep as you prefer
```

Config in Path A is the repo file `config/config.json` (mounted at
`/app/config`); after editing it, restart the server container to apply.

## Path B — systemd stack (persistent, sudo required)

Layout on the host:

| Path | Content |
|---|---|
| `/etc/pattern-tei-infra/` | TEI compose (from the `pattern-tei-infra` repo) |
| `/etc/systemd/system/pattern-tei-infra.service` | TEI stack unit |
| `/etc/architecture-pattern-mcp/` | MCP compose + `.env` |
| `/etc/architecture-pattern-mcp/config/config.json` | MCP configuration |
| `/etc/systemd/system/architecture-pattern-mcp.service` | MCP stack unit |

Run all steps as the user that will own the services (must be in the `docker`
group). Both unit templates hardcode `User=graemer` (the author's username) —
the `sed` below substitutes the invoking user.

### B0 — shared TEI infra (prerequisite, once)

```bash
TEI_VERSION=1.1.1   # TEI pins differ from the MCP version; see the tags table
git clone https://github.com/olk/pattern-tei-infra /tmp/pattern-tei-infra

# Pull Hub images and retag to the local names the infra compose expects
# (pattern-tei-embed:latest / pattern-tei-rerank:latest).
docker pull "olkowa/pattern-tei-embed:${TEI_VERSION}"
docker pull "olkowa/pattern-tei-rerank:${TEI_VERSION}"
docker tag "olkowa/pattern-tei-embed:${TEI_VERSION}" pattern-tei-embed:latest
docker tag "olkowa/pattern-tei-rerank:${TEI_VERSION}" pattern-tei-rerank:latest

sudo install -d /etc/pattern-tei-infra
sudo install -m 644 /tmp/pattern-tei-infra/docker-compose.yml /etc/pattern-tei-infra/
sed "s/^User=graemer$/User=${USER}/" /tmp/pattern-tei-infra/pattern-tei-infra.service \
  | sudo tee /etc/systemd/system/pattern-tei-infra.service > /dev/null
sudo chmod 644 /etc/systemd/system/pattern-tei-infra.service
sudo systemctl daemon-reload
sudo systemctl enable --now pattern-tei-infra.service

# Verify: both containers must report "healthy" (cold start up to ~2 min).
docker inspect -f '{{.Name}} {{.State.Health.Status}}' pattern-tei-embed pattern-tei-rerank
```

Note: this stack is shared with the sibling `agent-pattern-mcp` server. If it
is already installed and running on the host, skip B0 entirely.

### B1 — MCP image under the local name the unit checks

```bash
VERSION=$(grep -m 1 '^version' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')
docker pull "olkowa/architecture-pattern-mcp:${VERSION}"
docker tag "olkowa/architecture-pattern-mcp:${VERSION}" architecture-pattern-mcp:latest
```

(`architecture-pattern-mcp.service` runs `ExecStartPre=docker image inspect
architecture-pattern-mcp:latest` — the retag is what makes that pass.)

### B2 — configuration files under `/etc/architecture-pattern-mcp/`

```bash
sudo install -d /etc/architecture-pattern-mcp/config
sudo install -m 644 systemd/docker-compose.yml /etc/architecture-pattern-mcp/
# The repo config is the canonical template ({env:VAR:-default} expansion;
# compose-provided env vars override it).
sudo install -m 644 config/config.json /etc/architecture-pattern-mcp/config/

# .env — read by the unit (EnvironmentFile) and by compose interpolation.
# root:docker 640: the service runs as a non-root docker-group user, which
# must be able to read the file; the docker group is effectively privileged.
sudo tee /etc/architecture-pattern-mcp/.env > /dev/null <<EOF
MINIMAXAI_API_KEY=sk-REPLACE-ME
COMPOSE_PROJECT_NAME=apmcp-systemd
MCP_HOST_PORT=8050
EOF
sudo chown root:docker /etc/architecture-pattern-mcp/.env
sudo chmod 640 /etc/architecture-pattern-mcp/.env
```

### B3 — install and enable the unit

```bash
sed "s/^User=graemer$/User=${USER}/" systemd/architecture-pattern-mcp.service \
  | sudo tee /etc/systemd/system/architecture-pattern-mcp.service > /dev/null
sudo chmod 644 /etc/systemd/system/architecture-pattern-mcp.service
sudo systemctl daemon-reload
sudo systemctl enable --now architecture-pattern-mcp.service
```

### B4 — verify

```bash
systemctl is-active architecture-pattern-mcp                          # "active" (Type=oneshot → active (exited) is correct)
docker inspect -f '{{.State.Health.Status}}' architecture-pattern-mcp # "healthy" (≤ ~40 s after start)
curl -s -o /dev/null -w '%{http_code}\n' -X POST "http://localhost:8050/mcp" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"probe","version":"0.0.0"}},"id":1}'   # 200
docker exec architecture-pattern-mcp python -c "import urllib.request; print(urllib.request.urlopen('http://pattern-tei-embed:8080/health').status)"  # 200 = TEI reachable
```

Installed endpoint: `http://localhost:8050/mcp` (streamable-http).

### B5 — day-2 operations

```bash
sudo systemctl stop     architecture-pattern-mcp   # compose down
sudo systemctl start    architecture-pattern-mcp   # compose up -d
sudo systemctl reload   architecture-pattern-mcp   # recreate containers after editing
                                                 # /etc/architecture-pattern-mcp/ compose or .env
# Update to a newer release: re-run B1 pull+retag, then
sudo systemctl reload architecture-pattern-mcp
# Logs
journalctl -u architecture-pattern-mcp -n 50
docker compose -p apmcp-systemd -f /etc/architecture-pattern-mcp/docker-compose.yml logs -f
```

## Switching the generator LLM

Both compose files hardcode the MiniMax generator env block. To use another
LiteLLM provider, edit the four `GENERATOR_*` lines in the installed compose
file — Path A: `docker/docker-compose.yml`; Path B:
`/etc/architecture-pattern-mcp/docker-compose.yml` — e.g. for OpenAI:

```yaml
      - GENERATOR_PROVIDER=openai
      - GENERATOR_MODEL=openai/gpt-4o-mini      # LiteLLM syntax: provider/model
      - GENERATOR_BASE_URL=https://api.openai.com/v1
      - GENERATOR_API_KEY=${OPENAI_API_KEY}
```

then put `OPENAI_API_KEY=sk-...` in the env file (`docker/.env` resp.
`/etc/architecture-pattern-mcp/.env`) and restart (A: `down` + `up -d`;
B: `sudo systemctl restart architecture-pattern-mcp`). Full provider list:
[LiteLLM providers](https://docs.litellm.ai/docs/providers).

## Troubleshooting

| Symptom | Cause → fix |
|---|---|
| `GET /health` returns 404 | Expected — FastMCP streamable-http exposes no GET /health. Probe `POST /mcp` (A6/B4). |
| `docker image inspect architecture-pattern-mcp:latest` failed (unit start) | B1 retag step missed or used a different tag. |
| `network pattern-tei-shared not found` | TEI infra not running: `sudo systemctl start pattern-tei-infra.service`. |
| MCP container unhealthy; logs show TEI connection errors | TEI still cold-starting (start_period 120 s) — recheck health after ~2 min; if persistent, verify B0. |
| Container healthy but design tool calls fail with 401/502 | Generator API key wrong/missing in the env file, or provider env block mismatched — see generator section. |
| Unit fails reading environment file | `/etc/architecture-pattern-mcp/.env` missing or unreadable: recreate per B2 (`root:docker 640`, user in `docker` group). |
| `start request repeated too quickly` | Earlier start failed; inspect `journalctl -u architecture-pattern-mcp -n 50`, fix, then `systemctl reset-failed architecture-pattern-mcp` and start again. |
| Image pull fails for `${VERSION}`/`${TEI_VERSION}` | Tag not published; check tags endpoints (A1 comment) and use `latest`. |

## Uninstall

```bash
# Path B
sudo systemctl disable --now architecture-pattern-mcp.service
sudo rm /etc/systemd/system/architecture-pattern-mcp.service
sudo rm -rf /etc/architecture-pattern-mcp
# TEI infra — ONLY if no other pattern MCP server on this host uses it
# (stop MCP stacks first: removing it breaks their TEI connectivity)
sudo systemctl disable --now pattern-tei-infra.service
sudo rm /etc/systemd/system/pattern-tei-infra.service
sudo rm -rf /etc/pattern-tei-infra
docker network rm pattern-tei-shared 2>/dev/null || true
sudo systemctl daemon-reload

# Path A
docker compose --env-file docker/.env -f docker/docker-compose.yml down
rm docker/.env
```
