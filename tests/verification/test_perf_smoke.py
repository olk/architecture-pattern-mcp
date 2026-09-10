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
L10 performance smoke canary over the verified cores (nagini plan §5.5;
testing-strategies §3.10).

Rationale (AxDafny lesson): proofs guarantee functional correctness, NOT
performance — a refactor of a verified core cannot be allowed to silently
regress latency. Budgets are deliberately coarse (regression canary, not a
benchmark): orders-of-magnitude headroom, generous multipliers over the
observed baseline so CI noise never trips them.

Skipped unless RUN_PERF=1 (the perf marker's opt-in contract). Nightly TCB
canary job runs it (see .github/workflows/verification.yml).

NOTE: Twin verification was removed (verify/twin/ deleted). The twin-related
test_twin_operations test has been removed.
"""

import os
import time
from collections.abc import Callable

import pytest

from src.design_normalization import denormalize_contracts
from src.schemas import ArchitectureDesign
from src.text_validation import ensure_printable_text

ITERATIONS = 2_000
# Coarse budgets (seconds for ITERATIONS ops): >= 50x observed headroom.
BUDGET_TEXT_VALIDATION = 2.0
BUDGET_NORMALIZATION = 4.0


def _time_budgeted(name: str, fn: Callable[[], object], budget_s: float) -> None:
    start = time.perf_counter()
    for _ in range(ITERATIONS):
        fn()
    elapsed = time.perf_counter() - start
    assert elapsed < budget_s, (
        f"{name}: {elapsed:.2f}s for {ITERATIONS} ops exceeds canary budget "
        f"{budget_s}s — verified-core latency regressed; triage the refactor"
    )


@pytest.mark.perf
@pytest.mark.skipif(not os.getenv("RUN_PERF", ""), reason="RUN_PERF=1 perf canary")
class TestVerifiedCorePerfSmoke:
    def test_text_validation_core(self) -> None:
        _time_budgeted(
            "text_validation_core.ensure_printable_text",
            lambda: ensure_printable_text("  design a scalable system  ", field="value"),
            BUDGET_TEXT_VALIDATION,
        )

    def test_design_normalization_core(self) -> None:
        design = _sample_design()
        _time_budgeted(
            "design_normalization_core.denormalize_core",
            lambda: denormalize_contracts(design),
            BUDGET_NORMALIZATION,
        )


class _Contract:
    component_id = "ingest"
    base_path = "/api/v1/ingest"
    endpoints: list[object] = []


class _Component:
    api_contract: "_Contract | None" = _Contract()
    data_models: list[object] = []


class _Design:
    api_contracts = [_Contract()]
    components = [_Component(), _Component(), _Component()]
    shared_data_models: list[object] = []
    event_contracts: list[object] = []


def _sample_design() -> ArchitectureDesign:
    from src.schemas import (
        ApiContract,
        ArchitectureOverview,
        ArchitectureStyle,
        Component,
        DataModel,
        EventContract,
        PatternCategory,
    )

    return ArchitectureDesign(
        overview=ArchitectureOverview(
            style=ArchitectureStyle.MICROSERVICES,
            category=PatternCategory.STRUCTURAL,
            principles=["single responsibility"],
        ),
        components=[
            Component(
                id="svc",
                name="Service",
                type="service",
                description="A service",
                responsibilities=["process"],
                api_contract=ApiContract(
                    component_id="ingest",
                    base_path="/api/v1/ingest",
                    endpoints=[],
                ),
                data_models=[
                    DataModel(name="shared-model", fields=[], is_shared=True)
                ],
            )
        ],
        relationships=[],
        patterns=[],
        api_contracts=[ApiContract(component_id="ingest", base_path="/x", endpoints=[])],
        shared_data_models=[],
        event_contracts=[EventContract(event_name="created", payload_schema={}, published_by="svc")],
        quality_attributes={},
        domain="test",
    )
