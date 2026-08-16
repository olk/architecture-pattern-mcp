# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
ArchitecturePipeline - LlamaIndex Workflow-backed pipeline coordinator.

FR-214: Patterns SHALL flow through the pipeline with ANALYZE, GENERATE, EVALUATE, REFINE phases
DP-1: Pipeline Pattern - Coordinate multi-step workflow via typed events and @step
DP-5: Dependency Injection - ArchitecturePipeline receives SoftwareArchitectAgent, PatternLoader,
       DomainVectorIndex via constructor
DP-6: Observer Pattern REPLACED by Workflow's handler.stream_events() — add_observer
      remove_observer and _emit_event are removed; use WorkflowHandler.stream_events() instead.

Event flow:
  StartEvent(requirements, domain, style, evaluate_criteria)
      │
      ▼  @step _orchestrate
  StopEvent(result=PipelineResult)

  Internal routing (_orchestrate calls these directly as async methods, not via events):
      _analyze  → AnalysisDoneEvent (used internally)
      _generate → DesignGeneratedEvent
      _evaluate → EvaluationDoneEvent
      _refine  → loops via RefineNextEvent until done → StopEvent
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from workflows import Context, Workflow, step
from workflows.events import StartEvent, StopEvent

from src.agent import SoftwareArchitectAgent
from src.config import RetrievalConfig
from src.design_normalization import denormalize_contracts
from src.errors import ERROR_INVALID_ARCHITECTURE, MalformedArchitectureOverviewError
from src.patterns.bm25_index import DomainBM25Index
from src.patterns.loader import PatternLoader
from src.patterns.retriever import DEFAULT_FALLBACK_PATTERN_NAME, HybridPatternRetriever
from src.patterns.vector_index import DomainVectorIndex
from src.prompts import (
    ARCHITECTURE_DESIGN_EXAMPLE,
    ARCHITECTURE_EVALUATION_EXAMPLE,
)
from src.schemas.architecture import ArchitectureDesignResponse, ArchitectureDesignResponseWire
from src.schemas.components import Component, Relationship
from src.schemas.contracts import (
    ApiContract,
    DataModel,
    EventContract,
)

from src.schemas.design import ArchitectureDesign
from src.schemas.evaluation import (
    ArchitectureEvaluation,
    PipelineResult,
)
from src.schemas.patterns import Pattern
from src.schemas.quality import QualityMetrics

logger = logging.getLogger(__name__)


def _phase_extra(phase: str, domain: str, duration_s: float) -> dict[str, Any]:
    """Build a fresh dict per call to avoid mutating a shared one across log calls."""
    extra: dict[str, Any] = {"phase": phase, "duration_s": duration_s}
    if domain:
        extra["domain"] = domain
    return extra


@asynccontextmanager
async def _timed_phase(phase: str, domain: str = "", *, verbose: bool = False):
    """Async context manager that logs phase start/end with wall-clock duration.

    When DEBUG is disabled AND verbose is False, the timer machinery is skipped
    entirely so the instrumentation does not impose steady-state overhead.
    This is essential because the GENERATE-phase hot path passes through these
    blocks per attempt. Set verbose=True to emit INFO-level logs without
    changing the global logging level.
    """
    if not verbose and not logger.isEnabledFor(logging.DEBUG):
        yield
        return

    log_level = logging.INFO if verbose else logging.DEBUG
    start = time.monotonic()
    logger.log(log_level, f"Phase '{phase}' started", extra=_phase_extra(phase, domain, 0.0))
    try:
        yield
    finally:
        duration_s = round(time.monotonic() - start, 2)
        logger.log(log_level, f"Phase '{phase}' completed",
                   extra=_phase_extra(phase, domain, duration_s))


# ──────────────────────────────────────────────────────────────────────────────
# Internal Pydantic models for pipeline data (dict-based, LLM-compatible)
# These replace the original dataclasses while preserving dict-based field types
# for LLM-friendly JSON manipulation.
# ──────────────────────────────────────────────────────────────────────────────


class AnalysisResult(BaseModel):
    """
    Result of architecture requirements analysis (ANALYZE phase).

    Mirrors the original dataclass fields with identical names and defaults.
    Uses dict-based fields for selected_patterns to match LLM JSON output.
    """

    model_config = ConfigDict(extra="allow")

    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    quality_metrics: QualityMetrics | None = Field(default=None)
    recommended_style: str = Field(default="")
    selected_patterns: list[dict[str, Any]] = Field(default_factory=list)


# Canonical quality-attribute keys present in every pattern's quality_attributes.
# Verified uniform across the 35-pattern catalogue. Used for deterministic
# requirements-aware scoring of candidates in the analyze phase.
QUALITY_ATTRIBUTE_KEYS: tuple[str, ...] = (
    "scalability",
    "maintainability",
    "reliability",
    "security",
    "performance",
    "simplicity",
)


class RequirementWeights(BaseModel):
    """Requirement priority weights (0.0-1.0) extracted from requirements.

    Produced by a single lightweight LLM call in the analyze phase. Each weight
    expresses how strongly the requirements emphasise that quality attribute.
    Consumed by ``_score_patterns`` to deterministically score each candidate
    pattern's ``quality_attributes`` against the stated priorities.

    The LLM prompt carries ONLY the requirements and these six attribute names —
    no pattern data — keeping the call small and focused.
    """

    model_config = ConfigDict(extra="allow")

    scalability: float = Field(default=0.0, ge=0.0, le=1.0)
    maintainability: float = Field(default=0.0, ge=0.0, le=1.0)
    reliability: float = Field(default=0.0, ge=0.0, le=1.0)
    security: float = Field(default=0.0, ge=0.0, le=1.0)
    performance: float = Field(default=0.0, ge=0.0, le=1.0)
    simplicity: float = Field(default=0.0, ge=0.0, le=1.0)

    def as_dict(self) -> dict[str, float]:
        """Return the weights keyed by quality-attribute name."""
        return {k: float(getattr(self, k)) for k in QUALITY_ATTRIBUTE_KEYS}


@lru_cache(maxsize=16)
def _generate_system_prompt_cached(style: str) -> str:
    """Build the GENERATE-phase system prompt, cached by ``style``.

    The prompt body is purely a function of ``style`` — the ``_patterns``
    argument formerly passed into the class method is unused. Module-level
    caching makes the function cheap to call on every design_loop retry.
    """
    return f"""You are an expert software architect specializing in {style} architecture.

**ENUM CONSTRAINTS (CRITICAL - violations cause automatic retry):**
- `overview.category` MUST be exactly one of: messaging, structural, cloud, data,
  ai_cognitive, specialized, api_gateway, coordination, dataflow, presentation
- `overview.style` MUST be exactly one of: actor-based, aiml-centric, api-gateway,
  backend-for-frontend, blockchain-based, broker, command-query-responsibility-segregation,
  data-mesh, edge-computing, enterprise-service-bus, event-driven, event-sourcing,
  half-sync-half-async, hexagonal, hybrid-cloud, kappa-architecture, lambda-architecture,
  layered-monolith, microkernel-plugin, microservices, model-view-controller,
  modular-monolith, monolithic, multi-cloud, pipe-and-filter,
  presentation-abstraction-control, reactive-architecture, reflection-architecture,
  rule-based-system, saga, serverless, service-mesh, service-oriented-architecture,
  space-based, task-control-architecture

**EXAMPLE valid overview:**
```json
{{
  "style": "pipe-and-filter",
  "category": "dataflow",
  "principles": ["Single Responsibility", "Statelessness"],
  "constraints": ["10k events/sec throughput"]
}}
```

Do NOT use ArchitectureDomain values (e.g. "stream-processing", "etl", "data-processing")
for overview.category or overview.style — those are problem-space domain tags, not
pattern categories or architectural styles.

Your task is to design a comprehensive architecture based on the provided requirements and patterns.

Consider the following when designing:
1. Pattern context, benefits, and tradeoffs
2. Best practices from successful implementations
3. Quality attributes trade-offs
4. Component relationships and interactions
5. Deployment and operational concerns

Generate an architecture design that:
- Follows the principles of the selected patterns
- Addresses the requirements effectively
- Balances quality attributes appropriately
- Includes appropriate component decomposition
- Specifies technology choices justified by the patterns
    6. Contracts when applicable (suggestive, not mandatory):
   - If your design exposes HTTP APIs, include a top-level entry per API
     under api_contracts (component_id, base_path, endpoints).
   - If the same data entity is reused by multiple components, list it
     under shared_data_models with is_shared=true.
   - When defining component-level data_models, mark cross-component
     entities with is_shared=true — they will be auto-promoted to
     top-level shared_data_models by denormalize_contracts.
   - If components communicate asynchronously, define events under
     event_contracts (event_name, payload_schema, published_by,
     consumed_by).
   For architectures where these are not meaningful (e.g. a single-
   process layered monolith), leaving these lists empty is acceptable.

{ARCHITECTURE_DESIGN_EXAMPLE}
    """


# ──────────────────────────────────────────────────────────────────────────────
# ArchitecturePipeline (Workflow-backed)
# ──────────────────────────────────────────────────────────────────────────────

class ArchitecturePipeline(Workflow):
    """
    LlamaIndex Workflow-backed pipeline coordinator.

    FR-214: Patterns SHALL flow through the pipeline with ANALYZE, GENERATE, EVALUATE phases and a bounded design_loop for retries

    DP-1: Pipeline Pattern - Coordinates pattern loading, domain search, LLM generation
          through sequential phases driven by _orchestrate step.
    DP-5: Dependency Injection - Receives SoftwareArchitectAgent, PatternLoader,
          DomainVectorIndex via constructor.
    DP-6 (REMOVED): add_observer / remove_observer / _emit_event replaced by
          WorkflowHandler.stream_events() consumed externally.

    Attributes:
        _agent: SoftwareArchitectAgent instance for LLM interactions
        _pattern_loader: PatternLoader instance for pattern management
        _vector_index: DomainVectorIndex instance for domain similarity search
        _bm25_index: DomainBM25Index instance for lexical search
        _retrieval_config: RetrievalConfig for hybrid fusion tuning

    Public method signatures are unchanged (async where they already were) so that
    existing tool callers do not need to change their call sites.
    """

    DEFAULT_MAX_TRIES: int = 3
    PATTERN_CONTEXT_CACHE_MAX: int = 32

    def __init__(
        self,
        agent: SoftwareArchitectAgent,
        pattern_loader: PatternLoader,
        vector_index: DomainVectorIndex,
        bm25_index: DomainBM25Index,
        retrieval_config: RetrievalConfig | None = None,
    ) -> None:
        """
        Initialize ArchitecturePipeline with injected dependencies.

        DP-5: Dependency Injection - Constructor injection of all dependencies

        Args:
            agent: SoftwareArchitectAgent instance for LLM interactions
            pattern_loader: PatternLoader instance for pattern management
            vector_index: DomainVectorIndex instance for domain similarity search
            bm25_index: DomainBM25Index instance for lexical domain search
            retrieval_config: Retrieval tuning parameters (defaults to RetrievalConfig())
        """
        super().__init__(timeout=1200)
        self._agent = agent
        self._pattern_loader = pattern_loader
        self._vector_index = vector_index
        self._bm25_index = bm25_index
        self._retrieval_config = retrieval_config or RetrievalConfig()
        self._pattern_context_cache: OrderedDict[tuple, str] = OrderedDict()
        self._pattern_context_cache_max: int = self.PATTERN_CONTEXT_CACHE_MAX

        logger.debug(
            "ArchitecturePipeline initialized",
            extra={
                "agent_type": type(agent).__name__,
                "pattern_loader_loaded": pattern_loader._loaded,
                "retrieval_config": self._retrieval_config.model_dump(),
            }
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Public entry points (mirrors original API for tool compatibility)
    # ──────────────────────────────────────────────────────────────────────────

    async def run_design(
        self,
        requirements: str,
        domain: str,
        style: str | None = None,
        evaluate_criteria: str | None = None,
    ) -> PipelineResult:
        """
        Execute the full pipeline via the Workflow engine.

        FR-214: Patterns SHALL flow through the pipeline with
                ANALYZE, GENERATE, EVALUATE, REFINE phases.

        Args:
            requirements: Requirements string
            domain: Domain string
            style: Optional architecture style hint
            evaluate_criteria: Optional evaluation criteria

        Returns:
            PipelineResult after all phases complete
        """
        handler = super().run(
            requirements=requirements,
            domain=domain,
            style=style,
            evaluate_criteria=evaluate_criteria,
        )
        return await handler

    async def analyze(
        self,
        requirements: str,
        domain: str,
        style: str | None = None,
    ) -> AnalysisResult:
        """
        ANALYZE phase: Filter patterns by domain using HybridPatternRetriever,
        then derive analysis via LLM.

        FR-214: Patterns flow through ANALYZE (filters by domain)
        FR-189: filter_by_domain method filters patterns by domain suitability

        IC-31: Domain normalization (lowercase, hyphens, no spaces)

        Args:
            requirements: Requirements string for analysis
            domain: Domain string to filter patterns by
            style: Optional architecture style hint

        Returns:
            AnalysisResult with selected patterns, quality metrics, strengths,
            weaknesses, recommendations, and recommended_style
        """
        async with _timed_phase("analyze", domain=domain,
                               verbose=self._retrieval_config.verbose_timing):
            normalized_domain = domain.lower().replace(" ", "-")

            if not self._vector_index.is_built or not self._bm25_index.is_built:
                self._build_vector_index()

            retriever = HybridPatternRetriever(
                bm25_index=self._bm25_index,
                vector_index=self._vector_index,
                pattern_loader=self._pattern_loader,
                bm25_top_k=self._retrieval_config.bm25_top_k,
                dense_top_k=self._retrieval_config.dense_top_k,
                mode=self._retrieval_config.mode,
                min_fusion_score=self._retrieval_config.min_fusion_score,
                enable_reranking=self._retrieval_config.enable_reranking,
                rerank_top_n=self._retrieval_config.rerank_top_n,
                reranker_config=self._retrieval_config.reranker.config
                if self._retrieval_config.reranker
                else None,
            )

            # ── Stage 1 (recall): all candidate patterns + fusion scores ──
            # No top-K truncation here; selection happens AFTER scoring.
            # Issue #14: retriever is sync (CPU + HTTP for embedding); running
            # it on the event loop would stall concurrent MCP requests.
            recalled = await asyncio.to_thread(
                retriever.retrieve,
                user_domain=domain,
                normalized_domain=normalized_domain,
            )
            candidates: list[dict[str, Any]] = []
            has_real_candidate = False
            for pattern_dict, fusion_score in recalled:
                p = dict(pattern_dict)
                p["fusion_score"] = float(fusion_score)
                if not p.get("is_fallback"):
                    has_real_candidate = True
                candidates.append(p)
            # Issue #16: exclude fallback from scored candidates unless the
            # fallback is the only candidate (defence in depth alongside
            # issue #3's gate→0.0 fix).
            if has_real_candidate:
                candidates = [c for c in candidates if not c.get("is_fallback")]

            # ── Stage 2a (extract priorities): one lightweight LLM call ──
            # The prompt carries ONLY requirements + the 6 attribute names;
            # no pattern data is sent, keeping the call small and focused.
            weights = await self._extract_requirement_weights(requirements, domain)

            # ── Stage 2b (deterministic score): requirements-aware ranking ──
            scored = self._score_patterns(candidates, weights)

            # ── Selection: top_k_patterns AFTER scoring ──
            top_k = self._retrieval_config.top_k_patterns
            selected = scored[:top_k]

            quality_metrics = self._calculate_quality_metrics(selected)
            recommended_style = self._select_recommended_style(selected, style)

            logger.info(
                "Analyze scored %d patterns for domain '%s' (recommended_style=%s, top_k=%d)",
                len(selected),
                domain,
                recommended_style,
                top_k,
                extra={
                    "phase": "analyze",
                    "stage": "scored",
                    "domain": domain,
                    "recommended_style": recommended_style,
                    "requirement_weights": weights.as_dict(),
                    "patterns": [
                        {
                            "style": p.get("name"),
                            "analysis_score": p.get("analysis_score"),
                            "fusion_score": p.get("fusion_score"),
                            "fusion_score_normalized": p.get("fusion_score_normalized"),
                            "blended_score": p.get("blended_score"),
                        }
                        for p in selected
                    ],
                },
            )

            # Narrative from deterministic heuristics (LLM call stays focused
            # on weight extraction — Option B).
            return AnalysisResult(
                selected_patterns=selected,
                quality_metrics=quality_metrics,
                recommended_style=recommended_style,
                strengths=self._analyze_strengths(selected),
                weaknesses=self._analyze_weaknesses(selected),
                recommendations=self._generate_recommendations(selected),
            )

    async def generate(
        self,
        requirements: str,
        domain: str,
        style: str,
        selected_patterns: list[dict],
        analysis_result: AnalysisResult | None = None,
        override_user_prompt: str | None = None,
    ) -> ArchitectureDesign:
        """
        GENERATE phase: Include pattern metadata in LLM context via SoftwareArchitectAgent.

        FR-214: Patterns flow through GENERATE (includes pattern metadata in LLM context)

        The LLM prompt includes pattern context, benefits, tradeoffs, suitable_domains,
        quality_attributes, best_practices, and other pattern metadata.

        Args:
            requirements: Requirements string
            domain: Domain string
            style: Architecture style
            selected_patterns: List of patterns to include in context
            analysis_result: Optional analysis result for additional context
            override_user_prompt: If set, bypasses prompt construction and uses this directly

        Returns:
            ArchitectureDesign with components, relationships, and deployment strategy
        """
        async with _timed_phase("generate", domain=domain,
                               verbose=self._retrieval_config.verbose_timing):
            if override_user_prompt:
                user_prompt = override_user_prompt
                system_prompt = self._build_generate_system_prompt(style, selected_patterns)
            else:
                pattern_context = self._build_pattern_context(selected_patterns)
                system_prompt = self._build_generate_system_prompt(style, selected_patterns)
                user_prompt = self._build_generate_user_prompt(
                    requirements, domain, style, pattern_context, analysis_result
                )

            use_lean = self._retrieval_config.use_lean_wire_schema
            response_schema = ArchitectureDesignResponseWire if use_lean else ArchitectureDesignResponse
            design_response = await self._agent.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_schema=response_schema,
            )

            # For lean schema, default omitted fields to empty lists
            if use_lean:
                wire = cast(ArchitectureDesignResponseWire, design_response)
                api_contracts: list[Any] = []
                shared_data_models: list[Any] = []
                event_contracts: list[Any] = []
            else:
                full = cast(ArchitectureDesignResponse, design_response)
                api_contracts = [
                    ApiContract.model_validate(c) if isinstance(c, dict) else c
                    for c in full.api_contracts
                ]
                shared_data_models = [
                    DataModel.model_validate(d) if isinstance(d, dict) else d
                    for d in full.shared_data_models
                ]
                event_contracts = [
                    EventContract.model_validate(e) if isinstance(e, dict) else e
                    for e in full.event_contracts
                ]
                wire = full

            try:
                design = ArchitectureDesign(
                    overview=wire.overview,
                    components=[Component.model_validate(c) if isinstance(c, dict) else c for c in wire.components],
                    relationships=[Relationship.model_validate(r) if isinstance(r, dict) else r for r in wire.relationships],
                    quality_attributes=dict(wire.quality_attributes),
                    api_contracts=api_contracts,
                    shared_data_models=shared_data_models,
                    event_contracts=event_contracts,
                )
            except ValidationError as exc:
                errors = exc.errors()
                locator = ".".join(str(l) for l in errors[0]["loc"]) if errors else "unknown"
                logger.warning(
                    "ArchitectureDesign construction failed validation",
                    extra={"errors": exc.errors(include_url=False)},
                )
                raise MalformedArchitectureOverviewError(
                    code=ERROR_INVALID_ARCHITECTURE,
                    locator=locator,
                    errors=errors,
                ) from exc

            return denormalize_contracts(design)

    async def evaluate(
        self,
        architecture: ArchitectureDesign,
        criteria: str,
        domain: str,
        analysis_result: AnalysisResult | None = None,
    ) -> ArchitectureEvaluation:
        """
        EVALUATE phase: Benchmark architecture against quality attributes via LLM.

        FR-214: Patterns flow through EVALUATE (benchmarks against quality attributes)

        Args:
            architecture: ArchitectureDesign to evaluate
            criteria: Evaluation criteria string
            domain: Domain string for context
            analysis_result: Optional prior analysis result

        Returns:
            ArchitectureEvaluation with metrics and recommendations
        """
        async with _timed_phase("evaluate", domain=domain,
                               verbose=self._retrieval_config.verbose_timing):
            patterns: list[Pattern] = []
            if analysis_result is not None and analysis_result.selected_patterns:
                patterns = [
                    Pattern.model_validate(p) if isinstance(p, dict) else p
                    for p in analysis_result.selected_patterns
                ]

            pattern_alignment = self._evaluate_pattern_alignment(
                patterns, criteria
            )

            system_prompt = self._build_evaluate_system_prompt(patterns)
            user_prompt = self._build_evaluate_user_prompt(
                architecture, criteria, domain, patterns
            )

            llm_eval = await self._agent.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_schema=ArchitectureEvaluation,
            )
            llm_eval = cast(ArchitectureEvaluation, llm_eval)

            recs_dict: dict[str, list[str]] = {}
            for rec in self._generate_evaluation_recommendations(architecture, pattern_alignment):
                area = "general"
                recs_dict.setdefault(area, []).append(rec)

            for area, recs in recs_dict.items():
                llm_eval.recommendations.setdefault(area, []).extend(recs)

            return llm_eval

    async def design_loop(
        self,
        requirements: str,
        domain: str,
        style: str,
        selected_patterns: list[dict],
        criteria: str,
        analysis_result: AnalysisResult | None = None,
        max_tries: int = DEFAULT_MAX_TRIES,
        min_quality_score: float = 100.0,
    ) -> PipelineResult:
        """
        Design loop: generate → evaluate → (retry with feedback) × max_tries.

        Returns the best-scoring attempt (highest overall_quality).

        Args:
            requirements: Original requirements string
            domain: Application domain
            style: Architecture style
            selected_patterns: Patterns for context
            criteria: Evaluation criteria string
            analysis_result: Optional prior analysis result
            max_tries: Maximum generate attempts (default 3)
            min_quality_score: Early-stop threshold (default 100.0 = disabled)

        Returns:
            PipelineResult with the best design and its evaluation
        """
        async with _timed_phase("design_loop", domain=domain,
                               verbose=self._retrieval_config.verbose_timing):
            best_design: ArchitectureDesign | None = None
            best_evaluation: ArchitectureEvaluation | None = None
            best_score: float = -1.0
            attempts = 0
            last_error: Exception | None = None

            req_list = [requirements] if isinstance(requirements, str) else list(requirements)

            for attempt in range(1, max_tries + 1):
                attempts += 1
                score_before = best_score
                attempt_start = time.monotonic()
                logger.info(
                    f"Attempt {attempt}/{max_tries} started",
                    extra={"phase": "design_loop", "attempt": attempt, "score_before": score_before}
                )

                try:
                    if attempt == 1 or best_evaluation is None:
                        design = await self.generate(
                            requirements=requirements,
                            domain=domain,
                            style=style,
                            selected_patterns=selected_patterns,
                            analysis_result=analysis_result,
                        )
                    else:
                        assert best_design is not None and best_evaluation is not None
                        feedback_prompt = self._retry_prompt(
                            design=best_design,
                            evaluation=best_evaluation,
                            requirements=req_list,
                            style=style,
                            domain=domain,
                        )
                        design = await self.generate(
                            requirements=requirements,
                            style=style,
                            domain=domain,
                            selected_patterns=selected_patterns,
                            analysis_result=analysis_result,
                            override_user_prompt=feedback_prompt,
                        )

                    evaluation = await self.evaluate(
                        architecture=design,
                        criteria=criteria,
                        domain=domain,
                        analysis_result=analysis_result,
                    )

                    overall_metric = next((m for m in evaluation.metrics if m.name == "overall_quality"), None)
                    if overall_metric is not None:
                        current_score = overall_metric.score  # already 0-100
                    else:
                        current_score = evaluation.summary.overall_score  # already 0-100

                    if current_score > best_score:
                        best_design = design
                        best_evaluation = evaluation
                        best_score = current_score

                    attempt_duration = time.monotonic() - attempt_start
                    logger.info(
                        f"Attempt {attempt}/{max_tries} completed",
                        extra={
                            "phase": "design_loop",
                            "attempt": attempt,
                            "score_before": score_before,
                            "score_after": current_score,
                            "best_score": best_score,
                            "duration_s": round(attempt_duration, 2),
                        }
                    )

                    if current_score >= min_quality_score:
                        logger.info(
                            f"Early stop: score {current_score} >= threshold {min_quality_score}",
                            extra={"phase": "design_loop", "attempt": attempt}
                        )
                        break

                except MalformedArchitectureOverviewError as exc:
                    logger.warning(
                        f"Attempt {attempt} failed with MalformedArchitectureOverviewError",
                        extra={"phase": "design_loop", "attempt": attempt, "error": str(exc)}
                    )
                    last_error = exc
                    continue

            if best_design is None:
                if last_error is not None:
                    raise last_error from None
                raise RuntimeError("design_loop produced no valid design")

            return PipelineResult(
                design=cast(ArchitectureDesign, best_design),
                evaluation=cast(ArchitectureEvaluation, best_evaluation),
                attempts=attempts,
                final_style=best_design.overview.style.value,
                quality_metrics=analysis_result.quality_metrics if analysis_result else None,
                final_quality_score=best_score,  # already 0-100
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Workflow step — orchestrator
    # ──────────────────────────────────────────────────────────────────────────

    @step
    async def _orchestrate(
        self, _ctx: Context, ev: StartEvent
    ) -> StopEvent:
        """
        Orchestrator step: runs ANALYZE → GENERATE → EVALUATE → REFINE and returns.

        This is the single @step entry point. It calls the phase methods directly
        (not via events) to preserve the original sequential semantics while
        still running inside the Workflow engine.

        Args:
            _ctx: Workflow Context (reserved for future extensibility)
            ev: StartEvent carrying design request fields

        Returns:
            StopEvent wrapping PipelineResult
        """
        requirements = ev.get("requirements", "")
        domain = ev.get("domain", "")
        style = ev.get("style")
        evaluate_criteria = ev.get("evaluate_criteria")

        analysis_result = await self.analyze(
            requirements=requirements,
            domain=domain,
            style=style,
        )

        result = await self.design_loop(
            requirements=requirements,
            domain=domain,
            style=style or analysis_result.recommended_style,
            selected_patterns=analysis_result.selected_patterns,
            criteria=evaluate_criteria or "quality,maintainability,scalability",
            analysis_result=analysis_result,
            max_tries=self._retrieval_config.max_tries,
            min_quality_score=self._retrieval_config.min_quality_score,
        )

        return StopEvent(result=result)

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers (unchanged from original)
    # ──────────────────────────────────────────────────────────────────────────

    def _build_vector_index(self) -> None:
        """Build FAISS and BM25 indexes from pattern suitable_domains."""
        all_patterns = self._pattern_loader.load_all()

        domains_seen: set[str] = set()
        all_domains: list[str] = []
        for pattern in all_patterns:
            for domain in pattern.get("suitable_domains", []):
                if domain not in domains_seen:
                    domains_seen.add(domain)
                    all_domains.append(domain)

        if all_domains:
            self._vector_index.build_index(all_domains)
            self._bm25_index.build_index(all_domains)

    def _calculate_quality_metrics(self, patterns: list[dict]) -> QualityMetrics:
        """Calculate aggregate QualityMetrics from patterns."""
        if not patterns:
            return QualityMetrics(
                maintainability=0.0,
                scalability=0.0,
                reliability=0.0,
                security=0.0,
                performance=0.0,
            )

        attrs = ["maintainability", "scalability", "reliability", "security", "performance"]
        totals = dict.fromkeys(attrs, 0.0)

        for pattern in patterns:
            quality_attrs = pattern.get("quality_attributes", {})
            for attr in attrs:
                totals[attr] += quality_attrs.get(attr, 0.0)

        count = len(patterns)
        return QualityMetrics(
            maintainability=totals["maintainability"] / count,
            scalability=totals["scalability"] / count,
            reliability=totals["reliability"] / count,
            security=totals["security"] / count,
            performance=totals["performance"] / count,
        )

    def _analyze_strengths(self, patterns: list[dict]) -> list[str]:
        """Analyze strengths from patterns."""
        strengths = []
        quality_attrs = [
            "scalability",
            "maintainability",
            "reliability",
            "security",
            "performance",
            "simplicity",
        ]

        for attr in quality_attrs:
            total = sum(p.get("quality_attributes", {}).get(attr, 0) for p in patterns)
            avg = total / len(patterns) if patterns else 0
            if avg >= 7:
                strengths.append(f"High {attr} (avg: {avg:.1f}/10)")

        return strengths

    def _analyze_weaknesses(self, patterns: list[dict]) -> list[str]:
        """Analyze weaknesses from patterns."""
        weaknesses = []
        quality_attrs = [
            "scalability",
            "maintainability",
            "reliability",
            "security",
            "performance",
            "simplicity",
        ]

        for attr in quality_attrs:
            total = sum(p.get("quality_attributes", {}).get(attr, 0) for p in patterns)
            avg = total / len(patterns) if patterns else 0
            if avg < 5:
                weaknesses.append(f"Low {attr} (avg: {avg:.1f}/10)")

        return weaknesses

    def _generate_recommendations(self, patterns: list[dict]) -> list[str]:
        """Generate recommendations from patterns."""
        recommendations = []

        for pattern in patterns[:3]:
            name = pattern.get("name", "unknown")
            best_practices = pattern.get("best_practices", [])
            if best_practices:
                recommendations.append(f"Consider {name}: {best_practices[0]}")

        return recommendations

    def _pattern_context_key(self, patterns: list[dict[str, Any]]) -> tuple:
        """Build a content-stable hashable key for the pattern-context cache.

        The key has two parts:
          - patterns_part: a tuple of (name, context) pairs, in input order
          - limits_part:   a sorted-tuple view of pattern_context_limits

        Two equal-content selections produce equal keys (correct hit).
        A mutated or different selection produces a different key (correct miss).
        Including limits_part ensures changed limits invalidate the cache.
        """
        patterns_part = tuple(
            (p.get("name", ""), str(p.get("context", "")))
            for p in patterns
        )
        limits_part = tuple(
            sorted(self._retrieval_config.pattern_context_limits.items())
        )
        return (patterns_part, limits_part)

    def _build_pattern_context(self, patterns: list[dict]) -> str:
        """Build context string from pattern metadata for LLM prompt.

        Tier 1: Slice limits applied to all list fields.
        Tier 2: design_principles and unsuitable_domains dropped entirely.
        Tier 3: component_types and technology_stack deduplicated across patterns.

        Results are memoized by the object id of patterns to avoid rebuilding across
        design_loop retry attempts (selected_patterns is constant within a loop).
        """
        cache_key = self._pattern_context_key(patterns)
        if cache_key in self._pattern_context_cache:
            self._pattern_context_cache.move_to_end(cache_key)
            return self._pattern_context_cache[cache_key]

        limits = self._retrieval_config.pattern_context_limits

        seen_ct: set[str] = set()
        seen_tech: set[str] = set()

        context_parts = []

        for i, pattern in enumerate(patterns, 1):
            name = pattern.get("name", "unknown")
            ctx = pattern.get("context", "No context available")

            benefits = pattern.get("benefits", [])[: limits.get("benefits", float("inf"))]
            tradeoffs = pattern.get("tradeoffs", [])[: limits.get("tradeoffs", float("inf"))]
            best_practices = pattern.get("best_practices", [])[: limits.get("best_practices", float("inf"))]
            suitable_domains = pattern.get("suitable_domains", [])[: limits.get("suitable_domains", float("inf"))]
            anti_patterns = pattern.get("anti_patterns", [])[: limits.get("anti_patterns", float("inf"))]

            ct_limited: list[str] = []
            for ct in pattern.get("component_types", []):
                ct_lower = ct.lower()
                if ct_lower not in seen_ct:
                    seen_ct.add(ct_lower)
                    ct_limited.append(ct)

            tech_limited: list[str] = []
            for t in pattern.get("technology_stack", []):
                t_lower = t.lower()
                if t_lower not in seen_tech:
                    seen_tech.add(t_lower)
                    tech_limited.append(t)

            ct_section = "\n".join(f"  - {ct}" for ct in ct_limited)
            tech_section = "\n".join(f"  - {t}" for t in tech_limited)
            ap_section = "\n".join(f"  - {ap}" for ap in anti_patterns)

            pattern_text = (
                f"Pattern {i}: {name}\n\n"
                f"Context: {ctx}\n\n"
                f"Benefits:\n" + "\n".join(f"  - {b}" for b in benefits) + "\n\n"
                + "Tradeoffs:\n" + "\n".join(f"  - {t}" for t in tradeoffs) + "\n\n"
                + f"Suitable Domains: {', '.join(suitable_domains)}\n\n"
                + "Component Types:\n" + (ct_section or "  (none listed)") + "\n\n"
                + "Technology Stack:\n" + (tech_section or "  (none listed)") + "\n\n"
                + "Best Practices:\n" + "\n".join(f"  - {bp}" for bp in best_practices) + "\n\n"
                + "Anti-Patterns:\n" + (ap_section or "  (none listed)")
            )

            context_parts.append(pattern_text)

        result = "\n\n".join(context_parts)
        self._pattern_context_cache[cache_key] = result
        while len(self._pattern_context_cache) > self._pattern_context_cache_max:
            self._pattern_context_cache.popitem(last=False)
        return result

    def _build_generate_system_prompt(self, style: str, _patterns: list[dict]) -> str:
        """Build system prompt for generate phase.

        .. deprecated::
            The ``_patterns`` parameter is unused and is retained only to keep
            existing call sites compiling. Drop it in the next minor version.
        """
        return _generate_system_prompt_cached(style)

    def _build_generate_user_prompt(
        self,
        requirements: str,
        domain: str,
        style: str,
        pattern_context: str,
        analysis_result: AnalysisResult | None,
    ) -> str:
        """Build user prompt for generate phase."""
        user_prompt = f"""Requirements:
{requirements}

Target Domain: {domain}
Architecture Style: {style}
"""

        if analysis_result:
            user_prompt += f"""
Analysis Summary:
- Recommended Style: {analysis_result.recommended_style}
- Identified Strengths: {", ".join(analysis_result.strengths[:3]) if analysis_result.strengths else "None identified"}
- Identified Weaknesses: {", ".join(analysis_result.weaknesses[:3]) if analysis_result.weaknesses else "None identified"}
"""

        user_prompt += f"""
Selected Patterns:
{pattern_context}

Please generate an architecture design following the schema provided.
"""

        return user_prompt

    def _evaluate_pattern_alignment(
        self,
        patterns: list[Pattern],
        criteria: str,
    ) -> dict[str, float]:
        """Evaluate how well patterns align with evaluation criteria."""
        alignment = {}

        criteria_keywords = criteria.lower().split(",")

        for pattern in patterns:
            name = pattern.name
            context = pattern.context.lower()
            benefits = " ".join(pattern.benefits).lower()

            score = 0.0
            for kw in criteria_keywords:
                stripped = kw.strip()
                if stripped in context or stripped in benefits:
                    score += 1.0

            alignment[name] = min(score / max(len(criteria_keywords), 1) * 100, 100.0)

        return alignment

    def _generate_evaluation_recommendations(
        self,
        architecture: ArchitectureDesign,
        _pattern_alignment: dict[str, float],
    ) -> list[str]:
        """Generate evaluation recommendations."""
        recommendations = []

        if len(architecture.components) > 15:
            recommendations.append(
                "High component count may impact maintainability - consider consolidation"
            )

        return recommendations

    def _add_monitoring_components(self, architecture: ArchitectureDesign) -> None:
        """Add monitoring-related components if not present."""
        from src.schemas.components import Component
        has_monitoring = any(
            "monitoring" in getattr(c, "type", "") or ""
            or "monitoring" in getattr(c, "name", "") or ""
            for c in architecture.components
        )

        if not has_monitoring:
            architecture.components.append(Component(
                id="monitoring",
                name="Monitoring Service",
                type="monitoring",
                description="Centralized monitoring and observability",
                responsibilities=["metrics collection", "log aggregation", "alerting"],
            ))

    def _add_security_components(self, architecture: ArchitectureDesign) -> None:
        """Add security-related components if not present."""
        from src.schemas.components import Component
        has_security = any(
            "security" in getattr(c, "type", "") or ""
            or "auth" in getattr(c, "type", "") or ""
            for c in architecture.components
        )

        if not has_security:
            architecture.components.append(Component(
                id="security",
                name="Security Service",
                type="security",
                description="Authentication and authorization service",
                responsibilities=["authentication", "authorization", "token management"],
            ))

    # ──────────────────────────────────────────────────────────────────────────
    # Stage-2 analyze helpers: weight extraction + deterministic scoring
    # ──────────────────────────────────────────────────────────────────────────

    async def _extract_requirement_weights(
        self, requirements: str, domain: str
    ) -> RequirementWeights:
        """Stage-2a: one lightweight LLM call to extract requirement priorities.

        The prompt carries ONLY the requirements and the six quality-attribute
        names — no pattern data — so the call stays small and focused. The
        returned weights drive the deterministic scoring in ``_score_patterns``.

        Issue #17: if the LLM returns all-zero weights, retry once before
        falling back to unweighted mean — a silent all-zero result is the
        opposite of the commit's intent.
        """
        weights = await self._extract_requirement_weights_once(requirements, domain)
        if sum(weights.as_dict().values()) == 0.0:
            logger.warning(
                "All-zero RequirementWeights from LLM; retrying once...",
                extra={"phase": "analyze", "domain": domain},
            )
            weights = await self._extract_requirement_weights_once(requirements, domain)
            if sum(weights.as_dict().values()) == 0.0:
                logger.warning(
                    "RequirementWeights still all-zero after retry; using unweighted mean",
                    extra={"phase": "analyze", "domain": domain},
                )
        return weights

    async def _extract_requirement_weights_once(
        self, requirements: str, domain: str
    ) -> RequirementWeights:
        """Single LLM call to extract requirement weights (no retry)."""
        system_prompt = self._build_analyze_system_prompt(domain)
        user_prompt = self._build_analyze_user_prompt(requirements, domain)
        llm_result = await self._agent.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=RequirementWeights,
        )
        return self._smooth_weights(cast(RequirementWeights, llm_result))

    def _smooth_weights(self, weights: RequirementWeights) -> RequirementWeights:
        """Apply convex smoothing: w' = alpha*w + (1-alpha)*(1/n).

        Preserves LLM's relative ordering while preventing any attribute from
        being fully zeroed. No-op when alpha=1.0.
        """
        alpha = self._retrieval_config.weight_smoothing_alpha
        if alpha >= 1.0:
            return weights
        n = len(QUALITY_ATTRIBUTE_KEYS)
        uniform = 1.0 / n
        smoothed = {
            attr: round(alpha * float(getattr(weights, attr)) + (1.0 - alpha) * uniform, 4)
            for attr in QUALITY_ATTRIBUTE_KEYS
        }
        return RequirementWeights(**smoothed)

    def _score_patterns(
        self,
        patterns: list[dict[str, Any]],
        weights: RequirementWeights,
    ) -> list[dict[str, Any]]:
        """Stage-2b: deterministically score every candidate pattern.

        Computes analysis_score (requirements-weighted), then blends with
        min-max-normalized fusion_score. Sorts by blended_score when blending
        is active (fusion_blend_weight > 0), else by analysis_score.
        """
        w = weights.as_dict()
        weight_sum = sum(w.values())

        # Min-max normalize fusion_score within this recall set
        fusion_scores = [float(p.get("fusion_score", 0.0)) for p in patterns]
        f_min = min(fusion_scores) if fusion_scores else 0.0
        f_max = max(fusion_scores) if fusion_scores else 0.0
        f_range = f_max - f_min

        a_w = self._retrieval_config.analysis_blend_weight
        f_w = self._retrieval_config.fusion_blend_weight

        scored: list[dict[str, Any]] = []
        for pattern in patterns:
            qa = pattern.get("quality_attributes", {}) or {}
            if weight_sum > 0:
                weighted_avg = sum(
                    w[attr] * float(qa.get(attr, 0.0))
                    for attr in QUALITY_ATTRIBUTE_KEYS
                ) / weight_sum
            else:
                vals = [float(qa.get(attr, 0.0)) for attr in QUALITY_ATTRIBUTE_KEYS]
                weighted_avg = sum(vals) / len(vals) if vals else 0.0
            analysis_score = round(weighted_avg * 10.0, 2)

            raw_fusion = float(pattern.get("fusion_score", 0.0))
            fusion_normalized = (
                0.0 if f_range == 0
                else round((raw_fusion - f_min) / f_range * 100.0, 2)
            )
            blended_score = round(a_w * analysis_score + f_w * fusion_normalized, 2)

            scored_pattern = dict(pattern)
            scored_pattern["analysis_score"] = analysis_score
            scored_pattern["fusion_score_normalized"] = fusion_normalized
            scored_pattern["blended_score"] = blended_score
            scored.append(scored_pattern)

        sort_key = "blended_score" if f_w > 0 else "analysis_score"
        scored.sort(key=lambda p: p.get(sort_key, 0.0), reverse=True)
        return scored

    def _select_recommended_style(
        self,
        selected: list[dict[str, Any]],
        style_override: str | None,
    ) -> str:
        """Derive ``recommended_style`` from the scored patterns.

        Option A (threshold-gated): use the top-scoring pattern's name as the
        style when its ``analysis_score`` meets ``style_score_threshold``;
        otherwise fall back to ``DEFAULT_FALLBACK_PATTERN_NAME`` (layered-monolith).
        An explicit ``style_override`` always wins.
        """
        if style_override:
            return style_override
        if not selected:
            return DEFAULT_FALLBACK_PATTERN_NAME
        top = selected[0]
        top_score = float(top.get("analysis_score", 0.0))
        if top_score >= self._retrieval_config.style_score_threshold:
            return str(top.get("name", DEFAULT_FALLBACK_PATTERN_NAME))
        logger.info(
            "Top pattern '%s' analysis_score %.2f < threshold %.2f; "
            "falling back to '%s'",
            top.get("name"),
            top_score,
            self._retrieval_config.style_score_threshold,
            DEFAULT_FALLBACK_PATTERN_NAME,
        )
        return DEFAULT_FALLBACK_PATTERN_NAME

    def _build_analyze_system_prompt(self, domain: str) -> str:
        """Build system prompt for the ANALYZE phase (weight extraction only)."""
        return f"""You are an expert software architect analysing requirements.

Read the REQUIREMENTS and decide how strongly they emphasise each of the six
quality attributes below. Return a priority weight in [0.0, 1.0] for each one:
- 0.0 = not mentioned / irrelevant
- 1.0 = a dominant, explicit priority
Normalise so the most important attribute(s) receive 1.0 and the rest scale down
proportionally. Base the weights SOLELY on what the requirements actually state.

Quality attributes:
- scalability:      handle growing load / many users / horizontal scale
- maintainability:  ease of change, modularity, long-term evolution
- reliability:      fault tolerance, uptime, no data loss, resilience
- security:         authn/authz, data protection, regulatory compliance
- performance:      low latency, high throughput, fast response
- simplicity:       minimal operational complexity, small team, fast delivery

Target domain (context only — do not score it): {domain}

Example RequirementWeights response:
```json
{{
  "scalability": 1.0,
  "maintainability": 0.6,
  "reliability": 0.8,
  "security": 0.3,
  "performance": 0.9,
  "simplicity": 0.2
}}
```
"""

    def _build_analyze_user_prompt(
        self,
        requirements: str,
        domain: str,
    ) -> str:
        """Build user prompt for the ANALYZE phase (requirements → weights)."""
        return f"""Requirements:
{requirements}

Target Domain: {domain}

Extract the priority weight (0.0-1.0) for each of the six quality attributes
based solely on the requirements above. Return the weights matching the
RequirementWeights schema."""

    def _build_evaluate_system_prompt(self, patterns: list[Pattern]) -> str:
        """Build system prompt for the EVALUATE phase."""
        if not patterns:
            return f"""You are an expert software architect.
Evaluate the provided architecture against the specified criteria.
Respond with a detailed evaluation including metrics and recommendations.

{ARCHITECTURE_EVALUATION_EXAMPLE}
"""
        first = patterns[0]
        qa_lines = "\n".join(
            f"  - {attr}: {score}/10"
            for attr, score in first.quality_attributes.items()
        )
        ap_lines = "\n".join(f"  - {ap}" for ap in first.anti_patterns[:5])
        dp_lines = "\n".join(f"  - {dp}" for dp in first.design_principles[:5])
        return f"""You are an expert software architect.
Evaluate the provided architecture against the specified criteria.
Respond with a detailed evaluation including metrics and recommendations.

ARCHITECTURE PATTERN TO BENCHMARK: {first.name}

TARGET QUALITY ATTRIBUTES (expected scores):
{qa_lines}

ANTI-PATTERNS TO CHECK FOR:
{ap_lines}

DESIGN PRINCIPLES TO VERIFY:
{dp_lines}

{ARCHITECTURE_EVALUATION_EXAMPLE}
"""

    def _build_evaluate_user_prompt(
        self,
        architecture: ArchitectureDesign,
        criteria: str,
        domain: str,
        patterns: list[Pattern],
    ) -> str:
        """Build user prompt for the EVALUATE phase."""
        arch_json = architecture.model_dump_json(indent=2)
        criteria_list = ", ".join(criteria.split(",")) if criteria else "quality,maintainability,scalability"
        pattern_section = ""
        if patterns:
            ct_limit = self._retrieval_config.pattern_context_limits.get("component_types", 5)
            ct_lines = "\n".join(f"  - {ct}" for p in patterns for ct in (p.component_types or [])[:ct_limit])
            pattern_section = f"\nExpected component types (from patterns):\n{ct_lines}\n"
        return f"""Evaluate this architecture:

ARCHITECTURE:
{arch_json}

EVALUATION CRITERIA: {criteria_list}

DOMAIN: {domain}{pattern_section}

Provide the evaluation as JSON matching the ArchitectureEvaluation schema."""

    def _retry_prompt(
        self,
        design: ArchitectureDesign,
        evaluation: ArchitectureEvaluation,
        requirements: list[str],
        style: str,
        domain: str,
        selected_pattern: Pattern | None = None,
    ) -> str:
        """Build a refinement prompt from evaluation feedback.

        Args:
            design: The current architecture design
            evaluation: The evaluation result with weaknesses and recommendations
            requirements: Original requirements
            style: Architecture style
            domain: Application domain
            selected_pattern: Optional pattern for targeted refinement guidance

        Returns:
            Refinement prompt string
        """
        weaknesses = "\n".join(f"- {w}" for w in evaluation.summary.weaknesses)
        critical = "\n".join(f"- {c}" for c in evaluation.summary.critical_findings)

        refinement_guidance = []
        for metric_result in evaluation.metrics:
            if metric_result.score < 70:
                refinement_guidance.extend(metric_result.recommendations)

        pattern_section = ""
        if selected_pattern:
            limits = self._retrieval_config.pattern_context_limits
            bp_limit = limits.get("best_practices", 3)
            ap_limit = limits.get("anti_patterns", 3)
            tradeoffs_limit = limits.get("tradeoffs", 3)
            pattern_section = f"""
TARGET PATTERN: {selected_pattern.name}

PATTERN BEST PRACTICES FOR REFINEMENT:
{chr(10).join(f"- {bp}" for bp in (selected_pattern.best_practices or [])[:bp_limit])}

ANTI-PATTERNS IDENTIFIED IN EVALUATION:
{chr(10).join(f"- {ap}" for ap in (selected_pattern.anti_patterns or [])[:ap_limit])}

PATTERN TRADEOFFS (acceptable compromises):
{chr(10).join(f"- {t}" for t in (selected_pattern.tradeoffs or [])[:tradeoffs_limit])}
"""
        req_str = "\n".join(f"- {r}" for r in requirements) if isinstance(requirements, list) else requirements

        return f"""Refine this architecture design based on evaluation feedback:

ORIGINAL REQUIREMENTS:
{req_str}

CURRENT ARCHITECTURE STYLE: {style}
DOMAIN: {domain}
{pattern_section}

ARCHITECTURE TO REFINE:
{design.model_dump_json(indent=2)}

CRITICAL FINDINGS:
{critical}

WEAKNESSES:
{weaknesses}

REFINEMENT GUIDANCE:
{chr(10).join(f"- {g}" for g in refinement_guidance)}

When refining, preserve the populated api_contracts, shared_data_models,
and event_contracts from the current design. Add or refine entries as
needed to address the weaknesses above. Leaving these lists empty is
acceptable when not applicable to the architecture style.

Produce an improved architecture design that addresses the above weaknesses.
Respond ONLY with valid JSON matching the ArchitectureDesign schema.

{ARCHITECTURE_DESIGN_EXAMPLE}
"""
