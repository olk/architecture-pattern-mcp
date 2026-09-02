# syntax=docker/dockerfile:1.7

# =============================================================================
# FR-273: containerized deployment via Docker
# ADR-5:  multi-stage build for slim production image
# TECH-7: non-root user (mcpuser) for production; health check endpoint
# IC-41:  hatchling as build backend
# IC-42:  python -m src.main entry point
#
# Changes vs prior version:
#   - Reranking moved to a TEI sidecar; torch / sentence-transformers removed
#     from this image entirely (~8 GB saving).
#   - uv binary copied from the official distroless image instead of pip-installed.
#   - Layer ownership via COPY --chown avoids the extra chown -R layer that
#     duplicated the multi-GB venv in the filesystem.
#   - uv sync uses --no-install-project (project is never installed; runtime
#     uses PYTHONPATH=/app/src).
# =============================================================================

# ---- Build stage ------------------------------------------------------------
FROM python:3.12-slim-bookworm AS build

# Copy uv binary from the official distroless image (~50 MB, no Python layer).
# Pin to a stable tag; replace 0.7.0 with the current stable at release time.
COPY --from=ghcr.io/astral-sh/uv:0.7.0 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first — layer caching: edit pyproject.toml / uv.lock without
# reinstalling everything.
COPY pyproject.toml uv.lock ./

# Install ONLY dependencies.  The project itself is never installed; runtime
# uses PYTHONPATH=/app/src.  --no-install-project also avoids hatchling
# attempting to build a wheel before src/ is copied.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Source + pattern assets — copied after deps so a src/ edit does not bust
# the dependency cache layer.
COPY src/ ./src/
COPY ./pattern/*.json ./pattern/
COPY ../config/config.json ./config/config.json

# ---- Reasoning MCPs build stage ---------------------------------------------
# Plan v5: bakes the shannonthinking and code-reasoning MCP servers into the
# image so ReasoningClient invokes them directly via node (no runtime npx
# fetch). Version pins verified on npm 2026-08-31; override via --build-arg.
# Entry-point existence is asserted here so a wrong dist path fails the BUILD
# loudly (test -f works for global modules; require.resolve does not).
FROM node:20-bookworm-slim AS build-mcps

ARG SHANNON_NPM_PKG=server-shannon-thinking@0.1.1
ARG CODE_REASONING_NPM_PKG=@mettamatt/code-reasoning@0.8.1

RUN --mount=type=cache,target=/root/.npm \
    npm install -g --omit=dev "${SHANNON_NPM_PKG}" "${CODE_REASONING_NPM_PKG}" && \
    test -f /usr/local/lib/node_modules/server-shannon-thinking/dist/index.js && \
    test -f /usr/local/lib/node_modules/@mettamatt/code-reasoning/dist/index.js

# ---- Production stage ------------------------------------------------------
FROM python:3.12-slim-bookworm AS production

# Non-root user (TECH-7)
RUN groupadd --gid 1000 mcpgroup && \
    useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home mcpuser

WORKDIR /app

# Runtime shared libraries for the node binary (~5 MB) — node itself is
# copied from build-mcps below, guaranteeing version parity with the
# packages installed there (no apt nodejs / Debian-Node-18 mismatch).
RUN apt-get update && \
    apt-get install -y --no-install-recommends libstdc++6 ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# --chown creates files owned by mcpuser in a single filesystem operation.
# Unlike a separate `RUN chown -R`, this does NOT duplicate the multi-GB venv
# into an extra image layer.
COPY --from=build --chown=1000:1000 /app/.venv /app/.venv
COPY --from=build --chown=1000:1000 /app/src ./src
COPY --from=build --chown=1000:1000 /app/pyproject.toml ./
COPY --from=build --chown=1000:1000 /app/pattern ./pattern
COPY --from=build --chown=1000:1000 /app/config ./config

# Embedded reasoning MCP packages (Plan v5): node binary from the same
# image the packages were installed under, plus the global node_modules
# tree. Entry points are invoked by absolute path — no NODE_PATH needed.
COPY --from=build-mcps /usr/local/bin/node /usr/local/bin/node
COPY --from=build-mcps --chown=1000:1000 /usr/local/lib/node_modules /usr/local/lib/node_modules

# Build-time contract: node runs and both reasoning entry points exist.
RUN node --version && \
    test -f /usr/local/lib/node_modules/server-shannon-thinking/dist/index.js && \
    test -f /usr/local/lib/node_modules/@mettamatt/code-reasoning/dist/index.js && \
    echo "Reasoning MCPs embedded: shannon + code-reasoning"

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CONFIG_PATH=/app/config/config.json

USER 1000:1000

# HEALTHCHECK: verifies the app responds on port 8050 (not 8000 as older
# comments stated).
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8050/health')" || exit 1

# IC-42: python -m src.main for running the MCP server
CMD ["/app/.venv/bin/python", "-m", "src.main"]

LABEL org.opencontainers.image.title="architecture-pattern-mcp" \
      org.opencontainers.image.description="MCP server providing architecture pattern expertise with embedded structured reasoning" \
      org.opencontainers.image.version="1.0.19" \
      org.opencontainers.image.authors="Oliver Kowalke" \
      org.opencontainers.image.source="https://github.com/olk/architecture-pattern-mcp" \
      org.opencontainers.image.licenses="MIT" \
      io.architecture-pattern-mcp.reasoning-mcps="shannon,code-reasoning"
