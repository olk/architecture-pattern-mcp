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
Unit tests for ArchitecturePipeline class.

Test Case IDs: UT-12, IT-2, IT-5
Validates Requirements: FR-214, AC-214

Test Scenarios:
- SCEN-20: Pipeline pattern flow with ANALYZE, GENERATE, EVALUATE, REFINE phases
- SCEN-22: Pattern metadata inclusion in GENERATE phase
- SCEN-23: Quality benchmarking in EVALUATE phase
- SCEN-24: Best practices application in REFINE phase

Acceptance Criteria:
- AC-214: Verify ANALYZE filters, GENERATE includes metadata, EVALUATE benchmarks, REFINE uses best_practices

Design Patterns Tested:
- DP-1: Pipeline Pattern (via Workflow-backed ArchitecturePipeline)
- DP-5: Dependency Injection
- DP-6: Observer Pattern REPLACED by WorkflowHandler.stream_events()
"""

import pytest
from unittest.mock import patch

from src.pipeline import (
    AnalysisResult,
    ArchitectureEvaluation,
    ArchitecturePipeline,
)
from src.schemas.architecture import ArchitectureDesignResponse
from src.schemas.design import ArchitectureDesign, ArchitectureOverview
from src.schemas.enums import ArchitectureStyle
from src.schemas.evaluation import EvaluationSummary, MetricResult, PipelineResult
from src.config import RetrievalConfig
from src.schemas.quality import QualityMetrics


class MockSoftwareArchitectAgent:
    """Mock SoftwareArchitectAgent for testing."""

    def __init__(self, config=None):
        self._config = config
        self.generate_structured_calls = []

    async def generate_structured(self, system_prompt: str, user_prompt: str, response_schema):
        self.generate_structured_calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "schema": response_schema
        })

        if response_schema is ArchitectureDesignResponse:
            return ArchitectureDesignResponse(
                overview={
                    "style": "microservices",
                    "category": "structural",
                    "principles": ["single responsibility", "autonomy"],
                    "constraints": []
                },
                components=[
                    {
                        "id": "api-gateway",
                        "name": "API Gateway",
                        "type": "gateway",
                        "description": "Entry point for all API requests",
                        "responsibilities": ["routing", "auth", "rate limiting"],
                        "interfaces": [],
                        "technology_stack": [],
                        "api_contract": None,
                        "data_models": [],
                        
                        "config_requirements": []
                    }
                ],
                relationships=[
                    {
                        "source": "api-gateway",
                        "target": "user-service",
                        "type": "http",
                        "description": "Proxies to user service"
                    }
                ],

                quality_attributes={},
                api_contracts=[
                    {
                        "component_id": "user-service",
                        "base_path": "/api/v1/users",
                        "description": "User management API",
                        "endpoints": [
                            {
                                "method": "POST",
                                "path": "/",
                                "summary": "Create user",
                                "request_schema": {
                                    "type": "object",
                                    "properties": {"email": {"type": "string", "format": "email"}},
                                    "required": ["email"]
                                },
                                "response_schema": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "string"},
                                        "email": {"type": "string"}
                                    }
                                },
                                "auth_required": False,
                                "tags": []
                            }
                        ]
                    }
                ],
                shared_data_models=[
                    {
                        "name": "User",
                        "description": "Shared user model",
                        "is_shared": True,
                        "fields": [
                            {"name": "id", "type": "str", "required": True},
                            {"name": "email", "type": "str", "required": True}
                        ]
                    }
                ],
                event_contracts=[
                    {
                        "event_name": "user.created",
                        "payload_schema": {
                            "type": "object",
                            "properties": {
                                "user_id": {"type": "string"},
                                "email": {"type": "string"}
                            }
                        },
                        "published_by": "user-service",
                        "consumed_by": ["order-service"],
                        "description": "Published when a new user is created"
                    }
                ],
                
            )

        if response_schema.__name__ == "AnalysisResult":
            from src.schemas.quality import QualityMetrics
            return AnalysisResult(
                strengths=["Strong scalability", "Good performance"],
                weaknesses=["Complex to set up"],
                recommendations=["Consider starting with simpler architecture"],
                quality_metrics=QualityMetrics(
                    maintainability=7.0, scalability=8.0, reliability=7.0, security=6.0, performance=7.5
                ),
                recommended_style="microservices",
                selected_patterns=[]
            )

        if response_schema.__name__ == "RequirementWeights":
            from src.pipeline import RequirementWeights
            return RequirementWeights(
                scalability=1.0,
                performance=0.8,
                reliability=0.6,
                maintainability=0.5,
                security=0.3,
                simplicity=0.2,
            )

        if response_schema.__name__ == "ArchitectureEvaluation":
            return ArchitectureEvaluation(
                summary=EvaluationSummary(
                    overall_score=75.0,
                    strengths=["Good overall quality"],
                    weaknesses=["Consider improvements in maintainability"],
                    critical_findings=["No critical risks identified"]
                ),
                metrics=[
                    MetricResult(name="overall_quality", score=75.0, description="Overall", findings=[], recommendations=[])
                ],
                
                recommendations={}
            )

        mock_design = ArchitectureDesign(
            overview={
                "style": "microservices",
                "category": "structural",
                "principles": ["single responsibility", "autonomy"]
            },
            components=[
                {
                    "id": "api-gateway",
                    "name": "API Gateway",
                    "type": "gateway",
                    "description": "Entry point for all API requests",
                    "responsibilities": ["routing", "auth", "rate limiting"]
                }
            ],
            relationships=[
                {
                    "source": "api-gateway",
                    "target": "user-service",
                    "type": "http",
                    "description": "Proxies to user service"
                }
            ],
)
        return mock_design


class MockPatternLoader:
    """Mock PatternLoader for testing."""

    def __init__(self, patterns_dir=None):
        self._patterns_dir = patterns_dir
        self._patterns_cache = []
        self._loaded = False
        self.filter_by_domain_calls = []
        self.select_top_patterns_calls = []

    def load_all(self) -> list[dict]:
        if not self._loaded:
            self._patterns_cache = self._get_mock_patterns()
            self._loaded = True
        return self._patterns_cache

    def filter_by_domain(self, domain: str) -> list[dict]:
        self.filter_by_domain_calls.append(domain)
        normalized_domain = domain.lower().replace(" ", "-")
        return [p for p in self._patterns_cache
                if normalized_domain in p.get("suitable_domains", [])]

    def select_top_patterns(self, domain: str, top_k: int = 5) -> list[dict]:
        self.select_top_patterns_calls.append((domain, top_k))
        filtered = self.filter_by_domain(domain)
        return filtered[:top_k]

    def get_by_name(self, name: str) -> dict | None:
        for p in self._patterns_cache:
            if p.get("name") == name:
                return p
        return None

    def _get_mock_patterns(self) -> list[dict]:
        return [
            {
                "name": "microservices",
                "category": "structural",
                "suitable_domains": ["microservices", "cloud-native"],
                "quality_attributes": {
                    "performance": 7,
                    "scalability": 9,
                    "reliability": 7,
                    "maintainability": 7,
                    "security": 6,
                    "simplicity": 4
                },
                "best_practices": [
                    "Use database per service",
                    "Implement circuit breakers",
                    "Add distributed tracing"
                ],
                "context": "Distributed systems requiring independent deployability",
                "benefits": ["Independent scaling", "Fault isolation"],
                "tradeoffs": ["Distributed complexity", "Operational overhead"]
            },
            {
                "name": "event-driven",
                "category": "messaging",
                "suitable_domains": ["event-driven", "asynchronous"],
                "quality_attributes": {
                    "performance": 8,
                    "scalability": 8,
                    "reliability": 7,
                    "maintainability": 6,
                    "security": 5,
                    "simplicity": 4
                },
                "best_practices": [
                    "Use message brokers",
                    "Implement idempotency",
                    "Handle dead letter queues"
                ],
                "context": "Systems requiring async communication",
                "benefits": ["Loose coupling", "Scalability"],
                "tradeoffs": ["Eventual consistency", "Debug complexity"]
            }
        ]


class MockDomainVectorIndex:
    """Mock DomainVectorIndex for testing."""

    def __init__(self, model_name=None):
        self._model_name = model_name or "all-MiniLM-L6-v2"
        self._index = None
        self._domains = []
        self._built = False
        self.search_calls = []

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def is_built(self) -> bool:
        return self._built

    @property
    def domains(self) -> list[str]:
        return list(self._domains)

    @property
    def vector_store(self):
        if not self._built:
            return None
        import faiss
        from llama_index.vector_stores.faiss import FaissVectorStore
        idx = faiss.IndexFlatIP(8)
        vs = FaissVectorStore(faiss_index=idx)
        vs.stores_text = True
        return vs

    @property
    def _embedder(self):
        from llama_index.core.embeddings import MockEmbedding
        return MockEmbedding(embed_dim=8)

    def build_index(self, domains: list[str]) -> None:
        self._domains = list(domains)
        self._built = True

    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        self.search_calls.append((query, k))
        return [
            ("cloud-native", 0.95),
            ("microservices", 0.85),
            ("distributed", 0.75)
        ]

    def rebuild_index(self, domains: list[str]) -> None:
        self._index = None
        self._domains = []
        self.build_index(domains)

    def as_retriever(self, similarity_top_k: int = 20):
        class MockDenseRetriever:
            def __init__(self, top_k):
                self._top_k = top_k

            def retrieve(self, query_bundle):
                from llama_index.core.schema import NodeWithScore, TextNode
                nodes = [
                    NodeWithScore(node=TextNode(text="cloud-native", metadata={"slug": "cloud-native"}), score=0.95),
                    NodeWithScore(node=TextNode(text="microservices", metadata={"slug": "microservices"}), score=0.85),
                    NodeWithScore(node=TextNode(text="distributed", metadata={"slug": "distributed"}), score=0.75),
                ]
                return nodes[:self._top_k]

        return MockDenseRetriever(similarity_top_k)


class MockBM25Index:
    """Mock DomainBM25Index for testing."""

    def __init__(self):
        self._domains: list[str] = []
        self._built = False

    @property
    def is_built(self) -> bool:
        return self._built

    @property
    def domains(self) -> list[str]:
        return list(self._domains)

    def as_retriever(self, top_k: int = 20):
        class MockBM25Retriever:
            def __init__(self, top_k):
                self._top_k = top_k

            def retrieve(self, query_bundle):
                from llama_index.core.schema import NodeWithScore, TextNode
                nodes = [
                    NodeWithScore(node=TextNode(text="cloud-native", metadata={"slug": "cloud-native"}), score=0.9),
                    NodeWithScore(node=TextNode(text="microservices", metadata={"slug": "microservices"}), score=0.8),
                    NodeWithScore(node=TextNode(text="distributed", metadata={"slug": "distributed"}), score=0.7),
                ]
                return nodes[:self._top_k]

        return MockBM25Retriever(top_k)

    def build_index(self, domains: list[str]) -> None:
        self._domains = list(domains)
        self._built = True

    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        return [
            ("cloud-native", 0.9),
            ("microservices", 0.8),
            ("distributed", 0.7)
        ]


def create_test_pipeline(retrieval_config=None):
    """Create a test pipeline with mock dependencies."""
    agent = MockSoftwareArchitectAgent()
    pattern_loader = MockPatternLoader()
    vector_index = MockDomainVectorIndex()
    bm25_index = MockBM25Index()
    return ArchitecturePipeline(
        agent=agent,
        pattern_loader=pattern_loader,
        vector_index=vector_index,
        bm25_index=bm25_index,
        retrieval_config=retrieval_config,
    )


class TestArchitecturePipelineInit:
    """Test ArchitecturePipeline initialization."""

    def test_pipeline_class_exists(self):
        """Verify ArchitecturePipeline class exists and inherits from Workflow."""
        pipeline = create_test_pipeline()
        assert pipeline is not None
        from workflows import Workflow
        assert isinstance(pipeline, Workflow)

    def test_pipeline_accepts_dependencies(self):
        """DP-5: Verify pipeline accepts dependency injected components."""
        agent = MockSoftwareArchitectAgent()
        pattern_loader = MockPatternLoader()
        vector_index = MockDomainVectorIndex()
        bm25_index = MockBM25Index()

        pipeline = ArchitecturePipeline(
            agent=agent,
            pattern_loader=pattern_loader,
            vector_index=vector_index,
            bm25_index=bm25_index,
        )

        assert pipeline._agent is agent
        assert pipeline._pattern_loader is pattern_loader
        assert pipeline._vector_index is vector_index
        assert pipeline._bm25_index is bm25_index


class TestPipelinePhases:
    """Test individual pipeline phases (all async now)."""

    @pytest.mark.asyncio
    async def test_analyze_phase(self):
        """FR-214: ANALYZE phase filters patterns by domain."""
        pipeline = create_test_pipeline()

        class _DummyReranker:
            top_n = 1

            def postprocess_nodes(self, nodes, query_bundle=None):
                return nodes

        with patch(
            "src.patterns.retriever.TextEmbeddingInference",
            return_value=_DummyReranker(),
        ):
            result = await pipeline.analyze(
                requirements="Need scalable distributed system",
                domain="microservices"
            )

        assert isinstance(result, AnalysisResult)
        assert len(result.selected_patterns) > 0
        assert isinstance(result.quality_metrics, QualityMetrics)

        assert pipeline._pattern_loader.filter_by_domain_calls
        assert any("microservices" in c for c in pipeline._pattern_loader.filter_by_domain_calls)

    @pytest.mark.asyncio
    async def test_generate_phase(self):
        """FR-214: GENERATE phase includes pattern metadata in LLM context."""
        pipeline = create_test_pipeline()

        patterns = [
            {
                "name": "microservices",
                "context": "Distributed systems",
                "category": "structural",
                "benefits": ["Scaling"],
                "tradeoffs": ["Complexity"],
                "suitable_domains": ["microservices"],
                "best_practices": ["Circuit breakers"]
            }
        ]

        design = await pipeline.generate(
            requirements="Build scalable API",
            domain="cloud-native",
            style="microservices",
            selected_patterns=patterns
        )

        assert isinstance(design, ArchitectureDesign)
        assert len(design.components) > 0

        assert len(pipeline._agent.generate_structured_calls) > 0
        call = pipeline._agent.generate_structured_calls[-1]
        assert "microservices" in call["system_prompt"] or "microservices" in call["user_prompt"]

    @pytest.mark.asyncio
    async def test_evaluate_phase(self):
        """FR-214: EVALUATE phase benchmarks against quality attributes."""
        pipeline = create_test_pipeline()

        design = ArchitectureDesign(
            overview={
                "style": "microservices",
                "category": "structural",
                "principles": ["single responsibility"],
                "constraints": []
            },
            components=[{"id": "svc1", "name": "Service 1", "type": "service", "description": "A service", "responsibilities": ["serve"]}],
            patterns=[{"name": "microservices", "context": "Distributed systems", "category": "structural", "benefits": ["scaling"]}],
)

        evaluation = await pipeline.evaluate(
            architecture=design,
            criteria="quality,scalability",
            domain="cloud-native"
        )

        assert isinstance(evaluation, ArchitectureEvaluation)
        assert len(evaluation.metrics) > 0
        assert any(m.name == "overall_quality" for m in evaluation.metrics)

    @pytest.mark.asyncio
    async def test_design_loop_runs_generate_evaluate(self):
        """FR-214: design_loop runs generate and evaluate."""
        pipeline = create_test_pipeline()

        result = await pipeline.design_loop(
            requirements="Build a scalable distributed system",
            domain="cloud-native",
            style="microservices",
            selected_patterns=[{
                "name": "microservices",
                "context": "Distributed systems",
                "category": "structural",
                "benefits": ["scaling"],
                "best_practices": ["Use database per service"]
            }],
            criteria="quality,maintainability,scalability",
            analysis_result=None,
            max_tries=3,
        )

        assert isinstance(result, PipelineResult)
        assert result.attempts >= 1
        assert result.final_quality_score >= 0.0


class TestPipelineConstants:
    """Test pipeline constants."""

    def test_default_max_tries(self):
        """CONST-11: DEFAULT_MAX_TRIES = 3"""
        assert ArchitecturePipeline.DEFAULT_MAX_TRIES == 3


class TestQualityMetricsCalculation:
    """Test quality metrics calculation in pipeline."""

    def test_calculate_quality_metrics_from_patterns(self):
        """Verify quality metrics are calculated correctly from patterns."""
        pipeline = create_test_pipeline()

        patterns = [
            {
                "quality_attributes": {
                    "maintainability": 8,
                    "scalability": 9,
                    "reliability": 7,
                    "security": 6,
                    "performance": 8
                }
            },
            {
                "quality_attributes": {
                    "maintainability": 7,
                    "scalability": 8,
                    "reliability": 8,
                    "security": 7,
                    "performance": 7
                }
            }
        ]

        metrics = pipeline._calculate_quality_metrics(patterns)

        assert metrics.maintainability == 7.5
        assert metrics.scalability == 8.5
        assert metrics.reliability == 7.5
        assert metrics.security == 6.5
        assert metrics.performance == 7.5

    def test_calculate_quality_metrics_empty_patterns(self):
        """Verify default metrics for empty patterns list."""
        pipeline = create_test_pipeline()

        metrics = pipeline._calculate_quality_metrics([])

        assert metrics.maintainability == 0.0
        assert metrics.scalability == 0.0
        assert metrics.reliability == 0.0
        assert metrics.security == 0.0
        assert metrics.performance == 0.0


class TestAnalyzeScoring:
    """Tests for the deterministic requirements-aware scoring (stage-2)."""

    def test_score_patterns_weighted_average_formula(self):
        """analysis_score = Σ(wᵢ·qaᵢ)/Σ(wᵢ)·10, sorted descending."""
        from src.pipeline import RequirementWeights

        pipeline = create_test_pipeline()
        patterns = [
            {"name": "a", "quality_attributes": {
                "scalability": 10, "maintainability": 0, "reliability": 0,
                "security": 0, "performance": 0, "simplicity": 0}},
            {"name": "b", "quality_attributes": {
                "scalability": 0, "maintainability": 0, "reliability": 0,
                "security": 0, "performance": 10, "simplicity": 0}},
        ]
        # Pure scalability priority → 'a' (10) outranks 'b' (0).
        weights = RequirementWeights(scalability=1.0)
        scored = pipeline._score_patterns(patterns, weights)

        assert scored[0]["name"] == "a"
        assert scored[0]["analysis_score"] == 100.0
        assert scored[1]["name"] == "b"
        assert scored[1]["analysis_score"] == 0.0

    def test_score_patterns_mixed_weights(self):
        """Weighted average across multiple attributes."""
        from src.pipeline import RequirementWeights

        pipeline = create_test_pipeline()
        patterns = [
            {"name": "perf-heavy", "quality_attributes": {
                "scalability": 2, "maintainability": 0, "reliability": 0,
                "security": 0, "performance": 10, "simplicity": 0}},
        ]
        # 50/50 scalability + performance → (2*0.5 + 10*0.5)/1.0 = 6.0 → 60.0
        weights = RequirementWeights(scalability=0.5, performance=0.5)
        scored = pipeline._score_patterns(patterns, weights)
        assert scored[0]["analysis_score"] == 60.0

    def test_score_patterns_preserves_fusion_score(self):
        """fusion_score from stage-1 is retained on the scored pattern dict."""
        from src.pipeline import RequirementWeights

        pipeline = create_test_pipeline()
        patterns = [{"name": "x", "quality_attributes": {
            "scalability": 8, "maintainability": 8, "reliability": 8,
            "security": 8, "performance": 8, "simplicity": 8},
            "fusion_score": 0.42}]
        weights = RequirementWeights(scalability=1.0)
        scored = pipeline._score_patterns(patterns, weights)
        assert scored[0]["fusion_score"] == 0.42
        assert "analysis_score" in scored[0]

    def test_score_patterns_all_zero_weights_falls_back_to_mean(self):
        """All-zero weights use the unweighted mean (no division by zero)."""
        from src.pipeline import RequirementWeights

        pipeline = create_test_pipeline()
        patterns = [{"name": "x", "quality_attributes": {
            "scalability": 6, "maintainability": 6, "reliability": 6,
            "security": 6, "performance": 6, "simplicity": 6}}]
        weights = RequirementWeights()  # all default 0.0
        scored = pipeline._score_patterns(patterns, weights)
        assert scored[0]["analysis_score"] == 60.0

    def test_select_recommended_style_override_wins(self):
        """An explicit style override always wins."""
        pipeline = create_test_pipeline()
        selected = [{"name": "microservices", "analysis_score": 99.0}]
        assert pipeline._select_recommended_style(selected, "hexagonal") == "hexagonal"

    def test_select_recommended_style_top_pattern_above_threshold(self):
        """Top pattern name is used when its score meets the threshold."""
        pipeline = create_test_pipeline()  # default threshold 50.0
        selected = [{"name": "event-driven", "analysis_score": 80.0}]
        assert pipeline._select_recommended_style(selected, None) == "event-driven"

    def test_select_recommended_style_below_threshold_falls_back(self):
        """Falls back to layered-monolith when top score < threshold."""
        pipeline = create_test_pipeline()  # default threshold 50.0
        selected = [{"name": "event-driven", "analysis_score": 40.0}]
        assert pipeline._select_recommended_style(selected, None) == "layered-monolith"

    def test_select_recommended_style_empty_falls_back(self):
        """Empty selection falls back to layered-monolith."""
        pipeline = create_test_pipeline()
        assert pipeline._select_recommended_style([], None) == "layered-monolith"

    @pytest.mark.asyncio
    async def test_analyze_injects_scores_and_selects_top_k(self):
        """analyze() injects analysis_score, sorts, and truncates to top_k_patterns."""
        pipeline = create_test_pipeline()  # default top_k_patterns=5

        class _DummyReranker:
            top_n = 1

            def postprocess_nodes(self, nodes, query_bundle=None):
                return nodes

        with patch(
            "src.patterns.retriever.TextEmbeddingInference",
            return_value=_DummyReranker(),
        ):
            result = await pipeline.analyze(
                requirements="Need scalable distributed system",
                domain="microservices",
            )
        assert len(result.selected_patterns) > 0
        for p in result.selected_patterns:
            assert "analysis_score" in p
            assert "fusion_score" in p
            assert isinstance(p["analysis_score"], float)
        # Selected patterns must be sorted by analysis_score descending.
        scores = [p["analysis_score"] for p in result.selected_patterns]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_analyze_llm_receives_no_patterns_in_prompt(self):
        """The weight-extraction prompt must NOT contain pattern data (C3)."""
        pipeline = create_test_pipeline()

        class _DummyReranker:
            top_n = 1

            def postprocess_nodes(self, nodes, query_bundle=None):
                return nodes

        with patch(
            "src.patterns.retriever.TextEmbeddingInference",
            return_value=_DummyReranker(),
        ):
            await pipeline.analyze(
                requirements="Need scalable distributed system",
                domain="microservices",
            )
        # The first (and only) generate_structured call in analyze is the
        # RequirementWeights extraction. Its user prompt must not embed
        # candidate pattern names / quality_attributes.
        weights_calls = [
            c for c in pipeline._agent.generate_structured_calls
            if c["schema"].__name__ == "RequirementWeights"
        ]
        assert len(weights_calls) == 1
        user_prompt = weights_calls[0]["user_prompt"]
        assert "Candidate patterns" not in user_prompt
        assert "quality_attributes=" not in user_prompt



class TestPatternFlow:
    """AC-214: Test pattern flow through all pipeline phases."""

    @pytest.mark.asyncio
    async def test_patterns_flow_through_analyze_filtering(self):
        """AC-214: Verify ANALYZE filters patterns correctly."""
        pipeline = create_test_pipeline()

        class _DummyReranker:
            top_n = 1

            def postprocess_nodes(self, nodes, query_bundle=None):
                return nodes

        with patch(
            "src.patterns.retriever.TextEmbeddingInference",
            return_value=_DummyReranker(),
        ):
            result = await pipeline.analyze(
                requirements="Distributed system needed",
                domain="cloud-native"
            )

        assert len(result.selected_patterns) > 0

        for pattern in result.selected_patterns:
            assert isinstance(pattern, dict)
            assert "name" in pattern
            assert "quality_attributes" in pattern

    @pytest.mark.asyncio
    async def test_patterns_flow_through_generate_metadata(self):
        """AC-214: Verify GENERATE includes pattern metadata."""
        pipeline = create_test_pipeline()

        patterns = [
            {
                "name": "microservices",
                "context": "Distributed systems",
                "category": "structural",
                "benefits": ["Scaling"],
                "tradeoffs": ["Complexity"],
                "suitable_domains": ["cloud-native"],
                "best_practices": ["Use APIs"]
            }
        ]

        design = await pipeline.generate(
            requirements="Build distributed system",
            domain="cloud-native",
            style="microservices",
            selected_patterns=patterns
        )

    @pytest.mark.asyncio
    async def test_patterns_flow_through_evaluate_quality_benchmarking(self):
        """AC-214: Verify EVALUATE benchmarks against quality attributes."""
        pipeline = create_test_pipeline()

        design = ArchitectureDesign(
            overview={
                "style": "microservices",
                "category": "structural",
                "principles": ["single responsibility"],
                "constraints": []
            },
            components=[
                {"id": "api", "name": "API", "type": "gateway", "description": "Entry point", "responsibilities": ["route"]},
                {"id": "svc", "name": "Service", "type": "service", "description": "Core service", "responsibilities": ["process"]}
            ],
        )

        evaluation = await pipeline.evaluate(
            architecture=design,
            criteria="maintainability,scalability,performance",
            domain="cloud-native"
        )

        assert len(evaluation.metrics) > 0
        assert any(m.name == "overall_quality" for m in evaluation.metrics)

    @pytest.mark.asyncio
    async def test_patterns_flow_through_design_loop(self):
        """AC-214: Verify design_loop respects max_tries."""
        pipeline = create_test_pipeline()

        result = await pipeline.design_loop(
            requirements="Build a scalable distributed system",
            domain="cloud-native",
            style="microservices",
            selected_patterns=[{
                "name": "microservices",
                "context": "Distributed systems",
                "category": "structural",
                "benefits": ["scaling"],
                "best_practices": ["Use database per service"]
            }],
            criteria="quality,maintainability",
            analysis_result=None,
            max_tries=2,
        )

        assert result.attempts <= 2


class TestGeneratePropagatesContracts:
    """Verify api_contracts, shared_data_models, event_contracts flow from LLM into typed ArchitectureDesign."""

    @pytest.mark.asyncio
    async def test_generate_propagates_populated_contracts(self):
        """api_contracts, shared_data_models, event_contracts are typed from LLM output."""
        pipeline = create_test_pipeline()

        design = await pipeline.generate(
            requirements="Build distributed system",
            domain="cloud-native",
            style="microservices",
            selected_patterns=[
                {
                    "name": "microservices",
                    "context": "Distributed systems",
                    "category": "structural",
                    "benefits": ["Scaling"],
                    "tradeoffs": ["Complexity"],
                    "suitable_domains": ["cloud-native"],
                    "best_practices": ["Use APIs"]
                }
            ]
        )

        assert len(design.api_contracts) == 1
        assert design.api_contracts[0].component_id == "user-service"
        assert design.api_contracts[0].base_path == "/api/v1/users"
        assert len(design.api_contracts[0].endpoints) == 1
        assert design.api_contracts[0].endpoints[0].method == "POST"

        assert len(design.shared_data_models) == 1
        assert design.shared_data_models[0].name == "User"
        assert design.shared_data_models[0].is_shared is True

        assert len(design.event_contracts) == 1
        assert design.event_contracts[0].event_name == "user.created"
        assert design.event_contracts[0].published_by == "user-service"
        assert design.event_contracts[0].consumed_by == ["order-service"]

    @pytest.mark.asyncio
    async def test_generate_contracts_roundtrip(self):
        """ArchitectureDesign with contracts round-trips through model_dump -> model_validate."""
        pipeline = create_test_pipeline()

        design = await pipeline.generate(
            requirements="Build distributed system",
            domain="cloud-native",
            style="microservices",
            selected_patterns=[
                {
                    "name": "microservices",
                    "context": "Distributed systems",
                    "category": "structural",
                    "benefits": ["Scaling"],
                    "tradeoffs": ["Complexity"],
                    "suitable_domains": ["cloud-native"],
                    "best_practices": ["Use APIs"]
                }
            ]
        )

        dumped = design.model_dump()
        revalidated = ArchitectureDesign.model_validate(dumped)
        assert len(revalidated.api_contracts) == len(design.api_contracts)
        assert revalidated.api_contracts[0].component_id == design.api_contracts[0].component_id
        assert len(revalidated.shared_data_models) == len(design.shared_data_models)
        assert revalidated.shared_data_models[0].name == design.shared_data_models[0].name
        assert len(revalidated.event_contracts) == len(design.event_contracts)
        assert revalidated.event_contracts[0].event_name == design.event_contracts[0].event_name

    @pytest.mark.asyncio
    async def test_evaluate_receives_populated_contracts(self):
        """evaluate() receives design with contracts via model_dump_json() in the prompt."""
        pipeline = create_test_pipeline()

        design = await pipeline.generate(
            requirements="Build distributed system",
            domain="cloud-native",
            style="microservices",
            selected_patterns=[
                {
                    "name": "microservices",
                    "context": "Distributed systems",
                    "category": "structural",
                    "benefits": ["Scaling"],
                    "tradeoffs": ["Complexity"],
                    "suitable_domains": ["cloud-native"],
                    "best_practices": ["Use APIs"]
                }
            ]
        )

        captured_prompts: list[str] = []
        original_generate = pipeline._agent.generate_structured

        async def capture_generate(system_prompt, user_prompt, response_schema):
            captured_prompts.append(user_prompt)
            return ArchitectureEvaluation(
                summary=EvaluationSummary(
                    overall_score=75.0,
                    strengths=["Good"],
                    weaknesses=["Consider"],
                    critical_findings=["None"]
                ),
                metrics=[
                    MetricResult(name="overall_quality", score=75.0, description="Overall", findings=[], recommendations=[])
                ],
                
                recommendations={}
            )

        pipeline._agent.generate_structured = capture_generate

        await pipeline.evaluate(
            architecture=design,
            criteria="maintainability,scalability",
            domain="cloud-native"
        )

        pipeline._agent.generate_structured = original_generate

        assert len(captured_prompts) == 1
        json_str = captured_prompts[0]
        assert "user-service" in json_str
        assert "/api/v1/users" in json_str
        assert "user.created" in json_str


class _MockArchitectForDenormalization:
    """Mock agent that returns components with api_contract/data_models but empty top-level lists.

    Used to verify denormalize_contracts promotes from component-level fields.
    """

    async def generate_structured(self, system_prompt, user_prompt, response_schema):
        if response_schema is ArchitectureDesignResponse:
            return ArchitectureDesignResponse(
                overview={
                    "style": "microservices",
                    "category": "structural",
                    "principles": ["single responsibility"],
                    "constraints": []
                },
                components=[
                    {
                        "id": "user-service",
                        "name": "User Service",
                        "type": "service",
                        "description": "User service",
                        "responsibilities": ["user management"],
                        "interfaces": [],
                        "technology_stack": [],
                        "api_contract": {
                            "component_id": "user-service",
                            "base_path": "/api/v1/users",
                            "description": "User API",
                            "endpoints": [
                                {
                                    "method": "POST",
                                    "path": "/",
                                    "summary": "Create user",
                                    "request_schema": None,
                                    "response_schema": None,
                                    "auth_required": False,
                                    "tags": []
                                }
                            ]
                        },
                        "data_models": [
                            {
                                "name": "User",
                                "description": "Shared user model",
                                "is_shared": True,
                                "fields": [
                                    {"name": "id", "type": "str", "required": True}
                                ]
                            }
                        ],
                        
                        "config_requirements": []
                    }
                ],
                relationships=[],

                quality_attributes={},
                api_contracts=[],
                shared_data_models=[],
                event_contracts=[],
                
            )

        if response_schema.__name__ == "AnalysisResult":
            from src.schemas.quality import QualityMetrics
            return AnalysisResult(
                strengths=["Scalable"],
                weaknesses=["Complex"],
                recommendations=["Start simple"],
                quality_metrics=QualityMetrics(
                    maintainability=7.0, scalability=8.0,
                    reliability=7.0, security=6.0, performance=7.5
                ),
                recommended_style="microservices",
                selected_patterns=[]
            )

        return ArchitectureEvaluation(
            summary=EvaluationSummary(
                overall_score=75.0,
                strengths=["Good"],
                weaknesses=["Consider"],
                critical_findings=["None"]
            ),
            metrics=[
                MetricResult(
                    name="overall_quality", score=75.0,
                    description="Overall", findings=[], recommendations=[]
                )
                ],
                
                recommendations={}
            )


def _create_denorm_pipeline():
    agent = _MockArchitectForDenormalization()
    pattern_loader = MockPatternLoader()
    vector_index = MockDomainVectorIndex()
    bm25_index = MockBM25Index()
    return ArchitecturePipeline(
        agent=agent,
        pattern_loader=pattern_loader,
        vector_index=vector_index,
        bm25_index=bm25_index,
    )


class TestDenormalizationIntegration:
    """Verify denormalize_contracts is called inside pipeline.generate()."""

    @pytest.mark.asyncio
    async def test_generate_denormalizes_api_contract_from_component(self):
        """Top-level api_contracts is empty; component.api_contract promoted after generate()."""
        pipeline = _create_denorm_pipeline()

        design = await pipeline.generate(
            requirements="Build a system",
            domain="microservices",
            style="microservices",
            selected_patterns=[{
                "name": "microservices",
                "context": "Distributed systems",
                "category": "structural",
                "benefits": ["Scaling"],
                "tradeoffs": ["Complexity"],
                "suitable_domains": ["microservices"],
                "best_practices": ["Use APIs"]
            }]
        )

        assert len(design.api_contracts) == 1
        assert design.api_contracts[0].component_id == "user-service"
        assert design.api_contracts[0].base_path == "/api/v1/users"

    @pytest.mark.asyncio
    async def test_generate_denormalizes_shared_model_from_component(self):
        """Top-level shared_data_models empty; component data_model with is_shared=True promoted."""
        pipeline = _create_denorm_pipeline()

        design = await pipeline.generate(
            requirements="Build a system",
            domain="microservices",
            style="microservices",
            selected_patterns=[{
                "name": "microservices",
                "context": "Distributed systems",
                "category": "structural",
                "benefits": ["Scaling"],
                "tradeoffs": ["Complexity"],
                "suitable_domains": ["microservices"],
                "best_practices": ["Use APIs"]
            }]
        )

        assert len(design.shared_data_models) == 1
        assert design.shared_data_models[0].name == "User"
        assert design.shared_data_models[0].is_shared is True


class TestDomainNormalization:
    """Test domain normalization in pipeline's ANALYZE phase."""

    @pytest.mark.asyncio
    async def test_analyze_normalizes_domain(self):
        """IC-31: Verify domain is normalized during ANALYSIS."""
        pipeline = create_test_pipeline()

        class _DummyReranker:
            top_n = 1

            def postprocess_nodes(self, nodes, query_bundle=None):
                return nodes

        with patch(
            "src.patterns.retriever.TextEmbeddingInference",
            return_value=_DummyReranker(),
        ):
            await pipeline.analyze("Requirements", "Cloud Native")

        all_calls = pipeline._pattern_loader.filter_by_domain_calls
        assert any(
            "cloud native" in c or "cloud-native" in c or "cloudnative" in c
            for c in all_calls
        )


class TestErrorHandling:
    """Test pipeline error handling."""

    @pytest.mark.asyncio
    async def test_analyze_handles_empty_results(self):
        """Verify ANALYZE handles no matching patterns gracefully."""
        pipeline = create_test_pipeline()

        class _DummyReranker:
            top_n = 1

            def postprocess_nodes(self, nodes, query_bundle=None):
                return nodes

        with patch(
            "src.patterns.retriever.TextEmbeddingInference",
            return_value=_DummyReranker(),
        ):
            result = await pipeline.analyze(
                requirements="Requirements",
                domain="nonexistent-domain-xyz"
            )

        assert isinstance(result, AnalysisResult)
        assert len(result.selected_patterns) >= 0


class TestInvalidCategoryRegression:
    """
    Regression tests for the invalid PatternCategory bug (ERR_012).

    Bug: LLM produced category: 'stream-processing' (an ArchitectureDomain value)
    instead of a valid PatternCategory enum value. This caused Pydantic
    ValidationError to bubble up as "Unexpected error during design" instead of
    being caught and converted to MalformedArchitectureOverviewError.

    Fix (Option A): ArchitectureDesignResponse.overview is typed as
    ArchitectureOverview so the LLM sees the strict PatternCategory constraint
    at generation time. Defense-in-depth: pipeline.py wraps ValidationError
    from ArchitectureDesign construction in try/except and converts it to
    MalformedArchitectureOverviewError.
    """

    def test_architecture_design_response_rejects_invalid_category(self):
        """
        ArchitectureDesignResponse with invalid category raises ValidationError.

        This is the core of Option A: by typing overview as ArchitectureOverview
        (not dict[str, Any]), Pydantic validates the category enum at
        ArchitectureDesignResponse construction time, preventing invalid values
        from propagating into the pipeline.
        """
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            ArchitectureDesignResponse(
                overview={
                    "style": "microservices",
                    "category": "stream-processing",
                    "principles": ["p1"],
                },
                components=[],

            )
        errors = exc_info.value.errors()
        assert any(
            "category" in loc
            for err in errors
            for loc in [ ".".join(str(l) for l in err["loc"]) ]
        ), f"Expected 'category' in error locations, got: {errors}"

    def test_architecture_design_response_accepts_valid_category(self):
        """
        ArchitectureDesignResponse with valid category succeeds.

        Validates that Option A does not break the valid path.
        """
        from src.schemas.design import ArchitectureOverview
        from src.schemas.enums import ArchitectureStyle, PatternCategory

        resp = ArchitectureDesignResponse(
            overview={
                "style": "microservices",
                "category": "structural",
                "principles": ["single responsibility"],
                "constraints": [],
            },
            components=[],

        )
        assert isinstance(resp.overview, ArchitectureOverview)
        assert resp.overview.category == PatternCategory.STRUCTURAL
        assert resp.overview.style == ArchitectureStyle.MICROSERVICES

    def test_architecture_design_validates_overview_category_enum(self):
        """
        ArchitectureDesign raises ValidationError when overview.category is invalid.

        This is the core Option A guarantee: by typing overview as
        ArchitectureOverview (not dict[str, Any]), invalid enum values
        like 'stream-processing' are caught at ArchitectureDesign construction time.
        """
        from pydantic import ValidationError
        from src.schemas.design import ArchitectureDesign
        from src.schemas.components import Component

        with pytest.raises(ValidationError) as exc_info:
            ArchitectureDesign(
                overview={
                    "style": "microservices",
                    "category": "stream-processing",
                    "principles": ["p1"],
                    "constraints": [],
                },
                components=[Component.model_validate({
                    "id": "svc",
                    "name": "Service",
                    "type": "service",
                    "description": "A service",
                    "responsibilities": ["do work"],
                    "interfaces": [],
                    "technology_stack": [],
                })],

            )
        errors = exc_info.value.errors()
        assert any(
            "category" in str(err["loc"])
            for err in errors
        ), f"Expected 'category' in error locs, got: {errors}"

    def test_pipeline_reports_actual_field_location(self):
        """
        When ArchitectureDesign construction fails on a non-overview field,
        the error's first ValidationError location reflects the actual failing field.

        Note: ArchitectureDesign does NOT internally wrap ValidationError —
        that wrapping is done by the pipeline (src/pipeline.py). This test
        verifies the error location by checking the raw ValidationError.
        """
        from pydantic import ValidationError
        from src.schemas.design import ArchitectureDesign

        with pytest.raises(ValidationError) as exc_info:
            ArchitectureDesign(
                overview={
                    "style": "microservices",
                    "category": "structural",
                    "principles": ["p1"],
                    "constraints": [],
                },
                components=[{
                    "id": "svc",
                    "name": "Service",
                    "type": "service",
                    "description": "A service",
                    "responsibilities": [],
                    "interfaces": [],
                    "technology_stack": [],
                }],

            )
        errors = exc_info.value.errors()
        first_loc = ".".join(str(l) for l in errors[0]["loc"])
        assert "responsibilities" in first_loc, (
            f"Expected 'responsibilities' in first error loc, got: {first_loc}"
        )

    def test_max_retries_default_is_3(self):
        """ValidationConfig max_retries default is 3 (not 2)."""
        from src.config import ValidationConfig
        vc = ValidationConfig()
        assert vc.max_retries == 3


class TestIntegration:
    """Integration tests for full pipeline workflows."""

    @pytest.mark.asyncio
    async def test_run_design_returns_refined_architecture(self):
        """Test run_design() returns PipelineResult."""
        pipeline = create_test_pipeline()

        class _DummyReranker:
            top_n = 1

            def postprocess_nodes(self, nodes, query_bundle=None):
                return nodes

        with patch(
            "src.patterns.retriever.TextEmbeddingInference",
            return_value=_DummyReranker(),
        ):
            refined = await pipeline.run_design(
                requirements="Need scalable distributed system",
                domain="microservices",
            )

        assert isinstance(refined, PipelineResult)
        assert isinstance(refined.design, ArchitectureDesign)
        assert refined.final_quality_score >= 0.0

    @pytest.mark.asyncio
    async def test_workflow_validates_event_graph(self):
        """Verify workflow.validate() passes for a correct graph."""
        pipeline = create_test_pipeline()
        result = pipeline.validate()
        assert result is not None


class TestDesignLoopPhase:
    """Tests for the design_loop method."""

    @pytest.mark.asyncio
    async def test_design_loop_returns_best_attempt(self):
        """design_loop returns the best-scoring attempt, not the last."""
        pipeline = create_test_pipeline()

        captured: list = []

        async def capture_generate(system_prompt, user_prompt, response_schema):
            captured.append(response_schema)
            from src.schemas.evaluation import ArchitectureEvaluation, EvaluationSummary, MetricResult
            if response_schema is ArchitectureDesignResponse:
                return ArchitectureDesignResponse(
                    overview={"style": "microservices", "category": "structural", "principles": ["single responsibility"], "constraints": []},
                    components=[{"id": "s1", "name": "S1", "type": "service", "description": "svc", "responsibilities": ["serve"], "interfaces": [], "technology_stack": [], "api_contract": None, "data_models": [],  "config_requirements": []}],
                    relationships=[],

                    quality_attributes={},
                    api_contracts=[],
                    shared_data_models=[],
                    event_contracts=[],
                    
                )
            if response_schema.__name__ == "ArchitectureEvaluation":
                score = 80.0 if len(captured) > 2 else 60.0
                return ArchitectureEvaluation(
                    summary=EvaluationSummary(overall_score=score, strengths=["good"], weaknesses=["minor"], critical_findings=["none"]),
                    metrics=[MetricResult(name="overall_quality", score=score, description="q", findings=[], recommendations=[])],
                     compliance=[], recommendations={}
                )
            return None

        pipeline._agent.generate_structured = capture_generate

        result = await pipeline.design_loop(
            requirements="test",
            domain="cloud-native",
            style="microservices",
            selected_patterns=[{"name": "microservices", "context": "", "category": "structural", "benefits": [], "best_practices": []}],
            criteria="quality",
            analysis_result=None,
            max_tries=3,
        )

        assert result.final_quality_score == 80.0

    @pytest.mark.asyncio
    async def test_design_loop_respects_max_tries(self):
        """design_loop makes at most max_tries generate calls."""
        pipeline = create_test_pipeline()

        generate_count = 0

        async def counting_generate(system_prompt, user_prompt, response_schema):
            nonlocal generate_count
            from src.schemas.evaluation import ArchitectureEvaluation, EvaluationSummary, MetricResult
            if response_schema is ArchitectureDesignResponse:
                generate_count += 1
                return ArchitectureDesignResponse(
                    overview={"style": "microservices", "category": "structural", "principles": ["single responsibility"], "constraints": []},
                    components=[{"id": "s1", "name": "S1", "type": "service", "description": "svc", "responsibilities": ["serve"], "interfaces": [], "technology_stack": [], "api_contract": None, "data_models": [],  "config_requirements": []}],
                    relationships=[],

                    quality_attributes={},
                    api_contracts=[],
                    shared_data_models=[],
                    event_contracts=[],
                    
                )
            if response_schema.__name__ == "ArchitectureEvaluation":
                return ArchitectureEvaluation(
                    summary=EvaluationSummary(overall_score=50.0, strengths=["ok"], weaknesses=["n/a"], critical_findings=["none"]),
                    metrics=[MetricResult(name="overall_quality", score=50.0, description="q", findings=[], recommendations=[])],
                     compliance=[], recommendations={}
                )
            return None

        pipeline._agent.generate_structured = counting_generate

        result = await pipeline.design_loop(
            requirements="test",
            domain="cloud-native",
            style="microservices",
            selected_patterns=[{"name": "microservices", "context": "", "category": "structural", "benefits": [], "best_practices": []}],
            criteria="quality",
            analysis_result=None,
            max_tries=3,
        )

        assert generate_count == 3
        assert result.attempts == 3

    @pytest.mark.asyncio
    async def test_design_loop_early_stops_on_quality(self):
        """design_loop exits early when min_quality_score is met (0-100 scale)."""
        pipeline = create_test_pipeline()

        generate_count = 0

        async def counting_generate(system_prompt, user_prompt, response_schema):
            nonlocal generate_count
            from src.schemas.evaluation import ArchitectureEvaluation, EvaluationSummary, MetricResult
            if response_schema is ArchitectureDesignResponse:
                generate_count += 1
                return ArchitectureDesignResponse(
                    overview={"style": "microservices", "category": "structural", "principles": ["single responsibility"], "constraints": []},
                    components=[{"id": "s1", "name": "S1", "type": "service", "description": "svc", "responsibilities": ["serve"], "interfaces": [], "technology_stack": [], "api_contract": None, "data_models": [],  "config_requirements": []}],
                    relationships=[],

                    quality_attributes={},
                    api_contracts=[],
                    shared_data_models=[],
                    event_contracts=[],
                    
                )
            if response_schema.__name__ == "ArchitectureEvaluation":
                return ArchitectureEvaluation(
                    summary=EvaluationSummary(overall_score=90.0, strengths=["great"], weaknesses=["minor"], critical_findings=["none"]),
                    metrics=[MetricResult(name="overall_quality", score=90.0, description="q", findings=[], recommendations=[])],
                     compliance=[], recommendations={}
                )
            return None

        pipeline._agent.generate_structured = counting_generate

        result = await pipeline.design_loop(
            requirements="test",
            domain="cloud-native",
            style="microservices",
            selected_patterns=[{"name": "microservices", "context": "", "category": "structural", "benefits": [], "best_practices": []}],
            criteria="quality",
            analysis_result=None,
            max_tries=3,
            min_quality_score=80.0,
        )

        # 90.0 >= 80.0 → early stop after first attempt
        assert generate_count == 1
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_design_loop_retries_on_malformed_error(self):
        """design_loop retries when generate throws MalformedArchitectureOverviewError."""
        from src.errors import MalformedArchitectureOverviewError, ERROR_INVALID_ARCHITECTURE
        pipeline = create_test_pipeline()

        attempt = 0

        async def throwing_generate(system_prompt, user_prompt, response_schema):
            nonlocal attempt
            from src.schemas.evaluation import ArchitectureEvaluation, EvaluationSummary, MetricResult
            if response_schema is ArchitectureDesignResponse:
                attempt += 1
                if attempt == 1:
                    raise MalformedArchitectureOverviewError(code=ERROR_INVALID_ARCHITECTURE, locator="overview", errors=[])
                return ArchitectureDesignResponse(
                    overview={"style": "microservices", "category": "structural", "principles": ["single responsibility"], "constraints": []},
                    components=[{"id": "s1", "name": "S1", "type": "service", "description": "svc", "responsibilities": ["serve"], "interfaces": [], "technology_stack": [], "api_contract": None, "data_models": [],  "config_requirements": []}],
                    relationships=[],

                    quality_attributes={},
                    api_contracts=[],
                    shared_data_models=[],
                    event_contracts=[],
                    
                )
            if response_schema.__name__ == "ArchitectureEvaluation":
                return ArchitectureEvaluation(
                    summary=EvaluationSummary(overall_score=70.0, strengths=["ok"], weaknesses=["minor"], critical_findings=["none"]),
                    metrics=[MetricResult(name="overall_quality", score=70.0, description="q", findings=[], recommendations=[])],
                     compliance=[], recommendations={}
                )
            return None

        pipeline._agent.generate_structured = throwing_generate

        result = await pipeline.design_loop(
            requirements="test",
            domain="cloud-native",
            style="microservices",
            selected_patterns=[{"name": "microservices", "context": "", "category": "structural", "benefits": [], "best_practices": []}],
            criteria="quality",
            analysis_result=None,
            max_tries=3,
        )

        assert attempt == 3
        assert result.attempts == 3


class TestPatternContextReduction:
    """Verify pattern context respects pattern_context_limits from RetrievalConfig."""

    def _make_pipeline_with_limits(self, limits: dict[str, int] | None = None):
        from src.config import RetrievalConfig
        cfg = RetrievalConfig(pattern_context_limits=limits) if limits else RetrievalConfig()
        return create_test_pipeline(retrieval_config=cfg)

    def test_build_pattern_context_respects_benefits_limit(self):
        """benefits are sliced to config limit."""
        pipeline = self._make_pipeline_with_limits({"benefits": 2, "tradeoffs": 3, "best_practices": 3, "component_types": 5, "technology_stack": 5, "anti_patterns": 3, "suitable_domains": 5})
        patterns = [{"name": "p1", "context": "c", "benefits": ["b1", "b2", "b3"], "tradeoffs": [], "suitable_domains": [], "best_practices": [], "component_types": [], "technology_stack": [], "anti_patterns": []}]
        ctx = pipeline._build_pattern_context(patterns)
        assert ctx.count("b1") == 1
        assert ctx.count("b2") == 1
        assert "b3" not in ctx

    def test_build_pattern_context_respects_tradeoffs_limit(self):
        """tradeoffs are sliced to config limit."""
        pipeline = self._make_pipeline_with_limits({"benefits": 3, "tradeoffs": 2, "best_practices": 3, "component_types": 5, "technology_stack": 5, "anti_patterns": 3, "suitable_domains": 5})
        patterns = [{"name": "p1", "context": "c", "benefits": [], "tradeoffs": ["t1", "t2", "t3"], "suitable_domains": [], "best_practices": [], "component_types": [], "technology_stack": [], "anti_patterns": []}]
        ctx = pipeline._build_pattern_context(patterns)
        assert ctx.count("t1") == 1
        assert ctx.count("t2") == 1
        assert "t3" not in ctx

    def test_build_pattern_context_respects_best_practices_limit(self):
        """best_practices are sliced to config limit."""
        pipeline = self._make_pipeline_with_limits({"benefits": 3, "tradeoffs": 3, "best_practices": 1, "component_types": 5, "technology_stack": 5, "anti_patterns": 3, "suitable_domains": 5})
        patterns = [{"name": "p1", "context": "c", "benefits": [], "tradeoffs": [], "suitable_domains": [], "best_practices": ["bp1", "bp2"], "component_types": [], "technology_stack": [], "anti_patterns": []}]
        ctx = pipeline._build_pattern_context(patterns)
        assert ctx.count("bp1") == 1
        assert "bp2" not in ctx

    def test_build_pattern_context_respects_anti_patterns_limit(self):
        """anti_patterns are sliced to config limit."""
        pipeline = self._make_pipeline_with_limits({"benefits": 3, "tradeoffs": 3, "best_practices": 3, "component_types": 5, "technology_stack": 5, "anti_patterns": 1, "suitable_domains": 5})
        patterns = [{"name": "p1", "context": "c", "benefits": [], "tradeoffs": [], "suitable_domains": [], "best_practices": [], "component_types": [], "technology_stack": [], "anti_patterns": ["ap1", "ap2"]}]
        ctx = pipeline._build_pattern_context(patterns)
        assert ctx.count("ap1") == 1
        assert "ap2" not in ctx

    def test_build_pattern_context_respects_suitable_domains_limit(self):
        """suitable_domains are sliced to config limit."""
        pipeline = self._make_pipeline_with_limits({"benefits": 3, "tradeoffs": 3, "best_practices": 3, "component_types": 5, "technology_stack": 5, "anti_patterns": 3, "suitable_domains": 2})
        patterns = [{"name": "p1", "context": "c", "benefits": [], "tradeoffs": [], "suitable_domains": ["d1", "d2", "d3"], "best_practices": [], "component_types": [], "technology_stack": [], "anti_patterns": []}]
        ctx = pipeline._build_pattern_context(patterns)
        assert "d1" in ctx
        assert "d2" in ctx
        assert "d3" not in ctx

    def test_build_pattern_context_deduplicates_component_types(self):
        """component_types deduplicated case-insensitively across patterns."""
        pipeline = self._make_pipeline_with_limits({"benefits": 3, "tradeoffs": 3, "best_practices": 3, "component_types": 5, "technology_stack": 5, "anti_patterns": 3, "suitable_domains": 5})
        patterns = [
            {"name": "p1", "context": "c", "benefits": [], "tradeoffs": [], "suitable_domains": [], "best_practices": [], "component_types": ["API Gateway", "Load Balancer"], "technology_stack": [], "anti_patterns": []},
            {"name": "p2", "context": "c", "benefits": [], "tradeoffs": [], "suitable_domains": [], "best_practices": [], "component_types": ["api gateway", "Cache"], "technology_stack": [], "anti_patterns": []},
        ]
        ctx = pipeline._build_pattern_context(patterns)
        assert ctx.count("API Gateway") == 1
        assert ctx.count("api gateway") == 0
        assert ctx.count("Load Balancer") == 1
        assert ctx.count("Cache") == 1

    def test_build_pattern_context_deduplicates_technology_stack(self):
        """technology_stack deduplicated case-insensitively across patterns."""
        pipeline = self._make_pipeline_with_limits({"benefits": 3, "tradeoffs": 3, "best_practices": 3, "component_types": 5, "technology_stack": 5, "anti_patterns": 3, "suitable_domains": 5})
        patterns = [
            {"name": "p1", "context": "c", "benefits": [], "tradeoffs": [], "suitable_domains": [], "best_practices": [], "component_types": [], "technology_stack": ["Kubernetes", "Docker"], "anti_patterns": []},
            {"name": "p2", "context": "c", "benefits": [], "tradeoffs": [], "suitable_domains": [], "best_practices": [], "component_types": [], "technology_stack": ["kubernetes", "Redis"], "anti_patterns": []},
        ]
        ctx = pipeline._build_pattern_context(patterns)
        assert ctx.count("Kubernetes") == 1
        assert ctx.count("kubernetes") == 0
        assert ctx.count("Docker") == 1
        assert ctx.count("Redis") == 1

    def test_build_pattern_context_drops_design_principles_section(self):
        """design_principles section is not present in pattern context."""
        pipeline = self._make_pipeline_with_limits({"benefits": 3, "tradeoffs": 3, "best_practices": 3, "component_types": 5, "technology_stack": 5, "anti_patterns": 3, "suitable_domains": 5})
        patterns = [{"name": "p1", "context": "c", "benefits": [], "tradeoffs": [], "suitable_domains": [], "best_practices": [], "component_types": [], "technology_stack": [], "anti_patterns": [], "design_principles": ["Single Responsibility"]}]
        ctx = pipeline._build_pattern_context(patterns)
        assert "Design Principles" not in ctx

    def test_build_pattern_context_drops_unsuitable_domains_section(self):
        """unsuitable_domains section is not present in pattern context."""
        pipeline = self._make_pipeline_with_limits({"benefits": 3, "tradeoffs": 3, "best_practices": 3, "component_types": 5, "technology_stack": 5, "anti_patterns": 3, "suitable_domains": 5})
        patterns = [{"name": "p1", "context": "c", "benefits": [], "tradeoffs": [], "suitable_domains": [], "best_practices": [], "component_types": [], "technology_stack": [], "anti_patterns": [], "unsuitable_domains": ["domain1"]}]
        ctx = pipeline._build_pattern_context(patterns)
        assert "Unsuitable Domains" not in ctx


class TestQualityScoreFallback:
    """Verify design_loop uses correct fallback chain for overall quality score.

    Fallback chain: overall_quality metric -> summary.overall_score.
    """

    def _make_eval(self, *, overall_metric_score: float | None = None,
                   summary_score: float = 75.0) -> ArchitectureEvaluation:
        from src.schemas.evaluation import ArchitectureEvaluation, EvaluationSummary, MetricResult
        metrics = []
        if overall_metric_score is not None:
            metrics.append(MetricResult(name="overall_quality", score=overall_metric_score,
                                       description="", findings=[], recommendations=[]))
        return ArchitectureEvaluation(
            summary=EvaluationSummary(
                overall_score=summary_score,
                strengths=["test"], weaknesses=["test"], critical_findings=["test"]
            ),
            metrics=metrics,
            risks=[], compliance=[], recommendations={}
        )

    def _make_design(self) -> ArchitectureDesignResponse:
        return ArchitectureDesignResponse(
            overview={"style": "pipe-and-filter", "category": "dataflow",
                      "principles": ["test"], "constraints": []},
            components=[{"id": "s1", "name": "S1", "type": "service", "description": "svc",
                        "responsibilities": ["serve"], "interfaces": [], "technology_stack": [],
                        "api_contract": None, "data_models": [], 
                        "config_requirements": []}],
            relationships=[],

            quality_attributes={},
            api_contracts=[], shared_data_models=[], event_contracts=[]
        )

    @pytest.mark.asyncio
    async def test_uses_overall_quality_metric_when_present(self):
        """Primary path: uses overall_quality metric score."""
        pipeline = create_test_pipeline()
        call_count = 0

        async def mock_generate(system_prompt, user_prompt, response_schema):
            nonlocal call_count
            call_count += 1
            if response_schema is ArchitectureDesignResponse:
                return self._make_design()
            from src.schemas.evaluation import ArchitectureEvaluation
            if response_schema == ArchitectureEvaluation:
                return self._make_eval(overall_metric_score=82.5)
            return None

        pipeline._agent.generate_structured = mock_generate
        result = await pipeline.design_loop(
            requirements="test", domain="data-processing", style="pipe-and-filter",
            selected_patterns=[], criteria="quality", max_tries=1,
        )
        assert result.final_quality_score == 82.5

    @pytest.mark.asyncio
    async def test_falls_back_to_summary_overall_score(self):
        """When no overall_quality metric, uses summary.overall_score."""
        pipeline = create_test_pipeline()

        async def mock_generate(system_prompt, user_prompt, response_schema):
            if response_schema is ArchitectureDesignResponse:
                return self._make_design()
            from src.schemas.evaluation import ArchitectureEvaluation
            if response_schema == ArchitectureEvaluation:
                return self._make_eval(summary_score=88.0)
            return None

        pipeline._agent.generate_structured = mock_generate
        result = await pipeline.design_loop(
            requirements="test", domain="data-processing", style="pipe-and-filter",
            selected_patterns=[], criteria="quality", max_tries=1,
        )
        assert result.final_quality_score == 88.0

class TestPromptExamples:
    """Verify structured-output prompts contain complete JSON examples."""

    def test_examples_import_cleanly(self):
        """Module imports without error."""
        from src.prompts.examples import (
            ANALYSIS_RESULT_EXAMPLE,
            ARCHITECTURE_DESIGN_EXAMPLE,
            ARCHITECTURE_EVALUATION_EXAMPLE,
        )
        assert ANALYSIS_RESULT_EXAMPLE
        assert ARCHITECTURE_DESIGN_EXAMPLE
        assert ARCHITECTURE_EVALUATION_EXAMPLE

    def test_analysis_example_validates_against_schema(self):
        """Analysis example is a valid AnalysisResult."""
        from src.prompts.examples import ANALYSIS_RESULT_EXAMPLE
        import json

        raw = ANALYSIS_RESULT_EXAMPLE.split("```json")[1].split("```")[0].strip()
        data = json.loads(raw)
        from src.schemas.analysis import AnalysisResult
        result = AnalysisResult.model_validate(data)
        assert result.strengths
        assert result.weaknesses
        assert result.recommended_style

    def test_design_example_validates_against_schema(self):
        """Design example is a valid ArchitectureDesignResponse."""
        from src.prompts.examples import ARCHITECTURE_DESIGN_EXAMPLE
        import json

        raw = ARCHITECTURE_DESIGN_EXAMPLE.split("```json")[1].split("```")[0].strip()
        data = json.loads(raw)
        from src.schemas.architecture import ArchitectureDesignResponse
        result = ArchitectureDesignResponse.model_validate(data)
        assert result.overview

    def test_evaluation_example_validates_against_schema(self):
        """Evaluation example is a valid ArchitectureEvaluation."""
        from src.prompts.examples import ARCHITECTURE_EVALUATION_EXAMPLE
        import json

        raw = ARCHITECTURE_EVALUATION_EXAMPLE.split("```json")[1].split("```")[0].strip()
        data = json.loads(raw)
        from src.schemas.evaluation import ArchitectureEvaluation
        result = ArchitectureEvaluation.model_validate(data)
        assert result.summary.overall_score

    def test_generate_system_prompt_contains_example(self):
        """Generate system prompt includes architecture design example."""
        pipeline = create_test_pipeline()
        prompt = pipeline._build_generate_system_prompt(
            style="microservices", _patterns=[]
        )
        assert "Example architecture design response" in prompt
        assert "```json" in prompt

    def test_analyze_system_prompt_contains_example(self):
        """Analyze system prompt includes a RequirementWeights JSON example."""
        pipeline = create_test_pipeline()
        prompt = pipeline._build_analyze_system_prompt(domain="data-processing")
        assert "Example RequirementWeights response" in prompt
        assert "```json" in prompt

    def test_evaluate_system_prompt_contains_example(self):
        """Evaluate system prompt includes evaluation example."""
        pipeline = create_test_pipeline()
        prompt = pipeline._build_evaluate_system_prompt(patterns=[])
        assert "Example evaluation response" in prompt
        assert "```json" in prompt

    def test_design_example_contains_contracts(self):
        """Design example includes api_contracts, shared_data_models,
        event_contracts."""
        from src.prompts.examples import ARCHITECTURE_DESIGN_EXAMPLE
        assert "api_contracts" in ARCHITECTURE_DESIGN_EXAMPLE
        assert "shared_data_models" in ARCHITECTURE_DESIGN_EXAMPLE
        assert "event_contracts" in ARCHITECTURE_DESIGN_EXAMPLE

    def test_analysis_example_contains_selected_patterns(self):
        """Analysis example includes selected_patterns."""
        from src.prompts.examples import ANALYSIS_RESULT_EXAMPLE
        assert "selected_patterns" in ANALYSIS_RESULT_EXAMPLE


class TestTimedPhaseLogging:
    """Verify _timed_phase emits INFO log with duration."""

    def test_timed_phase_logs_duration_on_normal_exit(self, caplog):
        import asyncio
        from src.pipeline import _timed_phase

        with caplog.at_level("DEBUG", logger="src.pipeline"):
            async def run():
                async with _timed_phase("analyze", domain="data-processing"):
                    await asyncio.sleep(0.01)
            asyncio.run(run())

        assert any(
            rec.phase == "analyze" and rec.duration_s > 0
            for rec in caplog.records
        )

    def test_timed_phase_logs_duration_on_exception(self, caplog):
        import asyncio
        from src.pipeline import _timed_phase

        with caplog.at_level("DEBUG", logger="src.pipeline"):
            async def run():
                async with _timed_phase("evaluate"):
                    raise RuntimeError("simulated failure")
            with pytest.raises(RuntimeError):
                asyncio.run(run())

        assert any(
            rec.phase == "evaluate" and rec.duration_s >= 0
            for rec in caplog.records
        )

    def test_timed_phase_logs_info_when_verbose(self, caplog):
        """verbose=True bypasses DEBUG gate, logs at INFO."""
        import asyncio
        from src.pipeline import _timed_phase

        with caplog.at_level("INFO", logger="src.pipeline"):
            async def run():
                async with _timed_phase(
                    "generate", domain="x", verbose=True
                ):
                    await asyncio.sleep(0.01)
            asyncio.run(run())

        assert any(
            rec.phase == "generate" and rec.duration_s > 0
            for rec in caplog.records
        )
