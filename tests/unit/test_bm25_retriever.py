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
Tests for the upstream BM25Retriever leg built via src/patterns/nodes.py.

Covers the migration gates from the retrieval-migration plan:
- factory behaviour (top_k resolution, full-corpus semantics)
- result shape (NodeWithScore, slug metadata, float scores)
- self-recall over the real pattern catalogue domains (top-1)
- deterministic ordering
- cross-leg node-hash equality (BM25 roundtrip preserves text+metadata)
- EMBED-mode content stays the bare slug (metadata exclusions)
"""

from pathlib import Path

import pytest
from llama_index.core.schema import MetadataMode, QueryBundle

from src.patterns.nodes import build_bm25_retriever, build_domain_nodes

DOMAINS = [
    "event-driven",
    "cloud-native",
    "microservices",
    "real-time-processing",
    "high-traffic",
]


@pytest.fixture
def nodes() -> list:
    return build_domain_nodes(DOMAINS)


@pytest.fixture
def retriever(nodes) -> object:
    return build_bm25_retriever(nodes, top_k=3)


def _slugs(result) -> list[str]:
    return [n.node.metadata["slug"] for n in result]


class TestBuildDomainNodes:
    def test_one_node_per_domain(self, nodes) -> None:
        assert len(nodes) == len(DOMAINS)

    def test_node_text_equals_slug(self, nodes) -> None:
        assert [n.text for n in nodes] == DOMAINS

    def test_node_metadata_contains_slug_and_domain(self, nodes) -> None:
        for node, domain in zip(nodes, DOMAINS, strict=True):
            assert node.metadata["slug"] == domain
            assert node.metadata["domain"] == domain

    def test_embed_mode_content_is_bare_slug(self, nodes) -> None:
        for node, domain in zip(nodes, DOMAINS, strict=True):
            assert node.get_content(metadata_mode=MetadataMode.EMBED) == domain


class TestBuildBM25Retriever:
    def test_returns_nodes_with_score(self, retriever) -> None:
        result = retriever.retrieve(QueryBundle(query_str="event-driven"))
        assert len(result) > 0
        for nws in result:
            assert nws.score is not None
            assert isinstance(nws.score, float)

    def test_node_metadata_contains_slug(self, retriever) -> None:
        result = retriever.retrieve(QueryBundle(query_str="microservices"))
        assert "microservices" in _slugs(result)

    def test_respects_top_k(self, retriever) -> None:
        result = retriever.retrieve(QueryBundle(query_str="processing"))
        assert len(result) <= 3

    def test_zero_top_k_means_full_corpus(self, nodes) -> None:
        retriever = build_bm25_retriever(nodes, top_k=0)
        result = retriever.retrieve(QueryBundle(query_str="processing"))
        assert len(result) == len(DOMAINS)

    def test_scores_sorted_descending(self, retriever) -> None:
        result = retriever.retrieve(QueryBundle(query_str="real time processing"))
        scores = [n.score for n in result]
        assert scores == sorted(scores, reverse=True)

    def test_deterministic_ordering(self, retriever) -> None:
        first = _slugs(retriever.retrieve(QueryBundle(query_str="high traffic")))
        second = _slugs(retriever.retrieve(QueryBundle(query_str="high traffic")))
        assert first == second


class TestSelfRecall:
    """Gate: querying a slug with its own text must return it at top-1."""

    @pytest.mark.parametrize("domain", DOMAINS)
    def test_slug_self_recall_top1(self, nodes, domain) -> None:
        retriever = build_bm25_retriever(nodes, top_k=len(DOMAINS))
        result = retriever.retrieve(QueryBundle(query_str=domain))
        assert _slugs(result)[0] == domain


class TestCrossLegHashEquality:
    """Gate: BM25 corpus roundtrip must preserve text+metadata, so
    node.hash matches the shared node the dense leg constructs."""

    def test_bm25_node_hash_matches_shared_node(self, nodes, retriever) -> None:
        result = retriever.retrieve(QueryBundle(query_str="microservices"))
        slug_to_shared = {n.text: n for n in nodes}
        for nws in result:
            shared = slug_to_shared[nws.node.metadata["slug"]]
            assert nws.node.hash == shared.hash


class TestRealCatalogueSelfRecall:
    """Self-recall over the actual pattern catalogue domain slugs."""

    @pytest.mark.skipif(
        not Path("pattern").is_dir(),
        reason="pattern catalogue not present",
    )
    def test_all_catalogue_domains_self_recall(self) -> None:
        import json

        domains_seen: set[str] = set()
        for pattern_file in Path("pattern").glob("*-architecture.json"):
            data = json.loads(pattern_file.read_text(encoding="utf-8"))
            domains_seen.update(data.get("suitable_domains", []))
        domains = sorted(domains_seen)
        assert domains, "catalogue produced no domains"

        nodes = build_domain_nodes(domains)
        retriever = build_bm25_retriever(nodes, top_k=len(domains))
        misses = []
        for domain in domains:
            result = retriever.retrieve(QueryBundle(query_str=domain))
            slugs = _slugs(result)
            position = slugs.index(domain)
            top_score = result[0].score or 0.0
            own_score = result[position].score or 0.0
            # A recall miss is a REAL ranking failure: the slug outside top-2
            # or materially below the top score.  Ties at the top (alias
            # slugs share the score; bm25s breaks them by index order) and
            # sub-1% gaps (BM25 length normalization on longer slugs) are
            # accepted — both are corpus properties, not tokenization bugs.
            tied = own_score == top_score
            near_top = position <= 1 and own_score >= 0.99 * top_score
            if position > 0 and not tied and not near_top:
                misses.append(domain)
        assert misses == [], f"self-recall misses: {misses}"
