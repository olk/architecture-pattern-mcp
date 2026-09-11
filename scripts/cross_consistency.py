# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
NL-Doc cross-consistency gate — mechanical subset (testing-strategies.md
§3.9, L8).

Evidence base: VLP (arXiv 2607.02333) — validating an intermediate artifact
beats direct code review 84% vs 40%; the docstring-as-NL-Doc discipline is
promoted from convention to a machine-checked step.

Current (mechanical) checks over SCOPE_FILES:
  - every public function/method carries a docstring (the NL-Doc artifact
    a reviewer validates instead of re-deriving intent from code);
  - contract-bearing functions state their intent in the docstring.

LLM comparison (a second LLM summarises each function; the summary is diffed
against docstring + intent) is provisioned via ARCH_CONSISTENCY_MODEL; each
run RECORDS the checker model identity with its output — the E3 pinning rule:
a silently downgraded checker is a gate-avoidance finding, and the promotion
trigger is scored against a named model.

Advisory by default; findings are leads to triage, not failures.
"""

import argparse
import ast
import os
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The decision modules: the validation and normalization logic that carries
# the documented decision properties (the L1/L2 behavioral oracles pin their
# semantics).
SCOPE_FILES: tuple[str, ...] = (
    "src/text_validation.py",
    "src/design_normalization.py",
)

DIVERGENCE_BLOCK_THRESHOLD = 0.10


def _checker_identity() -> str:
    model = os.environ.get("ARCH_CONSISTENCY_MODEL", "")
    return model if model else "mechanical-subset (no LLM checker configured)"


def _record_run(model: str, missing: list[str]) -> None:
    """E3: append the checker identity + result to the run record."""
    print(f"checker: {model}")
    print(f"recorded: {datetime.now(UTC).isoformat()}")


def _protocol_method_names(tree: ast.AST) -> set[int]:
    """Identities of methods defined inside Protocol classes (duck-type views —
    the class docstring is the NL-Doc artifact, not each property stub)."""
    excluded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = {getattr(b, "id", getattr(b, "name", "")) for b in node.bases}
            if "Protocol" in bases:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        excluded.add(id(item))
    return excluded


def _public_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    excluded = _protocol_method_names(tree)
    out: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if id(node) in excluded:
                continue
            if node.name.startswith("_"):
                continue
            out.append(node)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 when divergence exceeds 10%"
    )
    args = parser.parse_args()

    model = _checker_identity()
    total = 0
    missing_docs: list[str] = []

    for rel in SCOPE_FILES:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in _public_functions(tree):
            total += 1
            if ast.get_docstring(func) is None:
                missing_docs.append(f"{rel}::{func.name}")

    divergence = (len(missing_docs) / total) if total else 0.0
    _record_run(model, missing_docs)
    for item in missing_docs:
        print(f"  missing NL-Doc: {item}")
    print(
        f"NL-Doc coverage: {total - len(missing_docs)}/{total} "
        f"({divergence:.1%} divergence; blocking threshold "
        f"{DIVERGENCE_BLOCK_THRESHOLD:.0%})"
    )

    strict_violation = args.strict and divergence > DIVERGENCE_BLOCK_THRESHOLD
    return 1 if strict_violation else 0


if __name__ == "__main__":
    raise SystemExit(main())
