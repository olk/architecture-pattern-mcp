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
Unit tests for DomainVectorIndex class.

Test Case IDs: UT-11
Validates Requirements: FR-200, FR-201, AC-201

Implementation Constraints Validated:
- IC-34: llama-index-vector-stores-faiss and LiteLLMEmbedding
- IC-36: FAISS index SHALL use IndexFlatIP with L2 normalized embeddings

Test Scenarios:
- SCEN-14: DomainVectorIndex class exists and can be instantiated
- SCEN-15: DomainVectorIndex builds FAISS index with L2 normalized embeddings
- SCEN-16: DomainVectorIndex search returns similar domains
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.patterns.vector_index import DomainVectorIndex
from src.config import EmbedderConfig, EmbedderInnerConfig


def _tei_config(
    model: str = "Qwen/Qwen3-Embedding-0.6B",
    base_url: str = "http://localhost:8080",
    query_instruction: str = "",
    text_instruction: str = "",
) -> EmbedderConfig:
    return EmbedderConfig(
        provider="tei",
        config=EmbedderInnerConfig(
            model=model,
            base_url=base_url,
            api_key=None,
            embed_batch_size=16,
            query_instruction=query_instruction,
            text_instruction=text_instruction,
            embedding_dim=1024,
            max_embedder_tokens=3000,
        ),
    )


class TestDomainVectorIndexInit:
    """SCEN-14: DomainVectorIndex class exists and can be instantiated"""

    def test_domain_vector_index_class_exists(self):
        """AC-201: Verify DomainVectorIndex class exists."""
        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )
        assert index is not None
        assert isinstance(index, DomainVectorIndex)

    def test_domain_vector_index_model_name_from_config(self):
        """Verify model_name is set from the config."""
        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="custom-model",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )
        assert index.model_name == "openai//data/qwen3-embedding-0.6b"

    def test_domain_vector_index_not_built_initially(self):
        """Verify is_built returns False before build_index is called."""
        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )
        assert index.is_built is False

    def test_from_embedder_config_sets_all_fields(self):
        """Verify from_embedder_config populates model_name and embedder."""
        cfg = _tei_config(
            model="Qwen/Qwen3-Embedding-0.6B",
            query_instruction="Instruct: Query: ",
            text_instruction="Instruct: Text: ",
        )
        index = DomainVectorIndex.from_embedder_config(cfg)
        assert index.model_name == "openai//data/qwen3-embedding-0.6b"
        assert getattr(index._embedder, "query_instruction", "") == "Instruct: Query: "
        assert getattr(index._embedder, "text_instruction", "") == "Instruct: Text: "

    def test_init_raises_without_provider(self):
        """Verify __init__ raises ValueError when provider is empty."""
        with pytest.raises(ValueError, match="provider is required"):
            DomainVectorIndex(
                base_url="http://localhost:8080",
                model="Qwen/Qwen3-Embedding-0.6B",
                api_key=None,
                embedding_dim=1024,
                max_tokens=3000,
                embed_batch_size=16,
                query_instruction="",
                text_instruction="",
                provider="",
            )


class TestDomainVectorIndexBuildIndex:
    """SCEN-15: DomainVectorIndex builds FAISS index with L2 normalized embeddings"""

    def test_build_index_stores_domains(self):
        """Verify build_index stores the domain list."""
        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )
        domains = ["cloud-native", "microservices", "data-mesh"]

        with patch.object(index, "_embed", return_value=np.random.rand(3, 1024).astype(np.float32)):
            index.build_index(domains)

        assert index._domains == domains

    def test_build_index_creates_faiss_index(self):
        """Verify build_index creates a FAISS IndexFlatIP."""
        import faiss

        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )
        domains = ["cloud-native", "microservices", "data-mesh"]

        mock_embeddings = np.random.rand(3, 1024).astype(np.float32)

        with patch.object(index, "_embed", return_value=mock_embeddings):
            index.build_index(domains)

        assert index._faiss_index is not None
        assert isinstance(index._faiss_index, faiss.IndexFlatIP)
        assert index._faiss_index.ntotal == 3

    def test_build_index_empty_domains(self):
        """Verify build_index handles empty domain list."""
        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )

        with patch.object(index, "_embed", return_value=np.array([])):
            index.build_index([])

        assert index.is_built is False

    def test_rebuild_index_resets_and_rebuilds(self):
        """Verify rebuild_index resets and rebuilds with new domains."""
        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )
        domains1 = ["domain1", "domain2"]
        domains2 = ["domain3", "domain4", "domain5"]

        with patch.object(index, "_embed", return_value=np.random.rand(2, 1024).astype(np.float32)):
            index.build_index(domains1)

        assert len(index._domains) == 2

        with patch.object(index, "_embed", return_value=np.random.rand(3, 1024).astype(np.float32)):
            index.rebuild_index(domains2)

        assert len(index._domains) == 3
        assert index._domains == domains2


class TestDomainVectorIndexSearch:
    """SCEN-16: DomainVectorIndex search returns similar domains"""

    def test_search_returns_results(self):
        """Verify search returns list of (domain, score) tuples."""
        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )
        domains = ["cloud-native", "microservices", "data-mesh"]
        embedding_dim = 1024

        mock_embeddings = np.random.rand(3, embedding_dim).astype(np.float32)

        with patch.object(index, "_embed", return_value=mock_embeddings):
            index.build_index(domains)

        with patch.object(index, "_embed", return_value=np.random.rand(1, embedding_dim).astype(np.float32)):
            results = index.search("distributed systems", k=2)

        assert isinstance(results, list)
        assert len(results) <= 2
        for result in results:
            assert isinstance(result, tuple)
            assert len(result) == 2
            assert isinstance(result[0], str)
            assert isinstance(result[1], float)

    def test_search_on_unbuilt_index_returns_empty(self):
        """Verify search on unbuilt index returns empty list."""
        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )
        results = index.search("query", k=3)
        assert results == []

    def test_search_respects_k_parameter(self):
        """Verify search respects the k parameter."""
        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )
        domains = ["d1", "d2", "d3", "d4", "d5"]
        embedding_dim = 1024
        mock_embeddings = np.random.rand(5, embedding_dim).astype(np.float32)

        with patch.object(index, "_embed", return_value=mock_embeddings):
            index.build_index(domains)

        with patch.object(index, "_embed", return_value=np.random.rand(1, embedding_dim).astype(np.float32)):
            results = index.search("query", k=3)

        assert len(results) == 3


class TestErrorHandling:
    """E-6/E-007: Error handling for embedding failures"""

    def test_embed_raises_on_connection_error(self):
        """E-007 (ERR_007): Failed to embed via LiteLLMEmbedding - connection error."""
        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )

        with patch.object(
            index._embedder,
            "_get_text_embeddings",
            side_effect=Exception("Connection refused"),
        ):
            with pytest.raises(Exception, match="Connection refused"):
                index._embed(["test"], is_query=False)


class TestL2Normalization:
    """IC-36: FAISS index SHALL use IndexFlatIP with L2 normalized embeddings"""

    def test_embed_applies_l2_normalization(self):
        """Verify _embed applies L2 normalization to returned embeddings via the embedder."""
        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )

        raw_vectors = {
            "a": [3.0, 4.0, 0.0],
            "b": [1.0, 0.0, 0.0],
        }

        async def async_text(t):
            return raw_vectors[t]

        async def async_query(t):
            return raw_vectors.get(t, [0.0, 0.0, 1.0])

        def batched_embed(texts):
            return [raw_vectors.get(t, [0.0, 0.0, 0.0]) for t in texts]

        with patch.object(
            index._embedder,
            "_get_text_embeddings",
            side_effect=batched_embed,
        ), patch.object(
            index._embedder,
            "_aget_text_embedding",
            side_effect=async_text,
        ):
            result = index._embed(["a", "b"], is_query=False)

        expected_first = np.array([0.6, 0.8, 0.0], dtype=np.float32)
        np.testing.assert_allclose(result[0], expected_first, rtol=1e-5)

        expected_second = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        np.testing.assert_allclose(result[1], expected_second, rtol=1e-5)

    def test_embed_handles_zero_vector(self):
        """Verify _embed handles zero vectors without division by zero."""
        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )

        raw_embeddings = np.array([[0.0, 0.0, 0.0]], dtype=np.float32)

        def fake_embed(texts, *, is_query=False):
            return raw_embeddings.copy()

        with patch.object(index, "_embed", side_effect=fake_embed):
            result = index._embed(["test"], is_query=False)

        assert result.shape == (1, 3)
        np.testing.assert_array_equal(result[0], [0.0, 0.0, 0.0])


class TestVectorStoreProperty:
    """Verify FaissVectorStore exposure via .vector_store property."""

    def test_vector_store_is_none_before_build(self):
        """Verify vector_store property is None before build_index."""
        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )
        assert index.vector_store is None

    def test_vector_store_is_faiss_vector_store_after_build(self):
        """Verify vector_store is a FaissVectorStore after build."""
        from llama_index.vector_stores.faiss import FaissVectorStore

        index = DomainVectorIndex(
            base_url="http://localhost:8080",
            model="Qwen/Qwen3-Embedding-0.6B",
            api_key=None,
            embedding_dim=1024,
            max_tokens=3000,
            embed_batch_size=16,
            query_instruction="",
            text_instruction="",
            provider="tei",
        )

        with patch.object(index, "_embed", return_value=np.random.rand(3, 1024).astype(np.float32)):
            index.build_index(["a", "b", "c"])

        assert isinstance(index.vector_store, FaissVectorStore)
