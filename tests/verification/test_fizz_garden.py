# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""Toolchain-free checks for the FizzBee spec-garden gate (L3/L4).

These tests pin the meta-oracle itself: scripts/fizz_garden.py must be able to
fail (repo vacuity rule). They exercise the runner's check layer — README<->>
garden.toml consistency, the AGENTS.md assertion-coverage rule, mutation
anchor health, and the outcome classifier — against the REAL repo artifacts,
plus synthetic classifier cases. None of them require the fizz binary;
`make verify-fizz-garden` runs the mutants themselves (nightly).
"""

from pathlib import Path

import pytest

from scripts.fizz_garden import (
    GardenError,
    Mutant,
    Op,
    _classify,
    anchor_errors,
    apply_ops,
    consistency_errors,
    coverage_errors,
    has_spec_explains,
    load_garden,
    parse_assertions,
    parse_readme_garden,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GARDEN = REPO_ROOT / "verify/fizz/garden.toml"
SPECS = REPO_ROOT / "verify/fizz"
README = REPO_ROOT / "verify/fizz/README.md"


def _mutant(**overrides: object) -> Mutant:
    base: dict[str, object] = {
        "id": "FG-T0",
        "spec": "retrieval_fusion",
        "status": "expect-fail",
        "assertion": "FUS1_RealHasPatterns",
        "ops": (Op(kind="replace", find="        self.resolved = 1", replace="        self.resolved = 0"),),
        "aliases": (),
        "max_actions": 0,
        "timeout_s": 300,
        "note": "synthetic test mutant",
    }
    base.update(overrides)
    return Mutant(**base)  # type: ignore[arg-type]


class TestGardenTable:
    def test_loads_all_rows(self) -> None:
        mutants = load_garden(GARDEN)
        assert len(mutants) == 32
        assert [m.id for m in mutants][:3] == ["FG-01", "FG-02", "FG-03"]

    def test_readme_and_garden_agree_1to1(self) -> None:
        mutants = load_garden(GARDEN)
        rows = parse_readme_garden(README)
        assert {m.id for m in mutants} == set(rows)

    def test_consistency_clean_on_current_repo(self) -> None:
        assert consistency_errors(load_garden(GARDEN), parse_readme_garden(README)) == []

    def test_mismatched_readme_id_is_flagged(self) -> None:
        rows = parse_readme_garden(README)
        rows["FG-99"] = "phantom row"
        errors = consistency_errors(load_garden(GARDEN), rows)
        assert any("FG-99" in e and "not in garden.toml" in e for e in errors)

    def test_renamed_assertion_is_flagged(self) -> None:
        rows = parse_readme_garden(README)
        rows["FG-01"] = "renamed: `SomeOther_Assertion` must fire"
        errors = consistency_errors(load_garden(GARDEN), rows)
        assert any("FG-01" in e and "J1_TerminalImmutable" in e for e in errors)


class TestAssertionCoverage:
    def test_every_always_assertion_covered_or_justified(self) -> None:
        assert coverage_errors(load_garden(GARDEN), SPECS) == []

    def test_removing_a_kill_row_breaks_coverage(self) -> None:
        mutants = [m for m in load_garden(GARDEN) if m.id != "FG-08"]
        errors = coverage_errors(mutants, SPECS)
        assert any("FP3_StageOrder" in e for e in errors)

    def test_unknown_expected_assertion_is_flagged(self) -> None:
        typo = _mutant(assertion="FUS1_Typo")
        errors = coverage_errors([typo], SPECS)
        assert any("FG-T0" in e and "FUS1_Typo" in e for e in errors)

    def test_spec_explains_window_detection(self) -> None:
        text = (SPECS / "jobs_protocol.fizz").read_text(encoding="utf-8")
        declarations = {name: line for _, name, line in parse_assertions(text)}
        assert has_spec_explains(text, declarations["J4_SingleRunner"]) is True
        assert has_spec_explains(text, declarations["J3_TimestampsMonotone"]) is False


class TestAnchorHealth:
    def test_all_executable_mutations_apply_cleanly(self) -> None:
        assert anchor_errors(load_garden(GARDEN), SPECS) == []

    def test_missing_anchor_is_flagged(self) -> None:
        stale = _mutant(ops=(Op(kind="replace", find="NO SUCH ANCHOR", replace="x"),))
        with pytest.raises(GardenError, match="occurs 0x"):
            apply_ops(stale, "body\n")

    def test_ambiguous_anchor_is_flagged(self) -> None:
        ambiguous = _mutant(ops=(Op(kind="replace", find="line", replace="x"),))
        with pytest.raises(GardenError, match="occurs 2x"):
            apply_ops(ambiguous, "line\nline\n")

    def test_net_noop_mutation_is_flagged(self) -> None:
        cancelling = _mutant(
            ops=(
                Op(kind="replace", find="alpha", replace="beta"),
                Op(kind="replace", find="beta", replace="alpha"),
            )
        )
        with pytest.raises(GardenError, match="no change"):
            apply_ops(cancelling, "alpha\n")

    def test_mutating_untracked_spec_is_flagged(self) -> None:
        errors = anchor_errors([_mutant(spec="nonexistent")], SPECS)
        assert any("nonexistent.fizz not found" in e for e in errors)


class TestClassifier:
    def test_expect_fail_killed_by_documented_invariant(self) -> None:
        out = "FAILED: Model checker failed. Invariant:  FUS1_RealHasPatterns"
        verdict = _classify(_mutant(), 1, out)
        assert verdict.ok and verdict.result == "KILLED"

    def test_expect_fail_killed_by_alias(self) -> None:
        out = "FAILED: Model checker failed. Invariant:  ALIAS_Target"
        verdict = _classify(_mutant(aliases=("ALIAS_Target",)), 1, out)
        assert verdict.ok and verdict.result == "KILLED"

    def test_expect_fail_survivor_fails_the_gate(self) -> None:
        verdict = _classify(_mutant(), 0, "PASSED: Model checker completed successfully")
        assert not verdict.ok and verdict.result == "SURVIVED"

    def test_expect_fail_deadlock_counts_as_kill(self) -> None:
        verdict = _classify(_mutant(), 0, "DEADLOCK detected\nFAILED: Model checker failed")
        assert verdict.ok and verdict.result == "KILLED"
        assert "deadlock" in verdict.detail

    def test_expect_fail_runtime_panic_counts_as_kill(self) -> None:
        out = "Model checking spec.json\npanic: runtime error: hash of unhashable"
        verdict = _classify(_mutant(), 2, out)
        assert verdict.ok and verdict.result == "KILLED"

    def test_expect_fail_compile_error_is_broken_not_killed(self) -> None:
        verdict = _classify(_mutant(), 1, "Error: failed to parse spec")
        assert not verdict.ok and verdict.result == "BROKEN"

    def test_expect_fail_budget_stop_is_inconclusive(self) -> None:
        out = "Model checking spec.json\nModel checker stopped"
        verdict = _classify(_mutant(), 0, out)
        assert not verdict.ok and verdict.result == "INCONCLUSIVE"

    def test_expect_fail_wrong_invariant_fails(self) -> None:
        # fizz v0.5.3 exits 0 on invariant failure — the WRONG case is exit 0.
        out = "FAILED: Model checker failed. Invariant:  SomeOther_Assertion"
        verdict = _classify(_mutant(), 0, out)
        assert not verdict.ok and verdict.result == "WRONG"

    def test_expect_pass_green_is_ok(self) -> None:
        verdict = _classify(_mutant(status="expect-pass"), 0, "PASSED: Model checker completed successfully")
        assert verdict.ok and verdict.result == "OK"

    def test_expect_pass_firing_is_wrong(self) -> None:
        # fizz v0.5.3 exits 0 on invariant failure — the WRONG case is exit 0.
        out = "FAILED: Model checker failed. Invariant:  FUS1_RealHasPatterns"
        verdict = _classify(_mutant(status="expect-pass"), 0, out)
        assert not verdict.ok and verdict.result == "WRONG"
