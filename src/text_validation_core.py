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
Pure text-validation decision core — the Nagini verification target (L5).

This module is verified with Nagini (nagini-verification-plan.md §3.4,
docs/verification.md L5); it carries the explicit Requires/Ensures/Invariant
contracts that the L5 gate checks.  The character-level Unicode facts that
Nagini cannot model (``unicodedata.category``, ``str.isspace``) are trusted
*precomputations* produced by the Pydantic adapter in ``src/text_validation.py``
and passed in as plain lists — the L5 claim is therefore "the decision logic is
correct on all inputs, assuming the Unicode oracles are correct" (the
verification.md L5 honest-claims row).

Verified properties (per input value of length ``n``):

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

The unmodelable str-level operations (character iteration, ``ord``,
``startswith``, ``strip``, f-string hex formatting) are not part of this
module's Nagini subset; the adapter reconstructs the message strings and the
stripped result identically to the historical implementation (the L1 oracle
``tests/unit/test_text_validation.py`` pins the exact messages).
"""


from nagini_contracts.contracts import (
    Acc,
    Ensures,
    Exists,
    Forall,
    Implies,
    Invariant,
    Pure,
    Requires,
    Result,
    list_pred,
)

# Unicode general-category classes (computed by the adapter via
# unicodedata.category; Nagini treats them as opaque integers).
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

# Public length limits (kept here so all import sites resolve against the
# pure core; the verified decision engine itself only takes max_length).
DOMAIN_MAX_LENGTH = 200
FREETEXT_MAX_LENGTH = 100_000
PATTERN_NAME_MAX_LENGTH = 100


class StripWindow:
    """Verified result of the strip-window computation over a char list."""

    def __init__(self) -> None:
        # Assignments precede the (runtime-inert) contract so the contract
        # expressions never touch attributes that do not exist yet.
        self.lo = 0
        self.hi = 0
        Ensures(Acc(self.lo) and Acc(self.hi) and self.lo == 0 and self.hi == 0)


class TextVerdict:
    """Verified decision record produced by evaluate_printable_text.

    Fields:
        kind:        KIND_OK / KIND_DISALLOWED / KIND_TOO_LONG / KIND_NO_PRINTABLE.
        error_index: index of the first disallowed character (kind == DISALLOWED).
        window_lo:   first character of the strip window (all kinds except DISALLOWED).
        window_hi:   one past the last character of the strip window.
    """

    def __init__(self) -> None:
        # Assignments precede the (runtime-inert) contract so the contract
        # expressions never touch attributes that do not exist yet.
        self.kind = KIND_OK
        self.error_index = 0
        self.window_lo = 0
        self.window_hi = 0
        Ensures(
            Acc(self.kind)
            and Acc(self.error_index)
            and Acc(self.window_lo)
            and Acc(self.window_hi)
            and self.kind == KIND_OK
            and self.error_index == 0
            and self.window_lo == 0
            and self.window_hi == 0
        )


@Pure
def no_disallowed(n: int, cats: list[int], allowed: list[bool]) -> bool:
    """True iff no character in [0, n) is a control char outside the allowed set."""
    Requires(list_pred(cats) and list_pred(allowed))
    Requires(len(cats) == n and len(allowed) == n)
    Ensures(
        Result()
        == Forall(
            int,
            lambda i: Implies(
                i >= 0 and i < n, Implies(cats[i] == CAT_CONTROL, allowed[i])
            ),
        )
    )
    return Forall(
        int,
        lambda i: Implies(
            i >= 0 and i < n, Implies(cats[i] == CAT_CONTROL, allowed[i])
        ),
    )


@Pure
def has_printable(cats: list[int], lo: int, hi: int) -> bool:
    """True iff the window [lo, hi) contains a letter or digit category."""
    Requires(list_pred(cats))
    Requires(lo >= 0 and lo <= hi <= len(cats))
    Ensures(
        Result()
        == Exists(
            int,
            lambda i: Implies(
                i >= lo and i < hi, cats[i] == CAT_LETTER or cats[i] == CAT_DIGIT
            ),
        )
    )
    return Exists(
        int,
        lambda i: Implies(
            i >= lo and i < hi, cats[i] == CAT_LETTER or cats[i] == CAT_DIGIT
        ),
    )


def compute_strip_window(n: int, strip_whitespace: list[bool]) -> StripWindow:
    """Compute the maximal strip window [lo, hi) of a length-n char list.

    ``strip_whitespace[i]`` is the trusted ``str.isspace`` oracle for
    character i.  The window removes leading/trailing whitespace only —
    interior whitespace stays (matching ``str.strip``).
    """
    Requires(list_pred(strip_whitespace))
    Requires(len(strip_whitespace) == n)
    Requires(n >= 0)
    Ensures(
        StripWindow,
        lambda w: (
            list_pred(strip_whitespace)
            and len(strip_whitespace) == n
            and Acc(w.lo)
            and Acc(w.hi)
            and w.lo >= 0
            and w.lo <= w.hi
            and w.hi <= n
            and Forall(
                int,
                lambda i: Implies(i >= 0 and i < w.lo, strip_whitespace[i]),
            )
            and (w.lo == n or not strip_whitespace[w.lo])
            and Forall(
                int,
                lambda i: Implies(i >= w.hi and i < n, strip_whitespace[i]),
            )
            and (w.hi == w.lo or not strip_whitespace[w.hi - 1])
        ),
    )
    lo = 0
    while lo < n:
        Invariant(
            list_pred(strip_whitespace)
            and len(strip_whitespace) == n
            and lo >= 0
            and lo <= n
            and Forall(
                int,
                lambda i: Implies(i >= 0 and i < lo, strip_whitespace[i]),
            )
        )
        if not strip_whitespace[lo]:
            break
        lo = lo + 1
    hi = n
    while hi > lo:
        Invariant(
            list_pred(strip_whitespace)
            and len(strip_whitespace) == n
            and lo <= hi
            and hi <= n
            and Forall(
                int,
                lambda i: Implies(i >= 0 and i < lo, strip_whitespace[i]),
            )
            and (lo == n or not strip_whitespace[lo])
            and Forall(
                int,
                lambda i: Implies(i >= hi and i < n, strip_whitespace[i]),
            )
        )
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
        categories:        Per-character category codes (CAT_*), precomputed by
                           the adapter from ``unicodedata.category``.
        strip_whitespace:  Per-character ``str.isspace`` oracle.
        allowed_whitespace: Per-character "is an allowed whitespace char"
                           oracle ("\\t" plus "\\n"/"\\r" when line breaks are
                           allowed) — the historical `ch not in _allowed` test.
        max_length:        Maximum length of the stripped text (>= 0).

    Returns:
        A TextVerdict whose postconditions capture the full decision semantics.
    """
    Requires(
        list_pred(categories)
        and list_pred(strip_whitespace)
        and list_pred(allowed_whitespace)
    )
    Requires(len(categories) == len(value))
    Requires(len(strip_whitespace) == len(value))
    Requires(len(allowed_whitespace) == len(value))
    Requires(max_length >= 0)
    Ensures(
        TextVerdict,
        lambda v: (
            list_pred(categories)
            and list_pred(strip_whitespace)
            and list_pred(allowed_whitespace)
            and len(categories) == len(value)
            and len(strip_whitespace) == len(value)
            and len(allowed_whitespace) == len(value)
            and Acc(v.kind)
            and Acc(v.error_index)
            and Acc(v.window_lo)
            and Acc(v.window_hi)
            and v.kind >= KIND_OK
            and v.kind <= KIND_NO_PRINTABLE
            and v.error_index >= 0
            and v.error_index <= len(value)
            and v.window_lo >= 0
            and v.window_lo <= v.window_hi
            and v.window_hi <= len(value)
            and Implies(
                v.kind != KIND_DISALLOWED,
                (
                    Forall(
                        int,
                        lambda i: Implies(
                            i >= 0 and i < v.window_lo, strip_whitespace[i]
                        ),
                    )
                    and (v.window_lo == len(value) or not strip_whitespace[v.window_lo])
                    and Forall(
                        int,
                        lambda i: Implies(
                            i >= v.window_hi and i < len(value), strip_whitespace[i]
                        ),
                    )
                    and (
                        v.window_hi == v.window_lo
                        or not strip_whitespace[v.window_hi - 1]
                    )
                ),
            )
            and Implies(
                v.kind == KIND_DISALLOWED,
                (
                    v.error_index >= 0
                    and v.error_index < len(value)
                    and categories[v.error_index] == CAT_CONTROL
                    and not allowed_whitespace[v.error_index]
                    and Forall(
                        int,
                        lambda i: Implies(
                            i >= 0 and i < v.error_index,
                            Implies(
                                categories[i] == CAT_CONTROL, allowed_whitespace[i]
                            ),
                        ),
                    )
                ),
            )
            and Implies(v.kind == KIND_TOO_LONG, v.window_hi - v.window_lo > max_length)
            and Implies(
                v.kind == KIND_NO_PRINTABLE,
                Forall(
                    int,
                    lambda i: Implies(
                        i >= v.window_lo and i < v.window_hi,
                        not (
                            categories[i] == CAT_LETTER or categories[i] == CAT_DIGIT
                        ),
                    ),
                ),
            )
            and Implies(
                v.kind == KIND_OK,
                (
                    no_disallowed(len(value), categories, allowed_whitespace)
                    and v.window_hi - v.window_lo <= max_length
                    and has_printable(categories, v.window_lo, v.window_hi)
                ),
            )
        ),
    )
    verdict = TextVerdict()
    n = len(value)
    i = 0
    while i < n:
        Invariant(
            Acc(verdict.kind)
            and Acc(verdict.error_index)
            and verdict.kind == KIND_OK
            and verdict.error_index == 0
            and i >= 0
            and i <= n
            and list_pred(categories)
            and list_pred(allowed_whitespace)
            and len(categories) == n
            and len(allowed_whitespace) == n
            and Forall(
                int,
                lambda j: Implies(
                    j >= 0 and j < i,
                    Implies(categories[j] == CAT_CONTROL, allowed_whitespace[j]),
                ),
            )
        )
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
        Invariant(
            Acc(verdict.kind)
            and Acc(verdict.error_index)
            and Acc(verdict.window_lo)
            and Acc(verdict.window_hi)
            and verdict.kind == KIND_OK
            and verdict.error_index == 0
            and verdict.window_lo == lo
            and verdict.window_hi == hi
            and lo <= j
            and j <= hi
            and list_pred(categories)
            and len(categories) == n
            and list_pred(allowed_whitespace)
            and len(allowed_whitespace) == n
            and Forall(
                int,
                lambda k: Implies(
                    k >= 0 and k < n,
                    Implies(categories[k] == CAT_CONTROL, allowed_whitespace[k]),
                ),
            )
            and Implies(
                not has,
                Forall(
                    int,
                    lambda k: Implies(
                        k >= lo and k < j,
                        not (
                            categories[k] == CAT_LETTER or categories[k] == CAT_DIGIT
                        ),
                    ),
                ),
            )
            and Implies(
                has,
                Exists(
                    int,
                    lambda k: Implies(
                        k >= lo and k < j,
                        categories[k] == CAT_LETTER or categories[k] == CAT_DIGIT,
                    ),
                ),
            )
        )
        if categories[j] == CAT_LETTER or categories[j] == CAT_DIGIT:
            has = True
        j = j + 1
    if not has:
        verdict.kind = KIND_NO_PRINTABLE
        return verdict
    verdict.kind = KIND_OK
    return verdict
