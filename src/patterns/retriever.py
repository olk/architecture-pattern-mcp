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
HybridPatternRetriever - Configurable two-leg fusion of BM25 + dense embeddings.

Stage-1 (recall) retrieval pipeline:
  1. Build FAISS index via DomainVectorIndex over domain slugs
  2. Build BM25Retriever over the same domain slugs
  3. Dense leg:  embed(user_domain) → faiss top-K via DomainVectorRetriever
  4. BM25 leg:   tokenize(normalized_domain) → bm25s top-K via DomainBM25Index.as_retriever
     (bm25_top_k / dense_top_k = 0 means "full corpus" — lossless recall)
  5. Apply fusion function: simple | reciprocal_rerank | relative_score | dist_based_score
  6. Optionally rerank with TextEmbeddingInference (cross-encoder via TEI sidecar)
  7. Resolve each NodeWithScore.slug → patterns via PatternLoader.filter_by_domain
  8. Aggregate: pattern_score = max(fusion_score) over slugs surfacing it
  9. Return ALL resolved patterns with fusion scores (NO top-K truncation here).
     Requirements-aware selection of top_k_patterns happens downstream in the
     analyze phase, which scores each candidate against the requirements.
     Fallback to layered-monolith only when retrieval is genuinely empty.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from llama_index.core.schema import QueryBundle
from llama_index.postprocessor.tei_rerank import TextEmbeddingInference

if TYPE_CHECKING:
    from llama_index.core.retrievers import BaseRetriever

from src.patterns._fusion import FusionMode, apply_fusion
from src.patterns.bm25_index import DomainBM25Index
from src.patterns.loader import PatternLoader
from src.patterns.vector_index import DomainVectorIndex
from src.patterns.vector_retriever import DomainVectorRetriever

logger = logging.getLogger(__name__)

# Canonical fallback: used ONLY when no pattern in the catalogue matches the
# user's domain.  This value reaches ArchitectureOverview.style only through
# a genuine retrieval result.  Adapter helpers (src/tools/_adapters.py) MUST
# NOT synthesise a style on validation failure — they raise
# MalformedArchitectureOverviewError (ERR_012) instead.
DEFAULT_FALLBACK_PATTERN_NAME = "layered-monolith"

# Fixed cap for INFO-log summaries only; decoupled from retrieval k so that
# k=0 (full corpus) does not produce "showing top 0" log lines.
LOG_SUMMARY_CAP = 10


def _summarize_nodes(nodes: list[Any], cap: int) -> dict[str, Any]:
    """Build a top-N summary of NodeWithScore items for INFO logging.

    Args:
        nodes: List of NodeWithScore from a retriever leg.
        cap:   Maximum number of items to include in the summary.

    Returns:
        A dict with ``count`` (total returned), ``shown`` (items in top list),
        and ``top`` (list of ``{slug, score}`` dicts).
    """
    shown = [
        {"slug": n.node.metadata.get("slug", ""), "score": float(n.score or 0.0)}
        for n in nodes[:cap]
    ]
    return {"count": len(nodes), "shown": len(shown), "top": shown}


class HybridPatternRetriever:
    """
    Hybrid retriever using two separate retrieval legs (dense + BM25) with a
    configurable fusion strategy and optional cross-encoder reranking.

    The two legs receive different queries:
    - Dense leg:    raw ``user_domain`` (benefits from embedding semantics)
    - BM25 leg:     ``normalized_domain`` (exact slug token matching)

    This separation is intentional: QueryFusionRetriever broadcasts the same query
    to all retrievers, which would lose the normalisation benefit for BM25.
    """

    def __init__(  # noqa: PLR0913
        self,
        bm25_index: DomainBM25Index,
        vector_index: DomainVectorIndex,
        pattern_loader: PatternLoader,
        bm25_top_k: int = 0,
        dense_top_k: int = 0,
        mode: FusionMode = "reciprocal_rerank",
        min_fusion_score: float = 0.0,
        enable_reranking: bool = False,
        rerank_top_n: int = 10,
        reranker_config: Any | None = None,
    ) -> None:
        self._bm25 = bm25_index
        self._vector = vector_index
        self._loader = pattern_loader
        self._bm25_top_k = bm25_top_k
        self._dense_top_k = dense_top_k
        self._mode: FusionMode = mode
        self._min_fusion_score = min_fusion_score
        self._enable_reranking = enable_reranking
        self._rerank_top_n = rerank_top_n
        self._reranker_config = reranker_config
        self._reranker: TextEmbeddingInference | None = None
        self._dense_retriever: BaseRetriever | None = None
        self._bm25_retriever: BaseRetriever | None = None

    def _ensure_retrievers(self) -> None:
        """Lazily build the underlying retrievers once.

        A top_k of 0 means "full corpus" (lossless stage-1 recall). It is
        resolved to the number of indexed domain slugs before being passed
        to the underlying retrievers, which require k >= 1.
        """
        if self._dense_retriever is not None and self._bm25_retriever is not None:
            return

        if not self._bm25.is_built:
            raise RuntimeError("BM25 index must be built before retrieving")

        if not self._vector.is_built:
            raise RuntimeError("Vector index must be built before retrieving")

        # 0 = full corpus (lossless recall); resolve to actual slug count.
        corpus_n = max(len(self._bm25.domains), len(self._vector.domains))
        dense_k = self._dense_top_k if self._dense_top_k > 0 else corpus_n
        bm25_k = self._bm25_top_k if self._bm25_top_k > 0 else corpus_n

        self._dense_retriever = DomainVectorRetriever(
            vector_index=self._vector,
            similarity_top_k=dense_k,
        )
        self._bm25_retriever = self._bm25.as_retriever(top_k=bm25_k)

        logger.debug(
            "Hybrid retriever initialised: mode=%s, reranking=%s, "
            "dense_k=%d, bm25_k=%d (corpus=%d)",
            self._mode,
            self._enable_reranking,
            dense_k,
            bm25_k,
            corpus_n,
        )

    def _ensure_reranker(self) -> None:
        """Lazily build the TEI-backed cross-encoder once.

        ``keep_retrieval_score=True`` causes TextEmbeddingInference to
        stash the RRF score in ``node.metadata["retrieval_score"]`` before
        overwriting ``node.score`` with the cross-encoder logit. The caller
        restores the RRF score after reranking so downstream fusion-score
        gating and observability stay calibrated.
        """
        if self._reranker is not None:
            return
        if self._reranker_config is None:
            raise RuntimeError(
                "enable_reranking=True but no reranker_config provided"
            )
        self._reranker = TextEmbeddingInference(
            base_url=self._reranker_config.base_url,
            model_name=self._reranker_config.model,
            timeout=self._reranker_config.timeout,
            top_n=1,
        )
        self._reranker.keep_retrieval_score = True

    def retrieve(
        self,
        user_domain: str,
        normalized_domain: str,
    ) -> list[tuple[dict[str, Any], float]]:
        """
        Find candidate patterns for user_domain using two-leg hybrid retrieval.

        Stage-1 (recall): returns ALL resolved patterns with their fusion scores.
        No top-K truncation is applied here — requirements-aware selection of
        ``top_k_patterns`` happens in the analyze phase (ArchitecturePipeline),
        which scores each candidate against the requirements and only then
        truncates.

        Args:
            user_domain:      Raw domain string from user (embedding query)
            normalized_domain: Pre-normalised domain (BM25 lexical query)

        Returns:
            List of (pattern_dict, fusion_score) tuples sorted by score
            descending. fusion_score is a domain-similarity rank signal (RRF),
            NOT a requirements-fit score.
        """
        self._ensure_retrievers()
        assert self._dense_retriever is not None
        assert self._bm25_retriever is not None

        dense_nodes = self._dense_retriever.retrieve(QueryBundle(query_str=user_domain))
        bm25_nodes = self._bm25_retriever.retrieve(QueryBundle(query_str=normalized_domain))

        logger.debug(
            "Two-leg retrieval: dense=%d nodes, bm25=%d nodes",
            len(dense_nodes),
            len(bm25_nodes),
        )

        logger.info(
            "Dense leg: %d candidates for domain '%s' (showing top %d)",
            len(dense_nodes),
            user_domain,
            min(len(dense_nodes), LOG_SUMMARY_CAP),
            extra={
                "stage": "dense",
                "domain": user_domain,
                "summary": _summarize_nodes(dense_nodes, LOG_SUMMARY_CAP),
            },
        )
        logger.info(
            "BM25 leg: %d candidates for domain '%s' (showing top %d)",
            len(bm25_nodes),
            normalized_domain,
            min(len(bm25_nodes), LOG_SUMMARY_CAP),
            extra={
                "stage": "bm25",
                "domain": normalized_domain,
                "summary": _summarize_nodes(bm25_nodes, LOG_SUMMARY_CAP),
            },
        )

        fused = apply_fusion(
            self._mode,
            dense_nodes,
            bm25_nodes,
        )

        logger.info(
            "Fusion: %d candidates after %s (showing top %d)",
            len(fused),
            self._mode,
            min(len(fused), LOG_SUMMARY_CAP),
            extra={
                "stage": "fusion",
                "mode": self._mode,
                "summary": _summarize_nodes(fused, LOG_SUMMARY_CAP),
            },
        )

        if not fused:
            return self._fallback(user_domain)

        if self._enable_reranking and len(fused) > 1:
            self._ensure_reranker()
            assert self._reranker is not None
            # Lossless: score every fused node, never truncate before scoring.
            # Downstream selection (analyze phase) does the top-N cut.
            self._reranker.top_n = len(fused)
            fused = self._reranker.postprocess_nodes(
                fused, query_bundle=QueryBundle(query_str=user_domain)
            )
            # Restore original RRF scores on NodeWithScore; stash the reranker
            # logit in node.metadata for observability. The downstream
            # min_fusion_score gate (and the analyze phase) still see RRF.
            for nws in fused:
                orig = nws.node.metadata.get("retrieval_score")
                nws.node.metadata["rerank_logit"] = float(nws.score)  # type: ignore[arg-type]
                nws.score = float(orig) if orig is not None else 0.0
            logger.debug("Reranking returned %d nodes (lossless)", len(fused))
            rerank_cap = min(self._rerank_top_n, len(fused))
            logger.info(
                "Reranking: %d candidates after rerank (showing top %d)",
                len(fused),
                rerank_cap,
                extra={
                    "stage": "rerank",
                    "summary": _summarize_nodes(fused, rerank_cap),
                },
            )

        pattern_best: dict[str, tuple[dict[str, Any], float]] = {}
        for nws in fused:
            slug = nws.node.metadata.get("slug", "")
            if not slug:
                continue
            score = nws.score if nws.score is not None else 0.0
            patterns = self._loader.filter_by_domain(slug)
            if not patterns:
                continue
            for p in patterns:
                pid = p.get("name", "")
                if pid not in pattern_best or score > pattern_best[pid][1]:
                    pattern_best[pid] = (p, float(score))

        resolved = list(pattern_best.values())
        resolved.sort(key=lambda x: x[1], reverse=True)

        if not resolved:
            return self._fallback(user_domain)

        best_score = resolved[0][1]
        if best_score < self._min_fusion_score:
            logger.warning(
                "Best fusion score %.4f below threshold %.4f for domain '%s'; "
                "using fallback pattern '%s'",
                best_score,
                self._min_fusion_score,
                user_domain,
                DEFAULT_FALLBACK_PATTERN_NAME,
            )
            return self._fallback(user_domain)

        logger.debug(
            "Hybrid retriever resolved %d patterns",
            len(resolved),
            extra={"top_pattern": resolved[0] if resolved else None},
        )
        logger.info(
            "Recall set: %d candidate patterns for domain '%s' (selection deferred to analyze)",
            len(resolved),
            user_domain,
            extra={
                "stage": "recall",
                "domain": user_domain,
                "normalized_domain": normalized_domain,
                "fusion_mode": self._mode,
                "patterns": [
                    {"name": p["name"], "score": float(s)}
                    for p, s in resolved[:LOG_SUMMARY_CAP]
                ],
            },
        )
        return resolved

    def _fallback(self, user_domain: str) -> list[tuple[dict[str, Any], float]]:
        """Return the fallback pattern (tagged ``is_fallback=True``) or an empty list.

        The ``is_fallback`` sentinel lets the analyze phase filter fallback
        out of the scored-candidate set when real candidates exist, so the
        fallback never outranks a real match.
        """
        fallback = self._loader.get_by_name(DEFAULT_FALLBACK_PATTERN_NAME)
        if fallback is not None:
            tagged = dict(fallback, is_fallback=True)
            logger.warning(
                "No pattern matched domain '%s'; using default fallback pattern '%s'",
                user_domain,
                DEFAULT_FALLBACK_PATTERN_NAME,
            )
            return [(tagged, 0.0)]
        logger.warning(
            "No pattern matched domain '%s' and fallback '%s' not found in catalogue",
            user_domain,
            DEFAULT_FALLBACK_PATTERN_NAME,
        )
        return []
