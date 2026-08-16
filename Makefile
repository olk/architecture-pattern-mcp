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

.PHONY: help install lint lint-fix typecheck unit-tests \
	client docker-build docker-build-all docker-publish \
	docker-up docker-down docker-logs docker-logs-follow \
	docker-rm clean

COMPOSE := docker compose -f docker/docker-compose.yml
UV ?= uv

DOCKER_IMAGE    := architecture-pattern-mcp
DOCKER_TAG      := $(shell grep -m 1 '^version' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')
DOCKER_HUB_REPO := olkowa/architecture-pattern-mcp
GHCR_REPO       := ghcr.io/olk/architecture-pattern-mcp

.DEFAULT_GOAL := help

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

install: ## Sync dependencies into .venv (dev group included by default)
	$(UV) sync

##@ Quality
lint: ## Run ruff check
	$(UV) run ruff check .

lint-fix: install ## Auto-fix linting issues
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

typecheck: install ## Run pyright for type checking
	$(UV) run pyright

##@ Tests
unit-tests: install ## Run unit tests with uv (tests/unit/)
	$(UV) run pytest tests/unit/ -v

##@ Demo
client: ## Run the pipes-and-filters MCP client demo
	@ARCHITECTURE_CLIENT_URL=http://localhost:8050/mcp uv run python examples/architecture_client.py

##@ Docker
docker-build: ## Build MCP server Docker image with dev dependencies
	docker build --target production -f docker/Dockerfile -t $(DOCKER_IMAGE):$(DOCKER_TAG) .
	docker build --target production -f docker/Dockerfile -t $(DOCKER_IMAGE):latest .

docker-build-all: docker-build ## Build all Docker images (MCP server + TEI embedder)
	docker build -f docker/Dockerfile.tei -t architecture-pattern-tei:local .

docker-publish: docker-build ## Push MCP server image to Docker Hub + GHCR + git tag v$(DOCKER_TAG)
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "ERROR: uncommitted changes - commit before publishing:"; \
		git status --short; exit 1; \
	fi
	docker login ghcr.io -u olk
	docker tag $(DOCKER_IMAGE):$(DOCKER_TAG) $(DOCKER_HUB_REPO):$(DOCKER_TAG)
	docker tag $(DOCKER_IMAGE):latest $(DOCKER_HUB_REPO):latest
	docker tag $(DOCKER_IMAGE):$(DOCKER_TAG) $(GHCR_REPO):$(DOCKER_TAG)
	docker tag $(DOCKER_IMAGE):latest $(GHCR_REPO):latest
	docker push $(DOCKER_HUB_REPO):$(DOCKER_TAG)
	docker push $(DOCKER_HUB_REPO):latest
	docker push $(GHCR_REPO):$(DOCKER_TAG)
	docker push $(GHCR_REPO):latest
	@echo "Publishing complete. Logging out of ghcr.io."
	docker logout ghcr.io
	@if git rev-parse -q --verify "refs/tags/v$(DOCKER_TAG)" >/dev/null; then \
		echo "git tag v$(DOCKER_TAG) already exists - skipping creation"; \
	else \
		echo "Creating annotated git tag v$(DOCKER_TAG)"; \
		git tag -a "v$(DOCKER_TAG)" -m "Release v$(DOCKER_TAG)"; \
	fi
	git push origin "v$(DOCKER_TAG)"

docker-up: ## Start services with docker compose
	$(COMPOSE) up -d --build

docker-down: ## Stop services with docker compose
	$(COMPOSE) down

docker-logs: ## Show docker compose logs (one-time)
	$(COMPOSE) logs architecture-pattern-mcp

docker-logs-follow: ## Show and follow docker compose logs
	$(COMPOSE) logs -f

docker-rm: ## Remove Docker image
	docker rmi $(DOCKER_IMAGE):$(DOCKER_TAG)

##@ Maintenance
clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache dist build
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
