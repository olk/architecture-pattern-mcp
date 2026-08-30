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

"""Compare two prompt-benchmark result files and decide the merge gate.

Reads the JSON produced by runner.py for a baseline (v1 prompt) and a candidate
(v2 prompt) arm, aligns cases by id, and reports paired statistics per metric.
Dependency-free: significance uses a seeded paired permutation test (10,000
resamples, two-sided).

Usage:
    uv run python tests/benchmark/compare.py results_baseline.json results_candidate.json

Exit codes: 0 = gate passed, 1 = gate failed, 2 = inputs unusable.
"""

import argparse
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any

# metric -> (direction, description); direction: higher-is-better / lower-is-better
PAIRED_METRICS: dict[str, str] = {
    "overall_quality": "higher",
    "attempts": "lower",
    "dangling_references": "lower",
    "generic_technologies": "lower",
}

COUNT_METRICS: tuple[str, ...] = ("validation_success", "qa_format_valid")

PERMUTATIONS = 10_000
SEED = 0


def load_results(path: str) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        by_id = {r["id"]: r for r in payload.get("results", [])}
    except (json.JSONDecodeError, OSError, AttributeError, KeyError) as exc:
        print(f"cannot read results from {path}: {exc}")
        raise SystemExit(2) from exc
    if not by_id:
        raise SystemExit(2)
    return by_id


def paired_differences(baseline: dict[str, dict[str, Any]], candidate: dict[str, dict[str, Any]], metric: str) -> list[float]:
    diffs = []
    for case_id, base_row in baseline.items():
        cand_row = candidate[case_id]
        b, c = base_row.get(metric), cand_row.get(metric)
        if b is None or c is None:
            continue
        diffs.append(float(c) - float(b))
    return diffs


def permutation_p_value(diffs: list[float]) -> float:
    """Two-sided paired permutation test on the mean difference."""
    if not diffs:
        return 1.0
    observed = abs(statistics.fmean(diffs))
    if observed == 0.0:
        return 1.0
    rng = random.Random(SEED)
    pool = [abs(d) for d in diffs]
    count = 0
    for _ in range(PERMUTATIONS):
        flipped = [d if rng.random() < 0.5 else -d for d in pool]
        if abs(statistics.fmean(flipped)) >= observed:
            count += 1
    return (count + 1) / (PERMUTATIONS + 1)


def rate(values: list[Any]) -> float:
    values = [v for v in values if v is not None]
    if not values:
        return 0.0
    return sum(1 for v in values if v) / len(values)


def evaluate_paired_metric(
    baseline: dict[str, dict[str, Any]],
    candidate: dict[str, dict[str, Any]],
    metric: str,
    direction: str,
    alpha: float,
) -> tuple[str, str, bool, dict[str, float]]:
    diffs = paired_differences(baseline, candidate, metric)
    mean_delta = statistics.fmean(diffs) if diffs else 0.0
    median_delta = statistics.median(diffs) if diffs else 0.0
    p_value = permutation_p_value(diffs)

    improves = (direction == "higher" and mean_delta > 0) or (direction == "lower" and mean_delta < 0)
    significant = p_value < alpha and len(diffs) >= 30
    regressed = mean_delta < 0 if direction == "higher" else mean_delta > 0

    baseline_mean = statistics.fmean(float(baseline[c].get(metric, 0)) for c in baseline)
    candidate_mean = statistics.fmean(float(candidate[c].get(metric, 0)) for c in candidate)
    label = f"{metric} ({direction}-is-better)"
    print(f"{label:<38} baseline_mean={baseline_mean:>8.2f}"
          f"  candidate_mean={candidate_mean:>8.2f}"
          f"  delta_mean={mean_delta:>+8.2f}  delta_median={median_delta:>+8.2f}  p={p_value:.4f}")

    if metric == "overall_quality":
        passed = improves and significant
    else:
        passed = not regressed
    verdict = "IMPROVED" if (improves and significant) else ("REGRESSED" if regressed else "NO CHANGE")
    return label, verdict, passed, {"mean": mean_delta}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare benchmark arms and decide the merge gate.")
    parser.add_argument("baseline", help="results JSON for the baseline (v1 prompt) arm")
    parser.add_argument("candidate", help="results JSON for the candidate (v2 prompt) arm")
    parser.add_argument("--alpha", type=float, default=0.05, help="significance threshold (default 0.05)")
    args = parser.parse_args()

    baseline = load_results(args.baseline)
    candidate = load_results(args.candidate)

    missing_in_candidate = sorted(set(baseline) - set(candidate))
    missing_in_baseline = sorted(set(candidate) - set(baseline))
    if missing_in_candidate or missing_in_baseline:
        print(f"UNALIGNED CASES: in_baseline_only={missing_in_baseline} in_candidate_only={missing_in_candidate}")
        return 2

    n = len(baseline)
    print(f"\nPaired comparison over {n} cases (alpha={args.alpha}, {PERMUTATIONS} permutations, seed={SEED})\n")

    gate_ok = True
    verdicts: list[tuple[str, str, bool]] = []

    for metric, direction in PAIRED_METRICS.items():
        label, verdict, passed, _stats = evaluate_paired_metric(baseline, candidate, metric, direction, args.alpha)
        gate_ok = gate_ok and passed
        verdicts.append((label, verdict, passed))

    for metric in COUNT_METRICS:
        b, c = rate([baseline[k].get(metric) for k in baseline]), rate([candidate[k].get(metric) for k in candidate])
        passed = c >= b
        gate_ok = gate_ok and passed
        verdicts.append((f"{metric} (rate)", f"{b:.0%} -> {c:.0%}", passed))
        print(f"{metric + ' (rate)':<38} baseline={b:>8.0%}  candidate={c:>8.0%}")

    print()
    for label, verdict, passed in verdicts:
        marker = "PASS" if passed else "FAIL"
        print(f"  [{marker}] {label}: {verdict}")

    generic_base = statistics.fmean([float(baseline[k].get("generic_technologies", 0)) for k in baseline])
    generic_cand = statistics.fmean([float(candidate[k].get("generic_technologies", 0)) for k in candidate])
    if generic_base > 0:
        reduction = (generic_base - generic_cand) / generic_base
        print(f"\n  generic_technologies reduction target (-50%): {reduction:+.0%} ({'MET' if reduction >= 0.5 else 'NOT MET'} — reported, not gated)")

    print(f"\nMERGE GATE: {'PASSED' if gate_ok else 'FAILED'}")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    sys.exit(main())
