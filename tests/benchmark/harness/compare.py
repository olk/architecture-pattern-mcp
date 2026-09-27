"""Two-arm comparison with the pre-registered decision rule.

Compares two complete run directories (baseline A, candidate B — e.g. shipped pipeline vs a
reasoning-off arm) and refuses to compare corpora that are not the same file (the
scenario-file sha256 is part of every manifest). Everything is *paired by scenario*:
per-scenario e2e deltas, a sign test over those deltas, hit-flip detection, Wilson/Newcombe
intervals on hit-rate differences and per-stage deltas that separate "fewer calls" from
"faster calls".

Pre-registered rule:

    the candidate wins iff p95 e2e improves ≥ 15% on the holdout split
    AND the holdout acceptable-primary hit rate stays ≥ the baseline's Wilson lower bound.

With the Stage-0 corpus (16 scenarios) the Wilson floor is wide; at this corpus size the
rule usually resolves to ``inconclusive`` — that is reported, never hidden.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config as cfg
from . import scoring
from .probes import percentile_fields

#: Pre-registered minimum p95 e2e improvement for a candidate win.
P95_IMPROVEMENT_THRESHOLD = 0.15

#: Percentile helper needs this many samples before p95 is defined (see probes).
MIN_P95_SAMPLES = 4

#: Metrics compared per scenario (name → (path, higher_is_better)).
# B drops the supporting-set and veto observables (no wire equivalents).
_METRICS: dict[str, tuple[tuple[str, ...], bool]] = {
    "recall_at_3": (("recall_at_3",), True),
    "recall_at_5": (("recall_at_5",), True),
    "acceptable_primary_f1": (("acceptable_primary_f1", "f1"), True),
    "score": (("score",), True),
}


@dataclass
class Arm:
    """One loaded run directory."""

    name: str
    root: Path
    manifest: dict[str, Any]
    summary: dict[str, Any]
    records: list[dict[str, Any]]

    @classmethod
    def load(cls, root: Path, name: str) -> Arm:
        """Load a run directory written by :mod:`runner` or :mod:`e2e`."""
        if not (root / "manifest.json").is_file() or not (root / "summary.json").is_file():
            hint = " (aborted run: see aborted.json)" if (root / "aborted.json").is_file() else ""
            raise ValueError(f"{root}: not a benchmark run directory (manifest.json/summary.json missing){hint}")
        records = [cfg.read_json(path) for path in sorted((root / "scenarios").glob("*.json"))]
        return cls(
            name=name,
            root=root,
            manifest=cfg.read_json(root / "manifest.json"),
            summary=cfg.read_json(root / "summary.json"),
            records=records,
        )

    def keyed(self) -> dict[str, dict[str, Any]]:
        """Records keyed by ``<scenario_id>#<repeat>``."""
        return {
            f"{record['scenario']['scenario_id']}#{record['repeat']}": record for record in self.records
        }

    def holdout(self) -> list[dict[str, Any]]:
        """Records of the holdout split only."""
        return [record for record in self.records if record["scenario"]["split"] == "holdout"]

    def describe(self) -> dict[str, Any]:
        """Compact arm identity for the comparison payload."""
        return {
            "name": self.name,
            "run_id": self.manifest.get("run_id"),
            "mode": self.manifest.get("mode"),
            "run_dir": str(self.root),
            "scenario_file": self.manifest.get("scenario_file"),
            "records": len(self.records),
            "git": self.manifest.get("git"),
        }


def _dig(record: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Value at ``path`` inside a record's ``quality`` block, or ``None``."""
    target: Any = record.get("quality")
    for key in path:
        if not isinstance(target, dict):
            return None
        target = target.get(key)
    return target


def _metric_delta(a: dict[str, Any], b: dict[str, Any], path: tuple[str, ...]) -> float | None:
    """Signed per-scenario metric delta (candidate − baseline), ``None`` when unobservable."""
    first = _dig(a, path)
    second = _dig(b, path)
    if not isinstance(first, (int, float)) or not isinstance(second, (int, float)):
        return None
    if isinstance(first, bool) or isinstance(second, bool):
        return None
    return float(second) - float(first)


def _config_diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Keys of the two effective server configs whose values differ."""
    differing: dict[str, Any] = {}
    for key in sorted(set(a) | set(b)):
        first, second = a.get(key), b.get(key)
        if json.dumps(first, sort_keys=True, default=str) != json.dumps(second, sort_keys=True, default=str):
            differing[key] = {"baseline": first, "candidate": second}
    return differing


def _env_diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Environment keys the two runs disagree on (drift attribution)."""
    return {
        key: {"baseline": a.get(key), "candidate": b.get(key)}
        for key in sorted(set(a) | set(b))
        if a.get(key) != b.get(key)
    }


def _paired(a: Arm, b: Arm) -> dict[str, Any]:
    """Pair the two arms by ``<scenario_id>#<repeat>``; refuse mismatched key sets."""
    first, second = a.keyed(), b.keyed()
    if set(first) != set(second):
        only_a = sorted(set(first) - set(second))
        only_b = sorted(set(second) - set(first))
        raise ValueError(
            "the two arms did not run the same scenario/repeat keys "
            f"(baseline-only: {only_a[:5]}, candidate-only: {only_b[:5]}); "
            "re-run both arms from the same corpus, split and limit"
        )
    keys = sorted(first)
    e2e_deltas = [float(second[key]["e2e_ms"]) - float(first[key]["e2e_ms"]) for key in keys]
    metric_deltas: dict[str, dict[str, Any]] = {}
    for name, (path, higher_is_better) in _METRICS.items():
        deltas = [
            delta for key in keys if (delta := _metric_delta(first[key], second[key], path)) is not None
        ]
        metric_deltas[name] = {
            "compared": len(deltas),
            "mean_delta": scoring.mean_or_none(deltas),
            "median_delta": scoring.median_or_none(deltas),
            "improved": sum(1 for delta in deltas if delta != 0 and (delta > 0) == higher_is_better),
            "worsened": sum(1 for delta in deltas if delta != 0 and (delta > 0) != higher_is_better),
            "unchanged": sum(1 for delta in deltas if delta == 0),
            "higher_is_better": higher_is_better,
        }
    flips = [
        {
            "key": key,
            "baseline_hit": bool(first[key]["quality"]["hit"]),
            "candidate_hit": bool(second[key]["quality"]["hit"]),
            "baseline_pattern": first[key]["quality"]["final_pattern"],
            "candidate_pattern": second[key]["quality"]["final_pattern"],
        }
        for key in keys
        if bool(first[key]["quality"]["hit"]) != bool(second[key]["quality"]["hit"])
    ]
    return {
        "scenarios": len(keys),
        "e2e_ms": {
            "mean_delta": scoring.mean_or_none(e2e_deltas),
            "median_delta": scoring.median_or_none(e2e_deltas),
            "faster": sum(1 for delta in e2e_deltas if delta < 0),
            "slower": sum(1 for delta in e2e_deltas if delta > 0),
            "sign_test": scoring.sign_test(e2e_deltas),
            "note": "deltas are candidate minus baseline (negative = candidate faster)",
        },
        "hit_flips": flips,
        "metric_deltas": metric_deltas,
        "errors": {
            "baseline": sum(1 for key in keys if first[key].get("provenance", {}).get("error")),
            "candidate": sum(1 for key in keys if second[key].get("provenance", {}).get("error")),
        },
    }


def _stage_deltas(a: Arm, b: Arm) -> dict[str, Any]:
    """Per-stage total-ms and call-count deltas between the arms (in-process modes only)."""
    first: dict[str, Any] = a.summary.get("latency", {}).get("stages", {}) or {}
    second: dict[str, Any] = b.summary.get("latency", {}).get("stages", {}) or {}
    if not first and not second:
        return {"available": False, "note": "neither arm recorded stage attribution (e2e mode)"}
    deltas: dict[str, Any] = {}
    for stage in sorted(set(first) | set(second)):
        entry_a: dict[str, Any] = first.get(stage) or {}
        entry_b: dict[str, Any] = second.get(stage) or {}
        calls_a, calls_b = int(entry_a.get("count", 0)), int(entry_b.get("count", 0))
        total_a, total_b = float(entry_a.get("total_ms", 0.0)), float(entry_b.get("total_ms", 0.0))
        deltas[stage] = {
            "calls_baseline": calls_a,
            "calls_candidate": calls_b,
            "calls_delta": calls_b - calls_a,
            "total_ms_baseline": round(total_a, 3),
            "total_ms_candidate": round(total_b, 3),
            "total_ms_delta": round(total_b - total_a, 3),
        }
    return {"available": True, "stages": deltas}


def _hit_rate_difference(a: Arm, b: Arm) -> dict[str, Any]:
    """Newcombe 95% CI on the candidate−baseline hit-rate difference (per split + overall)."""
    result: dict[str, Any] = {}
    for split in ("overall", "train", "holdout"):
        first = a.summary["quality"][split]
        second = b.summary["quality"][split]
        result[split] = {
            "baseline": {"rate": first["hit_rate"], "wilson": first["hit_rate_wilson"]},
            "candidate": {"rate": second["hit_rate"], "wilson": second["hit_rate_wilson"]},
            "difference": scoring.newcombe_difference_ci(
                int(second["hits"]), int(second["scenarios"]), int(first["hits"]), int(first["scenarios"])
            ),
        }
    return result


def _verdict(a: Arm, b: Arm, holdout_p95_a: dict[str, Any], holdout_p95_b: dict[str, Any]) -> dict[str, Any]:
    """Apply the pre-registered rule to the holdout split."""
    conditions: dict[str, Any] = {}
    reasons: list[str] = []
    samples_a = int(holdout_p95_a["samples"])
    samples_b = int(holdout_p95_b["samples"])
    conditions["holdout_samples"] = {"baseline": samples_a, "candidate": samples_b}
    if samples_a < MIN_P95_SAMPLES or samples_b < MIN_P95_SAMPLES:
        reasons.append(
            f"fewer than {MIN_P95_SAMPLES} holdout e2e samples per arm "
            f"(baseline {samples_a}, candidate {samples_b}): p95 is undefined"
        )
        return _verdict_block("inconclusive", conditions, reasons)
    p95_a, p95_b = float(holdout_p95_a["p95_ms"]), float(holdout_p95_b["p95_ms"])
    improvement = (p95_a - p95_b) / p95_a if p95_a > 0 else None
    conditions["holdout_p95_ms"] = {"baseline": p95_a, "candidate": p95_b}
    conditions["holdout_p95_improvement"] = None if improvement is None else round(improvement, 6)
    conditions["p95_improvement_threshold"] = P95_IMPROVEMENT_THRESHOLD
    if improvement is None:
        reasons.append("baseline holdout p95 is zero: improvement ratio undefined")
        return _verdict_block("inconclusive", conditions, reasons)
    candidate_wilson = b.summary["quality"]["holdout"]["hit_rate_wilson"]
    baseline_floor = a.summary["quality"]["holdout"]["hit_rate_wilson"]["low"]
    candidate_rate = b.summary["quality"]["holdout"]["hit_rate"]
    conditions["holdout_hit_rate"] = {"baseline": a.summary["quality"]["holdout"]["hit_rate"], "candidate": candidate_rate}
    conditions["baseline_wilson_lower_bound"] = baseline_floor
    conditions["candidate_wilson"] = candidate_wilson
    if improvement < P95_IMPROVEMENT_THRESHOLD:
        reasons.append(
            f"p95 e2e improved {100.0 * improvement:.1f}% (< {100.0 * P95_IMPROVEMENT_THRESHOLD:.0f}%)"
        )
    if baseline_floor is None or candidate_rate is None:
        reasons.append("holdout hit-rate floor undefined (no holdout records)")
    elif candidate_rate < baseline_floor:
        reasons.append(
            f"candidate holdout hit rate {candidate_rate:.3f} is below the baseline Wilson lower bound {baseline_floor:.3f}"
        )
    outcome = "candidate-win" if not reasons else "candidate-loss"
    return _verdict_block(outcome, conditions, reasons)


def _verdict_block(outcome: str, conditions: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    """Assemble the verdict block with the rule text."""
    return {
        "outcome": outcome,
        "rule": (
            "candidate wins iff holdout p95 e2e improves >= 15% AND candidate holdout "
            "acceptable-primary hit rate >= baseline holdout Wilson lower bound"
        ),
        "conditions": conditions,
        "reasons": reasons or ["every pre-registered condition held"],
    }


def compare_arms(
    a: Arm, b: Arm, *, allow_mismatch: bool = False, out_dir: Path | None = None
) -> dict[str, Any]:
    """Compare two arms and write ``comparison.json`` + ``comparison.md``."""
    warnings: list[str] = []
    first_hash = (a.manifest.get("scenario_file") or {}).get("sha256")
    second_hash = (b.manifest.get("scenario_file") or {}).get("sha256")
    if first_hash != second_hash and not allow_mismatch:
        raise ValueError(
            "the two arms ran different scenario files "
            f"({(a.manifest.get('scenario_file') or {}).get('path')} != "
            f"{(b.manifest.get('scenario_file') or {}).get('path')}); "
            "compare is only meaningful for the identical corpus (--allow-mismatch to override)"
        )
    if first_hash != second_hash:
        warnings.append("scenario-file hashes differ (--allow-mismatch override)")
    if a.manifest.get("mode") != b.manifest.get("mode"):
        detail = (
            f"the two arms ran different modes ({a.manifest.get('mode')} vs {b.manifest.get('mode')}): "
            "stage attribution and quality observables are not equivalent"
        )
        if not allow_mismatch:
            raise ValueError(f"{detail} (--allow-mismatch to override)")
        warnings.append(detail)
    error_keys_a = sorted(key for key, record in a.keyed().items() if record.get("provenance", {}).get("error"))
    error_keys_b = sorted(key for key, record in b.keyed().items() if record.get("provenance", {}).get("error"))
    if error_keys_a or error_keys_b:
        detail = (
            "an arm contains failed scenario runs "
            f"(baseline: {error_keys_a[:3] or 'none'}, candidate: {error_keys_b[:3] or 'none'}); "
            "a latency/quality verdict over failed runs is not interpretable — re-run the arm(s) "
            "with a higher VALIDATION_MAX_RETRIES or a more stable provider"
        )
        if not allow_mismatch:
            raise ValueError(detail)
        warnings.append(detail + " (--allow-mismatch override)")
    config_diff = _config_diff(a.manifest.get("server_config") or {}, b.manifest.get("server_config") or {})
    env_diff = _env_diff(a.manifest.get("env") or {}, b.manifest.get("env") or {})
    if config_diff:
        warnings.append(f"effective config differs in {sorted(config_diff)}")
    if env_diff:
        warnings.append(f"environment differs in {sorted(env_diff)}")

    paired = _paired(a, b)
    holdout_a = [float(record["e2e_ms"]) for record in a.holdout()]
    holdout_b = [float(record["e2e_ms"]) for record in b.holdout()]
    holdout_p95_a = percentile_fields(holdout_a)
    holdout_p95_b = percentile_fields(holdout_b)
    payload: dict[str, Any] = {
        "harness_version": cfg.HARNESS_VERSION,
        "generated_at": cfg.utc_now_iso(),
        "arms": {"baseline": a.describe(), "candidate": b.describe()},
        "integrity": {
            "scenario_file_match": first_hash == second_hash,
            "same_mode": a.manifest.get("mode") == b.manifest.get("mode"),
            "config_diff": config_diff,
            "env_diff": env_diff,
            "warnings": warnings,
        },
        "paired": paired,
        "quality": _hit_rate_difference(a, b),
        "latency": {
            "e2e_ms": {
                "baseline": a.summary["latency"]["e2e_ms"],
                "candidate": b.summary["latency"]["e2e_ms"],
            },
            "holdout_e2e_ms": {"baseline": holdout_p95_a, "candidate": holdout_p95_b},
            "stage_deltas": _stage_deltas(a, b),
        },
        "verdict": _verdict(a, b, holdout_p95_a, holdout_p95_b),
    }
    target_dir = out_dir or (b.root / "comparison")
    target_dir.mkdir(parents=True, exist_ok=True)
    payload["outputs"] = {
        "dir": str(target_dir),
        "json": str(target_dir / "comparison.json"),
        "markdown": str(target_dir / "comparison.md"),
    }
    (target_dir / "comparison.md").write_text(render_comparison(payload), encoding="utf-8")
    cfg.write_json(target_dir / "comparison.json", payload)
    return payload


def render_comparison(payload: dict[str, Any]) -> str:
    """Markdown rendering of a comparison payload."""
    baseline = payload["arms"]["baseline"]
    candidate = payload["arms"]["candidate"]
    verdict = payload["verdict"]
    paired = payload["paired"]
    lines: list[str] = [
        "# Benchmark comparison",
        "",
        (
            f"- baseline ({baseline['name']}): `{baseline['run_id']}` mode `{baseline['mode']}` "
            f"({baseline['records']} records) in `{baseline['run_dir']}`"
        ),
        (
            f"- candidate ({candidate['name']}): `{candidate['run_id']}` mode `{candidate['mode']}` "
            f"({candidate['records']} records) in `{candidate['run_dir']}`"
        ),
        f"- scenario file match: {payload['integrity']['scenario_file_match']} · paired scenarios: {paired['scenarios']}",
        "",
        f"## Verdict: `{verdict['outcome']}`",
        "",
        f"_{verdict['rule']}_",
        "",
    ]
    lines += [f"- {reason}" for reason in verdict["reasons"]]
    conditions = verdict["conditions"]
    if "holdout_p95_improvement" in conditions:
        improvement = conditions["holdout_p95_improvement"]
        lines.append(
            f"- holdout p95 e2e: baseline {conditions['holdout_p95_ms']['baseline']:.1f} ms → "
            f"candidate {conditions['holdout_p95_ms']['candidate']:.1f} ms "
            f"({'null' if improvement is None else f'{100.0 * improvement:.1f}%'})"
        )
    lines += ["", "## Hit rate (Wilson / Newcombe)", "", "| split | baseline | candidate | difference [95% CI] |", "|---|---|---|---|"]
    for split, block in payload["quality"].items():
        difference = block["difference"]
        ci = (
            f"{difference['difference']:+.3f} [{difference['low']:+.3f}, {difference['high']:+.3f}]"
            if difference["difference"] is not None
            else "null"
        )
        lines.append(
            f"| {split} | {_rate(block['baseline']['rate'])} | {_rate(block['candidate']['rate'])} | {ci} |"
        )
    lines += ["", "## Paired deltas (candidate minus baseline)", ""]
    e2e = paired["e2e_ms"]
    lines.append(
        f"- e2e: mean {_signed(e2e['mean_delta'])} ms · median {_signed(e2e['median_delta'])} ms · "
        f"faster {e2e['faster']} / slower {e2e['slower']} · sign test p={e2e['sign_test']['p_two_sided']} "
        f"(n={e2e['sign_test']['n']})"
    )
    lines += ["", "| metric | compared | mean Δ | median Δ | improved | worsened | unchanged |", "|---|---|---|---|---|---|---|"]
    for name, block in paired["metric_deltas"].items():
        lines.append(
            f"| {name} | {block['compared']} | {_signed(block['mean_delta'])} | {_signed(block['median_delta'])} | "
            f"{block['improved']} | {block['worsened']} | {block['unchanged']} |"
        )
    lines += ["", "## Hit flips", ""]
    if paired["hit_flips"]:
        lines += ["| key | baseline | candidate |", "|---|---|---|"]
        lines += [
            f"| {flip['key']} | {'hit' if flip['baseline_hit'] else 'miss'} `{flip['baseline_pattern']}` | "
            f"{'hit' if flip['candidate_hit'] else 'miss'} `{flip['candidate_pattern']}` |"
            for flip in paired["hit_flips"]
        ]
    else:
        lines.append("- none")
    lines += ["", "## Stage deltas", ""]
    stage_deltas = payload["latency"]["stage_deltas"]
    if not stage_deltas["available"]:
        lines.append(f"- not available: {stage_deltas['note']}")
    else:
        lines += ["| stage | calls Δ | total ms baseline | total ms candidate | Δ ms |", "|---|---|---|---|---|"]
        for stage, block in stage_deltas["stages"].items():
            lines.append(
                f"| `{stage}` | {block['calls_delta']:+d} | {block['total_ms_baseline']:.1f} | "
                f"{block['total_ms_candidate']:.1f} | {block['total_ms_delta']:+.1f} |"
            )
    if payload["integrity"]["warnings"]:
        lines += ["", "## Warnings", ""] + [f"- {warning}" for warning in payload["integrity"]["warnings"]]
    lines.append("")
    return "\n".join(lines)


def _rate(value: Any) -> str:
    """Format an optional hit rate."""
    return "null" if value is None else f"{100.0 * float(value):.1f}%"


def _signed(value: Any) -> str:
    """Format an optional signed delta."""
    return "null" if value is None else f"{float(value):+.4f}"


def build_parser() -> argparse.ArgumentParser:
    """CLI of the comparison tool."""
    parser = argparse.ArgumentParser(prog="tests.benchmark.harness.compare",
                                     description="Compare two benchmark run directories (A=baseline, B=candidate).")
    parser.add_argument("baseline", type=Path, help="baseline run directory (A)")
    parser.add_argument("candidate", type=Path, help="candidate run directory (B)")
    parser.add_argument("--out", type=Path, default=None, help="comparison output directory (default: <B>/comparison)")
    parser.add_argument("--allow-mismatch", action="store_true",
                        help="compare even when the scenario files or modes differ (records a warning)")
    parser.add_argument("--quiet", action="store_true", help="print only the verdict line")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: compare two runs and print the verdict."""
    args = build_parser().parse_args(argv)
    try:
        payload = compare_arms(
            Arm.load(args.baseline, "baseline"),
            Arm.load(args.candidate, "candidate"),
            allow_mismatch=args.allow_mismatch,
            out_dir=args.out,
        )
    except ValueError as exc:
        print(f"compare refused: {exc}", file=sys.stderr)
        return 2
    if args.quiet:
        print(payload["verdict"]["outcome"])
    else:
        print(json.dumps({"verdict": payload["verdict"], "outputs": payload["outputs"]}, indent=2, ensure_ascii=False))
    return 0 if payload["verdict"]["outcome"] != "candidate-loss" else 1


if __name__ == "__main__":
    sys.exit(main())
