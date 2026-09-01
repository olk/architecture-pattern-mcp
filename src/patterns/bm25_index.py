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
DomainBM25Index - Lexical retriever over architecture pattern domain slugs.

Uses bm25s.BM25 for efficient BM25 scoring over domain slugs.
as_retriever() returns a DomainBM25Retriever that wraps our search() method,
avoiding the broken LlamaIndex BM25Retriever(existing_bm25=...).corpus=None bug.
"""

from __future__ import annotations

import logging

import bm25s
import Stemmer

logger = logging.getLogger(__name__)


class DomainBM25Index:
    """
    BM25 lexical retriever over short hyphenated domain slugs.

    Corpus: 213 unique slugs (3-59 chars each) from pattern suitable_domains.
    Model: bm25s with Lucene defaults (k1=1.5, b=0.75) matching Elasticsearch.

    Wraps llama_index.retrievers.bm25.BM25Retriever. The underlying bm25s.BM25
    engine is retained so that as_retriever() can construct a fresh BM25Retriever
    for different top_k values without re-tokenising the corpus.

    Usage:
        index = DomainBM25Index()
        index.build_index(["event-driven-architecture", "cloud-native-applications"])
        results = index.search("real-time processing", k=5)
        retriever = index.as_retriever(top_k=20)  # BM25Retriever for QueryFusionRetriever
    """

    DEFAULT_LANGUAGE = "english"

    def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
        self._language = language
        self._stemmer = Stemmer.Stemmer(language)
        self._domains: list[str] = []
        self._bm25_engine: bm25s.BM25 | None = None

    @property
    def is_built(self) -> bool:
        return self._bm25_engine is not None

    @property
    def domains(self) -> list[str]:
        return list(self._domains)

    def build_index(self, domains: list[str]) -> None:
        if not domains:
            logger.warning("build_index called with empty domain list")
            self._domains = []
            self._bm25_engine = None
            return

        self._domains = list(domains)

        tokenized = bm25s.tokenize(
            self._domains,
            stopwords=self._language,
            stemmer=self._stemmer,
        )
        self._bm25_engine = bm25s.BM25()
        self._bm25_engine.index(tokenized)

        logger.info(
            "BM25 index built",
            extra={
                "domain_count": len(self._domains),
                "language": self._language,
            },
        )

    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        if not self.is_built:
            logger.warning("search called on unbuilt index, returning empty results")
            return []

        k = min(k, len(self._domains))

        query_tokens = bm25s.tokenize(
            [query],
            stopwords=self._language,
            stemmer=self._stemmer,
        )

        assert self._bm25_engine is not None
        indices, scores = self._bm25_engine.retrieve(query_tokens, k=k)

        results = []
        for idx, score in zip(indices[0], scores[0], strict=True):
            i = int(idx)
            if 0 <= i < len(self._domains):
                results.append((self._domains[i], float(score)))

        logger.debug(
            f"BM25 search '{query}' returned {len(results)} results",
            extra={"top_score": results[0][1] if results else 0.0},
        )
        return results

    def as_retriever(self, top_k: int = 20) -> "DomainBM25Retriever":  # type: ignore[valid-type]  # noqa: F821, UP037
        """Build a DomainBM25Retriever backed by our search() method.

        The returned retriever reuses the same bm25s.BM25 engine and avoids
        the broken LlamaIndex BM25Retriever(existing_bm25=...).corpus=None bug.

        Args:
            top_k: Number of top results to return from the retriever.

        Returns:
            DomainBM25Retriever configured with the indexed corpus.

        Raises:
            RuntimeError: If the index has not been built yet.
        """
        from src.patterns.bm25_retriever import DomainBM25Retriever

        if not self.is_built:
            raise RuntimeError("Index must be built before retrieving")

        effective_top_k = min(top_k, len(self._domains))

        return DomainBM25Retriever(
            bm25_index=self,
            similarity_top_k=effective_top_k,
        )
