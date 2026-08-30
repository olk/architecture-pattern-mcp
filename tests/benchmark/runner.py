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

"""Prompt A/B benchmark runner for the GENERATE-phase system prompt.

Executes the full design pipeline (analyze -> generate -> evaluate -> design_loop)
over tests/benchmark/requirements.jsonl and records per-case quality metrics to a
JSON file. Version-agnostic by design: the pipeline is imported from the source
tree given by --src, so the SAME runner measures a baseline checkout and a
candidate checkout (two-branch execution model — no prompt_version config needed).

Usage:
    uv run python tests/benchmark/runner.py --src . --out results_candidate.json
    uv run python tests/benchmark/runner.py --src ../apm-v1 --out results_baseline.json

Requires a live LLM (config/config.json credentials), the TEI embedding sidecar
and the reranker sidecar. See README.md in this directory for the full procedure.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

GENERIC_TECH_STOPWORDS: frozenset[str] = frozenset(
    {
        "web framework",
        "framework",
        "database",
        "a database",
        "database system",
        "relational database",
        "sql database",
        "nosql database",
        "sql",
        "nosql",
        "message queue",
        "queue",
        "message broker",
        "broker",
        "event bus",
        "cache",
        "storage",
        "object storage",
        "file storage",
        "load balancer",
        "api",
        "rest api",
        "http server",
        "web server",
        "application server",
        "search engine",
        "search index",
        "frontend framework",
        "ui framework",
        "programming language",
    }
)

_QA_FORMAT_RE = re.compile(r"^\d+\s*/\s*10$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run prompt A/B benchmark cases.")
    parser.add_argument(
        "--src",
        default=".",
        help="Checkout root containing the src/ package to benchmark (default: current directory)",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Path of the results JSON file to write",
    )
    parser.add_argument(
        "--cases",
        default=str(Path(__file__).with_name("requirements.jsonl")),
        help="Path to the benchmark case list (default: requirements.jsonl next to this file)",
    )
    parser.add_argument("--only", nargs="*", help="Run only the given case ids")
    parser.add_argument("--limit", type=int, default=None, help="Run at most N cases")
    return parser.parse_args()


def bootstrap_import_path(src_root: str) -> None:
    resolved = str(Path(src_root).resolve())
    if not (Path(resolved) / "src" / "pipeline.py").exists():
        raise SystemExit(f"--src {src_root!r} does not contain src/pipeline.py")
    sys.path.insert(0, resolved)


def load_cases(path: str, only: list[str] | None, limit: int | None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            case = json.loads(line)
            for key in ("id", "requirements", "domain"):
                if key not in case:
                    raise SystemExit(f"case missing {key!r}: {line[:80]}")
            cases.append(case)
    if only:
        wanted = set(only)
        cases = [c for c in cases if c["id"] in wanted]
        missing = wanted - {c["id"] for c in cases}
        if missing:
            raise SystemExit(f"unknown case ids: {sorted(missing)}")
    if limit is not None:
        cases = cases[:limit]
    if not cases:
        raise SystemExit("no cases selected")
    return cases


def build_pipeline() -> Any:
    from src.agent import SoftwareArchitectAgent
    from src.config import ConfigManager, RerankerConfig, RetrievalConfig, ServerConfig
    from src.patterns.bm25_index import DomainBM25Index
    from src.patterns.loader import PatternLoader
    from src.patterns.vector_index import DomainVectorIndex
    from src.pipeline import ArchitecturePipeline

    cfg = ConfigManager.load_config()
    agent = SoftwareArchitectAgent(ServerConfig.model_validate(cfg))
    retrieval = RetrievalConfig(**cfg.get("retrieval", {}))
    reranker = RerankerConfig(**cfg.get("reranker", {}))
    pipeline = ArchitecturePipeline(
        agent=agent,
        pattern_loader=PatternLoader(),
        vector_index=DomainVectorIndex(),
        bm25_index=DomainBM25Index(),
        retrieval_config=retrieval,
        reranker_config=reranker,
    )
    pipeline.warmup_indexes()
    return pipeline


def extract_metrics(case_id: str, result: Any, duration_s: float) -> dict[str, Any]:
    design = result.design
    components = list(design.components)
    component_ids = {c.id for c in components}

    dangling = sum(
        1
        for rel in design.relationships
        if rel.source not in component_ids or rel.target not in component_ids
    )

    technologies = [t for c in components for t in (c.technology_stack or [])]
    generic = sum(1 for t in technologies if t.strip().lower() in GENERIC_TECH_STOPWORDS)

    qa_values = list(design.quality_attributes.values())

    return {
        "id": case_id,
        "validation_success": True,
        "overall_quality": float(result.final_quality_score),
        "evaluation_overall_score": float(result.evaluation.summary.overall_score),
        "critical_findings": len(result.evaluation.summary.critical_findings),
        "attempts": int(result.attempts),
        "component_count": len(components),
        "relationship_count": len(design.relationships),
        "dangling_references": dangling,
        "technology_entries": len(technologies),
        "generic_technologies": generic,
        "qa_format_valid": bool(qa_values) and all(_QA_FORMAT_RE.match(v) for v in qa_values),
        "field_population": {
            "top_level_api_contracts": bool(design.api_contracts),
            "top_level_shared_data_models": bool(design.shared_data_models),
            "top_level_event_contracts": bool(design.event_contracts),
            "component_api_contracts": any(c.api_contract is not None for c in components),
            "component_data_models": any(bool(c.data_models) for c in components),
            "config_requirements": any(bool(c.config_requirements) for c in components),
        },
        "final_style": result.final_style,
        "is_fallback": bool(result.is_fallback),
        "duration_s": round(duration_s, 2),
    }


def run() -> None:
    args = parse_args()
    bootstrap_import_path(args.src)
    from src.pipeline import ArchitecturePipeline  # noqa: F401  (import check against --src tree)

    cases = load_cases(args.cases, args.only, args.limit)
    pipeline = build_pipeline()

    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, 1):
        started = time.monotonic()
        try:
            result = asyncio.run(
                pipeline.run_design(
                    requirements=case["requirements"],
                    domain=case["domain"],
                    style=case.get("style"),
                )
            )
            metrics = extract_metrics(case["id"], result, time.monotonic() - started)
        except Exception as exc:  # noqa: BLE001 - a failed case is a data point, not a crash
            metrics = {
                "id": case["id"],
                "validation_success": False,
                "overall_quality": 0.0,
                "attempts": 0,
                "dangling_references": -1,
                "generic_technologies": -1,
                "error": f"{type(exc).__name__}: {exc}"[:300],
                "duration_s": round(time.monotonic() - started, 2),
            }
        results.append(metrics)
        print(
            f"[{index}/{len(cases)}] {case['id']}: "
            f"quality={metrics.get('overall_quality')} "
            f"attempts={metrics.get('attempts')} "
            f"dangling={metrics.get('dangling_references')} "
            f"generic={metrics.get('generic_technologies')}",
            flush=True,
        )

    payload = {
        "meta": {
            "src_root": str(Path(args.src).resolve()),
            "cases_file": str(Path(args.cases).resolve()),
            "case_count": len(results),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        },
        "results": results,
    }
    out_path = Path(args.out)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {len(results)} results to {out_path}")


if __name__ == "__main__":
    run()
