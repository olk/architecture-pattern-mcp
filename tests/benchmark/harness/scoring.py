"""Pure quality metrics over :class:`AnalysisResult`/:class:`PipelineResult` + one scenario label.

Port of design-pattern-mcp-local ``tests/benchmark/harness/scoring.py`` (commit 25cbfba),
adapted to what this repository's pipeline observes:

- **hit** — ``final_style`` (or, for analyze-only runs, ``recommended_style``) is in
  ``acceptable_primary`` and the run is not a fallback; a fallback is an automatic miss.
- **recall@K** — the ordered selection set (analyze ``selected_patterns`` names) capped at K,
  scored against ``acceptable_primary``.
- **supporting F1 / veto-conflicts are dropped**: B exposes no supporting-set or veto-ledger
  observables.
- **calibration score** — ``final_quality_score / 100`` clipped to [0, 1].

Everything here is a pure function of its arguments, so :mod:`selfcheck` can pin every formula
against hand-computed values. Definitions (documented in ``tests/benchmark/README.md``):

- **acceptable-primary hit** — the pipeline's final pattern is in ``acceptable_primary`` and the
  run is not a fallback; a fallback is an automatic miss (never dropped).
- **recall@K** — the ordered selected set capped at K entries, scored against
  ``acceptable_primary``.
- **acceptable-primary F1** — a hit scores P = 1.0, R = 1/|A|; a miss scores 0/0.
- **Brier / ECE (10 equal-width bins)** — monitoring-only per-arm diagnostics (never cross-arm
  verdicts); the score source is ``final_quality_score / 100`` clipped to [0, 1].
- **risk-coverage** — within-arm ordering by score desc; risk (miss rate) at 80/90/100% coverage
  plus the trapezoidal AUC of the risk-coverage curve (anchored at (0, 0)).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from src.pipeline import AnalysisResult as PipelineAnalysisResult
from src.schemas.analysis import AnalysisResult
from src.schemas.evaluation import PipelineResult
from src.schemas.patterns import ScoredPattern

#: Structural analysis view: the schema model or the pipeline's dict-based variant.
# (The pipeline defines a second, dict-shaped ``AnalysisResult`` in ``src/pipeline.py``;
# both expose ``selected_patterns``, ``recommended_style`` and ``is_fallback``.)
_AnalysisLike = AnalysisResult | PipelineAnalysisResult

#: One selected-pattern entry: a ``ScoredPattern`` or a catalog/LLM-JSON dict.
_PatternEntry = ScoredPattern | dict[str, Any]

#: Recall cut-offs reported per scenario.
RECALL_KS: tuple[int, ...] = (3, 5)

#: Equal-width calibration bins over the clipped [0, 1] score.
ECE_BINS = 10

#: Two-sided 95% normal quantile (used by Wilson intervals and the Newcombe difference).
Z_95 = 1.959963984540054


def clip01(value: float) -> float:
    """Clip to [0, 1] for calibration (10-bin equal-width ECE, Brier)."""
    return max(0.0, min(1.0, value))


# --------------------------------------------------------------------------------------
# Selection observables
# --------------------------------------------------------------------------------------


def is_fallback(analysis: _AnalysisLike | None, result: PipelineResult | None) -> bool:
    """Run-level fallback: the loop's flag when a result exists, else the analysis flag."""
    if result is not None:
        return bool(result.is_fallback)
    if analysis is not None:
        return bool(analysis.is_fallback)
    return False


def final_pattern_of(analysis: _AnalysisLike | None, result: PipelineResult | None) -> str | None:
    """The pipeline's final style; analyze-only runs fall back to ``recommended_style``."""
    if result is not None:
        return result.final_style
    if analysis is not None:
        return analysis.recommended_style
    return None


def calibration_score(result: PipelineResult | None) -> float:
    """Calibration score: ``final_quality_score / 100`` clipped to [0, 1]; 0.0 without a result."""
    if result is None:
        return 0.0
    return clip01(result.final_quality_score / 100.0)


def selected_ordered(analysis: _AnalysisLike | None) -> list[str]:
    """Deduplicated selected pattern names in analyze-rank order."""
    if analysis is None:
        return []
    seen: list[str] = []
    for pattern in analysis.selected_patterns:
        name = selected_name(pattern)
        if name is not None and name not in seen:
            seen.append(name)
    return seen


def selected_name(pattern: _PatternEntry) -> str | None:
    """The catalogue name of one scored candidate (None when unset)."""
    if isinstance(pattern, dict):
        name = pattern.get("name")
        return name if isinstance(name, str) and name else None
    name = pattern.name
    return name or None


def recall_at_k(selected: Sequence[str], acceptable: Sequence[str], k: int) -> float:
    """|selected[:k] ∩ acceptable| / |acceptable| (0.0 for an empty acceptable set)."""
    if not acceptable:
        return 0.0
    capped = set(selected[:k])
    return len(capped & set(acceptable)) / len(set(acceptable))


def acceptable_primary_f1(hit: bool, acceptable: Sequence[str]) -> dict[str, float]:
    """P = 1.0 / R = 1/|A| on a hit, 0/0 on a miss, F1 = their harmonic mean."""
    if not hit or not acceptable:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    precision = 1.0
    recall = 1.0 / len(set(acceptable))
    return {
        "precision": precision,
        "recall": round(recall, 6),
        "f1": round(2 * precision * recall / (precision + recall), 6),
    }


# --------------------------------------------------------------------------------------
# Calibration (monitoring only)
# --------------------------------------------------------------------------------------


def reliability_bin(score: float, bins: int = ECE_BINS) -> int:
    """Index of the equal-width bin ``score`` falls into (0-based, last bin closed at 1.0)."""
    return min(int(clip01(score) * bins), bins - 1)


def brier(entries: Sequence[tuple[float, bool]]) -> float | None:
    """Mean squared error of the clipped score against the hit indicator; ``None`` when empty."""
    if not entries:
        return None
    return round(sum((clip01(score) - (1.0 if hit else 0.0)) ** 2 for score, hit in entries) / len(entries), 6)


def calibration(entries: Sequence[tuple[float, bool]], bins: int = ECE_BINS) -> dict[str, Any]:
    """Brier + 10-bin equal-width ECE with the full reliability table (per arm, train split only)."""
    table: list[dict[str, Any]] = [
        {"bin": index, "low": round(index / bins, 3), "high": round((index + 1) / bins, 3), "count": 0,
         "avg_score": None, "accuracy": None, "gap": None}
        for index in range(bins)
    ]
    # One pass: per bin, accumulate clipped scores and hit bits (n = score count = hit count).
    score_sums = [0.0] * bins
    hit_sums = [0.0] * bins
    counts = [0] * bins
    for score, hit in entries:
        index = reliability_bin(score, bins)
        clipped = clip01(score)
        score_sums[index] += clipped
        hit_sums[index] += float(hit)
        counts[index] += 1
    ece = 0.0
    for index in range(bins):
        if not counts[index]:
            continue
        avg_score = score_sums[index] / counts[index]
        accuracy = hit_sums[index] / counts[index]
        table[index].update(
            {"count": counts[index], "avg_score": round(avg_score, 6), "accuracy": round(accuracy, 6),
             "gap": round(abs(accuracy - avg_score), 6)}
        )
        ece += (counts[index] / len(entries)) * abs(accuracy - avg_score)
    return {"brier": brier(entries), "ece": round(ece, 6) if entries else None, "bins": table}


def risk_coverage(entries: Sequence[tuple[float, bool]]) -> dict[str, Any]:
    """Risk at 80/90/100% coverage and the trapezoidal AUC of the risk-coverage curve.

    ``entries`` are ``(score, hit)`` pairs; they are sorted by score descending (stable, so the
    caller's order breaks ties) and the curve is anchored at coverage 0 with risk 0.
    """
    if not entries:
        return {"samples": 0, "risk_at_80": None, "risk_at_90": None, "risk_at_100": None, "aurc": None}
    ordered = sorted(entries, key=lambda entry: -entry[0])
    total = len(ordered)
    misses = 0
    points: list[tuple[float, float]] = [(0.0, 0.0)]
    risks: list[float] = []
    for index, (_score, hit) in enumerate(ordered, start=1):
        if not hit:
            misses += 1
        risk = misses / index
        risks.append(risk)
        points.append((index / total, risk))
    auc = sum(
        (points[i + 1][0] - points[i][0]) * (points[i][1] + points[i + 1][1]) / 2
        for i in range(len(points) - 1)
    )
    return {
        "samples": total,
        "risk_at_80": round(risks[max(1, math.ceil(0.8 * total)) - 1], 6),
        "risk_at_90": round(risks[max(1, math.ceil(0.9 * total)) - 1], 6),
        "risk_at_100": round(risks[-1], 6),
        "aurc": round(auc, 6),
    }


# --------------------------------------------------------------------------------------
# Statistics (hand-rolled: no new dependencies)
# --------------------------------------------------------------------------------------


def _wilson_bounds(successes: int, total: int, z: float) -> tuple[float, float] | None:
    """Unrounded Wilson score bounds; ``None`` when there is nothing to estimate."""
    if total <= 0:
        return None
    p_hat = successes / total
    denominator = 1.0 + z * z / total
    center = (p_hat + z * z / (2 * total)) / denominator
    half = (z * math.sqrt(p_hat * (1 - p_hat) / total + z * z / (4 * total * total))) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def wilson_interval(successes: int, total: int, z: float = Z_95) -> dict[str, Any]:
    """Wilson score interval for a binomial proportion; ``null`` bounds when ``total == 0``."""
    bounds = _wilson_bounds(successes, total, z)
    if bounds is None:
        return {"successes": successes, "total": total, "p_hat": None, "low": None, "high": None,
                "note": "no samples"}
    low, high = bounds
    return {
        "successes": successes,
        "total": total,
        "p_hat": round(successes / total, 6),
        "low": round(low, 6),
        "high": round(high, 6),
        "note": None,
    }


def sign_test(deltas: Sequence[float]) -> dict[str, Any]:
    """Exact two-sided binomial sign test over paired deltas (zeros dropped).

    The sample space is the signs of the non-zero paired differences, so ``n`` counts
    non-zero deltas only and ``n_dropped`` reports how many tied pairs were excluded.
    """
    nonzero = [delta for delta in deltas if delta != 0]
    n = len(nonzero)
    if n == 0:
        return {
            "n": 0,
            "positive": 0,
            "p_two_sided": 1.0,
            "n_dropped": len(deltas),
            "note": "all paired deltas are zero",
        }
    positive = sum(1 for delta in nonzero if delta > 0)
    tail = sum(math.comb(n, i) for i in range(max(positive, n - positive), n + 1))
    p = min(1.0, 2.0 * tail / (2**n))
    return {
        "n": n,
        "positive": positive,
        "p_two_sided": round(p, 6),
        "n_dropped": len(deltas) - n,
        "note": None,
    }


def newcombe_difference_ci(k1: int, n1: int, k2: int, n2: int, z: float = Z_95) -> dict[str, Any]:
    """Newcombe's Wilson-based 95% CI for the difference of two independent proportions."""
    first, second = _wilson_bounds(k1, n1, z), _wilson_bounds(k2, n2, z)
    if first is None or second is None:
        return {"difference": None, "low": None, "high": None, "note": "no samples"}
    l1, u1 = first
    l2, u2 = second
    p1, p2 = k1 / n1, k2 / n2
    low = (p1 - p2) - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    high = (p1 - p2) + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return {
        "difference": round(p1 - p2, 6),
        "low": round(low, 6),
        "high": round(high, 6),
        "note": None,
    }


def mean_or_none(values: Sequence[float]) -> float | None:
    """Arithmetic mean rounded to 6 decimals, or ``None`` for an empty sequence."""
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def median_or_none(values: Sequence[float]) -> float | None:
    """Median rounded to 6 decimals, or ``None`` for an empty sequence."""
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 6)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 6)


def _metric_values(records: Sequence[dict[str, Any]], path: tuple[str, ...]) -> list[float]:
    """Numeric values at ``path`` inside each record's ``quality`` block, skipping ``None``."""
    values: list[float] = []
    for record in records:
        target: Any = record.get("quality")
        for key in path:
            if not isinstance(target, dict):
                target = None
                break
            target = target.get(key)
        if isinstance(target, (int, float)) and not isinstance(target, bool):
            values.append(float(target))
    return values


def aggregate_quality(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Hit rate (+ Wilson CI), fallbacks and mean/median metrics over a record list.

    Metrics a mode cannot observe (e2e cannot measure calibration scores or recall) are
    reported as ``null`` rather than dropped, so a cross-mode comparison can never mistake
    "not measured" for "zero".
    """
    hits = [bool(record["quality"]["hit"]) for record in records]
    fallbacks = [record["quality"]["fallback"] for record in records]
    known_fallbacks = [value for value in fallbacks if value is not None]
    recalls_3 = _metric_values(records, ("recall_at_3",))
    recalls_5 = _metric_values(records, ("recall_at_5",))
    primary_f1 = _metric_values(records, ("acceptable_primary_f1", "f1"))
    hit_count = sum(1 for hit in hits if hit)
    return {
        "scenarios": len(records),
        "hits": hit_count,
        "hit_rate": round(hit_count / len(records), 6) if records else None,
        "hit_rate_wilson": wilson_interval(hit_count, len(records)),
        "fallbacks": sum(1 for value in known_fallbacks if value) if known_fallbacks else None,
        "recall_at_3": {"mean": mean_or_none(recalls_3), "median": median_or_none(recalls_3)},
        "recall_at_5": {"mean": mean_or_none(recalls_5), "median": median_or_none(recalls_5)},
        "acceptable_primary_f1": {
            "mean": mean_or_none(primary_f1),
            "median": median_or_none(primary_f1),
        },
    }
