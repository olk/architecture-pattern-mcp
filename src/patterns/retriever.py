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
  1. Dense + BM25 retrievers are built ONCE at warmup (ArchitecturePipeline)
     over the shared domain-slug node set and injected here.
  2. Both legs are orchestrated by the upstream ``QueryFusionRetriever``.
     Per-leg queries stay split via ``QueryBundle``: the dense leg embeds
     ``custom_embedding_strs`` (= raw user_domain) while the BM25 leg
     tokenizes ``query_str`` (= normalized_domain).
  3. Fusion via upstream ``FUSION_MODES.RELATIVE_SCORE`` (per-leg min-max
     normalization, weighted by ``RETRIEVAL_RETRIEVER_WEIGHTS``) — locked
     as a module constant, deliberately not config-exposable; see
     ``docs/retrieval-fusion-modes.md`` for the full trade-off analysis.
   4. Optionally rerank with TextEmbeddingInference (cross-encoder via TEI sidecar).
The slug-cut strategy is fixed to the Vespa-style reciprocal-rank
         blend: keep top rerank_top_n by
         ``RR(fused_rank) + RR(ce_rank)`` with k=60.  Protective against CE
         outliers on short domain-slug inputs; the reported fusion_score
         is the blend (in [0, 2/60]).
      Scoring itself remains lossless regardless of pool size.
   5. Resolve each NodeWithScore.slug → patterns via PatternLoader.filter_by_domain
   6. Aggregate: pattern_score = max(fusion_score) over slugs surfacing it.
      fusion_score is the blended ``RR(fused) + RR(ce)`` value.
   7. Return resolved patterns with fusion scores. When reranking is enabled,
      the slug pool is bounded by rerank_top_n before pattern resolution.
      Requirements-aware selection of top_k_patterns happens downstream in the
      analyze phase, which scores each candidate against the requirements.
      Fallback to layered-monolith only when retrieval is genuinely empty.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from llama_index.core.llms.mock import MockLLM
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.core.schema import QueryBundle, NodeWithScore

from src.patterns.embedder import TEI_RERANKER_MODEL
from src.patterns.safe_tei_rerank import SafeTEIReranker

if TYPE_CHECKING:
    from llama_index.core.retrievers import BaseRetriever

from src.patterns.loader import PatternLoader

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

RRF_K: float = 60.0

# Lossless default for the fused result cap when the caller supplies no
# explicit ``fusion_top_k``.  The corpus is the domain-slug set (~213), so
# the union of both legs is far below this bound and stage-1 recall stays
# lossless by construction.
FALLBACK_FUSION_TOP_K = 2048

# Stage-1 fusion mode, locked to upstream relative_score: per-leg min-max
# normalization, weighted by RETRIEVAL_RETRIEVER_WEIGHTS, summed across legs.
# Deliberately not config-exposable — the embedder is fixed, the calibrated
# [0, 1] scale makes min_fusion_score meaningful, and score-based modes are
# the only ones honoring retriever_weights under the pinned llama-index-core
# (RRF silently ignores them).  Full analysis: docs/retrieval-fusion-modes.md.
RETRIEVAL_FUSION_MODE: FUSION_MODES = FUSION_MODES.RELATIVE_SCORE

# Stage-1 leg weights (dense, BM25).  Dense is the primary signal — the
# embedder encodes user-domain semantics while BM25 only catches exact slug
# tokens.  Upstream normalizes weights to sum 1, so with num_queries=1 the
# best possible consensus score is 1.0 and a dense-only hit caps at 0.7.
RETRIEVAL_RETRIEVER_WEIGHTS: tuple[float, float] = (0.7, 0.3)


def reciprocal_rank_score(rank: int, k: float = RRF_K) -> float:
    r"""Reciprocal-rank contribution for one ranked list position.

    Implements 1 / (rank + k - 1) — numerically identical to upstream
    QueryFusionRetriever's ``1 / (rank0 + k)`` (rank0 = rank - 1).  Applied
    to BOTH the stage-1 fused-list rank and the cross-encoder rank in the
    locked rank_fusion slug-cut (RR(fused) + RR(ce) with k=60).
    """
    return 1.0 / (rank + k - 1)


class _LoggingFusionRetriever(QueryFusionRetriever):
    """QueryFusionRetriever that emits per-leg candidate summaries.

    Overrides ``_run_sync_queries`` to log each leg's RAW (pre-fusion)
    result set before the upstream fusion runs, preserving the former
    two-leg observability contract (``stage="dense"`` / ``stage="bm25"``
    INFO records with slug/score summaries).  Retriever order maps to
    stages: index 0 → dense leg, index 1 → BM25 leg.
    """

    def _run_sync_queries(self, queries: list[QueryBundle]) -> dict[tuple[str, int], list[NodeWithScore]]:
        results = super()._run_sync_queries(queries)
        for (query_str, leg_idx), nodes in results.items():
            stage = "dense" if leg_idx == 0 else "bm25"
            logger.info(
                "%s leg: %d candidates for domain '%s' (showing top %d)",
                stage.capitalize(),
                len(nodes),
                query_str,
                min(len(nodes), LOG_SUMMARY_CAP),
                extra={
                    "stage": stage,
                    "domain": query_str,
                    "summary": _summarize_nodes(nodes, LOG_SUMMARY_CAP),
                },
            )
        return results


@dataclass(frozen=True)
class DomainMatch:
    """A resolved domain slug with its fusion score, surfaced for agent transparency.

    Attributes:
        fusion_score: relative_score fused value in [0, 1] (``rerank``
            selection mode — query-relative, per-leg min-max weighted sum)
            or the Vespa-style blended score ``RR(fused_rank) + RR(ce_rank)``
            (``rank_fusion`` mode) — reciprocal ranks over the stage-1
            fused-list positions and the CE ranking.  Higher values indicate stronger
            domain-similarity consensus; values are NOT comparable across
            different queries.
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
    Hybrid retriever using two separate retrieval legs (dense + BM25) with
    the locked relative_score fusion strategy and cross-encoder reranking.

    Both legs are orchestrated by the upstream ``QueryFusionRetriever``
    (num_queries=1, sync, lossless ``similarity_top_k``, mode locked to
    ``RETRIEVAL_FUSION_MODE``, leg weights ``RETRIEVAL_RETRIEVER_WEIGHTS``
    — dense 0.7 / BM25 0.3).  The per-leg query split is preserved via
    ``QueryBundle``: the dense leg embeds ``custom_embedding_strs`` (raw
    ``user_domain``, benefiting from embedding semantics) while the BM25
    leg tokenizes ``query_str`` (``normalized_domain``, exact slug token
    matching).
    """

    def __init__(
        self,
        dense_retriever: BaseRetriever,
        bm25_retriever: BaseRetriever,
        pattern_loader: PatternLoader,
        min_fusion_score: float = 0.0,
        rerank_top_n: int = 10,
        reranker_config: Any | None = None,
        fusion_top_k: int | None = None,
        retriever_weights: tuple[float, float] | list[float] | None = None,
    ) -> None:
        """Inject prebuilt per-leg retrievers (constructed once at warmup).

        Args:
            dense_retriever: Dense-leg retriever over domain-slug nodes.
                Receives the raw ``user_domain`` query (via
                ``QueryBundle.custom_embedding_strs``).
            bm25_retriever: BM25-leg retriever over the same nodes.
                Receives the ``normalized_domain`` query (via
                ``QueryBundle.query_str``).
            pattern_loader: Resolves slugs to pattern dicts.
            min_fusion_score: Relevance floor on the blended
                ``RR(fused) + RR(ce)`` value (in [0, 2/60]).  The slug-cut
                strategy is locked to the reciprocal-rank blend (see
                ``docs/retrieval-fusion-modes.md``); this gate fires only
                on degenerate recall or operator-set floor above the
                blend's theoretical maximum.  0.0 disables.
            rerank_top_n: Slug-pool cap after cross-encoder reranking.
            reranker_config: RerankerInnerConfig (base_url, timeout, batch).
            fusion_top_k: Lossless cap for the fused result set. Defaults to
                ``FALLBACK_FUSION_TOP_K`` (2048), which exceeds any possible
                union of the two legs over the domain-slug corpus.
            retriever_weights: (dense, BM25) leg weights for the
                relative_score fusion; defaults to
                ``RETRIEVAL_RETRIEVER_WEIGHTS``.  Both must be positive;
                upstream normalizes them to sum 1.
        """
        weights = (
            tuple(retriever_weights)
            if retriever_weights is not None
            else RETRIEVAL_RETRIEVER_WEIGHTS
        )
        if len(weights) != 2 or any(w <= 0 for w in weights):
            raise ValueError(
                "retriever_weights must be two positive numbers "
                f"(dense, bm25), got {retriever_weights!r}"
            )
        self._dense_retriever = dense_retriever
        self._bm25_retriever = bm25_retriever
        self._loader = pattern_loader
        self._retriever_weights: tuple[float, float] = (
            float(weights[0]),
            float(weights[1]),
        )
        self._fusion_top_k = fusion_top_k if fusion_top_k and fusion_top_k > 0 else FALLBACK_FUSION_TOP_K
        self._min_fusion_score = min_fusion_score
        self._rerank_top_n = rerank_top_n
        self._reranker_config = reranker_config
        self._reranker: SafeTEIReranker | None = None
        self._fusion: _LoggingFusionRetriever | None = None
        self._fusion_legs: tuple[Any, Any] | None = None

    def _ensure_fusion_retriever(self) -> _LoggingFusionRetriever:
        """Lazily build the upstream fusion retriever over the current legs.

        Built per leg identity so callers that swap the injected retrievers
        after construction (as tests do) keep working, while repeated calls
        reuse one instance.
        """
        legs = (self._dense_retriever, self._bm25_retriever)
        if self._fusion is None or self._fusion_legs != legs:
            self._fusion = _LoggingFusionRetriever(
                retrievers=[legs[0], legs[1]],
                llm=MockLLM(),
                mode=RETRIEVAL_FUSION_MODE,
                retriever_weights=list(self._retriever_weights),
                num_queries=1,
                use_async=False,
                similarity_top_k=self._fusion_top_k,
            )
            self._fusion_legs = legs
        return self._fusion

    def _ensure_reranker(self) -> None:
        """Lazily build the TEI-backed cross-encoder once.

        ``keep_retrieval_score=True`` causes TextEmbeddingInference to
        stash the stage-1 fused score in ``node.metadata["retrieval_score"]``
        before overwriting ``node.score`` with the cross-encoder logit. The
        caller restores the fused score after reranking so downstream
        fusion-score gating and observability stay calibrated.
        """
        if self._reranker is not None:
            return
        if self._reranker_config is None:
            raise RuntimeError(
                "Reranking is mandatory but no reranker_config provided"
            )
        self._reranker = SafeTEIReranker(
            base_url=self._reranker_config.base_url,
            model_name=TEI_RERANKER_MODEL,
            timeout=self._reranker_config.timeout,
            top_n=1,
        )
        self._reranker.keep_retrieval_score = True

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
        The slug-cut blend ``RR(fused_rank) + RR(ce_rank)`` (with k=60)
        always runs: it protects consensus-backed slugs from CE outliers on
        short domain-slug inputs. The reported ``fusion_score`` is the blend
        value (in [0, 2/60]).  For pools below ``rerank_top_n`` the blend
        produces the same ordering as CE-only (reciprocals are constant
        across all positions), so the cut is a no-op equivalent.

        The pattern dict carries ``rerank_logit`` (the raw CE logit); the
        tuple score equals the blend.

        Args:
            user_domain:      Raw domain string from user (embedding query)
            normalized_domain: Pre-normalised domain (BM25 lexical query)

        Returns:
            RetrievalOutcome containing:
            - patterns: list of (pattern_dict, fusion_score) tuples sorted by score
              descending. fusion_score is the blend ``RR(fused_rank) +
              RR(ce_rank)``, NOT a requirements-fit score.  When reranking ran
              the pattern dict additionally carries ``rerank_logit`` (the
              cross-encoder logit).
            - matched_domains: top matched ArchitectureDomain slugs (max 5)
              with their fusion scores and cross-encoder rerank logits
              (``fusion_score`` and ``rerank_score`` fields), for agent
              transparency.  ``fusion_score`` follows the same blend semantics.
              Drawn from the post-cap survivor pool.
        """
        assert self._dense_retriever is not None
        assert self._bm25_retriever is not None

        # Single QueryBundle carrying both per-leg query representations:
        # the dense leg embeds custom_embedding_strs (raw user_domain),
        # the BM25 leg tokenizes query_str (normalized_domain).
        query_bundle = QueryBundle(
            query_str=normalized_domain,
            custom_embedding_strs=[user_domain],
        )
        fused = self._ensure_fusion_retriever().retrieve(query_bundle)

        logger.info(
            "Fusion: %d candidates after %s (showing top %d)",
            len(fused),
            RETRIEVAL_FUSION_MODE.value,
            min(len(fused), LOG_SUMMARY_CAP),
            extra={
                "stage": "fusion",
                "mode": RETRIEVAL_FUSION_MODE.value,
                "summary": _summarize_nodes(fused, LOG_SUMMARY_CAP),
            },
        )

        if not fused:
            return self._fallback(user_domain)

        if len(fused) > 1:
            self._ensure_reranker()
            assert self._reranker is not None
            # Node copies: fused nodes may wrap instances shared via the
            # upstream docstore; the reranker (keep_retrieval_score) and the
            # survivor stamping below mutate node metadata, which must never
            # leak into concurrent or later requests.  Copies preserve
            # node.hash (text+metadata content), so rank maps stay valid.
            fused = [
                NodeWithScore(node=n.node.model_copy(deep=True), score=n.score)
                for n in fused
            ]
            # Fused rank: 1-based position in the stage-1 fused list (the
            # ordering relative_score produced — NOT an RRF score despite
            # the reciprocal-rank arithmetic used downstream).
            fused_rank = {n.node.hash: i for i, n in enumerate(fused, start=1)}
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

            # Always apply the Vespa-style blend.  When the pool is below
            # rerank_top_n the reciprocals are constant across all
            # positions, so the ordering matches CE-only — the cut is a
            # no-op equivalent (logged at debug).
            scored_hashes = ce_rank.keys()
            safe_fused_rank = {h: fused_rank[h] for h in scored_hashes if h in fused_rank}
            survivors = sorted(
                scored,
                key=lambda n: (
                    reciprocal_rank_score(safe_fused_rank.get(n.node.hash, len(scored)))
                    + reciprocal_rank_score(ce_rank[n.node.hash])
                ),
                reverse=True,
            )[: self._rerank_top_n]

            logger.info(
                "Rerank selection: RR(fused_rank) + RR(ce_rank), %d kept",
                len(survivors),
            )

            for nws in survivors:
                h = nws.node.hash
                nws.node.metadata["rerank_logit"] = float(nws.score)  # type: ignore[arg-type]
                blend = (
                    reciprocal_rank_score(safe_fused_rank.get(h, len(scored)))
                    + reciprocal_rank_score(ce_rank[h])
                )
                nws.node.metadata["selection_score"] = blend  # type: ignore[assignment]
                nws.score = blend

            logger.debug(
                "Reranking: %d candidates, kept %d after rerank_top_n cap",
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
                "Reranking: %d candidates kept after rerank_top_n cap",
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
                "No slug met the relevance floor (best fusion score %.4f < "
                "threshold %.4f) for domain '%s'; using fallback pattern '%s'",
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
                "fusion_mode": RETRIEVAL_FUSION_MODE.value,
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
