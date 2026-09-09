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
Pure text-validation logic — the Nagini verification core (nagini plan §3.4).

Split from src/text_validation.py so the pure logic carries only stdlib
imports (Pydantic metaprogramming is opaque to Nagini — F6). This file is in
NAGINI_FILES (scripts/verify_coverage.py) and is the Phase-0 contract target:
totality (no IndexError/KeyError/AttributeError on any input, Exsures(ValueError)
the only declared exception), len(result) <= max_length, result == value.strip().

Runtime no-op: this is a behaviour-preserving move; src/text_validation.py
re-exports the same callables, so the public API is unchanged.
"""

import unicodedata

DOMAIN_MAX_LENGTH = 200
FREETEXT_MAX_LENGTH = 100_000
PATTERN_NAME_MAX_LENGTH = 100

_ALLOWED_WHITESPACE = frozenset({"\t", "\n", "\r"})
_ALLOWED_WHITESPACE_NO_BREAKS = frozenset({"\t"})


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
    _allowed = (
        set(_ALLOWED_WHITESPACE) if allow_line_breaks else set(_ALLOWED_WHITESPACE_NO_BREAKS)
    )

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
