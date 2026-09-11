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

.PHONY: help install install-mcps \
	check-lint check-static-typing check-deadcode check-depcheck check-all \
	test-unit test-oracles test-mutations test-all \
	verify-fizz verify-fizz-simulation \
	verify-nagini \
	verify-ledger verify-cross-consistency verify-all \
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
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

install: ## Sync dependencies into .venv (dev group included by default)
	$(UV) sync

install-mcps: ## Install reasoning MCP servers globally (local dev; Docker embeds them at build time)
	npm install -g server-shannon-thinking@0.1.1 @mettamatt/code-reasoning@0.8.1

##@ Quality
check-lint: ## Run ruff check
	$(UV) run ruff check .

# mypy strict check on src/. --strict is redundant with [tool.mypy] strict=true —
# kept explicit so the gate survives future config edits.
check-static-typing: install ## Run mypy --strict static type check on src/
	$(UV) run mypy --strict

# Decorators that register callables with a framework (llama-index Workflow,
# pydantic validation, FastMCP resources/prompts): the decorated symbol is
# live even without a static call site. Keep in sync with whitelist.py.
VULTURE_IGNORE_DECORATORS := "@step,@field_validator,@model_validator,@*.resource,@*.prompt"

check-deadcode: ## Run vulture dead-code scan on src/ and examples/
	$(UV) run vulture src examples whitelist.py --min-confidence 80 \
		--ignore-decorators $(VULTURE_IGNORE_DECORATORS)

check-depcheck: ## Run deptry dependency-hygiene scan
	$(UV) run deptry .

# Side-effect-free gate aggregator — auto-fix/format targets must never join:
# a gate must not mutate the working tree. (lint-fix was removed; run
# `uv run ruff check --fix .` / `uv run ruff format .` directly when wanted.)
# Steps echo a banner and run strictly sequentially, fail-fast by cost.
check-all: ## Run every check-* gate (CI entry point)
	@echo "==> [1/4] check-lint";          $(MAKE) --no-print-directory check-lint
	@echo "==> [2/4] check-static-typing"; $(MAKE) --no-print-directory check-static-typing
	@echo "==> [3/4] check-deadcode";      $(MAKE) --no-print-directory check-deadcode
	@echo "==> [4/4] check-depcheck";      $(MAKE) --no-print-directory check-depcheck

##@ Tests
test-unit: install ## Run unit tests with uv (tests/unit/)
	$(UV) run pytest tests/unit/ -v

test-oracles: install ## Run executable oracles (tests/verification/): L1 canary, L2 PBT oracles, trace replay
	$(UV) run pytest tests/verification/ -v

# Hypothesis isolation: the gate re-runs the same tests under many executors;
# a per-run database keeps the shared repo database free of foreign executors
# (the normal suite's differing_executors health check stays meaningful).
MUTMUT_HYPO_DIR := $(shell mktemp -d)
test-mutations: ## L3: mutmut over Tier A/B/C + gardens (manual/nightly; ephemeral install via uv)
	HYPOTHESIS_STORAGE_DIRECTORY=$(MUTMUT_HYPO_DIR) $(UV) run --with mutmut python -c "import verify.mutmut.mutmut_compat as compat; compat.apply(); from mutmut.__main__ import cli; raise SystemExit(cli())" run
	$(UV) run --with mutmut mutmut results
	rm -rf $(MUTMUT_HYPO_DIR)

# Fast-path aggregator: unit + oracles only. test-mutations is deliberately
# outside — mutmut is a manual/nightly gate (ephemeral toolchain, long runtime).
test-all: ## Run the fast test gates (PR-time; test-mutations is nightly-only)
	@echo "==> [1/2] test-unit";    $(MAKE) --no-print-directory test-unit
	@echo "==> [2/2] test-oracles"; $(MAKE) --no-print-directory test-oracles

# fizz v0.5.3 exits 0 even on invariant failure (only panics exit non-zero),
# so `|| exit 1` alone is a vacuous gate — every run must also print the
# PASSED line. Both conditions are checked per spec.
FIZZ ?= fizz
SPEC_DIR := verify/fizz
FIZZ_PASS := ^PASSED: Model checker completed successfully

verify-fizz: ## L4: exhaustive FizzBee model checks over verify/fizz/
	@if ! command -v $(FIZZ) >/dev/null 2>&1; then \
		echo "fizz binary not found: brew install fizzbee, or set FIZZ=scripts/fizz-docker.sh"; exit 1; \
	else \
		set -e; for spec in $(SPEC_DIR)/*.fizz; do \
			echo ">> $$(date +%H:%M:%S) exhaustive check: $$spec"; \
			out=`$(FIZZ) "$$spec" 2>&1`; st=$$?; \
			printf '%s\n' "$$out"; \
			if [ $$st -ne 0 ] || ! printf '%s\n' "$$out" | grep -q "$(FIZZ_PASS)"; then \
				echo "verify-fizz: FAILED: $$spec (exit $$st)"; exit 1; \
			fi; \
		done; \
		echo "verify-fizz: all specs green (exhaustive, bounds per fizz.yaml)"; \
	fi

verify-fizz-simulation: ## L4: seeded parallel FizzBee simulation (nightly relief valve)
	@if ! command -v $(FIZZ) >/dev/null 2>&1; then \
		echo "fizz binary not found: brew install fizzbee, or set FIZZ=scripts/fizz-docker.sh"; exit 1; \
	else \
		set -e; seed=$$(date +%s); workers=$$(nproc); \
		echo ">> seeded simulation seed=$$seed workers=$$workers"; \
		for spec in $(SPEC_DIR)/*.fizz; do \
			echo ">> $$(date +%H:%M:%S) simulation: $$spec"; \
			out=`$(FIZZ) -x --seed $$seed --parallel $$workers "$$spec" 2>&1`; st=$$?; \
			printf '%s\n' "$$out"; \
			if [ $$st -ne 0 ] || printf '%s\n' "$$out" | grep -q '^FAILED'; then \
				echo "verify-fizz-simulation: FAILED: $$spec (exit $$st)"; exit 1; \
			fi; \
		done; \
	fi

NAGINI_FILES := $(shell $(UV) run python scripts/verify_coverage.py --files 2>/dev/null)
NAGINI_VERIFY_FILES := $(shell $(UV) run python scripts/verify_coverage.py --verify-files 2>/dev/null)

# The nagini CLI pins mypy==1.5.0 and cannot share the dev env, so L5 runs
# from a dedicated venv (.venv-nagini, provisioned on first use). Requires a
# JVM for the Viper backend. The Nagini MCP server tools (nagini_verify_file)
# remain the interactive/agent-facing way to run the same checks.
NAGINI_VENV := .venv-nagini
NAGINI := $(NAGINI_VENV)/bin/nagini

$(NAGINI):
	$(UV) venv --python 3.12 $(NAGINI_VENV)
	$(UV) pip install --python $(NAGINI_VENV)/bin/python nagini==1.3.1

verify-nagini: $(NAGINI) ## L5: Nagini deductive verification over the annotated cores
	@failed=0; 	for f in $(NAGINI_VERIFY_FILES); do 		echo "==> verify-nagini: $$f"; 		$(NAGINI) $$f || failed=1; 	done; 	if [ $$failed -ne 0 ]; then 		echo "verify-nagini: FAILED"; exit 1; 	fi; 	echo "verify-nagini: all files verified"

verify-ledger: ## L8: property-ID ledger consistency (verify/fizz/README.md <-> artifacts)
	@$(UV) run python scripts/verify_ledger.py

# Advisory NL-Doc cross-consistency gate (mechanical subset; the LLM
# comparison activates via ARCH_CONSISTENCY_MODEL, checker identity pinned
# per run — E3). Findings are leads to triage, not failures.
verify-cross-consistency: ## L8: NL-Doc/docstring consistency over NAGINI_FILES (advisory)
	@$(UV) run python scripts/cross_consistency.py

# Nightly aggregator over the formal/audit verify-* targets. verify-nagini
# provisions its own venv; verify-fizz/verify-fizz-simulation self-skip when
# their toolchain is missing — safe on toolchain-less boxes. test-oracles is
# a test-*, not a verify-*.
verify-all: ## Run every verify-* target (nightly entry point)
	@echo "==> [1/5] verify-fizz";              $(MAKE) --no-print-directory verify-fizz
	@echo "==> [2/5] verify-fizz-simulation";   $(MAKE) --no-print-directory verify-fizz-simulation
	@echo "==> [3/5] verify-nagini";            $(MAKE) --no-print-directory verify-nagini
	@echo "==> [4/5] verify-ledger";            $(MAKE) --no-print-directory verify-ledger
	@echo "==> [5/5] verify-cross-consistency"; $(MAKE) --no-print-directory verify-cross-consistency

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

docker-build-all: ## Build all Docker images
	@echo "==> [1/2] docker-build (MCP server)"; $(MAKE) --no-print-directory docker-build
	@echo "==> [2/2] docker-build-tei";          $(MAKE) --no-print-directory docker-build-tei

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
