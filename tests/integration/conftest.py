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
Pytest fixtures for integration tests.

Provides mocked ConfigManager to avoid file-system dependencies and
shared mock classes for the pipe-and-filter integration tests.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_config_manager():
    """Auto-mock ConfigManager.load_config for all integration tests."""
    mock_config = {
        "generator": {
            "provider": "openai",
            "config": {
                "model": "gpt-4",
                "base_url": "",
                "api_key": None,
                "temperature": 0.7,
                "top_p": 1.0,
                "top_k": 20,
            }
        },
        "embedder": {
            "provider": "tei",
            "config": {
                "model": "Qwen/Qwen3-Embedding-0.6B",
                "base_url": "http://localhost:8080",
                "api_key": None,
                "embed_batch_size": 16,
                "query_instruction": "Instruct: Given a software architecture pattern domain tag, retrieve the most relevant existing pattern domain from the catalogue\nQuery: ",
                "text_instruction": "",
                "embedding_dim": 1024,
                "max_embedder_tokens": 3000,
            }
        },
        "pattern_directory": "/tmp/test_patterns",
        "logging_level": "INFO",
        "logging_format": "text",
        "transport": "stdio",
        "host": "127.0.0.1",
        "port": 8000,
        "retrieval": {
            "bm25_top_k": 5,
            "dense_top_k": 5,
            "top_k_patterns": 5,
            "mode": "reciprocal_rerank",
            "retriever_weights": [0.5, 0.5],
            "min_fusion_score": 0.0,
            "enable_reranking": False,
            "rerank_top_n": 3,
            "min_quality_score": 50.0,
            "max_tries": 3,
            "style_score_threshold": 50.0,
            "pattern_context_limits": {
                "benefits": 3,
                "tradeoffs": 3,
                "best_practices": 3,
                "component_types": 5,
                "technology_stack": 5,
                "anti_patterns": 3,
                "suitable_domains": 5,
            },
        }
    }
    mock_cm = MagicMock()
    mock_cm.load_config.return_value = mock_config
    mock_cm.DEFAULT_CONFIG_PATH = "/tmp/test_config.json"
    with patch('src.config.ConfigManager.load_config', mock_cm.load_config):
        yield mock_cm


# ---------------------------------------------------------------------------
# Shared mock classes for pipe-and-filter integration tests
# ---------------------------------------------------------------------------

PIPE_AND_FILTER_PATTERN = {
    "name": "pipe-and-filter",
    "category": "dataflow",
    "context": "Sequential data transformation workflows where complex processing tasks are decomposed into independent, reusable filters connected by pipes",
    "benefits": [
        "Modular single-responsibility design",
        "High reusability through compositional filter recombination",
        "Independent horizontal scaling of individual filters",
    ],
    "tradeoffs": [
        "Data serialization overhead between filters",
        "Memory buffer requirements between pipeline stages",
    ],
    "quality_attributes": {
        "performance": 7,
        "scalability": 8,
        "reliability": 7,
        "maintainability": 9,
        "security": 6,
        "simplicity": 5,
    },
    "suitable_domains": [
        "data-processing", "etl", "stream-processing", "log-analysis",
        "media-processing", "serverless", "compiler-toolchains", "event-driven-workflows",
    ],
    "unsuitable_domains": [
        "highly-interactive-ui", "request-response-apis", "strong-transaction",
    ],
    "best_practices": [
        "Filter Granularity: Balance between small focused filters and large efficient filters",
        "Buffer Sizing: Large buffers reduce synchronization overhead but consume memory",
        "Error Handling: Implement retry mechanisms and compensation transactions",
    ],
    "component_types": [
        "Pipe: Conduit passing data between filters",
        "Filter: Processing unit with single responsibility",
        "DataSource: Input origin",
        "DataSink: Output destination",
        "Pipeline: Composed sequence of filters",
        "MessageBroker: Optional intermediate buffer",
    ],
    "use_cases": [
        "ETL pipelines transforming data through multiple stages",
        "Stream processing with enrichment and routing",
        "Serverless function chaining with event-driven triggers",
    ],
}


class MockPipeAndFilterPatternLoader:
    """PatternLoader that returns pipe-and-filter for data-processing domain."""

    def __init__(self, patterns_dir=None):
        self._patterns_dir = patterns_dir
        self._loaded = True
        self.filter_by_domain_calls = []
        self.get_by_name_calls = []

    def load_all(self) -> list[dict]:
        return [PIPE_AND_FILTER_PATTERN, {
            "name": "serverless",
            "category": "cloud",
            "suitable_domains": ["serverless", "data-processing"],
            "quality_attributes": {
                "performance": 7, "scalability": 9, "reliability": 7,
                "maintainability": 8, "security": 5,
            },
            "context": "Event-driven compute model",
            "benefits": ["Auto-scaling", "Pay-per-use"],
            "tradeoffs": ["Cold starts", "Vendor lock-in"],
            "best_practices": [],
            "component_types": [],
            "use_cases": [],
        }]

    def filter_by_domain(self, domain: str) -> list[dict]:
        self.filter_by_domain_calls.append(domain)
        normalized = domain.lower().replace(" ", "-")
        all_patterns = self.load_all()
        return [
            p for p in all_patterns
            if normalized in p.get("suitable_domains", [])
        ]

    def get_by_name(self, name: str) -> dict | None:
        self.get_by_name_calls.append(name)
        for p in self.load_all():
            if p.get("name") == name:
                return p
        return None

    def select_top_patterns(self, domain: str, top_k: int = 5) -> list[dict]:
        filtered = self.filter_by_domain(domain)
        return filtered[:top_k]


class MockPipeAndFilterVectorIndex:
    """Vector index that returns pipe-and-filter as top match for data-processing."""

    def __init__(self, **kwargs):
        self._built = True
        self._domains: list[str] = []
        self.search_calls = []

    @property
    def domains(self) -> list[str]:
        return list(self._domains)

    @property
    def is_built(self) -> bool:
        return self._built

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
        self._built = True

    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        self.search_calls.append((query, k))
        return [
            ("data-processing", 0.98),
            ("etl", 0.92),
            ("stream-processing", 0.88),
        ]

    def as_retriever(self, similarity_top_k: int = 20):
        class _Retriever:
            def __init__(self_, top_k):
                self_._top_k = top_k

            def retrieve(self_, query_bundle):
                from llama_index.core.schema import NodeWithScore, TextNode
                return [
                    NodeWithScore(
                        node=TextNode(
                            text="data-processing",
                            metadata={"slug": "data-processing"},
                        ),
                        score=0.98,
                    ),
                    NodeWithScore(
                        node=TextNode(
                            text="etl",
                            metadata={"slug": "etl"},
                        ),
                        score=0.92,
                    ),
                ][:self_._top_k]

        return _Retriever(similarity_top_k)


class MockPipeAndFilterBM25Index:
    """BM25 index that returns pipe-and-filter as top match."""

    def __init__(self):
        self._built = True
        self._domains: list[str] = []

    @property
    def is_built(self) -> bool:
        return self._built

    @property
    def domains(self) -> list[str]:
        return list(self._domains)

    def build_index(self, domains: list[str]) -> None:
        self._domains = list(domains)
        self._built = True

    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        return [
            ("data-processing", 0.95),
            ("etl", 0.88),
            ("stream-processing", 0.82),
        ]

    def as_retriever(self, top_k: int = 20):
        class _Retriever:
            def __init__(self_, top_k):
                self_._top_k = top_k

            def retrieve(self_, query_bundle):
                from llama_index.core.schema import NodeWithScore, TextNode
                return [
                    NodeWithScore(
                        node=TextNode(
                            text="data-processing",
                            metadata={"slug": "data-processing"},
                        ),
                        score=0.95,
                    ),
                    NodeWithScore(
                        node=TextNode(
                            text="etl",
                            metadata={"slug": "etl"},
                        ),
                        score=0.88,
                    ),
                ][:self_._top_k]

        return _Retriever(top_k)
