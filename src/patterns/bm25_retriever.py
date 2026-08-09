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
DomainBM25Retriever — wraps DomainBM25Index.search() as a LlamaIndex BaseRetriever.

Replaces the BM25Retriever path that was broken because
DomainBM25Index.build_index() never stored the corpus on the bm25s.BM25 engine
(via bm25s.BM25.index()), causing BM25Retriever(existing_bm25=...).corpus
to be None and crashing at retrieval time.

The new class bypasses LlamaIndex's BM25Retriever entirely, mirroring
how DomainVectorRetriever works for the dense leg.
"""

from __future__ import annotations

import logging
from typing import Any

from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from src.patterns.bm25_index import DomainBM25Index

logger = logging.getLogger(__name__)


class DomainBM25Retriever(BaseRetriever):
    """
    LlamaIndex BaseRetriever backed by DomainBM25Index.search().

    Wraps the already-tested DomainBM25Index.search() method, which
    searches via bm25s.BM25 using the indexed domain slugs and returns
    (domain, score) tuples. This retriever converts those into
    LlamaIndex NodeWithScore objects so it integrates seamlessly
    with HybridPatternRetriever's fusion pipeline.

    Attributes:
        _bm25_index: DomainBM25Index instance with built bm25s.BM25 index.
        _similarity_top_k: Number of top results to return.
    """

    def __init__(
        self,
        bm25_index: DomainBM25Index,
        similarity_top_k: int = 20,
        **kwargs: Any,
    ) -> None:
        """
        Initialize DomainBM25Retriever.

        Args:
            bm25_index: DomainBM25Index instance with built bm25s.BM25 index.
            similarity_top_k: Number of top-K results to return.
            **kwargs: Passed to BaseRetriever (callback_manager, etc.).
        """
        super().__init__(**kwargs)
        self._bm25_index = bm25_index
        self._similarity_top_k = similarity_top_k

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        """
        Retrieve top-K domains matching the lexical query.

        Calls DomainBM25Index.search() which:
        1. Tokenizes and stems the query via bm25s.tokenize()
        2. Scores domains via bm25s.BM25.retrieve()
        3. Returns (domain, score) tuples sorted by score descending

        Each result is wrapped as NodeWithScore(node=TextNode(...), score=...).

        Args:
            query_bundle: QueryBundle with query_str (embedding is not used for BM25).

        Returns:
            List of NodeWithScore objects sorted by score descending, or empty list
            if the index is not built.
        """
        if not self._bm25_index.is_built:
            logger.warning("DomainBM25Retriever retrieved on unbuilt index, returning empty")
            return []

        results = self._bm25_index.search(
            query=query_bundle.query_str,
            k=self._similarity_top_k,
        )

        nodes: list[NodeWithScore] = []
        for domain, score in results:
            node = TextNode(
                text=domain,
                metadata={"slug": domain, "domain": domain},
                id_=f"bm25-{domain}",
            )
            nodes.append(NodeWithScore(node=node, score=float(score)))

        return nodes
