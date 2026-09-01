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

.PHONY: help install install-mcps lint lint-fix typecheck deadcode depcheck unit-tests \
	client docker-build docker-build-tei \
	docker-build-all docker-publish docker-publish-tei \
	docker-publish-all \
	docker-up docker-down docker-logs docker-logs-follow \
	docker-rm clean

COMPOSE := docker compose -f docker/docker-compose.yml
UV ?= uv

DOCKER_IMAGE    := architecture-pattern-mcp
DOCKER_TAG      := $(shell grep -m 1 '^version' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')
DOCKER_HUB_REPO := olkowa/architecture-pattern-mcp
GHCR_REPO       := ghcr.io/olk/architecture-pattern-mcp

TEI_EMBED_IMAGE      := pattern-tei-embed
TEI_RERANK_IMAGE     := pattern-tei-rerank
TEI_EMBED_HUB_REPO   := olkowa/pattern-tei-embed
TEI_EMBED_GHCR_REPO  := ghcr.io/olk/pattern-tei-embed
TEI_RERANK_HUB_REPO  := olkowa/pattern-tei-rerank
TEI_RERANK_GHCR_REPO := ghcr.io/olk/pattern-tei-rerank

.DEFAULT_GOAL := help

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

install: ## Sync dependencies into .venv (dev group included by default)
	$(UV) sync

install-mcps: ## Install reasoning MCP servers globally (local dev; Docker embeds them at build time)
	npm install -g server-shannon-thinking@0.1.1 @mettamatt/code-reasoning@0.8.1

##@ Quality
lint: ## Run ruff check
	$(UV) run ruff check .

lint-fix: install ## Auto-fix linting issues
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

typecheck: install ## Run pyright for type checking
	$(UV) run pyright

# Decorators that register callables with a framework (llama-index Workflow,
# pydantic validation, FastMCP resources/prompts): the decorated symbol is
# live even without a static call site. Keep in sync with whitelist.py.
VULTURE_IGNORE_DECORATORS := "@step,@field_validator,@model_validator,@*.resource,@*.prompt"

deadcode: ## Run vulture dead-code scan on src/ and examples/
	$(UV) run vulture src examples whitelist.py --min-confidence 80 \
		--ignore-decorators $(VULTURE_IGNORE_DECORATORS)

depcheck: ## Run deptry dependency-hygiene scan
	$(UV) run deptry .

##@ Tests
unit-tests: install ## Run unit tests with uv (tests/unit/)
	$(UV) run pytest tests/unit/ -v

##@ Demo
client: ## Run the pipes-and-filters MCP client demo (synchronous design_architecture)
	@ARCHITECTURE_CLIENT_URL=http://localhost:8060/mcp uv run python examples/architecture_client.py

client-async: ## Run the async job trio demo (submit_architecture_design_job + get_architecture_design_status)
	@ARCHITECTURE_CLIENT_URL=http://localhost:8060/mcp uv run python examples/architecture_client_async.py

##@ Docker
docker-build: ## Build MCP server Docker image with dev dependencies
	docker build --target production -f docker/Dockerfile -t $(DOCKER_IMAGE):$(DOCKER_TAG) .
	docker build --target production -f docker/Dockerfile -t $(DOCKER_IMAGE):latest .

docker-build-tei: ## Build both TEI images (embedder + reranker)
	docker build -f docker/Dockerfile.tei-embed \
		-t $(TEI_EMBED_IMAGE):$(DOCKER_TAG) \
		-t $(TEI_EMBED_IMAGE):latest .
	docker build -f docker/Dockerfile.tei-rerank \
		-t $(TEI_RERANK_IMAGE):$(DOCKER_TAG) \
		-t $(TEI_RERANK_IMAGE):latest .

docker-build-all: docker-build docker-build-tei ## Build all Docker images

# Tag and push a local image to both Docker Hub and GHCR.
# Args: local_image hub_repo ghcr_repo
# Usage: $(call publish-image,$(DOCKER_IMAGE),$(DOCKER_HUB_REPO),$(GHCR_REPO))
publish-image = \
	docker tag $(1):$(DOCKER_TAG) $(2):$(DOCKER_TAG) && \
	docker tag $(1):latest $(2):latest && \
	docker tag $(1):$(DOCKER_TAG) $(3):$(DOCKER_TAG) && \
	docker tag $(1):latest $(3):latest && \
	docker push $(2):$(DOCKER_TAG) && \
	docker push $(2):latest && \
	docker push $(3):$(DOCKER_TAG) && \
	docker push $(3):latest

docker-publish: docker-build ## Push MCP server image to Docker Hub + GHCR + git tag v$(DOCKER_TAG)
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "ERROR: uncommitted changes - commit before publishing:"; \
		git status --short; exit 1; \
	fi
	docker login ghcr.io -u olk
	$(call publish-image,$(DOCKER_IMAGE),$(DOCKER_HUB_REPO),$(GHCR_REPO))
	@echo "MCP image published. Logging out of ghcr.io."
	docker logout ghcr.io
	@if git rev-parse -q --verify "refs/tags/v$(DOCKER_TAG)" >/dev/null; then \
		echo "git tag v$(DOCKER_TAG) already exists - skipping creation"; \
	else \
		echo "Creating annotated git tag v$(DOCKER_TAG)"; \
		git tag -a "v$(DOCKER_TAG)" -m "Release v$(DOCKER_TAG)"; \
	fi
	git push origin "v$(DOCKER_TAG)"

docker-publish-tei: docker-build-tei ## Push both TEI images to Docker Hub + GHCR
	docker login ghcr.io -u olk
	$(call publish-image,$(TEI_EMBED_IMAGE),$(TEI_EMBED_HUB_REPO),$(TEI_EMBED_GHCR_REPO))
	$(call publish-image,$(TEI_RERANK_IMAGE),$(TEI_RERANK_HUB_REPO),$(TEI_RERANK_GHCR_REPO))
	docker logout ghcr.io

docker-publish-all: docker-publish docker-publish-tei ## Build and push all three images

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
