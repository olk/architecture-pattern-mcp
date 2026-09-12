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
L3 meta-oracle for the mutmut baseline gate (plan R2 / review fixes P-01..P-08).

The gate itself (scripts/mutmut_baseline.py) audits the LAST mutation run
against the committed verify/mutmut-baseline.json. These tests audit the
auditor — the repo vacuity rule applied to the meta layer:

- the committed baseline exists, is schema-valid, and covers every Tier A/B/C
  module (a mutation run that silently lost a module is detected here);
- the status mapping, mangled-name stripping, and ratchet logic are pinned
  against hand-computed cases (including mutmut 3.7's two trampoline
  spellings: ``x_<fn>`` and ``xǁClsǁ<fn>``);
- the garden-class attestation covers every bug class the garden declares
  (the class set is read live from bug_garden.py — a new garden class without
  an anchor entry fails here instead of passing vacuously);
- can-fail: a tampered baseline/current pair must fire the gate (the gate
  itself must be able to fail — P2 of testing-strategies §4).

Toolchain-free: no mutmut import, no scratch-tree dependency — this module
audits committed artifacts, so it rides every `make test-oracles` pass.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.mutmut_baseline import (
    CLASSIFIED,
    DEFAULT_BASELINE,
    DEFAULT_GARDEN,
    DEFAULT_THRESHOLDS,
    SCHEMA_VERSION,
    BaselineError,
    FunctionStats,
    Thresholds,
    garden_classes,
    gate,
    functions_from_json,
    load_thresholds,
    mangled_to_function,
    status_for,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TIER_ABC_MODULES = frozenset(
    {
        "src/config_expansion.py",
        "src/design_normalization.py",
        "src/text_validation.py",
        "src/tools/jobs.py",
        "src/validation.py",
    }
)


def _load_baseline() -> dict[str, object]:
    document: object = json.loads(DEFAULT_BASELINE.read_text(encoding="utf-8"))
    assert isinstance(document, dict), "baseline must decode to an object"
    return document


class TestCommittedBaseline:
    def test_baseline_exists_and_is_current_schema(self) -> None:
        document = _load_baseline()
        assert document["schema"] == SCHEMA_VERSION

    def test_baseline_carries_run_provenance(self) -> None:
        """P-01: the baseline is the only committed record of a mutation run —
        it must name the commit the run was made at."""
        run = _load_baseline()["run"]
        assert isinstance(run, dict)
        assert run.get("git_commit"), "baseline must record the run's git commit"

    def test_baseline_covers_every_tier_abc_module(self) -> None:
        modules_raw = _load_baseline()["modules"]
        assert isinstance(modules_raw, dict)
        missing = TIER_ABC_MODULES - set(modules_raw)
        assert not missing, f"baseline lost mutation data for: {sorted(missing)}"

    def test_baseline_totals_are_consistent(self) -> None:
        document = _load_baseline()
        totals = document["totals"]
        assert isinstance(totals, dict)
        total = int(totals["total"])  # type: ignore[arg-type]
        classified = int(totals["classified"])  # type: ignore[arg-type]
        assert int(totals["killed"]) + int(totals["survived"]) == classified  # type: ignore[arg-type]
        assert classified <= total
        assert total > 0

    def test_baseline_function_entries_are_self_consistent(self) -> None:
        functions = _load_baseline()["functions"]
        assert isinstance(functions, dict)
        assert functions, "baseline must carry per-function stats"
        for label, entry in functions.items():  # type: ignore[union-attr]
            total, killed = int(entry["total"]), int(entry["killed"])  # type: ignore[index]
            survived, classified = int(entry["survived"]), int(entry["classified"])  # type: ignore[index]
            assert killed + survived == classified, label
            assert classified + int(entry["other"]) == total, label  # type: ignore[index]
            assert len(entry["survivor_keys"]) == survived, label  # type: ignore[index]

    def test_every_garden_class_is_attested_ok(self) -> None:
        """R7: no garden class may drift from the mutation engine."""
        attestation = _load_baseline()["garden_attestation"]
        assert isinstance(attestation, dict)
        declared = garden_classes(DEFAULT_GARDEN)
        assert declared, "garden class parse must not come back empty"
        assert set(attestation) == declared, "attestation vs garden class drift"
        for bug_class, entry in attestation.items():
            assert entry["ok"] is True, f"{bug_class}: {entry}"


class TestStatusMapping:
    def test_upstream_exit_code_table(self) -> None:
        """Mirror of mutmut/stats.py status_by_exit_code (3.7.0)."""
        assert status_for(0) == "survived"
        assert status_for(1) == "killed"
        assert status_for(3) == "killed"
        assert status_for(5) == "no tests"
        assert status_for(33) == "no tests"
        assert status_for(34) == "skipped"
        assert status_for(35) == "suspicious"
        assert status_for(36) == "timeout"
        assert status_for(37) == "caught by type check"
        assert status_for(-24) == "timeout"
        assert status_for(152) == "timeout"
        assert status_for(-11) == "segfault"
        assert status_for(None) == "not checked"

    def test_unknown_exit_codes_are_suspicious_not_killed(self) -> None:
        assert status_for(999) == "suspicious"


class TestMangledNameStripping:
    def test_plain_function_prefix_x_underscore(self) -> None:
        """mutmut 3.7: plain trampolines are ``x_<fn>__mutmut_<N>``."""
        assert mangled_to_function("src.mod.x_compute_strip_window__mutmut_5") == (
            "src.mod.compute_strip_window"
        )

    def test_private_function_keeps_its_underscore(self) -> None:
        """``x__category_code`` is the marker ``x_`` + ``_category_code``."""
        assert mangled_to_function("src.mod.x__category_code__mutmut_1") == (
            "src.mod._category_code"
        )

    def test_method_trampoline_uses_iland_separators(self) -> None:
        assert mangled_to_function("src.tools.jobs.xǁJobsStoreǁ_guarded_update__mutmut_2") == (
            "src.tools.jobs.JobsStore._guarded_update"
        )

    def test_x_named_function_round_trips(self) -> None:
        """A function genuinely called ``x_foo`` must not lose its name."""
        assert mangled_to_function("src.mod.x_x_foo__mutmut_1") == "src.mod.x_foo"


class TestFunctionStats:
    def test_add_classifies_kill_and_survival(self) -> None:
        stats = FunctionStats()
        stats.add("killed", "m1")
        stats.add("survived", "m2")
        stats.add("timeout", "m3")
        stats.finalize()
        assert (stats.total, stats.killed, stats.survived, stats.classified) == (3, 1, 1, 2)
        assert stats.other == 1
        assert stats.kill_ratio == 0.5
        assert stats.survivor_keys == ["m2"]

    def test_merge_recomputes_ratio(self) -> None:
        left = FunctionStats()
        left.add("killed", "m1")
        left.finalize()
        right = FunctionStats()
        right.add("survived", "m2")
        right.finalize()
        merged = left.merged(right)
        assert (merged.total, merged.killed, merged.survived) == (2, 1, 1)
        assert merged.kill_ratio == 0.5

    def test_zero_classified_ratio_is_none(self) -> None:
        stats = FunctionStats()
        stats.add("no tests", "m1")
        stats.finalize()
        assert stats.kill_ratio is None
        assert stats.classified == 0

    def test_classified_never_contains_unclassified_statuses(self) -> None:
        assert frozenset({"killed", "survived"}) == CLASSIFIED


class TestRatchetGate:
    @staticmethod
    def _stats(killed: int, survived: int, keys: list[str] | None = None) -> FunctionStats:
        stats = FunctionStats()
        for i in range(killed):
            stats.add("killed", keys[i] if keys else f"k{i}")
        for j in range(survived):
            stats.add("survived", keys[killed + j] if keys else f"s{j}")
        stats.finalize()
        return stats

    def test_new_survivor_fails_the_gate(self) -> None:
        baseline = {"mod.py::fn": TestRatchetGate._stats(9, 0)}
        current = {
            "mod.py::fn": TestRatchetGate._stats(
                9, 1, keys=[f"k{i}" for i in range(9)] + ["NEW"]
            )
        }
        failures = gate(baseline, current, Thresholds())
        assert any("NEW-SURVIVOR" in f for f in failures)

    def test_ratio_drop_beyond_tolerance_fails(self) -> None:
        baseline = {"mod.py::fn": TestRatchetGate._stats(9, 1)}
        current = {"mod.py::fn": TestRatchetGate._stats(7, 3)}
        failures = gate(baseline, current, Thresholds(ratio_tolerance=0.02))
        assert any("RATIO-DROP" in f for f in failures)

    def test_ratio_jitter_within_tolerance_passes(self) -> None:
        baseline = {"mod.py::fn": TestRatchetGate._stats(9, 1)}
        current = {"mod.py::fn": TestRatchetGate._stats(9, 1)}
        assert gate(baseline, current, Thresholds(ratio_tolerance=0.02)) == []

    def test_improvement_passes_and_never_tightens_the_gate(self) -> None:
        """A better run must NOT fail: the baseline moves only via regen."""
        baseline = {"mod.py::fn": TestRatchetGate._stats(8, 2)}
        current = {"mod.py::fn": TestRatchetGate._stats(10, 0)}
        assert gate(baseline, current, Thresholds()) == []

    def test_vanished_module_fails_but_deleted_function_does_not(self) -> None:
        """P-08 asymmetry: a deleted function is a regen concern; a vanished
        module means the run died early — that is a regression."""
        baseline = {
            "gone.py::fn": TestRatchetGate._stats(1, 0),
            "live.py::other": TestRatchetGate._stats(1, 0),
        }
        current = {"live.py::other": TestRatchetGate._stats(1, 0)}
        failures = gate(baseline, current, Thresholds())
        assert any("MISSING-MODULE: gone.py" in f for f in failures)
        assert not any("live.py" in f for f in failures)

    def test_unclassified_function_fails(self) -> None:
        baseline = {"mod.py::fn": TestRatchetGate._stats(5, 0)}
        broken = FunctionStats()
        broken.add("no tests", "m1")
        broken.finalize()
        failures = gate(baseline, {"mod.py::fn": broken}, Thresholds())
        assert any("UNCLASSIFIED" in f for f in failures)

    def test_can_fail_vacuity_check(self) -> None:
        """Repo rule P2: the gate must be able to fail (tampered pair)."""
        document = _load_baseline()
        functions = functions_from_json(document["functions"])
        assert functions, "baseline must decode"
        tampered = deepcopy(functions)
        first = next(iter(tampered))
        tampered[first].survivor_keys.append("synthetic-new-survivor")
        failures = gate(functions, tampered, Thresholds())
        assert failures, "gate accepted a tampered baseline — it cannot fail"

    def test_nulled_scratch_is_detected_as_unclassified(self) -> None:
        """A config-invalidation pass nulls every exit code (observed live:
        2026-09-11 23:21). The gate must refuse such a run — never certify it
        and never let --write record it as a floor.

        The gate flags UNCLASSIFIED only for functions that were classified in
        the baseline (scripts/mutmut_baseline.py: `base.classified > 0 and
        cur.classified == 0`) — a function whose mutants were never covered
        ("no tests", e.g. the mocked embedder paths) cannot regress to
        unclassified. The nulled run therefore mirrors the gate's classifiable
        subset; the widened post-regen baseline (2970 mutants, 14 fully
        uncovered functions) is what exposed this contract.
        """
        live_functions = functions_from_json(_load_baseline()["functions"])
        classifiable = {
            label: stats
            for label, stats in live_functions.items()
            if stats.classified > 0
        }
        nulled = {
            label: FunctionStats(
                total=stats.total,
                killed=0,
                survived=0,
                classified=0,
                other=stats.total,
                kill_ratio=None,
                survivor_keys=[],
            )
            for label, stats in classifiable.items()
        }
        failures = gate(live_functions, nulled, Thresholds())
        unclassified = [f for f in failures if "UNCLASSIFIED" in f]
        assert classifiable, "baseline must contain at least one classified function"
        assert len(unclassified) == len(classifiable), (
            "every previously-classified function must be flagged unclassified"
        )


class TestThresholdsAndDecoding:
    def test_committed_thresholds_load(self) -> None:
        thresholds = load_thresholds(DEFAULT_THRESHOLDS)
        assert thresholds == Thresholds(ratio_tolerance=0.02, max_new_survivors=0)

    def test_malformed_function_entry_raises_loudly(self) -> None:
        with pytest.raises(BaselineError, match="malformed entry"):
            functions_from_json({"mod.py::fn": {"total": "not-a-number"}})

    def test_functions_round_trip_through_json_shapes(self) -> None:
        stats = FunctionStats()
        stats.add("killed", "k0")
        stats.add("killed", "k1")
        stats.add("killed", "k2")
        stats.add("survived", "s0")
        stats.finalize()
        as_json = json.loads(json.dumps({"mod.py::fn": stats.__dict__}))
        decoded = functions_from_json(as_json)
        assert decoded["mod.py::fn"].killed == 3
        assert decoded["mod.py::fn"].survivor_keys == stats.survivor_keys
