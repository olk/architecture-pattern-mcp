# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
Input-text validation for MCP tool parameters.

Ensures domain, requirements, style, criteria, and other free-text parameters
contain non-empty, printable, human-readable text — rejecting empty strings,
whitespace-only strings, tab-only strings, mixed whitespace strings, and strings
containing invisible control or format characters (e.g. zero-width spaces, BOM).

Two enforcement layers:
  Layer 1 — Pydantic annotation: fails at the FastMCP protocol boundary before
             the handler body runs (Annotated types with AfterValidator).
  Layer 2 — Runtime guard: defence-in-depth for values read back from persistent
             storage (JobsStore SQLite) or passed through internal APIs.

Pure validation logic lives in src/text_validation_core.py (the Nagini
verification core — no third-party imports, nagini plan §3.4); this module
keeps the Pydantic-facing API and re-exports the core callables, so all
existing import sites keep working unchanged.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

from src.text_validation_core import (
    DOMAIN_MAX_LENGTH,
    FREETEXT_MAX_LENGTH,
    PATTERN_NAME_MAX_LENGTH,
    ensure_printable_text,
)

__all__ = [
    "DOMAIN_MAX_LENGTH",
    "FREETEXT_MAX_LENGTH",
    "PATTERN_NAME_MAX_LENGTH",
    "DomainName",
    "PatternName",
    "PrintableText",
    "ensure_printable_text",
]


def _freetext_validator(value: str) -> str:
    """AfterValidator for free-text fields (requirements, style, criteria)."""
    return ensure_printable_text(value, field="value", allow_line_breaks=True)


def _domain_validator(value: str) -> str:
    """AfterValidator for domain fields."""
    return ensure_printable_text(value, field="domain", allow_line_breaks=False)


def _pattern_name_validator(value: str) -> str:
    """AfterValidator for pattern name fields."""
    return ensure_printable_text(value, field="name", allow_line_breaks=False, max_length=PATTERN_NAME_MAX_LENGTH)


PrintableText = Annotated[
    str,
    StringConstraints(strip_whitespace=True),
    Field(min_length=1, max_length=FREETEXT_MAX_LENGTH),
    AfterValidator(_freetext_validator),
]

DomainName = Annotated[
    str,
    StringConstraints(strip_whitespace=True),
    Field(min_length=1, max_length=DOMAIN_MAX_LENGTH),
    AfterValidator(_domain_validator),
]

PatternName = Annotated[
    str,
    StringConstraints(strip_whitespace=True),
    Field(min_length=1, max_length=PATTERN_NAME_MAX_LENGTH),
    AfterValidator(_pattern_name_validator),
]
