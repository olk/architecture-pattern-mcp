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

Design decisions applied:
  - normalize (strip outer whitespace) before validation
  - require at least one letter or digit (Unicode categories L* or N*)
  - max_length: domain <= 200 chars, free text <= 100 000 chars, pattern name <= 100
"""

from __future__ import annotations

import unicodedata
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

DOMAIN_MAX_LENGTH = 200
FREETEXT_MAX_LENGTH = 100_000
PATTERN_NAME_MAX_LENGTH = 100


def _has_printable_content(value: str) -> bool:
    """Return True if value contains at least one letter or digit."""
    return any(
        unicodedata.category(ch).startswith(("L", "N"))
        for ch in value
    )


def _check_free_text(stripped: str) -> str:
    """Validate free-form text (requirements, criteria, style, etc.)."""
    if not _has_printable_content(stripped):
        raise ValueError(
            "Value must contain at least one visible letter or digit; "
            "whitespace-only and invisible-character-only strings are not allowed"
        )
    return stripped


def _check_domain(stripped: str) -> str:
    """Validate a domain string (strict: no line breaks)."""
    if not _has_printable_content(stripped):
        raise ValueError(
            "Domain must contain at least one visible letter or digit; "
            "whitespace-only and invisible-character-only strings are not allowed"
        )
    return stripped


def ensure_printable_text(
    value: str,
    *,
    field: str,
    allow_line_breaks: bool = True,
    max_length: int = FREETEXT_MAX_LENGTH,
) -> str:
    """
    Strip, validate, and return a text parameter.

    Used both as:
      1. Pydantic AfterValidator callable — runs after StringConstraints.
      2. Runtime guard callable in tool handlers (defence-in-depth).

    Args:
        value:        The string value to validate.
        field:        Human-readable field name used in error messages.
        allow_line_breaks: Whether ``\\n`` and ``\\r`` are permitted inside the text.
        max_length:   Maximum allowed character count after stripping.

    Returns:
        The stripped string (normalised).

    Raises:
        ValueError: When the value is whitespace-only, contains disallowed
                    control/format characters, or contains no printable letters/digits.
    """
    _allowed = {"\t", "\n", "\r"}
    if not allow_line_breaks:
        _allowed -= {"\n", "\r"}

    for ch in value:
        cat = unicodedata.category(ch)
        if cat.startswith("C") and ch not in _allowed:
            raise ValueError(
                f"{field} contains disallowed character U+{ord(ch):04X} "
                f"(category {cat}); control and format characters are not allowed"
            )

    stripped = value.strip()
    if len(stripped) > max_length:
        raise ValueError(
            f"{field} exceeds maximum length of {max_length} characters "
            f"(got {len(stripped)} after stripping)"
        )

    return _check_free_text(stripped) if allow_line_breaks else _check_domain(stripped)


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
