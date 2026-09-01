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
Unit tests for DomainBM25Index class.

Test Case IDs: UT-BM25-1 through UT-BM25-8
Validates Requirements: FR-BM25-1, FR-BM25-2

Test Scenarios:
- SCEN-BM25-1: DomainBM25Index is not built initially
- SCEN-BM25-2: DomainBM25Index builds from domain list
- SCEN-BM25-3: DomainBM25Index search returns (slug, score) tuples
- SCEN-BM25-4: DomainBM25Index search on unbuilt returns empty
- SCEN-BM25-6: DomainBM25Index as_retriever returns BM25Retriever when built
- SCEN-BM25-7: DomainBM25Index as_retriever raises when not built
- SCEN-BM25-8: DomainBM25Index handles empty domain list
"""

from src.patterns.bm25_index import DomainBM25Index


class TestDomainBM25IndexInit:
    def test_domain_bm25_index_class_exists(self):
        index = DomainBM25Index()
        assert index is not None

    def test_is_built_false_initially(self):
        index = DomainBM25Index()
        assert index.is_built is False

    def test_domains_empty_initially(self):
        index = DomainBM25Index()
        assert index.domains == []


class TestDomainBM25IndexBuildIndex:
    def test_build_index_stores_domains(self):
        index = DomainBM25Index()
        domains = ["event-driven", "cloud-native", "microservices"]
        index.build_index(domains)
        assert index.domains == domains
        assert index.is_built is True

    def test_build_index_empty_domains(self):
        index = DomainBM25Index()
        index.build_index([])
        assert index.domains == []
        assert index.is_built is False


class TestDomainBM25IndexSearch:
    def test_search_returns_results(self):
        index = DomainBM25Index()
        domains = ["event-driven-architecture", "cloud-native-applications", "microservices"]
        index.build_index(domains)
        results = index.search("event processing", k=5)
        assert isinstance(results, list)
        assert len(results) <= 5
        for slug, score in results:
            assert isinstance(slug, str)
            assert isinstance(score, float)

    def test_search_on_unbuilt_index_returns_empty(self):
        index = DomainBM25Index()
        results = index.search("event", k=5)
        assert results == []

    def test_search_respects_k_parameter(self):
        index = DomainBM25Index()
        domains = ["event-driven", "cloud-native", "microservices", "distributed", "serverless"]
        index.build_index(domains)
        results = index.search("event", k=3)
        assert len(results) == 3


class TestDomainBM25IndexAsRetriever:
    def test_as_retriever_returns_bm25_retriever_when_built(self):
        index = DomainBM25Index()
        domains = ["event-driven", "cloud-native"]
        index.build_index(domains)
        retriever = index.as_retriever(top_k=10)
        assert retriever is not None
        assert hasattr(retriever, "retrieve")

    def test_as_retriever_raises_when_unbuilt(self):
        index = DomainBM25Index()
        try:
            index.as_retriever(top_k=10)
        except RuntimeError as e:
            assert "must be built" in str(e)
        else:
            assert False, "Expected RuntimeError"

    def test_as_retriever_reuses_engine(self):
        index = DomainBM25Index()
        domains = ["event-driven", "cloud-native", "microservices"]
        index.build_index(domains)
        r1 = index.as_retriever(top_k=20)
        r2 = index.as_retriever(top_k=10)
        assert r1 is not None
        assert r2 is not None
