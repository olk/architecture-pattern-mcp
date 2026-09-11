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

Architecture: the decision engine (``compute_strip_window`` /
``evaluate_printable_text``) operates on per-character facts precomputed here
from the Unicode oracles (``unicodedata.category``, ``str.isspace``, the
allowed-whitespace test) and passed in as plain lists.  The ValueError messages
and the stripped result are reconstructed byte-identical to the historical
implementation (tests/unit/test_text_validation.py is the behavioral oracle).

Decision properties (pinned by tests/unit/test_text_validation.py):

- **totality**: no IndexError/KeyError/AttributeError on any input; the
  decision is a pure function of its inputs;
- **verdict well-formedness**: kind is one of OK/DISALLOWED/TOO_LONG/
  NO_PRINTABLE; indices and the strip window stay within ``[0, n]``;
- **disallowed-character scan** (first scan, mirrors runtime order):
  DISALLOWED points at the *first* control/format character that is not in the
  allowed-whitespace set, and no earlier character violates the rule;
- **strip window**: for every non-DISALLOWED verdict, ``[window_lo,
  window_hi)`` is exactly the maximal strip window — all characters before
  ``window_lo`` are strip whitespace, ``window_lo`` is not (unless it equals
  ``n``), all characters from ``window_hi`` on are strip whitespace, and
  ``window_hi - 1`` is not (unless the window is empty);
- **length check**: TOO_LONG iff ``window_hi - window_lo > max_length``;
- **printable check**: NO_PRINTABLE iff the window contains no letter/digit
  (category codes CAT_LETTER/CAT_DIGIT); OK iff the window has one and the
  whole input passes the disallowed-character scan.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

__all__ = [
    "DOMAIN_MAX_LENGTH",
    "FREETEXT_MAX_LENGTH",
    "PATTERN_NAME_MAX_LENGTH",
    "DomainName",
    "PatternName",
    "PrintableText",
    "ensure_printable_text",
]

# Unicode general-category classes (computed by _category_code via
# unicodedata.category).
CAT_OTHER = 0
CAT_LETTER = 1
CAT_DIGIT = 2
CAT_CONTROL = 3
CAT_SEPARATOR = 4

# Verdict kinds.
KIND_OK = 0
KIND_DISALLOWED = 1
KIND_TOO_LONG = 2
KIND_NO_PRINTABLE = 3

# Public length limits (kept here so all import sites resolve against this
# module; the decision engine itself only takes max_length).
DOMAIN_MAX_LENGTH = 200
FREETEXT_MAX_LENGTH = 100_000
PATTERN_NAME_MAX_LENGTH = 100


class StripWindow:
    """Result of the strip-window computation over a char list."""

    def __init__(self) -> None:
        self.lo = 0
        self.hi = 0


class TextVerdict:
    """Decision record produced by evaluate_printable_text.

    Fields:
        kind:        KIND_OK / KIND_DISALLOWED / KIND_TOO_LONG / KIND_NO_PRINTABLE.
        error_index: index of the first disallowed character (kind == DISALLOWED).
        window_lo:   first character of the strip window (all kinds except DISALLOWED).
        window_hi:   one past the last character of the strip window.
    """

    def __init__(self) -> None:
        self.kind = KIND_OK
        self.error_index = 0
        self.window_lo = 0
        self.window_hi = 0


def compute_strip_window(n: int, strip_whitespace: list[bool]) -> StripWindow:
    """Compute the maximal strip window [lo, hi) of a length-n char list.

    ``strip_whitespace[i]`` is the trusted ``str.isspace`` oracle for
    character i.  The window removes leading/trailing whitespace only —
    interior whitespace stays (matching ``str.strip``).
    """
    lo = 0
    while lo < n:
        if not strip_whitespace[lo]:
            break
        lo = lo + 1
    hi = n
    while hi > lo:
        if not strip_whitespace[hi - 1]:
            break
        hi = hi - 1
    result = StripWindow()
    result.lo = lo
    result.hi = hi
    return result


def evaluate_printable_text(
    value: str,
    categories: list[int],
    strip_whitespace: list[bool],
    allowed_whitespace: list[bool],
    *,
    max_length: int,
) -> TextVerdict:
    """Decide the printable-text verdict for a precomputed char model.

    Args:
        value:             The original string; only its length is used here.
        categories:        Per-character category codes (CAT_*), precomputed
                           from ``unicodedata.category``.
        strip_whitespace:  Per-character ``str.isspace`` oracle.
        allowed_whitespace: Per-character "is an allowed whitespace char"
                           oracle ("\\t" plus "\\n"/"\\r" when line breaks are
                           allowed) — the historical `ch not in _allowed` test.
        max_length:        Maximum length of the stripped text (>= 0).

    Returns:
        A TextVerdict recording the decision.  The properties documented in
        the module docstring hold on every input (pinned by the unit tests).
    """
    verdict = TextVerdict()
    n = len(value)
    i = 0
    while i < n:
        if categories[i] == CAT_CONTROL and not allowed_whitespace[i]:
            verdict.kind = KIND_DISALLOWED
            verdict.error_index = i
            return verdict
        i = i + 1
    w = compute_strip_window(n, strip_whitespace)
    lo = w.lo
    hi = w.hi
    verdict.window_lo = lo
    verdict.window_hi = hi
    if hi - lo > max_length:
        verdict.kind = KIND_TOO_LONG
        return verdict
    j = lo
    has = False
    while j < hi:
        if categories[j] == CAT_LETTER or categories[j] == CAT_DIGIT:
            has = True
        j = j + 1
    if not has:
        verdict.kind = KIND_NO_PRINTABLE
        return verdict
    verdict.kind = KIND_OK
    return verdict


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
