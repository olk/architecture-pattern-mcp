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
Unit tests for DomainVectorRetriever class.

Test Case IDs: UT-VRET-1 through UT-VRET-6
Validates Requirements: FR-200, FR-201 (via DomainVectorIndex.search())

Test Scenarios:
- UT-VRET-1: retrieve() returns NodeWithScore for each search match
- UT-VRET-2: node.metadata["slug"] equals the domain
- UT-VRET-3: score propagates from DomainVectorIndex.search()
- UT-VRET-4: similarity_top_k is respected
- UT-VRET-5: unbuilt index returns empty list
- UT-VRET-6: node.text equals the domain string
"""

from unittest.mock import MagicMock

from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from src.patterns.vector_retriever import DomainVectorRetriever


class TestRetrieveReturnsNodeWithScore:
    """UT-VRET-1: retrieve() returns NodeWithScore for each search match."""

    def test_returns_node_with_score_for_each_match(self):
        """Verify retrieve returns one NodeWithScore per search result."""
        mock_index = MagicMock()
        mock_index.is_built = True
        mock_results = [
            ("microservices", 0.95),
            ("event-driven", 0.87),
            ("layered-monolith", 0.72),
        ]
        mock_index.search.return_value = mock_results

        retriever = DomainVectorRetriever(
            vector_index=mock_index,
            similarity_top_k=5,
        )

        result = retriever._retrieve(QueryBundle(query_str="distributed systems"))

        assert isinstance(result, list)
        assert len(result) == len(mock_results)
        for item in result:
            assert isinstance(item, NodeWithScore)
            assert isinstance(item.node, TextNode)


class TestNodeMetadataContainsSlug:
    """UT-VRET-2: node.metadata["slug"] equals the domain."""

    def test_node_metadata_contains_slug(self):
        """Verify each result node has metadata["slug"] matching its domain."""
        mock_index = MagicMock()
        mock_index.is_built = True
        mock_index.search.return_value = [
            ("microservices", 0.9),
            ("event-driven", 0.8),
        ]

        retriever = DomainVectorRetriever(vector_index=mock_index, similarity_top_k=5)
        result = retriever._retrieve(QueryBundle(query_str="query"))

        slugs = {item.node.metadata["slug"] for item in result}
        assert slugs == {"microservices", "event-driven"}

    def test_node_metadata_contains_domain(self):
        """Verify metadata["domain"] also equals the domain string."""
        mock_index = MagicMock()
        mock_index.is_built = True
        mock_index.search.return_value = [("microservices", 0.9)]

        retriever = DomainVectorRetriever(vector_index=mock_index, similarity_top_k=5)
        result = retriever._retrieve(QueryBundle(query_str="query"))

        assert result[0].node.metadata["domain"] == "microservices"


class TestScoreMatchesSearchScore:
    """UT-VRET-3: score propagates from DomainVectorIndex.search()."""

    def test_score_matches_search_score(self):
        """Verify NodeWithScore.score matches what search() returned."""
        mock_index = MagicMock()
        mock_index.is_built = True
        mock_index.search.return_value = [
            ("microservices", 0.95),
            ("event-driven", 0.72),
        ]

        retriever = DomainVectorRetriever(vector_index=mock_index, similarity_top_k=5)
        result = retriever._retrieve(QueryBundle(query_str="query"))

        scores = {item.score for item in result}
        assert scores == {0.95, 0.72}

    def test_score_is_float(self):
        """Verify scores are Python floats."""
        mock_index = MagicMock()
        mock_index.is_built = True
        mock_index.search.return_value = [("microservices", 0.95)]

        retriever = DomainVectorRetriever(vector_index=mock_index, similarity_top_k=5)
        result = retriever._retrieve(QueryBundle(query_str="query"))

        assert isinstance(result[0].score, float)


class TestRespectsSimilarityTopK:
    """UT-VRET-4: similarity_top_k is respected."""

    def test_respects_similarity_top_k(self):
        """Verify at most similarity_top_k results are returned.

        The real DomainVectorIndex.search(k=2) returns at most 2 results.
        Our test mock must be configured to return only 2 so we verify
        that _retrieve passes k=similarity_top_k to search().
        """
        mock_index = MagicMock()
        mock_index.is_built = True
        expected_results = [
            ("d1", 0.9),
            ("d2", 0.8),
        ]
        mock_index.search.return_value = expected_results

        retriever = DomainVectorRetriever(vector_index=mock_index, similarity_top_k=2)

        result = retriever._retrieve(QueryBundle(query_str="query"))

        assert len(result) == len(expected_results)

    def test_search_called_with_k_equal_to_similarity_top_k(self):
        """Verify search() is called with k=similarity_top_k."""
        mock_index = MagicMock()
        mock_index.is_built = True
        mock_index.search.return_value = []

        retriever = DomainVectorRetriever(vector_index=mock_index, similarity_top_k=7)

        retriever._retrieve(QueryBundle(query_str="query"))

        mock_index.search.assert_called_once_with(query="query", k=7)


class TestUnbuiltIndexReturnsEmpty:
    """UT-VRET-5: unbuilt index returns empty list."""

    def test_unbuilt_index_returns_empty(self):
        """Verify retrieve on unbuilt index returns an empty list (no exception)."""
        mock_index = MagicMock()
        mock_index.is_built = False

        retriever = DomainVectorRetriever(vector_index=mock_index, similarity_top_k=5)

        result = retriever._retrieve(QueryBundle(query_str="query"))

        assert result == []
        mock_index.search.assert_not_called()


class TestTextNodeTextEqualsDomain:
    """UT-VRET-6: node.text equals the domain string."""

    def test_text_node_text_equals_domain(self):
        """Verify node.text is exactly the domain string returned by search()."""
        mock_index = MagicMock()
        mock_index.is_built = True
        mock_index.search.return_value = [
            ("microservices", 0.9),
            ("event-driven", 0.8),
        ]

        retriever = DomainVectorRetriever(vector_index=mock_index, similarity_top_k=5)
        result = retriever._retrieve(QueryBundle(query_str="query"))

        texts = {item.node.text for item in result}
        assert texts == {"microservices", "event-driven"}

    def test_node_id_is_vec_prefixed(self):
        """Verify node.id_ starts with 'vec-'."""
        mock_index = MagicMock()
        mock_index.is_built = True
        mock_index.search.return_value = [("microservices", 0.9)]

        retriever = DomainVectorRetriever(vector_index=mock_index, similarity_top_k=5)
        result = retriever._retrieve(QueryBundle(query_str="query"))

        assert result[0].node.id_.startswith("vec-")


class TestRetrieveInherited:
    """Smoke test that the public .retrieve() method (inherited from BaseRetriever) works."""

    def test_public_retrieve_method_works(self):
        """Verify .retrieve(query_str) routes to _retrieve correctly."""
        mock_index = MagicMock()
        mock_index.is_built = True
        expected_score = 0.9
        mock_index.search.return_value = [("microservices", expected_score)]

        retriever = DomainVectorRetriever(vector_index=mock_index, similarity_top_k=5)

        result = retriever.retrieve("distributed systems")

        assert len(result) == 1
        assert result[0].node.text == "microservices"
        assert result[0].score == expected_score
