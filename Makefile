# =============================================================================
# Makefile for architecture-pattern-mcp
# =============================================================================
# Task ID: TASK-24
# Feature: mcp
# Version: 0.1.0
# Status: in_progress
#
# Build automation targets for MCP server implementation
# Uses uv pip install for dependency management as specified in implementation_guidance
#
# Docker files: docker/Dockerfile, docker/docker-compose.yml
# =============================================================================

.PHONY: help install lint lint-fix typecheck integration-tests client docker-build docker-build-all docker-publish docker-up docker-down docker-logs docker-logs-follow docker-verify docker-rm

DOCKER_IMAGE := architecture-pattern-mcp
DOCKER_TAG := 1.0.1
DOCKER_HUB_REPO := olkowa/architecture-pattern-mcp

help:
	@echo "Available targets:"
	@echo "  install            - Install package in editable mode (MAKE-1)"
	@echo "  lint               - Run ruff check (MAKE-4)"
	@echo "  lint-fix           - Auto-fix linting issues"
	@echo "  typecheck          - Run pyright for type checking"
	@echo "  docker-test        - Run unit tests in Docker container (MAKE-6)"
	@echo "  integration-tests  - Run integration tests (tests/integration/)"
	@echo "  client             - Run the pipes-and-filters MCP client demo"
	@echo "  docker-build       - Build MCP server Docker image (MAKE-5)"
	@echo "  docker-build-all   - Build all Docker images (MCP server + TEI embedder)"
	@echo "  docker-publish    - Push MCP server image to Docker Hub (version + latest)"
	@echo "  docker-up          - Start services with docker compose (MAKE-9)"
	@echo "  docker-down        - Stop services with docker compose (MAKE-10)"
	@echo "  docker-logs        - Show docker compose logs (MAKE-11)"
	@echo "  docker-logs-follow - Show and follow docker compose logs (MAKE-11a)"
	@echo "  docker-verify      - Verify MCP server responds to proper client requests (MAKE-12)"
	@echo "  docker-rm          - Remove Docker image (MAKE-13)"

# MAKE-1: Install package in editable mode
install:
	uv sync --extra dev

# MAKE-4: Lint source code
lint:
	uv run ruff check .

lint-fix: install ## Auto-fix linting issues
	uv run ruff check --fix .
	uv run ruff format .

typecheck: install ## MAKE-5: Run pyright for type checking
	uv run pyright

integration-tests: install ## Run integration tests via pytest
	uv run pytest tests/integration/ -v

client: ## Run the pipes-and-filters MCP client demo
	@ARCHITECTURE_CLIENT_URL=http://localhost:8050/mcp uv run python examples/architecture_client.py

##@ Docker
docker-build: ## MAKE-3b: Build MCP server Docker image with dev dependencies
	docker build --target production -f docker/Dockerfile -t $(DOCKER_IMAGE):$(DOCKER_TAG) .
	docker build --target production -f docker/Dockerfile -t $(DOCKER_IMAGE):latest .

docker-build-all: docker-build ## Build all Docker images (MCP server + TEI embedder)
	docker build -f docker/Dockerfile.tei -t architecture-pattern-tei:local .

docker-publish: docker-build ## Push MCP server image to Docker Hub ($(DOCKER_TAG) + latest)
	docker tag $(DOCKER_IMAGE):$(DOCKER_TAG) $(DOCKER_HUB_REPO):$(DOCKER_TAG)
	docker tag $(DOCKER_IMAGE):latest $(DOCKER_HUB_REPO):latest
	docker push $(DOCKER_HUB_REPO):$(DOCKER_TAG)
	docker push $(DOCKER_HUB_REPO):latest

docker-up: ## MAKE-9: Start services with docker compose
	docker compose -f docker/docker-compose.yml up -d --build

docker-down: ## MAKE-10: Stop services with docker compose
	docker compose -f docker/docker-compose.yml down

docker-logs: ## MAKE-11: Show docker compose logs (one-time)
	docker compose -f docker/docker-compose.yml logs

docker-logs-follow: ## MAKE-11a: Show and follow docker compose logs
	docker compose -f docker/docker-compose.yml logs -f

docker-test: ## MAKE-6: Run unit tests in Docker container
	docker build --target test -f docker/Dockerfile -t $(DOCKER_IMAGE):test .
	docker run --rm $(DOCKER_IMAGE):test bash -c 'cd /app && /app/.venv/bin/pytest tests/unit/ -v'

# MAKE-12: Verify running MCP server responds to proper MCP client requests
# Tests against http://localhost:8050 (host network, see docker-compose.yml network_mode: host)
# Requires server to be running: make docker-up
docker-verify: ## Verify MCP server responds to proper MCP client requests (MAKE-12)
	@echo "=== Test 1: POST initialize (MCP client handshake) ==="
	@curl -sS -X POST http://localhost:8050/mcp \
	  -H "Content-Type: application/json" \
	  -H "Accept: application/json, text/event-stream" \
	  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"verify-client","version":"1.0"}}}'
	@echo ""
	@echo "=== Test 2: GET SSE stream (3s timeout) ==="
	@timeout 3 curl -sN -H "Accept: text/event-stream" http://localhost:8050/mcp || true
	@echo ""
	@echo "=== Test 3: Browser-style request (expect HTTP 406) ==="
	@echo "Browsers send Accept: text/html - the server correctly rejects this per MCP spec."
	@curl -sS -o /dev/null -w "HTTP %{http_code}\n" -H "Accept: text/html" http://localhost:8050/mcp

docker-rm: ## MAKE-13: Remove Docker image
	docker rmi $(DOCKER_IMAGE):$(DOCKER_TAG)
