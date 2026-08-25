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
  6. Optionally rerank with TextEmbeddingInference (cross-encoder via TEI sidecar).
     The slug-cut strategy is controlled by :paramref:`rerank_selection`:
       "rerank"       - keep top rerank_top_n by cross-encoder order only
                       (llama-index convention; correct when the CE signal dominates).
                       Reported fusion_score is the original RRF reciprocal-rank score.
       "rank_fusion" - keep top rerank_top_n by RR(rrf_rank) + RR(ce_rank)
                       (Vespa-style blend, k=60).  Protects consensus-backed slugs
                       from CE outliers on short domain-slug inputs.
                       Reported fusion_score is the blended selection score.
     Scoring itself remains lossless regardless of selection mode.
  7. Resolve each NodeWithScore.slug → patterns via PatternLoader.filter_by_domain
  8. Aggregate: pattern_score = max(fusion_score) over slugs surfacing it.
     fusion_score is RRF (``rerank``) or the blended RR(rrf)+RR(ce) (``rank_fusion``).
  9. Return resolved patterns with fusion scores. When reranking is enabled,
     the slug pool is bounded by rerank_top_n before pattern resolution.
     Requirements-aware selection of top_k_patterns happens downstream in the
     analyze phase, which scores each candidate against the requirements.
     Fallback to layered-monolith only when retrieval is genuinely empty.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal

import httpx
from llama_index.core.schema import QueryBundle, NodeWithScore
from llama_index.postprocessor.tei_rerank import TextEmbeddingInference

if TYPE_CHECKING:
    from llama_index.core.retrievers import BaseRetriever

from src.patterns._fusion import FusionMode, RRF_K, apply_fusion, reciprocal_rank_score
from src.patterns.bm25_index import DomainBM25Index
from src.patterns.embedder import TEI_RERANKER_MODEL
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

DOMAIN_MATCH_REPORT_LIMIT = 5


def _safe_tei_rerank_call(
    base_url: str,
    timeout: float,
    auth_token: str | Callable[[str], str] | None,
    query: str,
    texts: list[str],
) -> list[dict[str, Any]]:
    """Call TEI /rerank with HTTP status validation and informative error messages.

    Mirrors llama_index.postprocessor.tei_rerank.TextEmbeddingInference._call_api
    but raises RuntimeError (instead of an AssertionError) when TEI returns an
    error or a non-list response body.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if auth_token is not None:
        if callable(auth_token):
            headers["Authorization"] = auth_token(base_url)
        else:
            headers["Authorization"] = auth_token

    payload = {"query": query, "texts": texts}
    with httpx.Client() as client:
        resp = client.post(
            f"{base_url}/rerank",
            headers=headers,
            json=payload,
            timeout=timeout,
        )

    if resp.status_code >= 400:
        raise RuntimeError(
            f"TEI reranker {base_url}/rerank returned HTTP {resp.status_code}: {resp.text[:500]}"
        )

    body = resp.json()
    if not isinstance(body, list):
        raise RuntimeError(  # noqa: TRY004
            f"TEI reranker {base_url}/rerank returned non-list response "
            f"(HTTP {resp.status_code}): {str(body)[:500]}"
        )

    return body


@dataclass(frozen=True)
class DomainMatch:
    """A resolved domain slug with its fusion score, surfaced for agent transparency.

    Attributes:
        fusion_score: RRF fusion score (``rerank`` mode) or the Vespa-style
            blended score ``RR(rrf_rank) + RR(ce_rank)`` (``rank_fusion`` mode).
            Higher values indicate stronger domain-similarity consensus.
        rerank_score: Cross-encoder rerank logit for this slug, or None when
            reranking did not run (e.g. single-candidate path).
    """

    slug: str
    fusion_score: float
    rerank_score: float | None = None


@dataclass(frozen=True)
class RetrievalOutcome:
    """
    Result of a hybrid retrieval call.

    Attributes:
        patterns: Resolved patterns with fusion scores (same shape as the old list return).
        matched_domains: Top matched ArchitectureDomain slugs for transparency.
    """

    patterns: list[tuple[dict[str, Any], float]]
    matched_domains: list[DomainMatch]


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
    configurable fusion strategy and cross-encoder reranking.

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
        rerank_top_n: int = 10,
        reranker_config: Any | None = None,
        rerank_selection: Literal["rerank", "rank_fusion"] = "rerank",
    ) -> None:
        self._bm25 = bm25_index
        self._vector = vector_index
        self._loader = pattern_loader
        self._bm25_top_k = bm25_top_k
        self._dense_top_k = dense_top_k
        self._mode: FusionMode = mode
        self._min_fusion_score = min_fusion_score
        self._rerank_top_n = rerank_top_n
        self._reranker_config = reranker_config
        self._reranker: TextEmbeddingInference | None = None
        self._dense_retriever: BaseRetriever | None = None
        self._bm25_retriever: BaseRetriever | None = None
        self._rerank_selection: Literal["rerank", "rank_fusion"] = rerank_selection

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
            "Hybrid retriever initialised: mode=%s, "
            "dense_k=%d, bm25_k=%d (corpus=%d)",
            self._mode,
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
                "Reranking is mandatory but no reranker_config provided"
            )
        self._reranker = TextEmbeddingInference(
            base_url=self._reranker_config.base_url,
            model_name=TEI_RERANKER_MODEL,
            timeout=self._reranker_config.timeout,
            top_n=1,
        )
        self._reranker.keep_retrieval_score = True
        max_batch = getattr(self._reranker_config, "max_batch_size", 48)
        self._reranker._call_api = lambda q, t: _safe_tei_rerank_call(
            self._reranker.base_url,
            self._reranker.timeout,
            self._reranker.auth_token,
            q,
            t,
        )

    def _matched_domains_from_nodes(
        self, nodes: list[Any]
    ) -> list[DomainMatch]:
        slug_best: dict[str, tuple[float, float | None]] = {}
        for nws in nodes:
            slug = nws.node.metadata.get("slug", "")
            if not slug:
                continue
            fusion = float(nws.score) if nws.score is not None else 0.0
            rerank = nws.node.metadata.get("rerank_logit")
            rerank = float(rerank) if rerank is not None else None
            if slug not in slug_best or fusion > slug_best[slug][0]:
                slug_best[slug] = (fusion, rerank)
        sorted_slugs = sorted(slug_best.items(), key=lambda x: x[1][0], reverse=True)
        return [
            DomainMatch(slug=s, fusion_score=sc, rerank_score=sr)
            for s, (sc, sr) in sorted_slugs[:DOMAIN_MATCH_REPORT_LIMIT]
        ]

    def retrieve(  # noqa: PLR0912, PLR0915 — rationale in module docstring stage 6b
        self,
        user_domain: str,
        normalized_domain: str,
    ) -> RetrievalOutcome:
        """
        Find candidate patterns for user_domain using two-leg hybrid retrieval.

        Stage-1 (recall): returns resolved patterns with their fusion scores.
        The slug pool is bounded by ``rerank_top_n`` before pattern resolution
        (scoring itself is lossless). Requirements-aware selection of
        ``top_k_patterns`` happens in the analyze phase (ArchitecturePipeline),
        which scores each candidate against the requirements and only then truncates.

        When reranking runs, each survivor's :class:`DomainMatch` entry carries
        both the fusion score and the cross-encoder logit (``rerank_score``).
        The fusion score semantics differ by mode:

        - ``"rerank"`` mode: fusion_score is the original RRF reciprocal-rank
          score.  The CE rank alone decides the survivor cut; RRF score is
          preserved for downstream gating and observability.
        - ``"rank_fusion"`` mode: fusion_score is the Vespa-style blended
          selection score ``RR(rrf_rank) + RR(ce_rank)``.  Both RRF and CE
          ranks contribute to the cut; the reported score reflects that blend.
          The ``min_fusion_score`` gate applies to the blended value in this mode.

        In both modes the pattern dict carries ``rerank_logit`` (the raw CE
        logit) and the tuple score equals the mode's fusion_score.

        Args:
            user_domain:      Raw domain string from user (embedding query)
            normalized_domain: Pre-normalised domain (BM25 lexical query)

        Returns:
            RetrievalOutcome containing:
            - patterns: list of (pattern_dict, fusion_score) tuples sorted by score
              descending. fusion_score is the RRF score (``"rerank"``) or the
              blended score ``RR(rrf_rank) + RR(ce_rank)`` (``"rank_fusion"``),
              NOT a requirements-fit score.  When reranking ran the pattern dict
              additionally carries ``rerank_logit`` (the cross-encoder logit).
            - matched_domains: top matched ArchitectureDomain slugs (max 5)
              with their fusion scores and cross-encoder rerank logits
              (``fusion_score`` and ``rerank_score`` fields), for agent
              transparency.  ``fusion_score`` follows the same semantics as
              above.  Drawn from the post-cap survivor pool.
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

        if len(fused) > 1:
            self._ensure_reranker()
            assert self._reranker is not None
            rrf_rank = {n.node.hash: i for i, n in enumerate(fused, start=1)}
            max_batch = getattr(self._reranker_config, "max_batch_size", 48)
            query_bundle = QueryBundle(query_str=user_domain)
            scored: list[NodeWithScore] = []
            for i in range(0, len(fused), max_batch):
                chunk = fused[i : i + max_batch]
                self._reranker.top_n = len(chunk)
                scored.extend(
                    self._reranker.postprocess_nodes(
                        list(chunk), query_bundle=query_bundle
                    )
                )
            scored.sort(key=lambda n: n.score if n.score is not None else 0.0, reverse=True)
            logger.info(
                "Reranker chunking: %d candidates → %d chunk(s) of ≤ %d",
                len(fused),
                (len(fused) + max_batch - 1) // max_batch,
                max_batch,
            )
            ce_rank = {n.node.hash: i for i, n in enumerate(scored, start=1)}

            if (
                self._rerank_selection == "rank_fusion"
                and len(scored) >= self._rerank_top_n
            ):
                # Only include nodes present in scored (defensive: the reranker
                # must return a permutation of fused, but guard against it adding
                # or dropping nodes by intersecting with ce_rank keys).
                scored_hashes = ce_rank.keys()
                safe_rrf_rank = {h: rrf_rank[h] for h in scored_hashes if h in rrf_rank}
                survivors = sorted(
                    scored,
                    key=lambda n: (
                        reciprocal_rank_score(safe_rrf_rank.get(n.node.hash, len(scored)))
                        + reciprocal_rank_score(ce_rank[n.node.hash])
                    ),
                    reverse=True,
                )[: self._rerank_top_n]
                selection_mode = "rank_fusion"
            else:
                survivors = scored[: self._rerank_top_n]
                selection_mode = "rerank"

            logger.info(
                "Rerank selection mode: %s (%s)",
                selection_mode,
                "RR(rrf_rank) + RR(ce_rank)" if selection_mode == "rank_fusion" else "cross-encoder only",
            )

            for nws in survivors:
                h = nws.node.hash
                nws.node.metadata["rerank_logit"] = float(nws.score)  # type: ignore[arg-type]
                if selection_mode == "rank_fusion":
                    blend = (
                        reciprocal_rank_score(safe_rrf_rank.get(h, len(scored)))
                        + reciprocal_rank_score(ce_rank[h])
                    )
                    nws.node.metadata["selection_score"] = blend  # type: ignore[assignment]
                    nws.score = blend
                else:
                    orig = nws.node.metadata.get("retrieval_score")
                    nws.score = float(orig) if orig is not None else 0.0

            logger.debug(
                "Reranking (%s): %d candidates, kept %d after rerank_top_n cap",
                selection_mode,
                len(survivors),
                self._rerank_top_n,
            )
            rerank_summary = {
                "count": len(survivors),
                "shown": len(survivors),
                "top": [
                    {
                        "slug": n.node.metadata.get("slug", ""),
                        "score": float(n.score or 0.0),
                    }
                    for n in survivors
                ],
            }
            logger.info(
                "Reranking (%s): %d candidates kept after rerank_top_n cap",
                selection_mode,
                len(survivors),
                extra={
                    "stage": "rerank",
                    "summary": rerank_summary,
                },
            )
            fused = survivors

        pattern_best: dict[str, tuple[dict[str, Any], float]] = {}
        for nws in fused:
            slug = nws.node.metadata.get("slug", "")
            if not slug:
                continue
            score = nws.score if nws.score is not None else 0.0
            rerank_logit = nws.node.metadata.get("rerank_logit")
            patterns = self._loader.filter_by_domain(slug)
            if not patterns:
                continue
            for p in patterns:
                pid = p.get("name", "")
                if pid not in pattern_best or score > pattern_best[pid][1]:
                    p_with_rerank = dict(p) if rerank_logit is None else {**p, "rerank_logit": rerank_logit}
                    pattern_best[pid] = (p_with_rerank, float(score))

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

        matched_domain_list = self._matched_domains_from_nodes(fused)

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
        return RetrievalOutcome(patterns=resolved, matched_domains=matched_domain_list)

    def _fallback(self, user_domain: str) -> RetrievalOutcome:
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
            return RetrievalOutcome(patterns=[(tagged, 0.0)], matched_domains=[])
        logger.warning(
            "No pattern matched domain '%s' and fallback '%s' not found in catalogue",
            user_domain,
            DEFAULT_FALLBACK_PATTERN_NAME,
        )
        return RetrievalOutcome(patterns=[], matched_domains=[])
