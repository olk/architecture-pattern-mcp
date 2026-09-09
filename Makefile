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

.PHONY: help install install-mcps lint lint-fix typecheck static-typing deadcode depcheck unit-tests \
	verify-hypothesis-oracles mutation-tests verify-fizz verify-fizz-simulation \
	verify-nagini verify-coverage verify-import-inventory verify-deps-audit \
	verify-ledger verify-cross-consistency \
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

# mypy strict check on src/. --strict is redundant with [tool.mypy] strict=true —
# kept explicit so the gate survives future config edits.
static-typing: install ## Run mypy --strict static type check on src/
	$(UV) run mypy --strict

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

verify-hypothesis-oracles: install ## Run executable oracles (tests/verification/): L1 canary, L2 PBT oracles, trace replay
	$(UV) run pytest tests/verification/ -v

mutation-tests: ## L3: mutmut over Tier A/B/C + gardens (manual/nightly; ephemeral install via uv)
	$(UV) run --with mutmut mutmut run
	$(UV) run --with mutmut mutmut results

FIZZ ?= fizz
SPEC_DIR := specs/fizz

# Opt-in locally via RUN_VERIFY=1 (same pattern as verify-nagini); CI always
# sets it. Without RUN_VERIFY the targets are a no-op so an environment
# without the fizz binary can never break the standard gate set.
verify-fizz: ## L4: exhaustive FizzBee model checks over specs/fizz/ (RUN_VERIFY=1)
	@if [ -z "$(RUN_VERIFY)" ]; then \
		echo "verify-fizz: opt-in via RUN_VERIFY=1 (CI sets it unconditionally)"; exit 0; fi
	@if ! command -v $(FIZZ) >/dev/null 2>&1; then \
		echo "fizz binary not found: brew install fizzbee, or set FIZZ=scripts/fizz-docker.sh"; exit 1; fi
	@set -e; for spec in $(SPEC_DIR)/*.fizz; do \
		echo ">> $$(date +%H:%M:%S) exhaustive check: $$spec"; \
		$(FIZZ) "$$spec" || exit 1; \
	done
	@echo "verify-fizz: all specs green (exhaustive, bounds per fizz.yaml)"

verify-fizz-simulation: ## L4: seeded parallel FizzBee simulation (nightly relief valve)
	@if [ -z "$(RUN_VERIFY)" ]; then \
		echo "verify-fizz-simulation: opt-in via RUN_VERIFY=1"; exit 0; fi
	@if ! command -v $(FIZZ) >/dev/null 2>&1; then \
		echo "fizz binary not found: brew install fizzbee, or set FIZZ=scripts/fizz-docker.sh"; exit 1; fi
	@set -e; seed=$$(date +%s); workers=$$(nproc); \
	echo ">> seeded simulation seed=$$seed workers=$$workers"; \
	for spec in $(SPEC_DIR)/*.fizz; do \
		$(FIZZ) -x --seed $$seed --parallel $$workers "$$spec" || exit 1; \
	done

NAGINI_FILES := $(shell $(UV) run python scripts/verify_coverage.py --files 2>/dev/null)

# Opt-in via RUN_VERIFY=1 (nagini plan §3.9): CI sets it unconditionally; a
# local environment without Java can never break the standard gate set — but
# a pushed branch can never skip verification either.
verify-nagini: ## L5: Nagini deductive verification over NAGINI_FILES (RUN_VERIFY=1)
	@if [ -z "$(RUN_VERIFY)" ]; then \
		echo "verify-nagini: opt-in via RUN_VERIFY=1 (CI sets it unconditionally)"; exit 0; fi
	@if ! command -v nagini >/dev/null 2>&1; then \
		echo "nagini not found: pip install \"nagini[mcp,lsp,server]>=1.3.1\" (Java 11+ required; \$$JAVA_HOME set)"; exit 1; fi
	@set -e; for f in $(NAGINI_FILES); do \
		echo ">> nagini --counterexample $$f"; \
		nagini --counterexample $$f || exit 1; \
	done
	@echo "verify-nagini: all NAGINI_FILES verified"

verify-coverage: ## L5: contract-coverage report over NAGINI_FILES
	@$(UV) run python scripts/verify_coverage.py

IMPORT_SNAPSHOT := tests/verification/snapshots/import_inventory.txt

verify-ledger: ## L8: property-ID ledger consistency (specs/fizz/README.md <-> artifacts)
	@$(UV) run python scripts/verify_ledger.py

# Advisory NL-Doc cross-consistency gate (mechanical subset; the LLM
# comparison activates via ARCH_CONSISTENCY_MODEL, checker identity pinned
# per run — E3). STRICT=1 enforces the >10% divergence promotion trigger.
verify-cross-consistency: ## L8: NL-Doc/docstring consistency over NAGINI_FILES (advisory)
	@$(UV) run python scripts/cross_consistency.py $(if $(STRICT),--strict,)

verify-import-inventory: ## L7: third-party import inventory drift check (slopsquatting defence)
	@$(UV) run python scripts/import_inventory.py --check $(IMPORT_SNAPSHOT)

# Advisory vulnerability scan (pip-audit over the project environment).
# Not part of the standard gate set; promotes per testing-strategies §4.4.
verify-deps-audit: ## L7: pip-audit vulnerability scan (advisory; STRICT=1 to enforce)
	@if $(UV) run python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pip_audit') else 1)"; then \
		$(UV) run python -m pip_audit --progress-spinner off --desc off || [ -n "$(STRICT)" ] && exit $$?; \
	else \
		echo "pip-audit not installed — advisory skip (strict run: STRICT=1 $(UV) run --with pip-audit python -m pip_audit)"; \
		[ -z "$(STRICT)" ] || { $(UV) run --with pip-audit python -m pip_audit --progress-spinner off --desc off; exit $$?; } ; \
	fi

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
