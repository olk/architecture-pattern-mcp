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
Regression tests for the two-stage recall-then-score pipeline fixes (PR-1..PR-5).

T1: analysis_to_pydantic with empty lists does not raise (issue #1)
T2: ScoredPattern round-trips analysis_score + fusion_score (issue #11)
T3: generate tool resolves pattern names end-to-end (issue #12)
T4: min_quality_score=50 + mocked overall_quality=60 stops after attempt 1 (issue #2)
T5: All 36 catalogue JSONs have 6 QA keys; PAC loads (issue #8)
T6: rerank_enabled recall is lossless (issue #5)
T7: min_fusion_score gate no longer drops single-leg rank-7 hit (issue #3)
T8: simple fusion does not let BM25 dominate dense (issue #15)
T9: BM25 get_scores returns correct per-domain scores (issue #13)
T10: All-zero weights logs WARNING and retries (issue #17)
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from src.patterns._fusion import _fuse_simple
from src.patterns.bm25_index import DomainBM25Index
from src.patterns.retriever import (
    DEFAULT_FALLBACK_PATTERN_NAME,
    HybridPatternRetriever,
)
from src.config import RetrievalConfig
from src.pipeline import (
    AnalysisResult as PipelineAR,
)
from src.pipeline import (
    ArchitecturePipeline,
    RequirementWeights,
)
from src.schemas.analysis import AnalysisResult
from src.schemas.patterns import ScoredPattern
from src.tools._adapters import analysis_to_pydantic

# ─── T1 ────────────────────────────────────────────────────────────────────────


class TestT1EmptyListsAccepted:
    """T1: AnalysisResult accepts empty strengths/weaknesses/recommendations
    (issue #1: was min_length=1 → ValidationError on deterministic narratives
    that returned [] for mid-range candidate sets).
    """

    def test_empty_lists_no_validation_error(self):
        ar = AnalysisResult(
            strengths=[],
            weaknesses=[],
            recommendations=[],
            quality_metrics=None,
            recommended_style=DEFAULT_FALLBACK_PATTERN_NAME,
            selected_patterns=[],
        )
        assert ar.strengths == []
        assert ar.weaknesses == []
        assert ar.recommendations == []

    def test_adapter_round_trips_empty_lists(self):
        """The full adapter path (pipeline dataclass → Pydantic) also accepts empty."""
        dc = PipelineAR(
            strengths=[],
            weaknesses=[],
            recommendations=[],
            quality_metrics=None,
            recommended_style=DEFAULT_FALLBACK_PATTERN_NAME,
            selected_patterns=[],
        )
        res = analysis_to_pydantic(dc)
        assert res.strengths == []
        assert res.weaknesses == []
        assert res.recommendations == []


# ─── T2 ────────────────────────────────────────────────────────────────────────


class TestT2ScoredPatternRoundTrip:
    """T2: ScoredPattern preserves analysis_score + fusion_score through
    the adapter boundary (issue #11: Pydantic v2 default extra='ignore' was
    silently dropping the score keys).
    """

    def test_scored_pattern_from_dict(self):
        sp = ScoredPattern.model_validate({
            "name": "test",
            "context": "ctx",
            "category": "structural",
            "analysis_score": 85.5,
            "fusion_score": 0.0333,
        })
        assert sp.analysis_score == 85.5
        assert sp.fusion_score == 0.0333

    def test_scored_pattern_round_trip_via_adapter(self):
        dc = PipelineAR(
            strengths=["s"],
            weaknesses=[],
            recommendations=[],
            quality_metrics=None,
            recommended_style="test",
            selected_patterns=[{
                "name": "test",
                "context": "ctx",
                "category": "structural",
                "analysis_score": 75.0,
                "fusion_score": 0.5,
            }],
        )
        res = analysis_to_pydantic(dc)
        assert len(res.selected_patterns) == 1
        assert res.selected_patterns[0].analysis_score == 75.0
        assert res.selected_patterns[0].fusion_score == 0.5

    def test_scored_pattern_model_dump_preserves_scores(self):
        sp = ScoredPattern.model_validate({
            "name": "test",
            "context": "ctx",
            "category": "structural",
            "analysis_score": 60.0,
            "fusion_score": 0.025,
        })
        d = sp.model_dump()
        assert d["analysis_score"] == 60.0
        assert d["fusion_score"] == 0.025


# ─── T3 ────────────────────────────────────────────────────────────────────────


class TestT3GenerateResolvesPatternNames:
    """T3: generate tool resolves pattern names to dicts end-to-end
    (issue #12: list[str] was passed where list[dict] expected → AttributeError).
    """

    def _build_design(self):
        from src.schemas.components import Component

        from src.schemas.design import ArchitectureDesign, ArchitectureOverview
        from src.schemas.enums import ArchitectureStyle, PatternCategory
        return ArchitectureDesign(
            overview=ArchitectureOverview(
                style=ArchitectureStyle.MICROSERVICES,
                category=PatternCategory.STRUCTURAL,
                principles=["single responsibility"],
            ),
            components=[Component(
                id="c1", name="C1", type="service",
                description="d", responsibilities=["r"],
            )],
            relationships=[],
            patterns=[],
            quality_attributes={},
        )

    def test_pipeline_generate_called_with_resolved_dicts(self):
        from src.tools.generate import GenerateArchitectureTool

        cqrs_dict = {
            "name": "cqrs",
            "context": "Read/write segregation",
            "category": "structural",
            "quality_attributes": {
                "performance": 7, "scalability": 7, "reliability": 7,
                "maintainability": 7, "security": 7, "simplicity": 5,
            },
        }

        loader = MagicMock()
        loader.get_by_name.return_value = cqrs_dict

        pipeline = MagicMock()
        pipeline.generate = AsyncMock(return_value=self._build_design())
        pipeline._pattern_loader = loader

        agent = MagicMock()
        tool = GenerateArchitectureTool(agent=agent, pipeline=pipeline)

        asyncio.run(tool.generate(
            requirements="req",
            style="cqrs",
            domain="web",
            selected_patterns=["cqrs"],
        ))

        pipeline.generate.assert_called_once()
        call_kwargs = pipeline.generate.call_args.kwargs
        assert call_kwargs["selected_patterns"] == [cqrs_dict]

    def test_pipeline_generate_skips_unknown_names(self):
        from src.tools.generate import GenerateArchitectureTool

        loader = MagicMock()
        loader.get_by_name.return_value = None

        pipeline = MagicMock()
        pipeline.generate = AsyncMock(return_value=self._build_design())
        pipeline._pattern_loader = loader

        agent = MagicMock()
        tool = GenerateArchitectureTool(agent=agent, pipeline=pipeline)

        asyncio.run(tool.generate(
            requirements="req",
            style="x",
            domain="web",
            selected_patterns=["unknown-pattern"],
        ))

        call_kwargs = pipeline.generate.call_args.kwargs
        assert call_kwargs["selected_patterns"] == []


# ─── T4 ────────────────────────────────────────────────────────────────────────


class TestT4MinQualityScoreEarlyStop:
    """T4: min_quality_score=50 + mocked overall_quality=60 stops after 1 attempt
    (issue #2: was on 0-10 scale, 60/10=6.0, 6.0 < 50.0 → never early-stopped).
    """

    def test_early_stop_fires_at_attempt_one(self):
        from src.schemas.evaluation import (
            ArchitectureEvaluation,
            EvaluationSummary,
            MetricResult,
        )

        # Build a minimal pipeline with mocks.
        agent = MagicMock()
        agent.generate_structured = AsyncMock()

        # Return a canned design + evaluation with overall_quality=60.
        from src.schemas.architecture import ArchitectureDesignResponse

        design_response = ArchitectureDesignResponse(
            overview={"style": "microservices", "category": "structural",
                      "principles": ["single responsibility"], "constraints": []},
            components=[{"id": "c1", "name": "C1", "type": "service",
                         "description": "d", "responsibilities": ["r"],
                     "interfaces": [], "technology_stack": [],
                     "api_contract": None, "data_models": [],
                     "config_requirements": []}],
            relationships=[],
            quality_attributes={},
            api_contracts=[],
            shared_data_models=[],
            event_contracts=[],
        )
        evaluation = ArchitectureEvaluation(
            summary=EvaluationSummary(overall_score=60.0, strengths=[],
                                      weaknesses=[], critical_findings=[]),
            metrics=[MetricResult(name="overall_quality", score=60.0,
                                  description="q", findings=[], recommendations=[])],
            recommendations={},
        )

        async def gen(system_prompt, user_prompt, response_schema):
            if response_schema is ArchitectureDesignResponse:
                return design_response
            return evaluation

        agent.generate_structured = gen

        loader = MagicMock()
        loader._loaded = True
        loader.get_by_name.return_value = None
        loader.load_all.return_value = []
        loader.filter_by_domain.return_value = []

        vi = MagicMock()
        vi.is_built = True
        vi.domains = ["x"]
        bm = MagicMock()
        bm.is_built = True
        bm.domains = ["x"]

        pipeline = ArchitecturePipeline(
            agent=agent,
            pattern_loader=loader,
            vector_index=vi,
            bm25_index=bm,
        )

        gen_count = 0
        original_gen = agent.generate_structured

        async def counting_gen(*args, **kwargs):
            nonlocal gen_count
            r = await original_gen(*args, **kwargs)
            from src.schemas.architecture import ArchitectureDesignResponse as ADR
            if kwargs.get("response_schema") is ADR or (
                len(args) >= 3 and args[2] is ADR
            ):
                gen_count += 1
            return r

        agent.generate_structured = counting_gen

        asyncio.run(pipeline.design_loop(
            requirements="test",
            domain="cloud-native",
            style="microservices",
            selected_patterns=[{
                "name": "microservices", "context": "",
                "category": "structural", "benefits": [],
                "best_practices": [],
                "quality_attributes": {
                    "performance": 5, "scalability": 5, "reliability": 5,
                    "maintainability": 5, "security": 5, "simplicity": 5,
                },
            }],
            criteria="quality",
            analysis_result=None,
            max_tries=3,
            min_quality_score=50.0,
        ))

        # 60.0 >= 50.0 → early stop after 1 design attempt.
        assert gen_count == 1


# ─── T5 ────────────────────────────────────────────────────────────────────────


class TestT5CatalogueIntegrity:
    """T5: All 36 catalogue JSONs have 6 QA keys; PAC loads (issue #8)."""

    def test_all_catalogue_files_have_six_qa_keys(self):
        from src.patterns.loader import PatternLoader
        loader = PatternLoader()
        patterns = loader.load_all()
        assert len(patterns) >= 35, f"expected >=35 patterns, got {len(patterns)}"

        required = {"performance", "scalability", "reliability",
                    "maintainability", "security", "simplicity"}
        missing = []
        for p in patterns:
            qa = set(p.get("quality_attributes", {}).keys())
            if not required.issubset(qa):
                missing.append(p.get("name"))
        assert not missing, f"patterns missing QA keys: {missing}"

    def test_pac_loads_after_security_backfill(self):
        from src.patterns.loader import PatternLoader
        loader = PatternLoader()
        patterns = loader.load_all()
        pac = next((p for p in patterns if p["name"] == "presentation-abstraction-control"), None)
        assert pac is not None, "PAC not in catalogue"
        assert "security" in pac["quality_attributes"], "PAC missing security"
        assert "simplicity" in pac["quality_attributes"], "PAC missing simplicity"

    def test_soa_loads_after_simplicity_backfill(self):
        from src.patterns.loader import PatternLoader
        loader = PatternLoader()
        patterns = loader.load_all()
        soa = next((p for p in patterns if p["name"] == "service-oriented-architecture"), None)
        assert soa is not None, "SOA not in catalogue"
        assert "simplicity" in soa["quality_attributes"], "SOA missing simplicity"


# ─── T6 ────────────────────────────────────────────────────────────────────────


class TestT6RerankLossless:
    """T6: rerank recall is lossless (issue #5: top_n was
    pre-truncating before scoring, violating 'select only after scoring').
    """

    def test_rerank_scores_all_fused_nodes(self):
        """The recall set size after rerank == size before."""
        class _MockReranker:
            def __init__(self):
                self.top_n = 1
                self.input_count = 0

            def postprocess_nodes(self, nodes, query_bundle):
                self.input_count = len(nodes)
                # Lossless: return all input nodes (mimicking cross-encoder scoring).
                return nodes

        pattern = {
            "name": "microservices", "context": "Distributed system.",
            "category": "architectural", "benefits": ["Scalability"],
            "tradeoffs": ["Complexity"],
            "quality_attributes": {
                "performance": 8, "scalability": 9, "reliability": 7,
                "maintainability": 7, "security": 6, "simplicity": 4,
            },
            "suitable_domains": ["microservices"],
            "best_practices": [],
        }

        class _MockLoader:
            _loaded = True
            def filter_by_domain(self, _d): return [pattern]
            def get_by_name(self, _n): return None

        class _MockBM25:
            is_built = True
            domains = ["x"]
            def as_retriever(self, _k): return MagicMock(retrieve=lambda _: [])

        class _MockVec:
            is_built = True
            domains = ["x"]
            def as_retriever(self, _k):
                nodes = [
                    NodeWithScore(
                        node=TextNode(text="a", metadata={"slug": "microservices"}),
                        score=0.9,
                    ),
                    NodeWithScore(
                        node=TextNode(text="b", metadata={"slug": "event-driven"}),
                        score=0.7,
                    ),
                ]
                return MagicMock(retrieve=lambda _: nodes)

        retriever = HybridPatternRetriever(
            bm25_index=_MockBM25(),
            vector_index=_MockVec(),
            pattern_loader=_MockLoader(),
            rerank_top_n=1,
            reranker_config=MagicMock(base_url="http://localhost:8080", timeout=30.0, max_batch_size=48),
        )
        # Pre-seed retrievers
        retriever._dense_retriever = _MockVec().as_retriever(2)
        retriever._bm25_retriever = _MockBM25().as_retriever(2)

        mock_reranker = _MockReranker()
        with patch("src.patterns.retriever.TextEmbeddingInference", return_value=mock_reranker):
            result = retriever.retrieve(
                user_domain="microservices",
                normalized_domain="microservices",
            )

        # Scoring is lossless: reranker received both fused nodes.
        assert mock_reranker.input_count == 2
        # rerank_top_n=1 caps survivors to the top cross-encoder candidate,
        # so only the 'microservices' slug reaches pattern resolution.
        assert len(result.patterns) == 1
        assert result.patterns[0][0]["name"] == "microservices"
        # matched_domains draws from the post-slice survivor pool.
        assert len(result.matched_domains) == 1
        assert {m.slug for m in result.matched_domains} == {"microservices"}


# ─── T7 ────────────────────────────────────────────────────────────────────────


class TestT7MinFusionScoreGateDisabled:
    """T7: min_fusion_score gate no longer drops single-leg rank-7 hit
    (issue #3: default 0.015 fired on rank-7 RRF = 1/67 ≈ 0.01493).
    """

    def test_low_fusion_score_not_dropped_with_zero_threshold(self):
        """With min_fusion_score=0.0 (the new default), a low score is not
        demoted to fallback."""
        pattern = {
            "name": "microservices", "context": "Distributed system.",
            "category": "architectural", "benefits": ["Scalability"],
            "tradeoffs": ["Complexity"],
            "quality_attributes": {
                "performance": 8, "scalability": 9, "reliability": 7,
                "maintainability": 7, "security": 6, "simplicity": 4,
            },
            "suitable_domains": ["microservices"],
            "best_practices": [],
        }

        class _MockLoader:
            _loaded = True
            def filter_by_domain(self, _d): return [pattern]
            def get_by_name(self, _n): return None

        class _MockBM25:
            is_built = True
            domains = ["x"]
            def as_retriever(self, _k): return MagicMock(retrieve=lambda _: [])

        class _MockVec:
            is_built = True
            domains = ["x"]
            def as_retriever(self, _k):
                # Simulate single-leg rank-7 RRF score.
                return MagicMock(retrieve=lambda _: [
                    NodeWithScore(
                        node=TextNode(text="a", metadata={"slug": "microservices"}),
                        score=1/67,
                    ),
                ])

        retriever = HybridPatternRetriever(
            bm25_index=_MockBM25(),
            vector_index=_MockVec(),
            pattern_loader=_MockLoader(),
            min_fusion_score=0.0,
        )
        retriever._dense_retriever = _MockVec().as_retriever(2)
        retriever._bm25_retriever = _MockBM25().as_retriever(2)

        result = retriever.retrieve(
            user_domain="microservices",
            normalized_domain="microservices",
        )
        # Raw dense score was 1/67; after RRF (rank=1, k=60) the fused
        # score becomes 1/(1+60-1) = 1/60 ≈ 0.01667. The key invariant:
        # the recall set is NOT demoted to fallback (was the old 0.015 bug).
        assert len(result.patterns) == 1
        assert result.patterns[0][0]["name"] == "microservices"
        assert result.patterns[0][1] > 0.015  # would have been demoted under old threshold
        assert result.patterns[0][1] == pytest.approx(1/60, abs=1e-4)
        assert len(result.matched_domains) == 1
        assert result.matched_domains[0].slug == "microservices"

    def test_genuinely_empty_recall_uses_fallback(self):
        """When recall is genuinely empty (no candidates, score=0.0),
        the fallback fires."""
        pattern = {
            "name": "microservices", "context": "ctx",
            "category": "architectural", "benefits": [],
            "tradeoffs": [], "quality_attributes": {},
            "suitable_domains": [], "best_practices": [],
        }

        class _MockLoader:
            _loaded = True
            def filter_by_domain(self, _d): return []
            def get_by_name(self, _n): return pattern

        class _MockBM25:
            is_built = True
            domains = ["x"]
            def as_retriever(self, _k): return MagicMock(retrieve=lambda _: [])

        class _MockVec:
            is_built = True
            domains = ["x"]
            def as_retriever(self, _k): return MagicMock(retrieve=lambda _: [])

        retriever = HybridPatternRetriever(
            bm25_index=_MockBM25(),
            vector_index=_MockVec(),
            pattern_loader=_MockLoader(),
            min_fusion_score=0.0,
        )
        retriever._dense_retriever = _MockVec().as_retriever(2)
        retriever._bm25_retriever = _MockBM25().as_retriever(2)

        result = retriever.retrieve(
            user_domain="x",
            normalized_domain="x",
        )
        assert len(result.patterns) == 1
        assert result.patterns[0][0]["name"] == "microservices"
        assert result.patterns[0][1] == 0.0
        # Tag is set
        assert result.patterns[0][0].get("is_fallback") is True
        # Fallback path means no real matched domains
        assert result.matched_domains == []


# ─── T8 ────────────────────────────────────────────────────────────────────────


class TestT8SimpleFusionRankUnion:
    """T8: simple fusion does not let BM25 dominate dense (issue #15:
    was sorting by raw score; BM25 ∈ [0, 15+] dominated cosine ∈ [0, 1]).
    """

    def test_simple_fusion_uses_rank_not_raw_score(self):
        # Dense leg: a single node with cosine 0.5 (low).
        dense = [
            NodeWithScore(node=TextNode(text="a", id_="a"), score=0.5),
        ]
        # BM25 leg: a single node with raw score 10.0 (high).
        bm25 = [
            NodeWithScore(node=TextNode(text="b", id_="b"), score=10.0),
        ]
        fused = _fuse_simple(dense, bm25)
        # After rank-union: a at rank 0 → 1/1 = 1.0; b at rank 0 → 1/1 = 1.0.
        # Both have equal fusion score — order within a tied score is stable.
        # The important invariant: BOTH appear, neither is silently dropped.
        assert len(fused) == 2
        scores = [n.score for n in fused]
        assert scores[0] == pytest.approx(1.0)
        assert scores[1] == pytest.approx(1.0)

    def test_simple_fusion_top_rank_wins(self):
        # Dense leg: 2 nodes, dense node at rank 0, BM25 node at rank 1.
        dense = [
            NodeWithScore(node=TextNode(text="a", id_="a"), score=0.9),
            NodeWithScore(node=TextNode(text="b", id_="b"), score=0.5),
        ]
        bm25 = [
            NodeWithScore(node=TextNode(text="b", id_="b"), score=8.0),
        ]
        fused = _fuse_simple(dense, bm25)
        # 'a' at rank 0 (dense) → 1/1 = 1.0
        # 'b' at rank 1 (dense) → 1/2 = 0.5; rank 0 (bm25) → 1/1 = 1.0 → best=1.0
        # Tied — but 'a' should be first OR 'b' should be first; both 1.0
        assert fused[0].score == pytest.approx(1.0)


# ─── T9 ────────────────────────────────────────────────────────────────────────


class TestT9BM25GetScoresCorrectness:
    """T9: BM25 get_scores returns correct per-domain scores
    (issue #13: was passing query-local int ids to the index — wrong vocab).
    """

    def test_get_scores_returns_known_per_domain_scores(self):
        index = DomainBM25Index()
        domains = ["event-driven-architecture", "cloud-native", "microservices"]
        index.build_index(domains)

        scores = index.get_scores("event driven")
        assert isinstance(scores, dict)
        # event-driven-architecture should score higher than unrelated domains.
        assert "event-driven-architecture" in scores
        assert scores["event-driven-architecture"] > scores.get("cloud-native", 0.0)

    def test_get_scores_with_stemmer(self):
        """Stemming 'processing' should still hit 'data-processing'."""
        index = DomainBM25Index()
        domains = ["data-processing", "data-pipelines", "cloud-native"]
        index.build_index(domains)
        scores = index.get_scores("processing data")
        assert "data-processing" in scores or "data-pipelines" in scores


# ─── T10 ───────────────────────────────────────────────────────────────────────


class TestT10AllZeroWeightsRetry:
    """T10: RequirementWeights smoothing (alpha=0.7 default).

    The prior retry-on-all-zero logic was removed; smoothing at alpha=0.7
    subsumes it by lifting all-zero LLM output to a uniform 1/6 distribution.
    """

    def test_non_zero_weights_no_retry(self):
        """Non-zero weights produce one LLM call; smoothing at alpha=0.7
        adjusts the output (e.g. scalability 1.0 → 0.75)."""
        agent = MagicMock()
        call_count = 0

        async def gen(system_prompt, user_prompt, response_schema):
            nonlocal call_count
            call_count += 1
            return RequirementWeights(
                scalability=1.0, performance=0.8, reliability=0.6,
                maintainability=0.5, security=0.3, simplicity=0.2,
            )

        agent.generate_structured = gen

        loader = MagicMock()
        vi = MagicMock()
        vi.is_built = True
        vi.domains = ["x"]
        bm = MagicMock()
        bm.is_built = True
        bm.domains = ["x"]
        pipeline = ArchitecturePipeline(
            agent=agent, pattern_loader=loader, vector_index=vi, bm25_index=bm,
        )

        result = asyncio.run(pipeline._extract_requirement_weights("req", "domain"))
        assert call_count == 1
        # alpha=0.7 smoothing: 0.7*1.0 + 0.3*(1/6) = 0.75
        assert result.scalability == 0.75


# ─── T11 ─ Option B: rerank_top_n caps post-rerank survivor pool ─────────────────


class TestRerankTopNCap:
    """T11: rerank_top_n bounds the slug pool fed to pattern resolution.
    Scoring itself remains lossless. The cap is always honored inside the
    reranking branch.
    """

    @staticmethod
    def _build(
        *,
        fused_nodes: list,
        rerank_top_n: int,
        loader,
    ):
        """Build a retriever with mocked legs + reranker; rerank_top_n wired."""

        class _MockBM25:
            is_built = True

            def __init__(self):
                self.domains = [n.node.metadata["slug"] for n in fused_nodes]

            def as_retriever(self, _k):
                return MagicMock(retrieve=lambda _: [])

        class _MockVec:
            is_built = True

            def __init__(self):
                self.domains = [n.node.metadata["slug"] for n in fused_nodes]

            def as_retriever(self, _k):
                return MagicMock(retrieve=lambda _: list(fused_nodes))

        retriever = HybridPatternRetriever(
            bm25_index=_MockBM25(),
            vector_index=_MockVec(),
            pattern_loader=loader,
            rerank_top_n=rerank_top_n,
            reranker_config=MagicMock(base_url="http://localhost:8080", timeout=30.0, max_batch_size=48),
        )
        retriever._dense_retriever = _MockVec().as_retriever(len(fused_nodes))
        retriever._bm25_retriever = _MockBM25().as_retriever(len(fused_nodes))
        return retriever

    def test_rerank_top_n_caps_surviving_candidates(self):
        """When rerank_top_n < len(fused), only top-N survivors reach pattern
        resolution. Scoring itself remains lossless (mock sees all input)."""

        class _Loader:
            _loaded = True

            @staticmethod
            def filter_by_domain(slug):
                return [{"name": f"pattern-{slug[-1]}", "suitable_domains": [slug]}]

            @staticmethod
            def get_by_name(_n):
                return None

        nodes = [
            NodeWithScore(node=TextNode(text="a", metadata={"slug": "slug-a"}), score=0.9),
            NodeWithScore(node=TextNode(text="b", metadata={"slug": "slug-b"}), score=0.8),
            NodeWithScore(node=TextNode(text="c", metadata={"slug": "slug-c"}), score=0.7),
        ]
        retriever = self._build(
            fused_nodes=nodes,
            rerank_top_n=2,
            loader=_Loader(),
        )

        class _MockReranker:
            def __init__(self):
                self.input_count = 0

            def postprocess_nodes(self, ns, query_bundle=None):
                self.input_count = len(ns)
                return ns

        with patch("src.patterns.retriever.TextEmbeddingInference") as mock_cls:
            mock_cls.return_value = _MockReranker()
            result = retriever.retrieve(user_domain="test", normalized_domain="test")

        assert retriever._reranker.input_count == 3
        assert len(result.patterns) == 2
        assert {p["name"] for p, _ in result.patterns} == {"pattern-a", "pattern-b"}
        assert {m.slug for m in result.matched_domains} == {"slug-a", "slug-b"}

    def test_rerank_top_n_ge_len_is_noop(self):
        """When rerank_top_n >= len(fused), the slice is a no-op."""

        class _Loader:
            _loaded = True

            @staticmethod
            def filter_by_domain(slug):
                return [{"name": f"pattern-{slug[-1]}", "suitable_domains": [slug]}]

            @staticmethod
            def get_by_name(_n):
                return None

        nodes = [
            NodeWithScore(node=TextNode(text="a", metadata={"slug": "slug-a"}), score=0.9),
            NodeWithScore(node=TextNode(text="b", metadata={"slug": "slug-b"}), score=0.8),
        ]
        retriever = self._build(
            fused_nodes=nodes,
            rerank_top_n=10,
            loader=_Loader(),
        )

        class _MockReranker:
            def postprocess_nodes(self, ns, query_bundle=None):
                return ns

        with patch("src.patterns.retriever.TextEmbeddingInference") as mock_cls:
            mock_cls.return_value = _MockReranker()
            result = retriever.retrieve(user_domain="test", normalized_domain="test")

        assert len(result.patterns) == 2
        assert {p["name"] for p, _ in result.patterns} == {"pattern-a", "pattern-b"}

    def test_slice_to_no_resolving_slug_triggers_fallback(self):
        """When the slice drops all pattern-bearing slugs, the fallback path
        fires and matched_domains is empty."""

        pattern_b = {
            "name": "pattern-b",
            "suitable_domains": ["slug-b"],
            "quality_attributes": {},
            "benefits": [],
            "tradeoffs": [],
            "best_practices": [],
            "category": "x",
            "context": "ctx",
        }

        class _Loader:
            _loaded = True

            @staticmethod
            def filter_by_domain(slug):
                if slug == "slug-b":
                    return [pattern_b]
                return []

            @staticmethod
            def get_by_name(_n):
                return {
                    "name": "layered-monolith",
                    "suitable_domains": ["fallback"],
                    "category": "x",
                    "context": "fallback",
                    "benefits": [],
                    "tradeoffs": [],
                    "best_practices": [],
                    "quality_attributes": {},
                }

        nodes = [
            NodeWithScore(node=TextNode(text="a", metadata={"slug": "slug-a"}), score=0.9),
            NodeWithScore(node=TextNode(text="b", metadata={"slug": "slug-b"}), score=0.8),
        ]
        retriever = self._build(
            fused_nodes=nodes,
            rerank_top_n=1,
            loader=_Loader(),
        )

        class _MockReranker:
            def postprocess_nodes(self, ns, query_bundle=None):
                return ns

        with patch("src.patterns.retriever.TextEmbeddingInference") as mock_cls:
            mock_cls.return_value = _MockReranker()
            result = retriever.retrieve(user_domain="test", normalized_domain="test")

        assert len(result.patterns) == 1
        assert result.patterns[0][0]["name"] == "layered-monolith"
        assert result.patterns[0][0].get("is_fallback") is True
        assert result.patterns[0][1] == 0.0
        assert result.matched_domains == []


# ─── T8 ────────────────────────────────────────────────────────────────────────


class TestT8RankFusionSelection:
    """T8: rank_fusion slug-cut (Vespa-style) blends RRF consensus rank
    with cross-encoder rank, protecting consensus-backed slugs from CE outliers
    on short domain-slug inputs."""

    def _make_fused_nodes(self, rrf_scores_and_slugs):
        """Build a fused list where each node has:
        - score = RRF score (descending position = RRF rank)
        - node.hash = unique per node
        - node.metadata["slug"] = slug
        - node.metadata["retrieval_score"] = RRF score (for restore)

        The caller (retriever) mutates .score and metadata on these objects,
        so the same objects must be returned by the mock postprocess_nodes.
        """
        nodes = []
        for rrf_score, slug in rrf_scores_and_slugs:
            node = NodeWithScore(
                node=TextNode(
                    text=slug,
                    metadata={
                        "slug": slug,
                        "retrieval_score": rrf_score,
                    },
                ),
                score=rrf_score,
            )
            nodes.append(node)
        return nodes

    def _reranker_mock(self, fused_nodes, ce_scores_by_slug):
        """Build a mock reranker that mutates the SAME node objects
        in fused_nodes (setting node.score = CE logit) and returns them
        sorted by CE score descending.

        ce_scores_by_slug: dict mapping slug -> CE logit.
        The order of the returned list is CE-descending.
        """
        class _MockReranker:
            def __init__(self, nodes, scores):
                self.top_n = len(nodes)
                self._nodes = nodes
                self._scores = scores

            def postprocess_nodes(self, nodes, query_bundle):
                # Mutate each node's score to CE logit (in-place on the passed list)
                slug_to_ce = self._scores
                for n in nodes:
                    n.score = slug_to_ce.get(n.node.metadata["slug"], 0.0)
                # Sort descending by CE score (in-place on the passed list)
                nodes.sort(key=lambda n: n.score, reverse=True)
                return nodes

        return _MockReranker(fused_nodes, ce_scores_by_slug)

    def test_rerank_mode_discards_rrf_consensus_slug(self):
        """rerank mode keeps cross-encoder top-1 slug (CE-only ordering).

        slug-a is RRF rank 1, CE rank 2 (CE score 0.05).
        slug-b is RRF rank 2, CE rank 3 (CE score 0.01).
        slug-c is RRF rank 3, CE rank 1 (CE score 0.95).
        With top_n=1, rerank mode keeps slug-c (CE #1) and discards slug-a (RRF #1).
        """
        fused = self._make_fused_nodes([
            (1.0 / 60, "slug-a"),
            (1.0 / 61, "slug-b"),
            (1.0 / 62, "slug-c"),
        ])

        class _CR:
            is_built = True
            domains = ["x"]

            def __init__(self, nd):
                self._nodes = nd

            def as_retriever(self, _k):
                return self

            def retrieve(self, _q):
                from copy import deepcopy
                return deepcopy(self._nodes)

        class _MR:
            def __init__(self):
                self.top_n = 3

            def postprocess_nodes(self, nodes, query_bundle):
                slug_to_ce = {"slug-a": 0.05, "slug-b": 0.01, "slug-c": 0.95}
                for n in nodes:
                    n.score = slug_to_ce[n.node.metadata["slug"]]
                nodes.sort(key=lambda n: n.score, reverse=True)
                return nodes

        class _ML:
            _loaded = True

            def filter_by_domain(self, domain):
                return [{
                    "name": domain, "context": "T", "category": "a",
                    "benefits": [], "tradeoffs": [], "quality_attributes": {},
                    "suitable_domains": [],
                }]

            def get_by_name(self, _n):
                return None

        dr = _CR(fused)
        br = _CR([])
        retriever = HybridPatternRetriever(
            bm25_index=br, vector_index=dr, pattern_loader=_ML(),
            rerank_top_n=1,
            reranker_config=MagicMock(base_url="http://x", timeout=30.0, max_batch_size=48),
            rerank_selection="rerank",
        )
        retriever._dense_retriever = dr
        retriever._bm25_retriever = br
        mock = _MR()
        with patch("src.patterns.retriever.TextEmbeddingInference", return_value=mock):
            result = retriever.retrieve("microservices", "microservices")
        assert len(result.patterns) == 1
        assert result.patterns[0][0]["name"] == "slug-c"

    def test_rank_fusion_keeps_rrf_consensus_slug(self):
        """rank_fusion keeps RRF top-1 slug instead of CE top-1.

        slug-a is RRF rank 1, CE rank 2 (blended = 1/60 + 1/61 ≈ 0.033).
        slug-c is RRF rank 3, CE rank 1 (blended = 1/62 + 1/60 ≈ 0.033).
        slug-a wins the blend and survives the top-1 cut.
        """
        fused = self._make_fused_nodes([
            (1.0 / 60, "slug-a"),
            (1.0 / 61, "slug-b"),
            (1.0 / 62, "slug-c"),
        ])

        class _CR:
            is_built = True
            domains = ["x"]

            def __init__(self, nd):
                self._nodes = nd

            def as_retriever(self, _k):
                return self

            def retrieve(self, _q):
                from copy import deepcopy
                return deepcopy(self._nodes)

        class _MR:
            def __init__(self):
                self.top_n = 3

            def postprocess_nodes(self, nodes, query_bundle):
                slug_to_ce = {"slug-a": 0.05, "slug-b": 0.01, "slug-c": 0.95}
                for n in nodes:
                    n.score = slug_to_ce[n.node.metadata["slug"]]
                nodes.sort(key=lambda n: n.score, reverse=True)
                return nodes

        class _ML:
            _loaded = True

            def filter_by_domain(self, domain):
                return [{
                    "name": domain, "context": "T", "category": "a",
                    "benefits": [], "tradeoffs": [], "quality_attributes": {},
                    "suitable_domains": [],
                }]

            def get_by_name(self, _n):
                return None

        dr = _CR(fused)
        br = _CR([])
        retriever = HybridPatternRetriever(
            bm25_index=br, vector_index=dr, pattern_loader=_ML(),
            rerank_top_n=1,
            reranker_config=MagicMock(base_url="http://x", timeout=30.0, max_batch_size=48),
            rerank_selection="rank_fusion",
        )
        retriever._dense_retriever = dr
        retriever._bm25_retriever = br
        mock = _MR()
        with patch("src.patterns.retriever.TextEmbeddingInference", return_value=mock):
            result = retriever.retrieve("microservices", "microservices")
        assert len(result.patterns) == 1
        assert result.patterns[0][0]["name"] == "slug-a"

    def test_rank_fusion_reports_blended_scores(self):
        """In rank_fusion mode, fusion_score IS the blended RR(rrf)+RR(ce) score."""
        fused = self._make_fused_nodes([
            (1.0 / 60, "slug-a"),
            (1.0 / 61, "slug-b"),
            (1.0 / 62, "slug-c"),
        ])

        class _CR:
            is_built = True
            domains = ["x"]

            def __init__(self, nd):
                self._nodes = nd

            def as_retriever(self, _k):
                return self

            def retrieve(self, _q):
                from copy import deepcopy
                return deepcopy(self._nodes)

        class _MR:
            def __init__(self):
                self.top_n = 3

            def postprocess_nodes(self, nodes, query_bundle):
                slug_to_ce = {"slug-a": 0.05, "slug-b": 0.01, "slug-c": 0.95}
                for n in nodes:
                    n.score = slug_to_ce[n.node.metadata["slug"]]
                nodes.sort(key=lambda n: n.score, reverse=True)
                return nodes

        class _ML:
            _loaded = True

            def filter_by_domain(self, domain):
                return [{
                    "name": domain, "context": "T", "category": "a",
                    "benefits": [], "tradeoffs": [], "quality_attributes": {},
                    "suitable_domains": [],
                }]

            def get_by_name(self, _n):
                return None

        dr = _CR(fused)
        br = _CR([])
        retriever = HybridPatternRetriever(
            bm25_index=br, vector_index=dr, pattern_loader=_ML(),
            rerank_top_n=3,
            reranker_config=MagicMock(base_url="http://x", timeout=30.0, max_batch_size=48),
            rerank_selection="rank_fusion",
        )
        retriever._dense_retriever = dr
        retriever._bm25_retriever = br
        mock = _MR()
        with patch("src.patterns.retriever.TextEmbeddingInference", return_value=mock):
            result = retriever.retrieve("microservices", "microservices")
        blend_a = 1.0 / 60 + 1.0 / 61
        blend_c = 1.0 / 62 + 1.0 / 60
        blend_b = 1.0 / 61 + 1.0 / 62
        assert len(result.matched_domains) == 3
        assert result.matched_domains[0].slug == "slug-a"
        assert result.matched_domains[0].fusion_score == pytest.approx(blend_a)
        assert result.matched_domains[0].rerank_score == pytest.approx(0.05)
        assert result.matched_domains[1].slug == "slug-c"
        assert result.matched_domains[1].fusion_score == pytest.approx(blend_c)
        assert result.matched_domains[1].rerank_score == pytest.approx(0.95)
        assert result.matched_domains[2].slug == "slug-b"
        assert result.matched_domains[2].fusion_score == pytest.approx(blend_b)
        assert result.matched_domains[2].rerank_score == pytest.approx(0.01)
        assert len(result.patterns) == 3
        assert result.patterns[0][0]["name"] == "slug-a"
        assert result.patterns[0][1] == pytest.approx(blend_a)
        assert result.patterns[0][0]["rerank_logit"] == pytest.approx(0.05)

    def test_rerank_mode_default_unchanged(self):
        """Default rerank_selection='rerank' produces CE-only ordering (regression)."""
        fused = self._make_fused_nodes([
            (1.0 / 60, "slug-a"),
            (1.0 / 75, "slug-b"),
        ])

        class _ConcreteRetriever:
            def __init__(self, nodes):
                self._nodes = nodes

            def as_retriever(self, _k):
                return self

            def retrieve(self, _q):
                return list(self._nodes)

        class _MockReranker:
            def __init__(self):
                self.top_n = 3

            def postprocess_nodes(self, nodes, query_bundle):
                slug_to_ce = {"slug-a": 0.05, "slug-b": 0.01, "slug-c": 0.95}
                for n in nodes:
                    n.score = slug_to_ce[n.node.metadata["slug"]]
                nodes.sort(key=lambda n: n.score, reverse=True)
                return nodes

        class _MockLoader:
            _loaded = True

            def filter_by_domain(self, domain):
                return [
                    {
                        "name": domain,
                        "context": "Test.",
                        "category": "architectural",
                        "benefits": [],
                        "tradeoffs": [],
                        "quality_attributes": {},
                        "suitable_domains": [],
                    }
                ]

            def get_by_name(self, _n):
                return None

        dense_retriever = _ConcreteRetriever(fused)
        bm25_retriever = _ConcreteRetriever([])

        for selection_mode in ("rerank", "rank_fusion"):
            retriever = HybridPatternRetriever(
                bm25_index=bm25_retriever,
                vector_index=dense_retriever,
                pattern_loader=_MockLoader(),
                rerank_top_n=1,
                reranker_config=MagicMock(
                    base_url="http://localhost:8080", timeout=30.0, max_batch_size=48
                ),
                rerank_selection=selection_mode,
            )
            retriever._dense_retriever = dense_retriever
            retriever._bm25_retriever = bm25_retriever
            mock = _MockReranker()
            with patch(
                "src.patterns.retriever.TextEmbeddingInference",
                return_value=mock,
            ):
                result = retriever.retrieve(
                    user_domain="microservices", normalized_domain="microservices"
                )
            assert result.patterns[0][0]["name"] == "slug-a"

    def test_rank_fusion_noop_when_pool_le_topn(self):
        """When pool size <= rerank_top_n, rank_fusion produces identical survivors to rerank mode (cut is a no-op)."""
        fused = self._make_fused_nodes([
            (1.0 / 60, "slug-a"),
            (1.0 / 61, "slug-b"),
        ])

        class _CR:
            def __init__(self, nd):
                self._nodes = nd
            def as_retriever(self, _k): return self
            def retrieve(self, _q):
                from copy import deepcopy
                return deepcopy(self._nodes)

        class _MR:
            def __init__(self):
                self.top_n = 2
            def postprocess_nodes(self, nodes, query_bundle):
                slug_to_ce = {"slug-a": 0.05, "slug-b": 0.95}
                for n in nodes:
                    n.score = slug_to_ce[n.node.metadata["slug"]]
                nodes.sort(key=lambda n: n.score, reverse=True)
                return nodes

        class _ML:
            _loaded = True
            def filter_by_domain(self, domain):
                return [{"name": domain, "context": "T", "category": "a",
                         "benefits": [], "tradeoffs": [], "quality_attributes": {}, "suitable_domains": []}]
            def get_by_name(self, _n): return None

        results = {}
        for mode in ("rerank", "rank_fusion"):
            dr = _CR(fused)
            br = _CR([])
            retriever = HybridPatternRetriever(
                bm25_index=br,
                vector_index=dr,
                pattern_loader=_ML(),
                rerank_top_n=10,
                reranker_config=MagicMock(
                    base_url="http://localhost:8080", timeout=30.0, max_batch_size=48
                ),
                rerank_selection=mode,
            )
            retriever._dense_retriever = dr
            retriever._bm25_retriever = br
            mock = _MR()
            with patch(
                "src.patterns.retriever.TextEmbeddingInference",
                return_value=mock,
            ):
                results[mode] = retriever.retrieve(
                    user_domain="microservices", normalized_domain="microservices"
                )
        assert results["rerank"].patterns == results["rank_fusion"].patterns

    def test_domain_match_carries_rerank_score(self):
        """After reranking, matched_domains entries carry rerank_score (CE logit) alongside fusion_score (RRF)."""
        rrf_a = 1.0 / 60
        rrf_b = 1.0 / 61
        fused = self._make_fused_nodes([(rrf_a, "slug-a"), (rrf_b, "slug-b")])
        ce_logit = 3.7

        class _CR:
            def __init__(self, nd):
                self._nodes = nd
            def as_retriever(self, _k): return self
            def retrieve(self, _q):
                from copy import deepcopy
                return deepcopy(self._nodes)

        class _MR:
            def __init__(self): self.top_n = 2
            def postprocess_nodes(self, nodes, query_bundle):
                for n in nodes:
                    n.score = ce_logit
                return nodes

        class _ML:
            _loaded = True
            def filter_by_domain(self, domain):
                return [{"name": domain, "context": "T", "category": "a",
                         "benefits": [], "tradeoffs": [], "quality_attributes": {}, "suitable_domains": []}]
            def get_by_name(self, _n): return None

        dr = _CR(fused)
        br = _CR([])
        retriever = HybridPatternRetriever(
            bm25_index=br, vector_index=dr, pattern_loader=_ML(),
            rerank_top_n=1,
            reranker_config=MagicMock(base_url="http://x", timeout=30.0, max_batch_size=48),
            rerank_selection="rerank",
        )
        retriever._dense_retriever = dr
        retriever._bm25_retriever = br
        mock = _MR()
        with patch("src.patterns.retriever.TextEmbeddingInference", return_value=mock):
            result = retriever.retrieve("microservices", "microservices")
        assert len(result.matched_domains) >= 1
        assert result.matched_domains[0].slug == "slug-a"
        assert result.matched_domains[0].fusion_score == pytest.approx(rrf_a)
        assert result.matched_domains[0].rerank_score == pytest.approx(ce_logit)

    def test_domain_match_rerank_score_none_without_rerank(self):
        """When reranking is skipped (single candidate), matched_domains
        rerank_score is None."""
        fused = self._make_fused_nodes([(1.0 / 60, "slug-a")])

        class _ConcreteRetriever:
            def __init__(self, nodes):
                self._nodes = nodes

            def as_retriever(self, _k):
                return self

            def retrieve(self, _q):
                return self._nodes

        class _MockLoader:
            _loaded = True

            def filter_by_domain(self, domain):
                return [
                    {
                        "name": domain,
                        "context": "Test.",
                        "category": "architectural",
                        "benefits": [],
                        "tradeoffs": [],
                        "quality_attributes": {},
                        "suitable_domains": [],
                    }
                ]

            def get_by_name(self, _n):
                return None

        dense_retriever = _ConcreteRetriever(fused)
        bm25_retriever = _ConcreteRetriever([])

        retriever = HybridPatternRetriever(
            bm25_index=bm25_retriever,
            vector_index=dense_retriever,
            pattern_loader=_MockLoader(),
            rerank_top_n=1,
            reranker_config=None,
        )
        retriever._dense_retriever = dense_retriever
        retriever._bm25_retriever = bm25_retriever
        result = retriever.retrieve(
            user_domain="microservices", normalized_domain="microservices"
        )
        assert len(result.matched_domains) == 1
        assert result.matched_domains[0].slug == "slug-a"
        assert result.matched_domains[0].rerank_score is None

    def test_pattern_dict_carries_rerank_logit(self):
        """Resolved pattern dicts carry rerank_logit after reranking."""
        rrf_a = 1.0 / 60
        rrf_b = 1.0 / 61
        fused = self._make_fused_nodes([(rrf_a, "slug-a"), (rrf_b, "slug-b")])
        ce_logit = 2.3

        class _CR:
            def __init__(self, nd):
                self._nodes = nd
            def as_retriever(self, _k): return self
            def retrieve(self, _q):
                from copy import deepcopy
                return deepcopy(self._nodes)

        class _MR:
            def __init__(self):
                self.top_n = 2
            def postprocess_nodes(self, nodes, query_bundle):
                for n in nodes:
                    n.score = ce_logit
                return nodes

        class _ML:
            _loaded = True
            def filter_by_domain(self, domain):
                return [{"name": domain, "context": "T", "category": "a",
                         "benefits": [], "tradeoffs": [], "quality_attributes": {}, "suitable_domains": []}]
            def get_by_name(self, _n): return None

        dr = _CR(fused)
        br = _CR([])
        retriever = HybridPatternRetriever(
            bm25_index=br, vector_index=dr, pattern_loader=_ML(),
            rerank_top_n=1,
            reranker_config=MagicMock(base_url="http://x", timeout=30.0, max_batch_size=48),
            rerank_selection="rerank",
        )
        retriever._dense_retriever = dr
        retriever._bm25_retriever = br
        mock = _MR()
        with patch("src.patterns.retriever.TextEmbeddingInference", return_value=mock):
            result = retriever.retrieve("microservices", "microservices")
        assert len(result.patterns) == 1
        pattern_dict = result.patterns[0][0]
        assert "rerank_logit" in pattern_dict
        assert pattern_dict["rerank_logit"] == pytest.approx(ce_logit)
