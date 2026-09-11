# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""mutmut baseline export + ratchet gate (L3, plan R2 / review fixes P-01+P-08).

`make test-mutations` historically recorded nothing: mutmut exits 0 even with
survivors, `mutmut results` is print-only, and `mutants/` (the per-mutant
`.meta` exit-code data) is gitignored scratch. The mutation layer therefore
had no record and no enforcement. This script closes both gaps:

1. ``--write <path>``  distill the LAST mutation run (mutants/src/*.meta +
                       mutants/mutmut-stats.json) into a committed baseline
                       JSON: per-module and per-function status counts,
                       survivor keys, run provenance (git commit + config
                       fingerprint), and the garden-class attestation (R7).
2. ``--gate``          recompute from the current scratch tree and compare
                       against the committed baseline (ratchet): any new
                       survivor key, any per-function kill-ratio drop beyond
                       ``ratio_tolerance``, or any newly unclassified function
                       fails the gate with exit 1. The baseline only moves via
                       the deliberate `make regen-mutmut-baseline`.

Status mapping mirrors upstream mutmut (mutmut/stats.py status_by_exit_code,
3.7.0). The script is toolchain-free: it reads the scratch `.meta` files that
`mutmut run` leaves behind and never imports mutmut.

Usage:
    uv run python scripts/mutmut_baseline.py --write verify/mutmut-baseline.json
    uv run python scripts/mutmut_baseline.py --gate
    uv run python scripts/mutmut_baseline.py --summary
"""

from __future__ import annotations

import argparse
import ast
import json
import tomllib
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRATCH_DIR = REPO_ROOT / "mutants"
DEFAULT_BASELINE = REPO_ROOT / "verify" / "mutmut-baseline.json"
DEFAULT_THRESHOLDS = REPO_ROOT / "verify" / "mutmut-thresholds.toml"
DEFAULT_GARDEN = REPO_ROOT / "tests" / "verification" / "gardens" / "bug_garden.py"

SCHEMA_VERSION = 1

# Mirror of upstream mutmut/stats.py::status_by_exit_code (3.7.0).
STATUS_BY_EXIT_CODE: dict[int | None, str] = {
    1: "killed",
    3: "killed",  # internal error in pytest counts as a kill
    0: "survived",
    5: "no tests",
    2: "interrupted",
    None: "not checked",
    33: "no tests",
    34: "skipped",
    35: "suspicious",
    36: "timeout",
    37: "caught by type check",
    -24: "timeout",
    24: "timeout",
    152: "timeout",
    255: "timeout",
    -11: "segfault",
    -9: "segfault",
}
DEFAULT_STATUS = "suspicious"

# Statuses that prove the test suite decided about the mutant (vs the mutant
# never being classified at all). The gate treats an unclassified function as
# a regression: it means the run died before reaching it.
CLASSIFIED: frozenset[str] = frozenset({"killed", "survived"})

# Garden bug class -> (module, function) anchors carrying that class in the
# production tree (plan R7 attestation: each hand-planted class must have at
# least one generated, classified mutmut mutant at an anchor function, else
# the two L3 layers have drifted apart). Anchors are semantic, NOT mutant-key
# based — mutmut's `__mutmut_<N>` indices shift on every source edit, so a
# committed key map would break per PR (review finding P-07).
GARDEN_CLASS_ANCHORS: dict[str, tuple[tuple[str, str], ...]] = {
    "off-by-one": (
        ("src/text_validation.py", "compute_strip_window"),
        ("src/design_normalization.py", "promote_api_contract_ids"),
    ),
    "none-deref": (
        ("src/text_validation.py", "_category_code"),
        ("src/design_normalization.py", "_select_first"),
    ),
    "unbounded-loop": (
        ("src/tools/jobs.py", "_guarded_update"),
    ),
    "shape-keyerror": (
        ("src/tools/jobs.py", "set_cancelled"),
        ("src/validation.py", "validate_with_retries"),
    ),
    "arithmetic-flip": (
        ("src/text_validation.py", "evaluate_printable_text"),
        ("src/config_expansion.py", "expand_env"),
    ),
    "boundary-tolerance": (
        ("src/validation.py", "format_validation_errors"),
        ("src/config_expansion.py", "expand_env_in_obj"),
    ),
}


class BaselineError(Exception):
    """Baseline/gate data defect — the gate must fail."""


@dataclass
class FunctionStats:
    """Status counts + survivor keys for one mangled function."""

    total: int = 0
    killed: int = 0
    survived: int = 0
    classified: int = 0
    other: int = 0
    kill_ratio: float | None = None
    survivor_keys: list[str] = field(default_factory=list)

    def add(self, status: str, key: str) -> None:
        self.total += 1
        if status == "survived":
            self.survivor_keys.append(key)
        if status in CLASSIFIED:
            self.classified += 1
            if status == "killed":
                self.killed += 1
            else:
                self.survived += 1
        else:
            self.other += 1

    def finalize(self) -> None:
        self.survivor_keys = sorted(self.survivor_keys)
        self.kill_ratio = (
            round(self.killed / self.classified, 4) if self.classified else None
        )

    def merged(self, other: FunctionStats) -> FunctionStats:
        combined = FunctionStats(
            total=self.total + other.total,
            killed=self.killed + other.killed,
            survived=self.survived + other.survived,
            classified=self.classified + other.classified,
            other=self.other + other.other,
            kill_ratio=None,
            survivor_keys=[*self.survivor_keys, *other.survivor_keys],
        )
        combined.finalize()
        return combined


@dataclass(frozen=True)
class Thresholds:
    """Ratchet parameters (verify/mutmut-thresholds.toml)."""

    ratio_tolerance: float = 0.02
    max_new_survivors: int = 0


@dataclass(frozen=True)
class AttestationEntry:
    """R7: per bug class, do classified mutants exist at the anchor functions?"""

    ok: bool
    anchors: list[str] = field(default_factory=list)
    mutants: int = 0
    killed: int = 0
    detail: str = ""


def status_for(exit_code: int | None) -> str:
    """Map a mutmut per-mutant exit code to its status label."""
    return STATUS_BY_EXIT_CODE.get(exit_code, DEFAULT_STATUS)


def parse_meta_file(path: Path) -> dict[str, int | None]:
    """Read one mutants/src/<module>.py.meta into {mutant_key: exit_code}."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    exit_codes = raw.get("exit_code_by_key")
    if not isinstance(exit_codes, dict):
        raise BaselineError(f"{path}: missing exit_code_by_key mapping")
    return exit_codes


def mangled_to_function(mangled: str) -> str:
    """Strip mutmut 3.7's trampoline mangling down to the function name.

    Plain functions get the literal prefix ``x_`` (``x__category_code`` is
    ``_category_code``; ``x_promote_api_contract_ids`` is
    ``promote_api_contract_ids`` — the prefix round-trips original names that
    themselves start with ``x_``). Methods are named ``xǁClsǁ<name>`` — after
    the ǁ->. rewrite the marker is the standalone ``x`` segment.
    """
    base = mangled.split("__mutmut_", 1)[0]
    if "ǁ" in base:
        base = base.replace("ǁ", ".")
        parts = [part for part in base.split(".") if part != "x"]
        return ".".join(parts)
    parts = base.split(".")
    if parts and parts[-1].startswith("x_"):
        parts[-1] = parts[-1][2:]
    return ".".join(parts)


def summarize_pair(key: str, exit_code: int | None) -> FunctionStats:
    stats = FunctionStats()
    stats.add(status_for(exit_code), key)
    return stats


def module_label_for(meta: Path, scratch_dir: Path) -> str:
    """``mutants/src/tools/jobs.py.meta`` -> ``src/tools/jobs.py`` (the anchor
    module path mutmut's keys are prefixed with — nested dirs included)."""
    relative = meta.relative_to(scratch_dir).with_suffix("")  # src/tools/jobs.py
    return relative.as_posix()


def collect_scratch(
    scratch_dir: Path = SCRATCH_DIR,
) -> tuple[dict[str, FunctionStats], dict[str, str | None]]:
    """Read every mutated module's .meta file from the scratch tree.

    Returns (functions, run_info): functions maps ``<module.py>::<function>``
    to merged FunctionStats; run_info carries provenance from
    mutmut-stats.json when present.
    """
    meta_files = sorted(scratch_dir.glob("src/**/*.meta"))
    if not meta_files:
        raise BaselineError(
            f"{scratch_dir}/src/**/*.meta: no mutmut scratch data — run "
            "`make test-mutations` first (mutmut run writes the .meta files)"
        )
    functions: dict[str, FunctionStats] = {}
    for meta in meta_files:
        module = module_label_for(meta, scratch_dir)
        for key, code in parse_meta_file(meta).items():
            bare = mangled_to_function(key).rsplit(".", 1)[-1]
            label = f"{module}::{bare}"
            entry = summarize_pair(key, code)
            functions[label] = (
                entry if label not in functions else functions[label].merged(entry)
            )
    for stats in functions.values():
        stats.finalize()
    run_info: dict[str, str | None] = {"scratch_dir": str(scratch_dir)}
    stats_path = scratch_dir / "mutmut-stats.json"
    if stats_path.exists():
        stats_json = json.loads(stats_path.read_text(encoding="utf-8"))
        run_info["git_commit"] = stats_json.get("git_commit")
        run_info["config_fingerprint"] = stats_json.get("config_fingerprint")
        run_info["stats_time"] = stats_json.get("stats_time")
    return functions, run_info


def module_of_label(label: str) -> str:
    """``src/text_validation.py::fn`` -> ``src/text_validation.py``."""
    return label.split("::", 1)[0]


def module_summaries(functions: dict[str, FunctionStats]) -> dict[str, dict[str, float | int | None]]:
    """Aggregate per-function stats by module path."""
    totals: dict[str, FunctionStats] = defaultdict(FunctionStats)
    for label, stats in functions.items():
        module = module_of_label(label)
        totals[module] = totals[module].merged(stats)
    return {
        module: {
            "total": stats.total,
            "killed": stats.killed,
            "survived": stats.survived,
            "classified": stats.classified,
            "kill_ratio": stats.kill_ratio,
        }
        for module, stats in sorted(totals.items())
    }


def garden_classes(garden_path: Path) -> set[str]:
    """Bug classes declared in the garden's MUTANTS registry (no import)."""
    tree = ast.parse(garden_path.read_text(encoding="utf-8"))
    classes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        first, second = node.args[0], node.args[1]
        if (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and first.value.startswith("M-")
            and isinstance(second, ast.Constant)
            and isinstance(second.value, str)
        ):
            classes.add(second.value)
    return classes


def garden_attestation(
    functions: dict[str, FunctionStats],
    garden_path: Path = DEFAULT_GARDEN,
) -> dict[str, AttestationEntry]:
    """R7: per bug class, do classified mutants exist at the anchor functions?

    The class ID set is read live from the garden (MUTANTS registry) so a new
    garden class without an anchor entry fails the attestation instead of
    passing vacuously.
    """
    by_anchor: dict[tuple[str, str], FunctionStats] = {}
    for label, stats in functions.items():
        module = module_of_label(label)
        bare = label.split("::", 1)[1]
        by_anchor[(module, bare)] = stats
    attestation: dict[str, AttestationEntry] = {}
    for bug_class in sorted(garden_classes(garden_path)):
        anchors = GARDEN_CLASS_ANCHORS.get(bug_class)
        if not anchors:
            attestation[bug_class] = AttestationEntry(
                ok=False, detail="no anchor mapping — add a GARDEN_CLASS_ANCHORS entry"
            )
            continue
        mutants = sum(by_anchor[a].total for a in anchors if a in by_anchor)
        killed = sum(by_anchor[a].killed for a in anchors if a in by_anchor)
        classified_present = any(
            by_anchor[a].classified > 0 for a in anchors if a in by_anchor
        )
        attestation[bug_class] = AttestationEntry(
            ok=mutants > 0 and classified_present,
            anchors=[f"{m}::{f}" for m, f in anchors],
            mutants=mutants,
            killed=killed,
            detail="" if classified_present else "no classified mutants at anchors",
        )
    return attestation


def load_thresholds(path: Path) -> Thresholds:
    """Read verify/mutmut-thresholds.toml (ratchet parameters)."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return Thresholds(
        ratio_tolerance=float(raw.get("ratio_tolerance", 0.02)),
        max_new_survivors=int(raw.get("max_new_survivors", 0)),
    )


def gate(
    baseline_functions: dict[str, FunctionStats],
    current: dict[str, FunctionStats],
    thresholds: Thresholds,
) -> list[str]:
    """Ratchet comparison: current run vs the committed baseline.

    Fails on (a) any new survivor key, (b) a per-function kill ratio that
    dropped by more than ``ratio_tolerance``, (c) a function that was fully
    classified in the baseline but is unclassified now. Improvements never
    fail the gate — the baseline moves only via regen-mutmut-baseline.
    """
    failures: list[str] = []
    modules_seen = {module_of_label(label) for label in current}
    for label, base in sorted(baseline_functions.items()):
        cur = current.get(label)
        if cur is None:
            # A vanished function whose module still reports data is a
            # legitimate deletion (function removed from src) — informational
            # only; the ratchet floor shrinks at the next regen. A vanished
            # MODULE means the run died before reaching it — a regression.
            if module_of_label(label) not in modules_seen:
                failures.append(
                    f"MISSING-MODULE: {module_of_label(label)} has no classified "
                    "data in the current run (run died early or module left scope)"
                )
            continue
        new_survivors = sorted(set(cur.survivor_keys) - set(base.survivor_keys))
        if len(new_survivors) > thresholds.max_new_survivors:
            failures.append(
                f"NEW-SURVIVOR: {label}: {len(new_survivors)} new survivor(s): "
                f"{new_survivors[:5]}"
            )
        if (
            base.kill_ratio is not None
            and cur.kill_ratio is not None
            and cur.kill_ratio < base.kill_ratio - thresholds.ratio_tolerance
        ):
            failures.append(
                f"RATIO-DROP: {label}: kill_ratio {cur.kill_ratio} < baseline "
                f"{base.kill_ratio} (tolerance {thresholds.ratio_tolerance})"
            )
        if base.classified > 0 and cur.classified == 0:
            failures.append(f"UNCLASSIFIED: {label}: no mutant classified in current run")
    new_functions = sorted(set(current) - set(baseline_functions))
    if new_functions:
        # New functions under mutation are information, not regressions —
        # they enter the ratchet at the next deliberate regen.
        print(
            f"note: {len(new_functions)} new function(s) will join the baseline "
            "at the next regen-mutmut-baseline"
        )
    return failures


def build_baseline_document(
    functions: dict[str, FunctionStats],
    run_info: dict[str, str | None],
) -> dict[str, object]:
    totals: dict[str, int] = defaultdict(int)
    for stats in functions.values():
        totals["total"] += stats.total
        totals["killed"] += stats.killed
        totals["survived"] += stats.survived
        totals["classified"] += stats.classified
    return {
        "schema": SCHEMA_VERSION,
        "totals": dict(totals),
        "run": run_info,
        "modules": module_summaries(functions),
        "functions": {label: asdict(stats) for label, stats in sorted(functions.items())},
    }


def functions_from_json(raw: object) -> dict[str, FunctionStats]:
    """Decode the baseline document's functions mapping (schema-checked)."""
    if not isinstance(raw, dict):
        raise BaselineError("baseline 'functions' must be an object")
    out: dict[str, FunctionStats] = {}
    for label, entry in raw.items():
        if not isinstance(entry, dict):
            raise BaselineError(f"baseline function {label!r}: entry must be an object")
        try:
            out[str(label)] = FunctionStats(
                total=int(entry["total"]),
                killed=int(entry["killed"]),
                survived=int(entry["survived"]),
                classified=int(entry["classified"]),
                other=int(entry["other"]),
                kill_ratio=entry["kill_ratio"],
                survivor_keys=[str(k) for k in entry["survivor_keys"]],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BaselineError(f"baseline function {label!r}: malformed entry ({exc})") from exc
    return out


def print_summary(document: dict[str, object]) -> None:
    totals = document["totals"]
    if isinstance(totals, dict):
        print(
            f"mutmut baseline: {totals.get('total')} mutants, "
            f"{totals.get('killed')} killed, {totals.get('survived')} survived, "
            f"unclassified {totals.get('total', 0) - totals.get('classified', 0)}"
        )
    modules = document.get("modules")
    if isinstance(modules, dict):
        print(f"{'module':40} {'total':>6} {'killed':>7} {'surv':>5} {'ratio':>7}")
        for module, entry in sorted(modules.items()):
            if not isinstance(entry, dict):
                continue
            ratio = entry.get("kill_ratio")
            ratio_text = f"{ratio:.4f}" if isinstance(ratio, float) else "-"
            print(
                f"{module:40} {entry.get('total', 0):>6} {entry.get('killed', 0):>7} "
                f"{entry.get('survived', 0):>5} {ratio_text:>7}"
            )
    attestation = document.get("garden_attestation")
    if isinstance(attestation, dict):
        for bug_class, entry in sorted(attestation.items()):
            if not isinstance(entry, dict):
                continue
            mark = "ok" if entry.get("ok") else "FAIL"
            print(
                f"garden {bug_class:20} {mark} "
                f"({entry.get('killed', 0)}/{entry.get('mutants', 0)} killed)"
            )


def write_refusal_reason(totals: dict[str, object], force: bool) -> str | None:
    """Guard against recording a garbage floor (e.g. from an aborted run whose
    config-invalidation pass nulled every exit code)."""
    if force:
        return None
    total = totals.get("total", 0)
    classified = totals.get("classified", 0)
    if not isinstance(total, int) or not isinstance(classified, int):
        return "baseline totals are malformed (non-integer counts)"
    if total == 0 or classified < total // 2:
        return (
            f"only {classified}/{total} mutants are classified — the scratch "
            "tree is from an aborted or invalidated run (a config change nulls "
            "cached exit codes). Run `make test-mutations` first, or pass "
            "--force to record anyway (records a garbage floor)."
        )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write",
        type=Path,
        metavar="PATH",
        help="write a fresh baseline document to PATH (deliberate regen)",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="compare the current scratch run against the committed baseline",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help=f"baseline path (default: {DEFAULT_BASELINE.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=DEFAULT_THRESHOLDS,
        help=f"thresholds path (default: {DEFAULT_THRESHOLDS.relative_to(REPO_ROOT)})",
    )
    parser.add_argument("--summary", action="store_true", help="print the document summary and exit")
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow --write even when most mutants are unclassified (dangerous: "
        "records a garbage floor; the normal cause is an aborted/invalidated run)",
    )
    args = parser.parse_args(argv)

    functions, run_info = collect_scratch()
    document = build_baseline_document(functions, run_info)
    document["garden_attestation"] = {
        bug_class: asdict(entry)
        for bug_class, entry in garden_attestation(functions).items()
    }

    if args.write is not None:
        totals = document["totals"]
        assert isinstance(totals, dict)
        refusal = write_refusal_reason(totals, args.force)
        if refusal is not None:
            print(f"REFUSED: {refusal}")
            return 1
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"wrote baseline: {args.write}")
        print_summary(document)
        return 0

    if args.summary:
        print_summary(document)
        return 0

    if args.gate:
        if not args.baseline.exists():
            print(f"GATE FAIL: baseline missing: {args.baseline}")
            return 1
        baseline_doc = json.loads(args.baseline.read_text(encoding="utf-8"))
        thresholds = (
            load_thresholds(args.thresholds) if args.thresholds.exists() else Thresholds()
        )
        failures = gate(functions_from_json(baseline_doc.get("functions")), functions, thresholds)
        attestation = garden_attestation(functions)
        for bug_class, entry in sorted(attestation.items()):
            if not entry.ok:
                failures.append(
                    f"GARDEN-DRIFT: class {bug_class}: {entry.detail or 'no classified mutants at anchors'}"
                )
        if failures:
            print("MUTMUT GATE FAILURES:")
            for failure in failures:
                print(f"  - {failure}")
            print(
                "\nFix the test suite (kill the survivors) or, for documented "
                "equivalents, acknowledge them and refresh deliberately:\n"
                "  make regen-mutmut-baseline"
            )
            return 1
        print("mutmut gate: no regressions against the committed baseline")
        return 0

    parser.error("nothing to do: pass --write, --gate, or --summary")
    raise AssertionError("unreachable: parser.error exits the process")


if __name__ == "__main__":
    raise SystemExit(main())
