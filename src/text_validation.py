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

Architecture: the pure decision logic lives in src/text_validation_core.py
(the Nagini-verified core, L5); this module is the Pydantic-facing adapter. It
precomputes the per-character Unicode facts Nagini cannot model
(``unicodedata.category``, ``str.isspace``, the allowed-whitespace test),
delegates the decision to the verified core, and reconstructs the ValueError
messages and the stripped result — byte-identical to the historical
implementation (tests/unit/test_text_validation.py is the oracle).
"""

from __future__ import annotations

import unicodedata
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

from src.text_validation_core import (
    CAT_CONTROL,
    CAT_DIGIT,
    CAT_LETTER,
    CAT_OTHER,
    CAT_SEPARATOR,
    DOMAIN_MAX_LENGTH,
    FREETEXT_MAX_LENGTH,
    KIND_DISALLOWED,
    KIND_NO_PRINTABLE,
    KIND_TOO_LONG,
    PATTERN_NAME_MAX_LENGTH,
    evaluate_printable_text,
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


def _category_code(ch: str) -> int:
    """Map a character to its CAT_* code via unicodedata (trusted oracle).

    General categories are exactly two letters; the first letter is the class.
    """
    cat = unicodedata.category(ch)
    if cat.startswith("L"):
        return CAT_LETTER
    if cat.startswith("N"):
        return CAT_DIGIT
    if cat.startswith("C"):
        return CAT_CONTROL
    if cat.startswith("Z"):
        return CAT_SEPARATOR
    return CAT_OTHER


def ensure_printable_text(
    value: str,
    *,
    field: str,
    allow_line_breaks: bool = True,
    max_length: int = FREETEXT_MAX_LENGTH,
) -> str:
    """
    Strip, validate, and return a text parameter.

    Intent (why): every LLM/user-supplied free-text parameter must contain
    visible, printable human-readable text; the fact-set is machine-checked:
    on ANY input the only possible failure is ValueError, the result is the
    stripped input, and its length is within max_length.

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
    categories = [_category_code(ch) for ch in value]
    strip_whitespace = [ch.isspace() for ch in value]
    allowed_whitespace = [
        ch == "\t" or (allow_line_breaks and ch in ("\n", "\r"))
        for ch in value
    ]
    verdict = evaluate_printable_text(
        value,
        categories,
        strip_whitespace,
        allowed_whitespace,
        max_length=max_length,
    )
    if verdict.kind == KIND_DISALLOWED:
        index = verdict.error_index
        cat = unicodedata.category(value[index])
        raise ValueError(
            f"{field} contains disallowed character U+{ord(value[index]):04X} "
            f"(category {cat}); control and format characters are not allowed"
        )
    if verdict.kind == KIND_TOO_LONG:
        stripped_len = verdict.window_hi - verdict.window_lo
        raise ValueError(
            f"{field} exceeds maximum length of {max_length} characters "
            f"(got {stripped_len} after stripping)"
        )
    if verdict.kind == KIND_NO_PRINTABLE:
        raise ValueError(
            "Value must contain at least one visible letter or digit; "
            "whitespace-only and invisible-character-only strings are not allowed"
        )
    return value[verdict.window_lo : verdict.window_hi]


def _freetext_validator(value: str) -> str:
    """AfterValidator for free-text fields (requirements, style, criteria)."""
    return ensure_printable_text(value, field="value", allow_line_breaks=True)


def _domain_validator(value: str) -> str:
    """AfterValidator for domain fields."""
    return ensure_printable_text(value, field="domain", allow_line_breaks=False)


def _pattern_name_validator(value: str) -> str:
    """AfterValidator for pattern name fields."""
    return ensure_printable_text(
        value, field="name", allow_line_breaks=False, max_length=PATTERN_NAME_MAX_LENGTH
    )


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
