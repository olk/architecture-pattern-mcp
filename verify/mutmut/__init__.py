# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
mutmut tooling (docs/verification.md L3): the in-process compatibility shim
patching mutmut 3.7's ``src.``-layout assumptions for this repo. Loaded from
the Makefile bootstrap (generation time) and via ``[tool.mutmut]
pytest_add_cli_args`` in every mutmut pytest run; regular pytest runs never
import it.
"""
