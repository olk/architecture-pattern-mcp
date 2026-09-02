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
Shared domain-slug node set and LlamaIndex-native leg factories.

Both retrieval legs consume the SAME TextNode objects (one per unique domain
slug).  Node identity matters for stage-1 fusion: ``TextNode.hash`` is
``sha256(str(text) + str(metadata))`` (``id_`` is NOT part of the hash), so
identical text+metadata across legs is what lets reciprocal-rank fusion
accumulate consensus scores per slug.

The ``excluded_*_metadata_keys`` lists keep EMBED/LLM-mode content equal to
the bare slug (upstream BM25Retriever tokenizes ``get_content(EMBED)`` and
VectorStoreIndex embeds the same), while leaving ``node.metadata`` — and
therefore ``node.hash`` — untouched.
"""

from __future__ import annotations

import logging

import faiss
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.schema import TextNode
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.vector_stores.faiss import FaissVectorStore

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "english"


def build_domain_nodes(unique_domains: list[str]) -> list[TextNode]:
    """Build the shared node set (one TextNode per unique domain slug).

    Args:
        unique_domains: Deduplicated domain slugs from the pattern catalogue.

    Returns:
        TextNodes with slug metadata and metadata-mode exclusions applied.
    """
    return [
        TextNode(
            text=domain,
            metadata={"slug": domain, "domain": domain},
            id_=domain,
            excluded_embed_metadata_keys=["slug", "domain"],
            excluded_llm_metadata_keys=["slug", "domain"],
        )
        for domain in unique_domains
    ]


def build_bm25_retriever(nodes: list[TextNode], top_k: int) -> BM25Retriever:
    """Build the BM25 retrieval leg via the upstream LlamaIndex retriever.

    Uses ``bm25s.BM25`` internally (same engine the former custom
    DomainBM25Index wrapped) with Lucene defaults (k1=1.5, b=0.75),
    PyStemmer english stemming (upstream default when ``stemmer`` is
    omitted), and english stopword removal on the corpus side.

    Args:
        nodes: Shared domain-slug nodes (see :func:`build_domain_nodes`).
        top_k: Candidates per query. ``<= 0`` means "full corpus"
            (lossless stage-1 recall) and is resolved to the node count.

    Returns:
        BM25Retriever constructed once at warmup; safe to reuse across
        requests (corpus tokenization happens exactly here, never per
        query).
    """
    effective_top_k = top_k if top_k > 0 else len(nodes)
    effective_top_k = min(effective_top_k, len(nodes))

    retriever = BM25Retriever.from_defaults(
        nodes=nodes,
        language=DEFAULT_LANGUAGE,
        similarity_top_k=effective_top_k,
    )
    logger.debug(
        "BM25 retrieval leg built via upstream BM25Retriever",
        extra={"corpus_size": len(nodes), "top_k": effective_top_k},
    )
    return retriever


def build_vector_index(
    nodes: list[TextNode],
    embed_model: BaseEmbedding,
) -> VectorStoreIndex:
    """Build the dense retrieval index via the upstream LlamaIndex stack.

    ``FaissVectorStore`` wraps an ``faiss.IndexFlatIP``; because every
    embedding is L2-normalised (see embedder.py), inner product equals
    cosine similarity — identical score semantics to the former custom
    DomainVectorIndex.  Everything stays in memory: no ``persist()`` is
    called anywhere.

    Args:
        nodes: Shared domain-slug nodes (same objects as the BM25 leg,
            which guarantees identical ``node.hash`` per slug across legs).
        embed_model: InstructionAwareEmbedding (or compatible BaseEmbedding).

    Returns:
        VectorStoreIndex; call ``.as_retriever(similarity_top_k=k)`` for
        the dense leg. Constructed once at warmup.
    """
    dim = len(embed_model.get_query_embedding("dimension-probe"))
    vector_store = FaissVectorStore(faiss_index=faiss.IndexFlatIP(dim))
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex(
        nodes=nodes,
        storage_context=storage_context,
        embed_model=embed_model,
        show_progress=False,
    )
    logger.debug(
        "Dense retrieval leg built via VectorStoreIndex over FaissVectorStore",
        extra={"corpus_size": len(nodes), "dim": dim},
    )
    return index
