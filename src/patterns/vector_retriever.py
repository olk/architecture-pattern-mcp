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
DomainVectorRetriever — wraps DomainVectorIndex.search() as a LlamaIndex BaseRetriever.

Replaces the VectorIndexRetriever path that was broken because
DomainVectorIndex.build_index() never populated the LlamaIndex docstore
(via FaissVectorStore.add(nodes)), causing KeyError when the retriever
tried to look up node IDs that didn't exist in index_struct.nodes_dict.

The new class bypasses LlamaIndex's broken docstore plumbing entirely,
mirroring how DomainBM25Index.as_retriever() / BM25Retriever already work
with their own bm25s.BM25 engine and corpus.

Note: FaissVectorStore is no longer used; DomainVectorIndex now stores
the raw faiss.IndexFlatIP directly.
"""

from __future__ import annotations

import logging
from typing import Any

from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from src.patterns.vector_index import DomainVectorIndex

logger = logging.getLogger(__name__)


class DomainVectorRetriever(BaseRetriever):
    """
    LlamaIndex BaseRetriever backed by DomainVectorIndex.search().

    Wraps the already-tested DomainVectorIndex.search() method, which
    embeds the query via InstructionAwareEmbedding, searches FAISS directly,
    and returns (domain, score) tuples.  This retriever converts those
    into LlamaIndex NodeWithScore objects so it integrates seamlessly
    with HybridPatternRetriever's fusion pipeline.

    Attributes:
        _vector_index: DomainVectorIndex instance for FAISS search.
        _similarity_top_k: Number of top results to return.
    """

    def __init__(
        self,
        vector_index: DomainVectorIndex,
        similarity_top_k: int = 20,
        **kwargs: Any,
    ) -> None:
        """
        Initialize DomainVectorRetriever.

        Args:
            vector_index: DomainVectorIndex instance with built FAISS index.
            similarity_top_k: Number of top-K results to return.
            **kwargs: Passed to BaseRetriever (callback_manager, etc.).
        """
        super().__init__(**kwargs)
        self._vector_index = vector_index
        self._similarity_top_k = similarity_top_k

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        """
        Retrieve top-K domains most similar to the query.

        Calls DomainVectorIndex.search() which:
        1. Embeds the query via InstructionAwareEmbedding (query_instruction prefix)
        2. Searches FAISS via IndexFlatIP (cosine similarity on L2-normalised vectors)
        3. Returns (domain, score) tuples sorted by score descending

        Each result is wrapped as NodeWithScore(node=TextNode(...), score=...).

        Args:
            query_bundle: QueryBundle with query_str (embedding is computed on demand).

        Returns:
            List of NodeWithScore objects sorted by score descending, or empty list
            if the index is not built.
        """
        if not self._vector_index.is_built:
            logger.warning("DomainVectorRetriever retrieved on unbuilt index, returning empty")
            return []

        results = self._vector_index.search(
            query=query_bundle.query_str,
            k=self._similarity_top_k,
        )

        nodes: list[NodeWithScore] = []
        for domain, score in results:
            node = TextNode(
                text=domain,
                metadata={"slug": domain, "domain": domain},
                id_=f"vec-{domain}",
            )
            nodes.append(NodeWithScore(node=node, score=float(score)))

        return nodes
