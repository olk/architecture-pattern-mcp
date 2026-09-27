"""Black-box e2e runner: the running compose stack through a fastmcp client.

Mirrors the demo-client default (``ARCHITECTURE_CLIENT_URL``, default
``http://localhost:8050/mcp``) and calls ``design_architecture`` once per scenario.
This mode measures what a real deployment costs *in total* against the real stack,
and nothing else:

- latency: wall clock per call (no stage attribution — the seams are on the far side)
- quality: the ``DesignArchitectureOutput`` wire contract (``final_style``,
  ``alternative_styles[].name``)

Two wire-contract limits are reported as ``null``, never as zero: the tool result carries
no calibration score (the evaluation rides along as ``evaluation.summary.overall_score`` is
internal to the design payload, so its score is out of scope for a black-box hit check) and
the fallback flag IS on the wire here (unlike A), so fallbacks are observable. A tool error
is recorded as a failed scenario instead of being dropped, so an arm cannot win by failing
loudly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastmcp import Client

from . import config as cfg
from . import scoring
from .probes import percentile_fields, stage_table
from .runner import render_report

#: MCP server URL of the compose stack (same default as the demo client).
DEFAULT_URL = os.environ.get("ARCHITECTURE_CLIENT_URL", "http://localhost:8050/mcp")

#: The tool under test (wire name).
TOOL_NAME = "design_architecture"


@dataclass
class E2EOptions:
    """One black-box arm invocation."""

    url: str = DEFAULT_URL
    scenarios_path: Path = cfg.DEFAULT_SCENARIOS
    out_dir: Path | None = None
    split: str = "all"
    limit: int | None = None
    repeats: int = 1
    warmup: bool = True
    run_id: str | None = None
    call_timeout_seconds: float | None = None


def _tool_arguments(scenario: cfg.Scenario) -> dict[str, Any]:
    """Tool arguments for one scenario (the corpus authors the domain; see runner.py)."""
    return {
        "requirements": scenario.description,
        "domain": scenario.domain,
    }


def _quality_block(payload: dict[str, Any] | None, scenario: cfg.Scenario) -> dict[str, Any]:
    """Wire-contract-derived quality block (``null`` where the contract hides a metric)."""
    payload = payload or {}
    fallback = bool(payload.get("is_fallback", False))
    final = payload.get("final_style")
    alternatives: list[Any] = payload.get("alternative_styles") or []
    names = [entry.get("name") for entry in alternatives if isinstance(entry, dict)]
    selected: list[str] = []
    for name in [final, *names]:
        if isinstance(name, str) and name and name not in selected:
            selected.append(name)
    acceptable = set(scenario.acceptable)
    hit = (not fallback) and isinstance(final, str) and final in set(scenario.acceptable_primary)
    return {
        "hit": hit,
        "fallback": fallback,
        "final_pattern": final if isinstance(final, str) else None,
        "expected_primary": scenario.primary,
        "acceptable_primary": list(scenario.acceptable_primary),
        "acceptable_supporting": list(scenario.acceptable_primary),
        "selected": selected,
        "selected_true_positives": sorted(set(selected) & acceptable),
        "recall_at_3": round(scoring.recall_at_k(selected, scenario.acceptable, 3), 6),
        "recall_at_5": round(scoring.recall_at_k(selected, scenario.acceptable, 5), 6),
        "supporting": None,
        "acceptable_primary_f1": scoring.acceptable_primary_f1(hit, scenario.acceptable_primary),
        "veto_conflicts": None,
        "veto_violations": None,
        "score": None,
        "score_scaled": None,
        "reliability_bin": None,
        "brier": None,
        "calibration_eligible": scenario.split == "train",
        "score_source": "none: the wire carries no normalized calibration score",
    }


async def _call_tool_once(client: Client[Any], scenario: cfg.Scenario) -> dict[str, Any]:
    """One tool call; returns ``{"payload": …, "error": …}`` (never raises for tool failures)."""
    try:
        result = await client.call_tool(TOOL_NAME, _tool_arguments(scenario))
        payload: dict[str, Any] = result.data
        return {"payload": payload, "error": None}
    except Exception as exc:  # noqa: BLE001 - a failed call is data, not a crash
        return {"payload": None, "error": f"{type(exc).__name__}: {exc}"}


async def _run_scenario(
    client: Client[Any], scenario: cfg.Scenario, *, repeat: int, warmup: bool
) -> dict[str, Any]:
    """Time one scenario call and build its record."""
    started_ns = time.perf_counter_ns()
    outcome = await _call_tool_once(client, scenario)
    e2e_ms = round((time.perf_counter_ns() - started_ns) / 1_000_000.0, 3)
    payload = outcome["payload"]
    return {
        "harness_version": cfg.HARNESS_VERSION,
        "mode": "e2e",
        "scenario": scenario.record_identity(),
        "repeat": repeat,
        "warmup": warmup,
        "e2e_ms": e2e_ms,
        "stages": {},
        "stage_total_ms": 0.0,
        "residual_ms": e2e_ms,
        "quality": _quality_block(payload, scenario),
        "pipeline": None,
        "selection": None,
        "provenance": {"error": outcome["error"], "wire_final_style": (payload or {}).get("final_style")},
    }


async def run_e2e(options: E2EOptions) -> dict[str, Any]:
    """Execute one black-box arm; write its run directory and return the run id/paths."""
    config = cfg.load_server_config("e2e")
    catalog = cfg.load_repo_catalog(config)
    corpus = cfg.load_scenarios(options.scenarios_path, catalog)
    selected = cfg.select_scenarios(corpus, split=options.split, limit=options.limit)
    if not selected:
        raise ValueError(f"no scenarios selected (split={options.split!r}, limit={options.limit})")
    run_id = options.run_id or cfg.default_run_id("e2e")
    out_dir = options.out_dir or (cfg.DEFAULT_OUT_DIR / run_id)
    paths = cfg.RunPaths.for_run(out_dir)
    started_at = cfg.utc_now_iso()

    async with Client(options.url, timeout=options.call_timeout_seconds) as client:
        tools = await client.list_tools()
        available = sorted(tool.name for tool in tools)
        if TOOL_NAME not in available:
            raise RuntimeError(f"{TOOL_NAME} not exposed by {options.url}; tools: {available}")
        warmup_record: dict[str, Any] | None = None
        if options.warmup:
            warmup_record = await _run_scenario(client, selected[0], repeat=0, warmup=True)
            cfg.write_json(paths.root / "warmup.json", warmup_record)
        records: list[dict[str, Any]] = []
        for repeat in range(1, options.repeats + 1):
            for scenario in selected:
                record = await _run_scenario(client, scenario, repeat=repeat, warmup=False)
                records.append(record)
                cfg.write_json(paths.scenarios_dir / f"{scenario.scenario_id}-r{repeat}.json", record)

    errors = [record for record in records if record["provenance"]["error"]]
    notes = [
        (
            "e2e mode has no stage attribution and no normalized calibration score; "
            "those metrics are null, not zero (fallback IS observable on this wire)"
        ),
        f"{len(errors)} of {len(records)} calls failed",
    ]
    summary = _summary(records, options=options, paths=paths, run_id=run_id, started_at=started_at,
                       notes=notes, warmup_record=warmup_record, catalog=catalog)
    manifest = _manifest(options=options, config=config, catalog=catalog, records=records, run_id=run_id,
                         started_at=started_at, notes=notes, warmup_record=warmup_record)
    cfg.write_json(paths.manifest, manifest)
    cfg.write_json(paths.summary, summary)
    paths.report.write_text(render_report(summary, manifest), encoding="utf-8")
    return {"run_id": run_id, "run_dir": str(paths.root), "records": len(records), "summary": summary, "manifest": manifest}


def _summary(
    records: Sequence[dict[str, Any]],
    *,
    options: E2EOptions,
    paths: cfg.RunPaths,
    run_id: str,
    started_at: str,
    notes: Sequence[str],
    warmup_record: dict[str, Any] | None,
    catalog: Any,
) -> dict[str, Any]:
    """Run summary in the shared shape (stage table empty by contract)."""
    train = [record for record in records if record["scenario"]["split"] == "train"]
    holdout = [record for record in records if record["scenario"]["split"] == "holdout"]
    return {
        "harness_version": cfg.HARNESS_VERSION,
        "run_id": run_id,
        "mode": "e2e",
        "started_at": started_at,
        "finished_at": cfg.utc_now_iso(),
        "scenario_file": {"path": str(options.scenarios_path), "sha256": cfg.file_sha256(options.scenarios_path)},
        "selection": {
            "split": options.split,
            "limit": options.limit,
            "repeats": options.repeats,
            "warmup": options.warmup,
            "flips": [],
            "scenario_ids": [record["scenario"]["scenario_id"] for record in records],
        },
        "run_dir": str(paths.root),
        "catalog": {"records": len(catalog.load_all())},
        "quality": {
            "overall": scoring.aggregate_quality(records),
            "train": scoring.aggregate_quality(train),
            "holdout": scoring.aggregate_quality(holdout),
        },
        "latency": {
            "e2e_ms": percentile_fields([float(record["e2e_ms"]) for record in records]),
            "warmup_e2e_ms": warmup_record["e2e_ms"] if warmup_record else None,
            "stages": stage_table([]),
            "negative_residual_scenarios": 0,
            "residual_note": None,
            "per_scenario_e2e_ms": {
                f"{record['scenario']['scenario_id']}#{record['repeat']}": record["e2e_ms"] for record in records
            },
        },
        "calibration": {"available": False, "note": "no normalized score on the design_architecture wire"},
        "risk_coverage": {
            "available": False,
            "note": "risk-coverage needs per-record scores; the wire carries none",
        },
        "per_scenario": [
            {
                "scenario_id": record["scenario"]["scenario_id"],
                "repeat": record["repeat"],
                "family": record["scenario"]["family"],
                "category": record["scenario"]["category"],
                "split": record["scenario"]["split"],
                "hit": record["quality"]["hit"],
                "fallback": record["quality"]["fallback"],
                "final_pattern": record["quality"]["final_pattern"],
                "expected_primary": record["quality"]["expected_primary"],
                "score": None,
                "recall_at_3": record["quality"]["recall_at_3"],
                "recall_at_5": record["quality"]["recall_at_5"],
                "supporting_f1": None,
                "acceptable_primary_f1": record["quality"]["acceptable_primary_f1"]["f1"],
                "veto_violations": None,
                "e2e_ms": record["e2e_ms"],
                "residual_ms": record["residual_ms"],
                "error": record["provenance"]["error"],
            }
            for record in records
        ],
        "notes": list(notes),
    }


def _manifest(
    *,
    options: E2EOptions,
    config: Any,
    catalog: Any,
    records: Sequence[dict[str, Any]],
    run_id: str,
    started_at: str,
    notes: Sequence[str],
    warmup_record: dict[str, Any] | None,
) -> dict[str, Any]:
    """Run provenance for a black-box arm."""
    return {
        "harness_version": cfg.HARNESS_VERSION,
        "run_id": run_id,
        "mode": "e2e",
        "started_at": started_at,
        "finished_at": cfg.utc_now_iso(),
        "scenario_file": {"path": str(options.scenarios_path), "sha256": cfg.file_sha256(options.scenarios_path)},
        "selection": {
            "split": options.split,
            "limit": options.limit,
            "repeats": options.repeats,
            "warmup": options.warmup,
            "flips": [],
        },
        "scenario_ids": [record["scenario"]["scenario_id"] for record in records],
        "warmup": {
            "enabled": options.warmup,
            "scenario_id": warmup_record["scenario"]["scenario_id"] if warmup_record else None,
            "e2e_ms": warmup_record["e2e_ms"] if warmup_record else None,
        },
        "git": cfg.git_snapshot(),
        "env": cfg.masked_env_snapshot(),
        "server_config": cfg.mask_secrets(config.model_dump()),
        "catalog": {"records": len(catalog.load_all())},
        "executor": {
            "seams": {
                "transport": f"fastmcp Client → {options.url}",
                "tool": TOOL_NAME,
            },
            "note": "black-box: the server owns every seam; no stage attribution",
        },
        "runtime": {"python": sys.version.split()[0]},
        "counts": {
            "records": len(records),
            "train": sum(1 for record in records if record["scenario"]["split"] == "train"),
            "holdout": sum(1 for record in records if record["scenario"]["split"] == "holdout"),
            "errors": sum(1 for record in records if record["provenance"]["error"]),
        },
        "notes": list(notes),
    }


def build_parser() -> argparse.ArgumentParser:
    """CLI of the black-box runner."""
    parser = argparse.ArgumentParser(prog="tests.benchmark.harness.e2e",
                                     description="Run the black-box e2e arm against a running MCP server.")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"MCP endpoint (default: {DEFAULT_URL})")
    parser.add_argument("--scenarios", type=Path, default=cfg.DEFAULT_SCENARIOS)
    parser.add_argument("--split", choices=(*cfg.SPLITS, "all"), default="all")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--call-timeout-seconds", type=float, default=None,
                        help="per-request timeout in seconds (default: no client-side timeout; "
                             "live requests take minutes on the CPU tier)")
    parser.add_argument("--log-level", default="warning")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for ``--mode e2e`` runs."""
    args = build_parser().parse_args(argv)
    cfg.configure_logging(args.log_level)
    options = E2EOptions(
        url=args.url,
        scenarios_path=args.scenarios,
        out_dir=args.out,
        split=args.split,
        limit=args.limit,
        repeats=args.repeat,
        warmup=not args.no_warmup,
        run_id=args.run_id,
        call_timeout_seconds=args.call_timeout_seconds,
    )
    result = asyncio.run(run_e2e(options))
    summary = result["summary"]
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "run_dir": result["run_dir"],
                "records": result["records"],
                "quality": summary["quality"]["overall"],
                "e2e_ms": summary["latency"]["e2e_ms"],
                "notes": summary["notes"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
