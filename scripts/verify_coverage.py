# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
Contract-coverage report for the Nagini verification set
(nagini-verification-plan.md §6.3; formal_verification.md §4.5.6).

Lists every file in NAGINI_FILES with its functions split into
"explicit-contract" (Requires/Ensures/Exsures/Invariant calls or
@Pure/@Predicate decorators present) vs "default-safety-only" — keeping the
5-10% scope decision and its coverage visible in CI.

Usage:
  python scripts/verify_coverage.py            # human-readable report, exit 0
  python scripts/verify_coverage.py --files    # print NAGINI_FILES (for Make)
"""

import argparse
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The verification set: pure cores in src/ (contract-ready) + the sync twins.
# Scope discipline: the critical ~5-10% of modules, never the whole tree.
NAGINI_FILES: tuple[str, ...] = (
    "src/text_validation_core.py",
    "src/design_normalization_core.py",
    "verify/twin/jobs_state_twin.py",
    "verify/twin/pipeline_control_twin.py",
)

CONTRACT_CALLS = {"Requires", "Ensures", "Exsures", "Invariant", "Assert", "Assume"}
CONTRACT_DECORATORS = {"Pure", "Predicate", "Inline", "Opaque"}


def _function_names(tree: ast.AST) -> list[tuple[str, bool]]:
    """(qualified name, has_explicit_contracts) per function/method."""
    out: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names_in_body = {
            n.func.id
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        decorator_names = {
            d.id for d in node.decorator_list if isinstance(d, ast.Name)
        }
        has_contracts = bool(names_in_body & CONTRACT_CALLS) or bool(
            decorator_names & CONTRACT_DECORATORS
        )
        out.append((node.name, has_contracts))
    return out


def report() -> str:
    lines: list[str] = ["NAGINI_FILES contract coverage", "=" * 40]
    total = 0
    with_contracts = 0
    for rel in NAGINI_FILES:
        path = REPO_ROOT / rel
        if not path.exists():
            lines.append(f"\n{rel}: MISSING")
            continue
        funcs = _function_names(ast.parse(path.read_text(encoding="utf-8")))
        covered = [name for name, has in funcs if has]
        total += len(funcs)
        with_contracts += len(covered)
        lines.append(
            f"\n{rel}: {len(funcs)} functions, {len(covered)} with explicit contracts"
        )
        for name, has in funcs:
            marker = "contracts" if has else "default-safety-only"
            lines.append(f"  - {name}: {marker}")
    if total:
        lines.append(
            f"\nTotal: {with_contracts}/{total} functions carry explicit contracts"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", action="store_true", help="print NAGINI_FILES")
    args = parser.parse_args()
    if args.files:
        for rel in NAGINI_FILES:
            print(rel)
        return 0
    print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
