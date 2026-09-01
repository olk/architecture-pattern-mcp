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
Fusion function adapter for HybridPatternRetriever.

Provides a callable wrapper around LlamaIndex's internal fusion instance methods
so they can be used in a manual two-leg retrieval pipeline (separate queries for
dense vs. BM25 legs) without going through QueryFusionRetriever.

LlamaIndex's _run_sync_queries broadcasts the SAME query to all retrievers,
so QueryFusionRetriever cannot be used when the two legs need different queries
(normalized_domain for BM25, raw user_domain for dense).

Fusion strategies implemented manually to avoid LlamaIndex's query_tuple[1] usage
which conflates fusion_rank (ordering) with retriever_idx (weight lookup).

Supported modes:
  simple             - rank-union de-duplication (dense + BM25 ranks)
  reciprocal_rerank  - Reciprocal Rank Fusion (RRF), k=60
"""

from __future__ import annotations

from llama_index.core.schema import NodeWithScore

from src.config import FusionMode

RRF_K: float = 60.0


def reciprocal_rank_score(rank: int, k: float = RRF_K) -> float:
    r"""Reciprocal-rank contribution for one ranked list position.

    Implements 1 / (rank + k - 1) — the same arithmetic used by
    :func:`_fuse_rrf` per leg (rank starts at 1, so the best item
    scores 1/k).  Shared by stage-1 fusion and the retriever's
    :paramref:`HybridPatternRetriever.rerank_selection` =\ ``rank_fusion``
    slug-cut so both use one definition of "reciprocal rank".

    Note: the historical module docstring claimed ``rank=1 -> 1/61``; the
    code has always computed 1/60 for k=60.  This helper documents the
    actual behaviour; the stale claim is corrected rather than the formula
    changed, because altering it would shift every stored fusion score
    relative to the :paramref:`RetrievalConfig.min_fusion_score` threshold.
    """
    return 1.0 / (rank + k - 1)


def apply_fusion(
    mode: FusionMode,
    dense_nodes: list[NodeWithScore],
    bm25_nodes: list[NodeWithScore],
) -> list[NodeWithScore]:
    """
    Apply the specified fusion strategy to dense + BM25 result sets.

    Uses RETRIVER-SPECIFIC ranks (not cross-retriever fusion ranks) to avoid
    LlamaIndex's query_tuple[1] misuse where fusion_rank and retriever_idx collide.

    Args:
        mode:         Fusion strategy ("simple", "reciprocal_rerank").
        dense_nodes:  Results from the dense / embedding retriever.
        bm25_nodes:   Results from the BM25 lexical retriever.

    Returns:
        Fused list of NEW NodeWithScore objects sorted by fusion score descending.
        Input NodeWithScore objects are NOT mutated (issue #24).
    """
    if mode == "simple":
        return _fuse_simple(dense_nodes, bm25_nodes)
    if mode == "reciprocal_rerank":
        return _fuse_rrf(dense_nodes, bm25_nodes)
    raise ValueError(f"Unknown fusion mode: {mode}")


def _fuse_simple(
    dense_nodes: list[NodeWithScore],
    bm25_nodes: list[NodeWithScore],
) -> list[NodeWithScore]:
    """Rank-union: dense cosine and BM25 raw scores are not comparable, so we
    score each node by the best per-leg rank (1.0/rank). Top of merged list wins.
    """
    best: dict[str, tuple[float, NodeWithScore]] = {}
    for rank, node in enumerate(dense_nodes):
        h = node.node.hash
        rrf = 1.0 / (rank + 1)
        if h not in best or rrf > best[h][0]:
            best[h] = (rrf, node)
    for rank, node in enumerate(bm25_nodes):
        h = node.node.hash
        rrf = 1.0 / (rank + 1)
        if h not in best or rrf > best[h][0]:
            best[h] = (rrf, node)
    return [NodeWithScore(node=nws.node, score=score) for score, nws in sorted(
        best.values(), key=lambda x: x[0], reverse=True
    )]


def _fuse_rrf(
    dense_nodes: list[NodeWithScore],
    bm25_nodes: list[NodeWithScore],
    k: float = RRF_K,
) -> list[NodeWithScore]:
    """Reciprocal Rank Fusion (Cormack et al. SIGIR'09).

    For each retriever, rank starts at 1 (off-by-one fix, issue #23):
    rank=1 → 1/(k); rank=60 → 1/(k+59).
    """
    fused_scores: dict[str, float] = {}
    hash_to_node: dict[str, NodeWithScore] = {}
    for rank, node in enumerate(dense_nodes, start=1):
        h = node.node.hash
        hash_to_node[h] = node
        fused_scores[h] = fused_scores.get(h, 0.0) + reciprocal_rank_score(rank, k)
    for rank, node in enumerate(bm25_nodes, start=1):
        h = node.node.hash
        hash_to_node[h] = node
        fused_scores[h] = fused_scores.get(h, 0.0) + reciprocal_rank_score(rank, k)
    new_nodes = [
        NodeWithScore(node=hash_to_node[h].node, score=score)
        for h, score in fused_scores.items()
    ]
    return sorted(new_nodes, key=lambda x: x.score or 0.0, reverse=True)
