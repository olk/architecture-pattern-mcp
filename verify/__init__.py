# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
Verification artifacts (nagini-verification-plan.md §3.5-§3.6).

This tree is NOT shipped (hatch packages only src/), NOT mypy-checked
(files = ["src"]), and NOT scanned by vulture (scope: src + examples).
It holds:
  - twin/   synchronous Nagini twins of the async control logic
  - stubs/  annotated .pyi stubs for third-party libraries (unproven oracle
            assumptions — reviewed like source, spot-checked where feasible)

Contracts go through verify._contracts — a typed runtime no-op shim mirroring
the nagini_contracts.contracts surface; swap the import when the nagini
toolchain is provisioned (docs/phase-0-decisions.md).
"""
