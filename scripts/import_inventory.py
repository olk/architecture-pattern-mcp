# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
Import-inventory generator (testing-strategies.md §3.8, L7 supply-chain).

Mechanizes the review rule "import-inventory diff for any new third-party
import": walking src/ (+ verify/) with ast, collecting top-level import
names, subtracting stdlib and first-party modules, and printing the sorted
inventory. `make verify-import-inventory` regenerates this listing and diffs
it against the checked-in snapshot — drift fails the target and forces the
review decision (typed lib? stub available? allowlist?), the structural
slopsquatting defence: new package names need a human decision, not a scan.

Usage:
  python scripts/import_inventory.py                 # print inventory
  python scripts/import_inventory.py --check FILE    # exit 1 if FILE differs
"""

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("src", "verify")
FIRST_PARTY = {"src", "verify"}


def _top_level_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def inventory() -> list[str]:
    stdlib = set(sys.stdlib_module_names)
    third_party: set[str] = set()
    for scan_dir in SCAN_DIRS:
        for path in (REPO_ROOT / scan_dir).rglob("*.py"):
            imports = _top_level_imports(path)
            third_party |= imports - stdlib - FIRST_PARTY
    return sorted(third_party)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", type=Path, help="diff against a snapshot file")
    args = parser.parse_args()

    current = "\n".join(inventory()) + "\n"
    if args.check is None:
        print(current, end="")
        return 0

    snapshot = args.check.read_text(encoding="utf-8")
    if snapshot != current:
        import difflib

        diff = difflib.unified_diff(
            snapshot.splitlines(keepends=True),
            current.splitlines(keepends=True),
            fromfile=str(args.check),
            tofile="current inventory",
        )
        sys.stdout.writelines(diff)
        print(
            "\nimport inventory drift: a third-party import appeared or "
            "disappeared — review it (typed? stub available? allowlist?) and "
            "update the snapshot in the same PR."
        )
        return 1
    print(f"import inventory unchanged ({len(inventory())} third-party roots)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
