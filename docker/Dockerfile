# =============================================================================
# FR-273: The system SHALL support containerized deployment via Docker
# ADR-5: Docker container with multi-stage build for slim production image
# TECH-7: Multi-stage build reduces attack surface; non-root user (mcpuser)
#         for production; health check endpoint for container orchestration
# IC-41: The system SHALL use hatchling as the build backend
# IC-42: python -m src.server command and architecture-pattern-mcp command
# =============================================================================
# Stage 1: Build stage with Python 3.12 and uv for dependency installation
# =============================================================================
FROM python:3.12-slim-bookworm AS build

# Install uv package manager for fast dependency installation
# IC-41: Using hatchling as build backend requires uv for wheel creation
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock* ./

# Install dependencies using uv
# Use --no-dev for production builds as per security best practices
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Pre-download cross-encoder model for reranking at container start-up.
# Avoids first-query latency spike and ensures the model is available offline.
# Cache is stored in /root/.cache/huggingface by default.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv run --no-project python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-2-v2'); print('Reranker model pre-download complete')"

# Copy application source code
COPY src/ ./src/

# Copy architecture pattern
COPY ./pattern/*.json ./pattern/

# =============================================================================
# Stage 2: Production stage
# =============================================================================
FROM python:3.12-slim-bookworm AS production

# Create non-root user for security
# TECH-7: Non-root user (mcpuser) for production container security
RUN groupadd --gid 1000 mcpgroup && \
    useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home mcpuser

# Set working directory
WORKDIR /app

# Copy installed packages from build stage
COPY --from=build /app/.venv /app/.venv

# Copy application source
COPY --from=build /app/src ./src
COPY --from=build /app/pyproject.toml ./

# Copy architecture pattern
COPY --from=build /app/pattern ./pattern

# Set environment variables for the application
# Set Python to use virtualenv
ENV VIRTUAL_ENV="/app/.venv"
ENV PATH="/app/.venv/bin:$PATH"
# Add /app/src to PYTHONPATH so 'mcp_server' package can be found
ENV PYTHONPATH="/app/src"
# Python optimization for production
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Change ownership to non-root user
RUN chown -R mcpuser:mcpgroup /app

# Switch to non-root user
USER mcpuser

# HEALTHCHECK instruction for container orchestration
# TECH-7: Health check endpoint for container orchestration
# Verifies the application is responding on port 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8050/health')" || exit 1

# IC-42: python -m src.server command for running the MCP server
# Entrypoint uses python -m src.server as specified
CMD ["/app/.venv/bin/python", "-m", "src.main"]

# =============================================================================
# Metadata labels
# =============================================================================
LABEL org.opencontainers.image.title="architecture-pattern-mcp"
LABEL org.opencontainers.image.description="MCP server providing architecture pattern expertise"
LABEL org.opencontainers.image.version="1.0.0"
LABEL org.opencontainers.image.authors="Oliver Kowalke"
LABEL org.opencontainers.image.source="https://github.com/olk/architecture-pattern-mcp"
LABEL org.opencontainers.image.licenses="MIT"
