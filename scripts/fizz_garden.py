# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""FizzBee spec-garden mechanical revalidator (L3/L4, AGENTS.md vacuity rule).

`verify/fizz/garden.toml` is the machine-executable twin of the "Spec garden"
table in `verify/fizz/README.md`. For every FG-* row this script

1. checks 1:1 ID agreement between garden.toml and the README table, and that
   each expect-fail row's assertion name appears in the README row it belongs to;
2. checks the AGENTS.md assertion-coverage rule: every ``always`` /
   ``always eventually`` assertion in every spec must be the documented kill
   target of at least one expect-fail row OR carry a ``# spec-explains:``
   justification in its spec comment;
3. checks anchor health: every mutation op matches EXACTLY ONCE and changes
   the spec text — a silent no-op (stale anchor after a spec edit) is a gate
   failure, never a vacuous green;
4. for each executable mutant (expect-fail / expect-pass), applies the
   mutation to a HERMETIC TEMP COPY (never the working tree — the fizz gate
   convention from scripts/fizz-check.sh) and requires the documented
   outcome from an exhaustive fizz run.

Outcome semantics per expect-fail mutant:
- KILLED        the documented assertion (or a calibrated alias) fired, or the
                run deadlocked, or the checker panicked mid-run (FG-03's
                documented missing-key kill mode);
- SURVIVED      the mutated spec still PASSED — vacuous assertion, gate fails;
- INCONCLUSIVE  the action budget was exhausted without a verdict — treated as
                a failure (a mutant that cannot decide proves nothing);
- BROKEN        the mutation produced an unparseable spec — a garden bug,
                gate fails;
- WRONG         the run failed on an assertion outside expected ∪ aliases.

Usage:
    uv run python scripts/fizz_garden.py --check-only          # no toolchain
    uv run python scripts/fizz_garden.py --specs verify/fizz   # full revalidation
    uv run python scripts/fizz_garden.py --only FG-01,FG-32    # subset
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GARDEN = REPO_ROOT / "verify/fizz/garden.toml"
DEFAULT_SPECS = REPO_ROOT / "verify/fizz"
DEFAULT_README = REPO_ROOT / "verify/fizz/README.md"

PASSED_MARKER = "PASSED: Model checker completed successfully"
DEADLOCK_MARKER = "DEADLOCK detected"
STOPPED_MARKER = "Model checker stopped"
RUNNING_MARKER = "Model checking"
INVARIANT_RE = re.compile(r"Invariant:\s*(\w+)")
DECLARATION_RE = re.compile(
    r"^(?P<kind>always( eventually)?|eventually always|exists)\s+assertion\s+(?P<name>\w+):"
)
README_ROW_RE = re.compile(r"^\|\s*(FG-\d+)\s*\|(.+)\|\s*$")
FRONTMATTER_BUDGET_RE = re.compile(r"^  max_actions:\s*\d+.*$", re.MULTILINE)

EXECUTABLE_STATUSES = ("expect-fail", "expect-pass")


class GardenError(Exception):
    """A garden-table, anchor, or coverage defect — the gate must fail."""


@dataclass(frozen=True)
class Op:
    """One text mutation: replace a unique substring or delete its line."""

    kind: str  # "replace" | "delete_line"
    find: str
    replace: str = ""


@dataclass(frozen=True)
class Mutant:
    """One FG-* garden row (machine ledger verify/fizz/garden.toml)."""

    id: str
    spec: str
    status: str  # expect-fail | expect-pass | retired | killed-elsewhere
    assertion: str
    ops: tuple[Op, ...]
    aliases: tuple[str, ...] = ()
    max_actions: int = 0  # 0 = suite default (fizz.yaml)
    timeout_s: int = 300
    note: str = ""


@dataclass
class Outcome:
    """The classified result of one mutant's fizz run (or pre-check)."""

    mutant_id: str
    spec: str
    status: str
    ok: bool
    result: str  # KILLED | SURVIVED | INCONCLUSIVE | BROKEN | WRONG | OK | SKIPPED
    detail: str = ""
    skipped: bool = field(default=False, repr=False)


def load_garden(path: Path) -> list[Mutant]:
    """Parse verify/fizz/garden.toml into validated Mutant records."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    mutants: list[Mutant] = []
    for entry in raw.get("mutant", []):
        ops = tuple(Op(kind=o["kind"], find=o["find"], replace=o.get("replace", "")) for o in entry.get("ops", []))
        mutant = Mutant(
            id=entry["id"],
            spec=entry["spec"],
            status=entry["status"],
            assertion=entry.get("assertion", ""),
            ops=ops,
            aliases=tuple(entry.get("aliases", ())),
            max_actions=int(entry.get("max_actions", 0)),
            timeout_s=int(entry.get("timeout_s", 300)),
            note=entry.get("note", ""),
        )
        _validate_mutant(mutant)
        mutants.append(mutant)
    if not mutants:
        raise GardenError(f"{path}: no [[mutant]] entries")
    ids = [m.id for m in mutants]
    if len(set(ids)) != len(ids):
        raise GardenError(f"{path}: duplicate mutant IDs")
    return mutants


def _validate_mutant(mutant: Mutant) -> None:
    if mutant.status not in (*EXECUTABLE_STATUSES, "retired", "killed-elsewhere"):
        raise GardenError(f"{mutant.id}: unknown status {mutant.status!r}")
    if mutant.status in EXECUTABLE_STATUSES:
        if not mutant.ops:
            raise GardenError(f"{mutant.id}: executable mutant has no ops")
        for op in mutant.ops:
            if op.kind not in ("replace", "delete_line"):
                raise GardenError(f"{mutant.id}: unknown op kind {op.kind!r}")
            if op.kind == "replace" and op.find == op.replace:
                raise GardenError(f"{mutant.id}: replace op is a no-op")
            if "\n" in op.find and op.kind == "delete_line":
                raise GardenError(f"{mutant.id}: delete_line anchor must be single-line")
        if mutant.status == "expect-fail" and not mutant.assertion:
            raise GardenError(f"{mutant.id}: expect-fail row without an expected assertion")
    elif mutant.ops:
        raise GardenError(f"{mutant.id}: {mutant.status} row must not carry ops")


def parse_readme_garden(readme: Path) -> dict[str, str]:
    """Return {FG-ID: assertion-cell text} from the README spec-garden table."""
    section = re.split(r"^## Spec garden", readme.read_text(encoding="utf-8"), maxsplit=1, flags=re.MULTILINE)
    if len(section) < 2:
        raise GardenError(f"{readme}: no '## Spec garden' section")
    body = re.split(r"^## ", section[1], maxsplit=1, flags=re.MULTILINE)[0]
    rows: dict[str, str] = {}
    for line in body.splitlines():
        match = README_ROW_RE.match(line)
        if match:
            # Row layout: | ID | mutated element | assertion that must fire |
            columns = [c.strip() for c in match.group(2).split("|")]
            rows[match.group(1)] = columns[1] if len(columns) > 1 else ""
    if not rows:
        raise GardenError(f"{readme}: spec-garden table has no FG-* rows")
    return rows


def parse_assertions(spec_text: str) -> list[tuple[str, str, int]]:
    """Return (kind, name, line_index) for every assertion declaration."""
    found: list[tuple[str, str, int]] = []
    for i, line in enumerate(spec_text.splitlines()):
        match = DECLARATION_RE.match(line)
        if match:
            found.append((match.group("kind"), match.group("name"), i))
    return found


def has_spec_explains(spec_text: str, decl_line: int) -> bool:
    """True if a ``# spec-explains:`` marker sits in the assertion's comment block.

    The window is the run of comment/blank lines immediately after the
    declaration (the assertion's justification comment precedes its body).
    """
    lines = spec_text.splitlines()
    for line in lines[decl_line + 1 : decl_line + 20]:
        stripped = line.strip()
        if stripped.startswith("#"):
            if "spec-explains" in stripped:
                return True
        elif stripped:
            break
    return False


def consistency_errors(
    mutants: list[Mutant], readme_rows: dict[str, str]
) -> list[str]:
    """1:1 ID agreement README<->garden.toml + assertion-cell agreement."""
    errors: list[str] = []
    garden_ids = {m.id for m in mutants}
    readme_ids = set(readme_rows)
    for missing in sorted(readme_ids - garden_ids):
        errors.append(f"CONSISTENCY: {missing} in README garden table but not in garden.toml")
    for missing in sorted(garden_ids - readme_ids):
        errors.append(f"CONSISTENCY: {missing} in garden.toml but not in README garden table")
    for mutant in mutants:
        if mutant.status != "expect-fail":
            continue
        cell = readme_rows.get(mutant.id, "")
        if mutant.assertion not in cell:
            errors.append(
                f"CONSISTENCY: {mutant.id} expects {mutant.assertion} but the README "
                f"row does not name it: {cell!r}"
            )
    return errors


def coverage_errors(mutants: list[Mutant], specs_dir: Path) -> list[str]:
    """AGENTS.md rule: every always/always-eventually assertion kills >= 1
    garden mutant or carries ``# spec-explains:`` in its spec comment."""
    errors: list[str] = []
    kill_targets: set[str] = set()
    for m in mutants:
        if m.status == "expect-fail":
            kill_targets.update((m.assertion, *m.aliases))
    kill_targets.discard("")
    for spec_path in sorted(specs_dir.glob("*.fizz")):
        text = spec_path.read_text(encoding="utf-8")
        for kind, name, line_no in parse_assertions(text):
            if kind not in ("always", "always eventually"):
                continue
            if name in kill_targets:
                continue
            if has_spec_explains(text, line_no):
                continue
            errors.append(
                f"COVERAGE: {spec_path.name}::{name} ({kind}) has no expect-fail garden "
                f"row and no '# spec-explains:' justification"
            )
    # Reverse guard: expected assertions and aliases must actually be declared.
    declared: dict[str, set[str]] = {}
    for spec_path in sorted(specs_dir.glob("*.fizz")):
        text = spec_path.read_text(encoding="utf-8")
        declared[spec_path.stem] = {name for _, name, _ in parse_assertions(text)}
    for mutant in mutants:
        if mutant.status != "expect-fail":
            continue
        names = declared.get(mutant.spec, set())
        for target in (mutant.assertion, *mutant.aliases):
            if target not in names:
                errors.append(
                    f"COVERAGE: {mutant.id} expects {target!r} which is not declared in {mutant.spec}.fizz"
                )
    return errors


def apply_ops(mutant: Mutant, text: str) -> str:
    """Apply the mutation ops; raise on anchor drift or a no-op result."""
    current = text
    for op in mutant.ops:
        occurrences = current.count(op.find)
        if occurrences != 1:
            raise GardenError(
                f"{mutant.id}: anchor occurs {occurrences}x (expected exactly 1): {op.find[:70]!r}"
            )
        if op.kind == "replace":
            current = current.replace(op.find, op.replace)
        else:
            lines = current.splitlines(keepends=True)
            indices = [i for i, line in enumerate(lines) if op.find in line]
            del lines[indices[0]]
            current = "".join(lines)
    if current == text:
        raise GardenError(f"{mutant.id}: mutation produced no change (stale anchor / vacuous mutant)")
    return current


def anchor_errors(mutants: list[Mutant], specs_dir: Path) -> list[str]:
    """In-memory dry run of every executable mutant's ops (no toolchain)."""
    errors: list[str] = []
    texts = {p.stem: p.read_text(encoding="utf-8") for p in sorted(specs_dir.glob("*.fizz"))}
    for mutant in mutants:
        if mutant.status not in EXECUTABLE_STATUSES:
            continue
        text = texts.get(mutant.spec)
        if text is None:
            errors.append(f"ANCHOR: {mutant.id}: spec {mutant.spec}.fizz not found in {specs_dir}")
            continue
        try:
            apply_ops(mutant, text)
        except GardenError as exc:
            errors.append(f"ANCHOR: {exc}")
    return errors


def _override_budget(spec_text: str, max_actions: int) -> tuple[str, bool]:
    """Rewrite the options-level max_actions in a spec frontmatter / fizz.yaml."""
    def sub(match: re.Match[str]) -> str:
        prefix = match.group(0)
        return re.sub(r"\d+", str(max_actions), prefix, count=1)

    patched, count = FRONTMATTER_BUDGET_RE.subn(sub, spec_text, count=1)
    return patched, count > 0


def run_mutant(mutant: Mutant, specs_dir: Path, fizz_bin: str) -> Outcome:
    """Apply the mutant to a hermetic temp copy and classify the fizz verdict."""
    base = Outcome(mutant_id=mutant.id, spec=mutant.spec, status=mutant.status, ok=False, result="")
    original = (specs_dir / f"{mutant.spec}.fizz").read_text(encoding="utf-8")
    tmpdir = Path(tempfile.mkdtemp(prefix=".fizz-garden-", dir=specs_dir))
    try:
        for fizz_file in sorted(specs_dir.glob("*.fizz")):
            shutil.copy(fizz_file, tmpdir / fizz_file.name)
        shutil.copy(specs_dir / "fizz.yaml", tmpdir / "fizz.yaml")
        mutated = apply_ops(mutant, original)
        budget_applied = False
        if mutant.max_actions:
            mutated, frontmatter_changed = _override_budget(mutated, mutant.max_actions)
            yaml_path = tmpdir / "fizz.yaml"
            yaml_text = yaml_path.read_text(encoding="utf-8")
            yaml_patched, yaml_changed = _override_budget(yaml_text, mutant.max_actions)
            if yaml_changed:
                yaml_path.write_text(yaml_patched, encoding="utf-8")
            budget_applied = frontmatter_changed or yaml_changed
            if not budget_applied:
                base.result = "BROKEN"
                base.detail = f"max_actions={mutant.max_actions} override found no target"
                return base
        (tmpdir / f"{mutant.spec}.fizz").write_text(mutated, encoding="utf-8")
        try:
            proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
                [fizz_bin, f"{mutant.spec}.fizz"],
                capture_output=True,
                text=True,
                timeout=mutant.timeout_s,
                cwd=tmpdir,
                check=False,
            )
        except subprocess.TimeoutExpired:
            base.result = "INCONCLUSIVE"
            base.detail = f"fizz timed out after {mutant.timeout_s}s"
            return base
        return _classify(mutant, proc.returncode, proc.stdout + proc.stderr)
    except GardenError as exc:
        base.result = "BROKEN"
        base.detail = str(exc)
        return base
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _classify_expect_pass(
    mutant: Mutant, exit_code: int, passed: bool, ran: bool, fired: tuple[str, ...], deadlock: bool
) -> Outcome:
    base = Outcome(mutant_id=mutant.id, spec=mutant.spec, status=mutant.status, ok=False, result="")
    if passed and exit_code == 0:
        base.ok, base.result = True, "OK"
        base.detail = "mutation applied, spec still PASSED (expected: nothing fires)"
        return base
    if exit_code != 0 and not ran:
        base.result = "BROKEN"
        base.detail = "mutated spec failed to compile"
        return base
    base.result = "WRONG"
    base.detail = f"expect-pass mutant fired: invariants={fired} deadlock={deadlock}"
    return base


def _failed(base: Outcome, result: str, detail: str) -> Outcome:
    base.result, base.detail = result, detail
    return base


def _classify_expect_fail(
    mutant: Mutant,
    exit_code: int,
    passed: bool,
    ran: bool,
    stopped: bool,
    fired: tuple[str, ...],
    deadlock: bool,
) -> Outcome:
    base = Outcome(mutant_id=mutant.id, spec=mutant.spec, status=mutant.status, ok=False, result="")
    accepted = {mutant.assertion, *mutant.aliases} - {""}
    if passed and exit_code == 0:
        return _failed(base, "SURVIVED", "mutated spec PASSED — the documented assertion is vacuous")
    kill_reason = ""
    if accepted & set(fired):
        kill_reason = f"invariant fired: {', '.join(f for f in fired if f in accepted)}"
    elif deadlock:
        kill_reason = "mutated model deadlocked (documented deadlock kill mode)"
    elif exit_code != 0 and ran:
        kill_reason = "checker panicked mid-run (documented panic kill mode, e.g. FG-03)"
    if kill_reason:
        base.ok, base.result, base.detail = True, "KILLED", kill_reason
        return base
    if exit_code != 0:
        return _failed(base, "BROKEN", "mutated spec failed to compile")
    if stopped:
        return _failed(base, "INCONCLUSIVE", "action budget exhausted without a verdict")
    return _failed(base, "WRONG", f"failed on undocumented invariant(s): {fired or 'none'}")


def _classify(mutant: Mutant, exit_code: int, output: str) -> Outcome:
    """Map a fizz run to the five-outcome semantics (module docstring)."""
    passed = PASSED_MARKER in output
    fired = tuple(dict.fromkeys(INVARIANT_RE.findall(output)))
    deadlock = DEADLOCK_MARKER in output
    stopped = STOPPED_MARKER in output
    ran = RUNNING_MARKER in output
    if mutant.status == "expect-pass":
        return _classify_expect_pass(mutant, exit_code, passed, ran, fired, deadlock)
    return _classify_expect_fail(mutant, exit_code, passed, ran, stopped, fired, deadlock)


def _print_outcomes(outcomes: list[Outcome]) -> None:
    print(f"{'ID':7} {'spec':18} {'status':16} {'result':12} detail")
    for o in outcomes:
        print(f"{o.mutant_id:7} {o.spec:18} {o.status:16} {o.result:12} {o.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--garden", type=Path, default=DEFAULT_GARDEN, help="garden.toml path")
    parser.add_argument("--specs", type=Path, default=DEFAULT_SPECS, help="directory holding the .fizz specs")
    parser.add_argument("--readme", type=Path, default=DEFAULT_README, help="ledger README with the garden table")
    parser.add_argument("--fizz-bin", default="fizz", help="fizz binary (default: fizz)")
    parser.add_argument("--only", default="", help="comma-separated FG-IDs to run (default: all)")
    parser.add_argument("--check-only", action="store_true", help="consistency + coverage + anchors, no fizz run")
    parser.add_argument("--list", action="store_true", help="list the garden table and exit")
    args = parser.parse_args(argv)

    mutants = load_garden(args.garden)
    readme_rows = parse_readme_garden(args.readme)

    if args.list:
        for m in mutants:
            targets = ", ".join(t for t in (m.assertion, *m.aliases) if t) or "-"
            print(f"{m.id:7} {m.spec:18} {m.status:16} targets={targets} ops={len(m.ops)}")
        return 0

    errors = consistency_errors(mutants, readme_rows)
    errors += coverage_errors(mutants, args.specs)
    errors += anchor_errors(mutants, args.specs)
    if errors:
        print("SPEC-GARDEN DEFECTS DETECTED:")
        for error in errors:
            print(f"  - {error}")
        return 1

    executable_count = sum(1 for m in mutants if m.status in EXECUTABLE_STATUSES)
    if args.check_only:
        print(
            f"check-only: garden consistent ({len(mutants)} rows, {executable_count} executable); "
            "consistency + coverage + anchor checks passed"
        )
        return 0

    selected = mutants
    if args.only:
        wanted = {part.strip() for part in args.only.split(",") if part.strip()}
        selected = [m for m in mutants if m.id in wanted]

    executable = [m for m in selected if m.status in EXECUTABLE_STATUSES]
    skipped = [m for m in selected if m.status not in EXECUTABLE_STATUSES]
    outcomes = [Outcome(m.id, m.spec, m.status, True, "SKIPPED", f"{m.status} ({m.note[:60]})", skipped=True) for m in skipped]
    print(f">> revalidating {len(executable)} executable garden mutants "
          f"({len(skipped)} skipped: retired/killed-elsewhere)")
    for mutant in executable:
        outcome = run_mutant(mutant, args.specs, args.fizz_bin)
        outcomes.append(outcome)
        flag = "ok" if outcome.ok else "FAIL"
        print(f">> {mutant.id}: {outcome.result} [{flag}] {outcome.detail}", flush=True)

    _print_outcomes(outcomes)
    failures = [o for o in outcomes if not o.ok]
    if failures:
        print(f"\nverify-fizz-garden: FAILED ({len(failures)} of {len(outcomes)} rows unexpected)")
        return 1
    print(f"\nverify-fizz-garden: all {len(outcomes)} garden rows behaved as documented")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
