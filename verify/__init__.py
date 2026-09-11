# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
Verification artifacts (docs/verification.md L3/L4).

This tree is NOT shipped (hatch packages only src/ and nagini_contracts/),
NOT mypy-checked (files = ["src"]), and NOT scanned by vulture
(scope: src + examples). It holds:

  - mutmut/  the L3 mutmut tooling: an in-process shim for mutmut 3.7's
    ``src.``-prefix assumption (this repo's import package IS ``src``) —
    loaded by the test-mutations Make target and by pytest via
    ``[tool.mutmut] pytest_add_cli_args``; regular pytest runs never
    import it.

  - fizz/  the L4 FizzBee model-checking specs (.fizz models, fizz.yaml
    bounds, and the property-ID ledger README.md) — consumed by the
    verify-fizz / verify-fizz-simulation / verify-ledger Make targets,
    never imported at runtime.

The former Nagini twins/stubs/contracts shim that also lived here were
removed with the L5 rework — the contract vocabulary now ships as the
top-level ``nagini_contracts/`` package.
"""
