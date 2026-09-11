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
L3 bridge — hand-planted garden (M-*) <-> mutation engine (plan R7).

The two halves of L3 must not drift apart: every bug class the garden plants
must exist as generated, classified mutmut mutants at anchor functions in the
production tree (the per-run attestation recorded in the committed baseline),
and every anchor the bridge declares must name a class the garden actually
plants. Mutant-key-based mappings are impossible here by design — mutmut's
``__mutmut_<N>`` indices shift on every source edit — so the bridge compares
the SEMANTIC class sets and the attestation, never individual keys.

The live mutants exist in the .meta files, but this test audits only the
committed baseline (toolchain-free, rides `make test-oracles`).
"""

import json
from pathlib import Path

from scripts.mutmut_baseline import (
    DEFAULT_BASELINE,
    DEFAULT_GARDEN,
    GARDEN_CLASS_ANCHORS,
    garden_classes,
)
from tests.verification.gardens.bug_garden import MUTANTS, mutants_by_class

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _baseline() -> dict[str, object]:
    document: object = json.loads(DEFAULT_BASELINE.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


class TestGardenEngineBridge:
    def test_garden_classes_and_anchor_map_agree(self) -> None:
        """Both directions: an anchored class without garden mutants is dead
        weight; a planted class without an anchor has no engine-side witness."""
        garden = garden_classes(DEFAULT_GARDEN)
        assert garden == set(GARDEN_CLASS_ANCHORS)

    def test_garden_registry_classes_match_parsed_classes(self) -> None:
        """The AST parse of bug_garden.py must see exactly the classes the
        live MUTANTS registry carries (parse drift = bridge blind spot)."""
        assert mutants_by_class().keys() == garden_classes(DEFAULT_GARDEN)

    def test_every_garden_mutant_id_is_unique_and_typed(self) -> None:
        ids = [m.id for m in MUTANTS]
        assert len(ids) == len(set(ids)), "mutant IDs must be unique"
        assert all(m.klass in GARDEN_CLASS_ANCHORS for m in MUTANTS)

    def test_attestation_recorded_for_every_class_in_baseline(self) -> None:
        baseline = _baseline()
        attestation = baseline.get("garden_attestation")
        assert isinstance(attestation, dict)
        assert set(attestation) == set(GARDEN_CLASS_ANCHORS)
        for bug_class, entry in attestation.items():
            assert entry["ok"] is True, f"{bug_class}: {entry}"
            assert int(entry["mutants"]) > 0, f"{bug_class}: no engine-side mutants"  # type: ignore[arg-type]

    def test_anchor_functions_exist_in_baseline(self) -> None:
        """Anchor rot detection: every (module, function) the bridge declares
        must appear as a function label in the committed baseline — an anchor
        renamed out of existence would otherwise attest nothing, silently."""
        baseline = _baseline()
        functions = baseline.get("functions")
        assert isinstance(functions, dict)
        labels = set(functions)  # type: ignore[arg-type]
        for bug_class, anchors in GARDEN_CLASS_ANCHORS.items():
            for module, function in anchors:
                label = f"{module}::{function}"
                assert label in labels, (
                    f"{bug_class} anchor {label} not found in baseline — "
                    "update GARDEN_CLASS_ANCHORS"
                )
