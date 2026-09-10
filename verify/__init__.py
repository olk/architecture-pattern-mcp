# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
Verification artifacts (docs/verification.md L3).

This tree is NOT shipped (hatch packages only src/ and nagini_contracts/),
NOT mypy-checked (files = ["src"]), and NOT scanned by vulture
(scope: src + examples). It holds:

  - mutmut_compat.py  in-process shim for mutmut 3.7's ``src.``-prefix
    assumption (this repo's import package IS ``src``) — loaded by the
    test-mutations Make target and by pytest via ``[tool.mutmut]
    pytest_add_cli_args``; regular pytest runs never import it.

The former Nagini twins/stubs/contracts shim that also lived here were
removed with the L5 rework — the contract vocabulary now ships as the
top-level ``nagini_contracts/`` package.
"""
