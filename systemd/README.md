# systemd integration

This directory contains the systemd unit that starts the
**architecture-pattern-mcp** Docker Compose stack on boot.

## File layout

This directory ships **two compose files** with different purposes:

| File | Purpose |
|---|---|
| `docker/docker-compose.yml` (repo root) | **Development**. Has `build:` sections, uses `${HOME}` for the config volume, designed for `make docker-up` / `make docker-down`. |
| `systemd/docker-compose.yml` (this dir) | **Production / systemd**. No `build:` (images must be pre-built), uses absolute paths, designed for `systemctl enable`. |

Both describe the **MCP server** but differ in TEI handling: the systemd
stack reaches TEI via the shared `pattern-tei-shared` external network (sidecars
owned by `pattern-tei-infra`), while the dev stack runs its own TEI sidecars
with unique container names. Don't edit one expecting the other to pick up
the change.

## Prerequisites

- systemd-based Linux host (Arch, Debian, Ubuntu, Fedora, …).
- Docker Engine with the Compose plugin (`docker compose version`).
- `graemer` is in the `docker` group.
- Network access at boot.
- **Both images pre-built locally** (see Step 0 below).
- **Shared TEI infra stack installed and enabled** — see
  [`pattern-tei-infra/README.md`](https://github.com/olk/pattern-tei-infra/README.md).
  The systemd MCP stack joins the `pattern-tei-shared` external network to reach
  the embedder/reranker; `pattern-tei-infra.service` must be active first.

## Step 0 — Pre-flight: build or pull the images

The systemd service runs `docker compose up -d` against **pre-built images**.
The unit has `ExecStartPre` checks that fail loudly if the MCP image is missing,
so you must either build or pull it first. TEI images are managed by the
`pattern-tei-infra` stack — build them from either repo:

**Option A — Build from source** *(requires ~10 GB disk, ~5 GB download on first run)*:
```bash
# From the repo root:
make docker-build-all
# Produces: architecture-pattern-mcp:latest, pattern-tei-embed:latest,
#           pattern-tei-rerank:latest
# TEI images are consumed by pattern-tei-infra, not this stack.
```

**Option B — Pull published images** *(skip the 5 GB local build; retag to :local so the
`ExecStartPre` guard still passes)*:
```bash
VERSION=$(grep -m 1 '^version' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')
for image in olkowa/architecture-pattern-mcp \
            olkowa/pattern-tei-embed \
            olkowa/pattern-tei-rerank; do
    docker pull "${image}:${VERSION}"
    docker tag "${image}:${VERSION}" "${image##*/}:local"
done
```

If you re-pull the repo later, rerun the same pull+tag commands to refresh images.

## Step 1 — Coexist with the dev compose

The systemd-managed project is given a distinct name (`apmcp-systemd`, set via
`COMPOSE_PROJECT_NAME` in the `.env` file). The dev compose uses unique TEI
container names (`architecture-pattern-tei*`) and a different host port (8060 vs
8050). Both stacks can now run **concurrently** — no need to stop one before
starting the other:

```bash
make docker-up                                  # dev on :8060
sudo systemctl start architecture-pattern-mcp  # prod on :8050
```

## Step 2 — Install

```bash
# 0. Install + enable shared TEI infra (once — see ${HOME}/pattern-tei-infra/)
sudo install -m 644 ${HOME}/pattern-tei-infra/pattern-tei-infra.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pattern-tei-infra.service

# 1. Create the deployment directory tree.
sudo install -d /etc/architecture-pattern-mcp/config

# 2. Copy the production compose file.
sudo install -m 644 systemd/docker-compose.yml /etc/architecture-pattern-mcp/

# 3. Copy the application config from your existing user config.
sudo install -m 644 ~/.config/architecture-pattern-mcp/config.json \
                /etc/architecture-pattern-mcp/config/

# 4. Create the secret + project-name file (root:docker 640) and edit it.
#     640 root:docker — not 600 root:root — so the systemd service
#     running as User=graemer (a member of the `docker` group) can read this
#     file when docker compose auto-loads it.  The `docker` group is
#     effectively privileged; this is the standard trade-off for non-root
#     systemd services that manage Docker containers.
sudo install -o root -g docker -m 640 /dev/null /etc/architecture-pattern-mcp/.env
sudo $EDITOR /etc/architecture-pattern-mcp/.env
# File contents:
#   MINIMAXAI_API_KEY=sk-...
#   COMPOSE_PROJECT_NAME=apmcp-systemd
#   MCP_HOST_PORT=8050          # change to avoid port conflicts with other MCP servers

# 5. Install the unit file.
sudo install -m 644 systemd/architecture-pattern-mcp.service \
                /etc/systemd/system/

# 6. Reload systemd, enable, and start.
sudo systemctl daemon-reload
sudo systemctl enable --now architecture-pattern-mcp.service
```

The `.env` file lives **inside** `/etc/architecture-pattern-mcp/` alongside the
compose file, keeping the entire deployment self-contained.

### Generator LLM configuration

The generator LLM inside the container is accessed via the **LlamaIndex
LiteLLM** integration and follows **LiteLLM's model syntax**:
`<provider>/<model>` (e.g. `openai/gpt-4o-mini`). It is configured through
`config/config.json` (step 3 above) or the `GENERATOR_PROVIDER`,
`GENERATOR_MODEL`, `GENERATOR_BASE_URL`, and `GENERATOR_API_KEY` settings —
the API key in the `.env` file (step 4) must match the provider you configure.
For the full list of providers and model names see the
[LiteLLM Providers documentation](https://docs.litellm.ai/docs/providers) and
the main README's
[Generator LLM section](../README.md#generator-llm-llamaindex-litellm).

## Step 3 — Verify

`systemctl status` reports `active (exited)` within seconds of boot, but the
MCP container takes **up to ~40 s** to become healthy (`start_period: 40s`);
TEI readiness is owned by `pattern-tei-infra` (`start_period: 120s` there).
The unit does **not** wait for healthchecks.

```bash
systemctl status architecture-pattern-mcp                          # service state
journalctl -u architecture-pattern-mcp -n 50                     # last 50 log lines
docker compose -p apmcp-systemd -f /etc/architecture-pattern-mcp/docker-compose.yml ps
curl -fsS http://localhost:${MCP_HOST_PORT:-8050}/health         # MCP HTTP health
```

## Day-to-day commands

```bash
sudo systemctl start architecture-pattern-mcp       # start
sudo systemctl stop architecture-pattern-mcp        # stop (compose down)
sudo systemctl restart architecture-pattern-mcp     # stop + start
sudo systemctl reload architecture-pattern-mcp      # recreate containers to pick up
                                                     # compose / env file edits
journalctl -u architecture-pattern-mcp -n 200     # recent logs
docker compose -p apmcp-systemd -f /etc/architecture-pattern-mcp/docker-compose.yml logs -f
```

`restart` stops the stack (SIGTERM, 10 s grace, then SIGKILL via `compose down`)
and brings it back up. `reload` is lighter: it recreates changed containers in
place and is the right tool after editing the compose file or the `.env` file.

## Updating the stack (new code → new containers)

```bash
# 1. Rebuild images in the repo.
make docker-build-all

# 2. Recreate containers without full stop/start.
sudo systemctl reload architecture-pattern-mcp
```

## Restart policy

Container restart policies live in `systemd/docker-compose.yml`
(`on-failure` for the MCP server). TEI restart policies live in the
`pattern-tei-infra` stack. The systemd unit deliberately does **not** set
`Restart=`, so we don't double-manage the stack: containers own their
in-run restarts, the unit only manages the stack's presence at boot.

## Uninstall

```bash
sudo systemctl disable --now architecture-pattern-mcp.service
sudo rm /etc/systemd/system/architecture-pattern-mcp.service
sudo systemctl daemon-reload
sudo rm -rf /etc/architecture-pattern-mcp
```

## Troubleshooting

- **`start request repeated too quickly`** / **`docker image inspect` failed** →
  images aren't built locally. Run `make docker-build-all` from the repo.
- **`Failed to load environment file`** → `/etc/architecture-pattern-mcp/.env`
  is missing or unreadable. Recreate with `sudo install -m 600 …`.
- **`active (exited)` but `docker compose ps` shows `Exit`/`Restarting`** → a
  container is crash-looping. Check `docker compose -p apmcp-systemd logs <svc>`.
- **`active (exited)` but no containers** → `docker compose up -d` failed;
  check `journalctl -u architecture-pattern-mcp`.
- **MCP server can't reach TEI at boot** → wait ~2 min for TEI's
  `start_period` to elapse, or check TEI health with `docker compose ps`.
- **`network pattern-tei-shared not found`** → the shared TEI infra stack isn't
  running. Start it first: `sudo systemctl start pattern-tei-infra`.

## Files

- `architecture-pattern-mcp.service` — the systemd unit.
- `docker-compose.yml` — production Compose (installed to `/etc/architecture-pattern-mcp/`).
- `README.md` — this file.
