# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
Property-ID ledger consistency check (testing-strategies.md §3.9, L8; fizzbee
plan §3.4/§5.3).

The specs/fizz/README.md ledger is the single mapping between the .fizz
models, the Nagini twins, the Hypothesis oracles, and the conformance tests.
This script makes the mapping mechanically checkable:

1. every property ID referenced in an artifact (specs, twins, oracles,
   conformance) must exist as a ledger row — an unmapped assertion is
   deleted at phase-boundary review (fizzbee plan §3.7);
2. every ledger row must either reference at least one existing artifact
   path or be explicitly marked planned/n/a — a row pointing at nothing is
   intent drift.

Exit 1 on either violation; `make verify-ledger` gates it.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER = REPO_ROOT / "specs/fizz/README.md"

ID_PATTERN = re.compile(r"\b(?:J|P|FP|FC)-\d+\b")
ARTIFACT_GLOBS = (
    "specs/fizz/*.fizz",
    "verify/twin/*.py",
    "tests/verification/*.py",
    "tests/verification/gardens/*.py",
    "src/*_core.py",
)
DEFERRED_MARKERS = ("planned", "n/a", "future twin", "F1 addition", "phase F2")


def ledger_ids_with_rows() -> dict[str, str]:
    """ID -> its full ledger row text."""
    rows: dict[str, str] = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if line.startswith("|") and "---" not in line:
            match = ID_PATTERN.search(line)
            if match:
                rows.setdefault(match.group(0), line)
    return rows


def artifact_ids() -> dict[str, list[str]]:
    """Relative path -> IDs referenced in that artifact."""
    found: dict[str, list[str]] = {}
    for pattern in ARTIFACT_GLOBS:
        for path in REPO_ROOT.glob(pattern):
            text = path.read_text(encoding="utf-8")
            ids = set(ID_PATTERN.findall(text))
            if ids:
                found[str(path.relative_to(REPO_ROOT))] = sorted(ids)
    return found


def main() -> int:
    rows = ledger_ids_with_rows()
    artifacts = artifact_ids()
    failures: list[str] = []

    referenced: set[str] = set()
    for path, ids in sorted(artifacts.items()):
        for prop_id in ids:
            referenced.add(prop_id)
            if prop_id not in rows:
                failures.append(
                    f"UNMAPPED: {prop_id} referenced in {path} has no ledger row"
                )

    for prop_id, row in sorted(rows.items()):
        lowered = row.lower()
        deferred = any(marker in lowered for marker in DEFERRED_MARKERS)
        appears = any(prop_id in ids for ids in artifacts.values())
        if not appears and not deferred:
            failures.append(
                f"DANGLING: ledger row {prop_id} references no existing artifact "
                "and is not marked planned/n/a"
            )

    if failures:
        print("LEDGER DRIFT DETECTED:")
        for failure in failures:
            print(f"  - {failure}")
        print(f"\nLedger rows: {len(rows)}; artifact references: {len(referenced)}")
        return 1

    print(
        f"ledger consistent: {len(rows)} rows, "
        f"{len(referenced)} referenced IDs, {len(artifacts)} artifacts checked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
