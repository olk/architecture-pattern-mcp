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

"""GENERATE-phase prompt-quality regression benchmark.

Two execution modes:

Recorded mode (default, offline, CI-safe)
    Validates structurally against golden designs in ``tests/regression/golden/``.
    Fixtures without a golden file are skipped. Assertions:
      1. overview.reasoning is populated (reason-before-commit contract)
      2. cross-reference integrity: every relationship.source/target,
         ApiContract.component_id, and EventContract.published_by/consumed_by
         resolves to an existing component id
      3. requirement traceability: every ``required_capabilities`` keyword of a
         fixture appears in at least one component's name/description/
         responsibilities
      4. scoring honesty: no quality attribute scored above 9/10
      5. delivered style matches one of the fixture's expected styles

Live mode (opt-in; requires a working config.json + LLM endpoint)
    ARCH_BENCH_LLM=1 uv run pytest tests/regression -m llm -v
    Runs the real pipeline per fixture and applies assertions 1-5 plus the
    exact-style check. Capture goldens for the recorded mode with:
    ARCH_BENCH_LLM=1 ARCH_BENCH_CAPTURE=1 uv run pytest tests/regression -m llm -v

Baseline workflow (plan v2 validation flow):
    1. Capture goldens against the CURRENT code  -> baseline
    2. Apply prompt/schema changes               -> capture again elsewhere
    3. Diff structural assertion results and quality between runs
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parent / "golden"


# ─── Fixtures ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BenchFixture:
    """One benchmark requirement set.

    ``required_capabilities`` keywords are matched case-insensitively as
    substrings against each component's name, description, and
    responsibilities — every keyword must land on at least one component.
    """

    name: str
    domain: str
    primary_style: str
    expected_styles: frozenset[str]
    requirements: str
    required_capabilities: tuple[str, ...] = field(default_factory=tuple)


FIXTURES: tuple[BenchFixture, ...] = (
    BenchFixture(
        name="ecommerce-order-processing",
        domain="e-commerce",
        primary_style="event-driven",
        expected_styles=frozenset({"event-driven", "microservices"}),
        requirements=(
            "Build an order processing platform: customers place orders, payments "
            "are confirmed asynchronously, inventory is updated on every order, and "
            "the marketing team consumes an order activity feed. Expect 10k orders "
            "per minute at peak and 99.9% uptime. Payment data is PCI-relevant."
        ),
        required_capabilities=("order", "payment", "inventory"),
    ),
    BenchFixture(
        name="healthcare-patient-portal",
        domain="healthcare",
        primary_style="modular-monolith",
        expected_styles=frozenset({"modular-monolith", "layered-monolith"}),
        requirements=(
            "A patient portal where patients manage appointments and view lab "
            "results. All access must be written to an audit trail, and data is "
            "subject to strict privacy regulation. Team of 8, moderate traffic."
        ),
        required_capabilities=("patient", "appointment", "audit"),
    ),
    BenchFixture(
        name="iot-sensor-ingestion",
        domain="iot",
        primary_style="lambda-architecture",
        expected_styles=frozenset({"lambda-architecture", "kappa-architecture", "event-driven"}),
        requirements=(
            "Ingest telemetry from 500k sensors. The speed layer serves live "
            "dashboards with sub-second latency while the batch layer recomputes "
            "accurate hourly aggregates. Devices push over MQTT from the field."
        ),
        required_capabilities=("sensor", "ingest", "batch"),
    ),
    BenchFixture(
        name="banking-transaction-processing",
        domain="fintech",
        primary_style="event-sourcing",
        expected_styles=frozenset({"event-sourcing", "saga"}),
        requirements=(
            "Process account transactions with a complete, immutable ledger. Every "
            "balance change must be auditable and reproducible; regulators require "
            "exact transaction history. Strong consistency per account."
        ),
        required_capabilities=("transaction", "ledger", "audit"),
    ),
    BenchFixture(
        name="video-streaming-platform",
        domain="media",
        primary_style="microservices",
        expected_styles=frozenset({"microservices", "event-driven"}),
        requirements=(
            "A video platform where uploads are transcoded into multiple "
            "renditions, metadata is searchable, and playback streams to 100k "
            "concurrent viewers. Transcoding is bursty and CPU-heavy."
        ),
        required_capabilities=("video", "transcod", "stream"),
    ),
    BenchFixture(
        name="internal-admin-dashboard",
        domain="internal-tools",
        primary_style="layered-monolith",
        expected_styles=frozenset({"layered-monolith", "monolithic"}),
        requirements=(
            "An internal admin dashboard for support staff: browse users, adjust "
            "permissions, and export reports. Fewer than 100 concurrent users; "
            "built and maintained by one small team."
        ),
        required_capabilities=("user", "permission", "report"),
    ),
    BenchFixture(
        name="ml-inference-api",
        domain="aiml",
        primary_style="serverless",
        expected_styles=frozenset({"serverless", "aiml-centric"}),
        requirements=(
            "Serve model inference over a public REST API with spiky, unpredictable "
            "traffic — from zero requests at night to thousands per second during "
            "batch customer jobs. Scale to zero when idle to control cost."
        ),
        required_capabilities=("inference", "model", "scale"),
    ),
    BenchFixture(
        name="legacy-erp-modernization",
        domain="enterprise",
        primary_style="strangler-fig",
        expected_styles=frozenset({"strangler-fig"}),
        requirements=(
            "Incrementally replace a 15-year-old ERP: new capabilities ship as "
            "modern services while the legacy core stays alive, traffic shifts "
            "slice by slice behind a routing facade, and data stays in sync "
            "between old and new until each capability is retired."
        ),
        required_capabilities=("legacy", "route", "sync"),
    ),
)


# ─── Shared assertion helpers ───────────────────────────────────────────────


def _component_ids(design) -> set[str]:
    return {c.id for c in design.components}


def _capability_text(design, component) -> str:
    return " ".join(
        [component.name, component.description, *component.responsibilities]
    ).lower()


def assert_structural_quality(design, fixture: BenchFixture) -> None:
    """Assertions 1-5 (reasoning, cross-refs, traceability, honesty, style)."""
    # 1. reasoning populated (reason-before-commit contract)
    assert design.overview.reasoning.strip(), "overview.reasoning must be populated"

    ids = _component_ids(design)
    assert ids, "design must contain components"

    # 2. cross-reference integrity
    for rel in design.relationships:
        assert rel.source in ids, f"orphan relationship source: {rel.source}"
        assert rel.target in ids, f"orphan relationship target: {rel.target}"
    for ac in design.api_contracts:
        assert ac.component_id in ids, f"orphan api contract: {ac.component_id}"
    for comp in design.components:
        if comp.api_contract is not None:
            assert comp.api_contract.component_id in ids, (
                f"component {comp.id} embeds api contract for unknown id "
                f"{comp.api_contract.component_id}"
            )
    for ec in design.event_contracts:
        assert ec.published_by in ids, f"orphan event publisher: {ec.published_by}"
        for consumer in ec.consumed_by:
            assert consumer in ids, f"orphan event consumer: {consumer}"

    # 3. requirement traceability
    for capability in fixture.required_capabilities:
        hits = [
            c for c in design.components if capability in _capability_text(design, c)
        ]
        assert hits, (
            f"capability '{capability}' traces to no component "
            f"(capabilities checked: {fixture.required_capabilities})"
        )

    # 4. scoring honesty: nothing above 9/10
    for attr, value in design.quality_attributes.items():
        try:
            score = float(str(value).split("/")[0])
        except ValueError:
            continue
        assert score <= 9.0, f"quality attribute '{attr}' inflated: {value}"

    # 5. style within expectation
    assert design.overview.style.value in fixture.expected_styles, (
        f"style {design.overview.style.value!r} not in expected "
        f"{sorted(fixture.expected_styles)}"
    )


# ─── Recorded mode (offline) ────────────────────────────────────────────────


def _load_golden(fixture: BenchFixture):
    golden_path = GOLDEN_DIR / f"{fixture.name}.json"
    if not golden_path.exists():
        return None
    from src.schemas.design import ArchitectureDesign

    return ArchitectureDesign.model_validate(json.loads(golden_path.read_text()))


@pytest.mark.parametrize(
    "fixture", FIXTURES, ids=lambda f: f.name
)
def test_golden_design_structural_quality(fixture: BenchFixture):
    """Recorded mode: validate a captured golden design structurally."""
    design = _load_golden(fixture)
    if design is None:
        pytest.skip(
            f"no golden for {fixture.name!r} — capture with "
            "ARCH_BENCH_LLM=1 ARCH_BENCH_CAPTURE=1 uv run pytest tests/regression -m llm"
        )
    assert_structural_quality(design, fixture)


def test_golden_coverage_report():
    """Transparency: report how many fixtures currently have goldens."""
    have = [f.name for f in FIXTURES if (GOLDEN_DIR / f"{f.name}.json").exists()]
    missing = [f.name for f in FIXTURES if f.name not in have]
    print(f"\nGolden coverage: {len(have)}/{len(FIXTURES)} (missing: {missing or 'none'})")


# ─── Live mode (opt-in) ─────────────────────────────────────────────────────


def _build_live_pipeline():
    """Build a real ArchitecturePipeline from the deployed config.

    generate() never touches the retrieval legs, so they are left
    unbuilt — no TEI dependency for the GENERATE-only benchmark.
    """
    from src.agent import SoftwareArchitectAgent
    from src.config import ConfigManager, RetrievalConfig, RerankerConfig, ServerConfig
    from src.patterns.loader import PatternLoader
    from src.pipeline import ArchitecturePipeline

    cfg = ConfigManager.load_config()
    server_cfg = ServerConfig.model_validate(cfg)
    agent = SoftwareArchitectAgent(server_cfg)
    retrieval = RetrievalConfig(**cfg.get("retrieval", {}))
    reranker = RerankerConfig(**cfg.get("reranker", {}))
    return ArchitecturePipeline(
        agent=agent,
        pattern_loader=PatternLoader(),
        embedder_config=server_cfg.embedder,
        retrieval_config=retrieval,
        reranker_config=reranker,
    )


def _select_patterns(pipeline, fixture: BenchFixture) -> list[dict]:
    """Select the fixture's primary pattern as generation context."""
    for pattern in pipeline._pattern_loader.load_all():
        if pattern.get("name") == fixture.primary_style:
            return [pattern]
    pytest.skip(f"pattern {fixture.primary_style!r} not found in pattern directory")


@pytest.mark.llm
@pytest.mark.skipif(
    not os.getenv("ARCH_BENCH_LLM", ""),
    reason="ARCH_BENCH_LLM=1 to run live GENERATE benchmark (requires config + LLM)",
)
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda f: f.name)
def test_live_generate_quality(fixture: BenchFixture):
    """Live mode: run the real GENERATE phase and assert structural quality."""
    capture = bool(os.getenv("ARCH_BENCH_CAPTURE", ""))

    try:
        pipeline = _build_live_pipeline()
    except Exception as exc:  # config missing/invalid → skip, not fail
        pytest.skip(f"cannot build live pipeline: {exc}")

    selected = _select_patterns(pipeline, fixture)

    design = asyncio.run(
        pipeline.generate(
            requirements=fixture.requirements,
            domain=fixture.domain,
            style=fixture.primary_style,
            selected_patterns=selected,
        )
    )

    assert_structural_quality(design, fixture)
    # live-only: the design must use exactly the requested style
    assert design.overview.style.value == fixture.primary_style

    if capture:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        out = GOLDEN_DIR / f"{fixture.name}.json"
        out.write_text(design.model_dump_json(indent=2) + "\n")
        print(f"captured golden: {out}")
