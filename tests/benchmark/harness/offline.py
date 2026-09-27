"""Offline wiring: stub retrieval legs + scripted agent over the real pipeline/catalog.

Offline mode exercises the REAL analyze/scoring/fusion path of
:class:`~src.pipeline.ArchitecturePipeline` with two seams replaced:

- **Retrieval legs** — both ``_dense_retriever`` and ``_bm25_retriever`` are stub legs that
  return a fixed, domain-slug-ordered ``NodeWithScore`` list (primary slug first, sibling
  second, then two safe decoys resolving to no acceptable pattern); the stubs ignore the
  query, so the scenario's authored ``domain`` never reaches them. Real RR fusion +
  ``filter_by_domain`` pattern resolution + requirements-weighted scoring then produce the
  ranking; ``SafeTEIReranker`` is patched with a pass-through double (offline has no TEI).
- **Agent** — ``generate_structured`` answers ``RequirementWeights`` from the scenario's
  seed weights, ``ArchitectureDesignResponse`` from the style named in the generate prompt,
  and ``ArchitectureEvaluation`` with a fixed 85.0 ``overall_quality`` metric.

``--flip`` swaps the leg order so the sibling slug outranks the primary slug; the fused
normalized score (and therefore the blended selection score) follows the rank, and the run
misses exactly the flipped scenario.

Rerank latency is not attributable offline (the production reranker is built inside the
retriever, not injected); it lands in the request residual alongside harness overhead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

from llama_index.core.schema import NodeWithScore, TextNode

from src.agent import SoftwareArchitectAgent
from src.config import EmbedderConfig, EmbedderInnerConfig, ServerConfig
from src.patterns.loader import PatternLoader
from src.pipeline import ArchitecturePipeline
from src.schemas.analysis import RequirementWeights
from src.schemas.architecture import ArchitectureDesignResponse
from src.schemas.enums import PatternCategory
from src.schemas.evaluation import ArchitectureEvaluation, EvaluationSummary, MetricResult

from .config import Scenario
from .probes import AgentTimingProxy, StageRecorder, SyncLegTimingProxy

#: Stub slugs per scenario: [primary-unique, sibling/neutral, decoy, decoy].
#: Every slug is verified: slug 1 resolves to exactly the primary pattern, slug 2 to at most
#: the sibling (never a higher-scoring foreign pattern), slugs 3-4 resolve to no acceptable
#: pattern. Leg order encodes the fusion outcome, so ``--flip`` deterministically reverses it.
SLUG_MAP: dict[str, list[str]] = {
    "messaging-async-integration": [
        "microservices-ecosystem", "high-concurrency",
        "telecom-and-real-time-messaging", "financial-trading-platforms",
    ],
    "messaging-broker-integration": [
        "legacy-system-integration", "enterprise-application-integration",
        "telecom-and-real-time-messaging", "financial-trading-platforms",
    ],
    "structural-plugin-boundary": [
        "multi-external-integrations", "long-lived-applications",
        "telecom-and-real-time-messaging", "iot-device-management",
    ],
    "structural-team-autonomy": [
        "ci-cd-environments", "e-commerce-platforms-with-multiple-product-categories",
        "telecom-and-real-time-messaging", "iot-device-management",
    ],
    "coordination-payment-saga": [
        "e-commerce-order-processing", "legal",
        "telecom-and-real-time-messaging", "iot-device-management",
    ],
    "coordination-robot-orchestration": [
        "autonomous-mobile-robots", "batch-processing",
        "telecom-and-real-time-messaging", "cpu-bound-computation",
    ],
    "data-cqrs-dashboards": [
        "real-time-dashboards", "fintech",
        "telecom-and-real-time-messaging", "gaming-servers",
    ],
    "data-event-ledger": [
        "finance-banking", "real-time-analytics-dashboards",
        "telecom-and-real-time-messaging", "gaming-servers",
    ],
    "cloud-burst-scaling": [
        "companies-undertaking-multi-year-cloud-migration-journeys", "global-distribution",
        "telecom-and-real-time-messaging", "iot-device-management",
    ],
    "cloud-elastic-functions": [
        "event-driven-workloads", "companies-undertaking-multi-year-cloud-migration-journeys",
        "telecom-and-real-time-messaging", "gaming-servers",
    ],
    "ai-blackboard-fusion": [
        "artificial-intelligence", "legal-regulatory",
        "telecom-and-real-time-messaging", "multi-agent-ai-systems",
    ],
    "ai-rules-advisor": [
        "legal-regulatory", "artificial-intelligence",
        "telecom-and-real-time-messaging", "multi-agent-ai-systems",
    ],
    "gateway-central-edge": [
        "microservices-architectures-with-multiple-backend-services", "enterprise-saas",
        "telecom-and-real-time-messaging", "multi-agent-ai-systems",
    ],
    "gateway-bff-clients": [
        "enterprise-saas", "microservices-architectures-with-multiple-backend-services",
        "telecom-and-real-time-messaging", "multi-agent-ai-systems",
    ],
    "dataflow-stream-kappa": [
        "real-time-analytics", "data-processing",
        "telecom-and-real-time-messaging", "iot-device-management",
    ],
    "dataflow-etl-pipeline": [
        "data-processing", "real-time-analytics",
        "telecom-and-real-time-messaging", "iot-device-management",
    ],
}

#: The generate prompt's style sentence: "Design a <style> architecture ...".
_STYLE_RE = re.compile(r"Design a ([a-z0-9-]+) architecture")

#: Fixed EVALUATE score the scripted agent returns (clean production runs early-stop here).
_SCRIPTED_EVALUATION_SCORE = 85.0


@dataclass(frozen=True)
class _StubLeg:
    """One scripted retrieval leg: fixed slugs at descending scores."""

    slugs: tuple[str, ...]

    def retrieve(self, query_bundle: Any) -> list[NodeWithScore]:
        return [
            NodeWithScore(
                node=TextNode(id_=slug, text=slug, metadata={"slug": slug}),
                score=round(1.0 - 0.02 * index, 6),
            )
            for index, slug in enumerate(self.slugs)
        ]


class _DummyReranker:
    """Pass-through reranker double installed for offline runs (no TEI sidecar)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.top_n = 10
        self.keep_retrieval_score = True

    def postprocess_nodes(self, nodes: Any, query_bundle: Any = None) -> list[Any]:
        return list(nodes)


class _ScriptedAgent:
    """Scripted ``generate_structured`` dispatching by ``response_schema.__name__``."""

    def __init__(self, weights: dict[str, float] | None) -> None:
        self._weights = weights or {}

    async def generate_structured(
        self, system_prompt: str, user_prompt: str, response_schema: Any
    ) -> Any:
        name = getattr(response_schema, "__name__", "")
        if name == "RequirementWeights":
            return RequirementWeights(
                scalability=self._weights.get("scalability", 0.0),
                maintainability=self._weights.get("maintainability", 0.0),
                reliability=self._weights.get("reliability", 0.0),
                security=self._weights.get("security", 0.0),
                performance=self._weights.get("performance", 0.0),
                simplicity=self._weights.get("simplicity", 0.0),
            )
        if name in ("ArchitectureDesignResponse", "ArchitectureDesignResponseWire"):
            match = _STYLE_RE.search(user_prompt)
            if match is None:
                raise ValueError(
                    f"scripted agent: no style sentence in generate prompt: {user_prompt[:160]!r}"
                )
            style = match.group(1)
            return ArchitectureDesignResponse.model_validate(
                {
                    "overview": {
                        "reasoning": "scripted offline design rationale",
                        "style": style,
                        "category": PatternCategory.MESSAGING.value,
                        "principles": ["scripted principle"],
                        "constraints": ["scripted constraint"],
                    },
                    "components": [
                        {
                            "id": "core",
                            "name": "core",
                            "type": "service",
                            "description": "scripted core service",
                            "responsibilities": ["scripted responsibility"],
                        }
                    ],
                }
            )
        if name == "ArchitectureEvaluation":
            return ArchitectureEvaluation(
                summary=EvaluationSummary(overall_score=_SCRIPTED_EVALUATION_SCORE),
                metrics=[
                    MetricResult(
                        name="overall_quality",
                        score=_SCRIPTED_EVALUATION_SCORE,
                        description="scripted offline evaluation",
                    )
                ],
                recommendations={"quality": ["scripted recommendation"]},
            )
        raise ValueError(f"scripted agent: unexpected response schema {name!r}")


@dataclass(frozen=True)
class OfflineScript:
    """One scenario's scripted seams plus the provenance of the stub pool."""

    slugs: tuple[str, ...]
    flip: bool

    def describe(self) -> dict[str, Any]:
        """Compact provenance block for the run record."""
        return {"slugs": list(self.slugs), "flip": self.flip}


def build_script(scenario: Scenario, catalog: PatternLoader, *, flip: bool) -> OfflineScript:
    """Build the scripted seams for ``scenario`` (label order, or demoted primary when flipped).

    Flipping demotes the primary slug from rank 1 to last rank (fused score 0) while a decoy
    pattern takes rank 1. Mere sibling promotion is insufficient: the sibling is itself in
    ``acceptable_primary``, so a sibling-first pool would still count as a hit, and strongly
    weighted scenarios (e.g. ``simplicity``-heavy cloud-elastic-functions) can out-score the
    fusion deficit and keep the primary on top. With the primary at fusion rank 4 and a
    non-acceptable decoy at rank 1, the recommended style leaves ``acceptable_primary`` for
    every scenario.
    """
    slugs = SLUG_MAP.get(scenario.scenario_id)
    if slugs is None:
        raise ValueError(
            f"scenario {scenario.scenario_id!r}: no offline slug map entry; "
            "extend OfflineScript.SLUG_MAP for new scenarios"
        )
    if flip and len(slugs) >= 4:
        ordered = [slugs[2], slugs[1], slugs[3], slugs[0]]
    else:
        ordered = list(slugs)
    return OfflineScript(slugs=tuple(ordered), flip=flip)


def build_pipeline(
    script: OfflineScript,
    scenario: Scenario,
    *,
    config: ServerConfig,
    catalog: PatternLoader,
    recorder: StageRecorder,
) -> ArchitecturePipeline:
    """A real :class:`ArchitecturePipeline` over the scripted seams.

    The stub legs go straight onto the pipeline's retriever attributes (the same seams
    ``_build_retrievers`` would fill), wrapped in timing proxies; the agent is wrapped in the
    LLM dispatch proxy. ``SafeTEIReranker`` is patched before any retrieval runs so offline
    never dials a TEI sidecar.
    """
    import src.patterns.retriever as retriever_module

    # Both codes needed: implicit re-import (attr-defined) + class replacement (assignment).
    retriever_module.SafeTEIReranker = _DummyReranker  # type: ignore[attr-defined,assignment]

    agent = _ScriptedAgent(scenario.weights)
    pipeline = ArchitecturePipeline(
        agent=cast("SoftwareArchitectAgent", agent),  # duck-typed: only generate_structured is called
        pattern_loader=catalog,
        embedder_config=EmbedderConfig(provider="none", config=EmbedderInnerConfig()),
    )
    leg_kwargs: dict[str, Any] = {"recorder": recorder}
    pipeline._dense_retriever = SyncLegTimingProxy(  # type: ignore[assignment]
        _StubLeg(script.slugs), stage="retrieval.dense", **leg_kwargs
    )
    pipeline._bm25_retriever = SyncLegTimingProxy(  # type: ignore[assignment]
        _StubLeg(script.slugs), stage="retrieval.bm25", **leg_kwargs
    )
    pipeline._retrieval_corpus_size = len(script.slugs)
    pipeline._agent = AgentTimingProxy(agent, recorder)  # type: ignore[assignment]
    return pipeline
