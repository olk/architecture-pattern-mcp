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
Direct unit tests for the src.text_validation decision engine.

The public wrapper ``ensure_printable_text`` is pinned by
tests/unit/test_text_validation.py (behavioral oracle). This module tests the
internals directly — ``compute_strip_window``, ``evaluate_printable_text``,
``_category_code``, ``StripWindow``, ``TextVerdict`` — because the wrapper only
exercises them transitively: an index-arithmetic mutant (e.g. ``lo = lo + 1``
to ``lo = lo + 2``) survives wrapper-level tests whenever the visible strip
output happens to coincide.

Case design (each documented case names the mutation class it kills):

- whitespace runs of >= 3 characters distinguish ``+1`` from ``+2`` steps
  (a 2-space run reaches the same break index under both);
- stripped length exactly ``max_length`` distinguishes ``>`` from ``>=``;
- verdict field assertions (window_lo/window_hi/error_index) kill deleted
  assignments, not just wrong verdict kinds;
- totality cases (empty input, all-whitespace input) kill loop-bound mutants
  that would raise IndexError.
"""

import unicodedata

from src.text_validation import (
    CAT_CONTROL,
    CAT_DIGIT,
    CAT_LETTER,
    CAT_OTHER,
    CAT_SEPARATOR,
    KIND_DISALLOWED,
    KIND_NO_PRINTABLE,
    KIND_OK,
    KIND_TOO_LONG,
    StripWindow,
    TextVerdict,
    _category_code,
    compute_strip_window,
    evaluate_printable_text,
)


def _cat_facts(value: str) -> tuple[list[int], list[bool], list[bool], list[bool]]:
    """Precompute the per-character fact lists exactly like the production wrapper."""
    categories = [_category_code(ch) for ch in value]
    strip_whitespace = [ch.isspace() for ch in value]
    allowed = [ch == "\t" or ch in ("\n", "\r") for ch in value]
    disallowed_forbidden = [False for _ in value]
    return categories, strip_whitespace, allowed, disallowed_forbidden


def _evaluate(
    value: str, *, max_length: int = 1000, allow_line_breaks: bool = True
) -> TextVerdict:
    categories, strip_ws, allowed_ws, _ = _cat_facts(value)
    if not allow_line_breaks:
        allowed_ws = [ch == "\t" for ch in value]
    return evaluate_printable_text(
        value,
        categories,
        strip_whitespace=strip_ws,
        allowed_whitespace=allowed_ws,
        max_length=max_length,
    )


class TestStripWindowInit:
    def test_fresh_window_is_zeroed(self) -> None:
        """Kills ``self.lo = 0`` -> ``self.lo = 1`` (and hi) constant mutants."""
        window = StripWindow()
        assert window.lo == 0
        assert window.hi == 0


class TestTextVerdictInit:
    def test_fresh_verdict_is_ok_and_zeroed(self) -> None:
        """Kills constant mutants on all four field initialisations."""
        verdict = TextVerdict()
        assert verdict.kind == KIND_OK
        assert verdict.error_index == 0
        assert verdict.window_lo == 0
        assert verdict.window_hi == 0


class TestComputeStripWindow:
    def test_empty_input_window_is_empty(self) -> None:
        """Totality: n=0 must not raise (loop-bound mutants raise IndexError)."""
        window = compute_strip_window(0, [])
        assert (window.lo, window.hi) == (0, 0)

    def test_no_whitespace_full_window(self) -> None:
        window = compute_strip_window(3, [False, False, False])
        assert (window.lo, window.hi) == (0, 3)

    def test_three_space_prefix_distinguishes_plus_one_from_plus_two(self) -> None:
        """Kills ``lo = lo + 1`` -> ``lo = lo + 2``.

        Reference: lo steps 0,1,2,3 and breaks at the non-whitespace index 3.
        Mutant: lo steps 0,2,4 — landing on index 4 and skipping index 3.
        A 2-space run cannot distinguish the two (both break at index 2).
        """
        facts = [True, True, True, False, False]
        window = compute_strip_window(5, facts)
        assert window.lo == 3
        assert window.hi == 5

    def test_three_space_suffix_distinguishes_minus_one_from_minus_two(self) -> None:
        """Kills ``hi = hi - 1`` -> ``hi = hi - 2``.

        facts = non-whitespace only at index 0. Reference: hi walks
        5 -> 4 -> 3 -> 2 -> 1 and breaks on facts[0]; window (0, 1).
        Mutant (-2): hi walks 5 -> 3 -> 1, then reads facts[-1] (True) and
        steps past lo to -1; window (0, -1). Fields differ.
        """
        facts = [False, True, True, True, True]
        window = compute_strip_window(5, facts)
        assert (window.lo, window.hi) == (0, 1)

    def test_all_whitespace_window_is_empty_at_n(self) -> None:
        """Kills ``while lo < n`` -> ``while lo <= n`` (IndexError at index n)."""
        window = compute_strip_window(4, [True, True, True, True])
        assert (window.lo, window.hi) == (4, 4)

    def test_interior_whitespace_is_preserved(self) -> None:
        """Strip removes leading/trailing whitespace only (mirrors str.strip)."""
        facts = [True, False, True, False, True]
        window = compute_strip_window(5, facts)
        assert (window.lo, window.hi) == (1, 4)

    def test_hi_starts_at_n_not_n_plus_one(self) -> None:
        """Kills ``hi = n`` -> ``hi = n + 1``.

        The mutant reads strip_whitespace[n] on a length-n list -> IndexError,
        which fails this test (the reference returns the full window).
        """
        window = compute_strip_window(3, [False, False, False])
        assert (window.lo, window.hi) == (0, 3)


class TestEvaluatePrintableText:
    def test_empty_string_is_no_printable_with_empty_window(self) -> None:
        """Totality + window fields on the degenerate input."""
        verdict = _evaluate("")
        assert verdict.kind == KIND_NO_PRINTABLE
        assert (verdict.window_lo, verdict.window_hi) == (0, 0)

    def test_ok_verdict_carries_exact_window(self) -> None:
        """Kills deleted ``verdict.window_lo/hi = ...`` assignments on OK path."""
        verdict = _evaluate("  ab  ")
        assert verdict.kind == KIND_OK
        assert (verdict.window_lo, verdict.window_hi) == (2, 4)

    def test_disallowed_points_at_first_control_character(self) -> None:
        """Disallowed scan: error_index is the FIRST violating character."""
        verdict = _evaluate("ab\x00cd")
        assert verdict.kind == KIND_DISALLOWED
        assert verdict.error_index == 2

    def test_scan_step_mutant_is_caught_by_second_character(self) -> None:
        """Kills ``i = i + 1`` -> ``i = i + 2`` in the disallowed scan.

        The only disallowed character sits at index 1; a +2 step skips it and
        the verdict flips from DISALLOWED to OK.
        """
        verdict = _evaluate("a\x00b")
        assert verdict.kind == KIND_DISALLOWED
        assert verdict.error_index == 1

    def test_allowed_whitespace_suppresses_the_scan(self) -> None:
        """Kills deletion of ``and not allowed_whitespace[i]`` (tab must pass).

        'a' at index 0 is not strip-whitespace, so the window is the full
        (0, 3) — the interior tab is preserved, matching str.strip.
        """
        categories = [CAT_LETTER, CAT_CONTROL, CAT_LETTER]
        strip_ws = [False, True, False]
        allowed_ws = [False, True, False]  # tab is always allowed
        verdict = evaluate_printable_text(
            "a\tb",
            categories,
            strip_whitespace=strip_ws,
            allowed_whitespace=allowed_ws,
            max_length=10,
        )
        assert verdict.kind == KIND_OK
        assert (verdict.window_lo, verdict.window_hi) == (0, 3)

    def test_line_break_allowed_flag_flips_the_verdict(self) -> None:
        """Kills the ``allow_line_breaks and ...`` conjunct in the wrapper facts."""
        verdict_with = _evaluate("a\nb", allow_line_breaks=True)
        verdict_without = _evaluate("a\nb", allow_line_breaks=False)
        assert verdict_with.kind == KIND_OK
        assert verdict_without.kind == KIND_DISALLOWED
        assert verdict_without.error_index == 1

    def test_length_boundary_exactly_max_length_is_ok(self) -> None:
        """Kills ``hi - lo > max_length`` -> ``>=`` (equal length must pass)."""
        verdict = _evaluate("abc", max_length=3)
        assert verdict.kind == KIND_OK

    def test_too_long_carries_the_window_fields(self) -> None:
        """TOO_LONG verdict records the (rejected) window, not zeros."""
        verdict = _evaluate("abcd", max_length=3)
        assert verdict.kind == KIND_TOO_LONG
        assert (verdict.window_lo, verdict.window_hi) == (0, 4)

    def test_too_long_counts_after_strip_not_before(self) -> None:
        """Window length, not raw length, feeds the check (strip-must-run)."""
        verdict = _evaluate("  abc  ", max_length=3)
        assert verdict.kind == KIND_OK

    def test_punctuation_only_window_is_no_printable(self) -> None:
        verdict = _evaluate("---")
        assert verdict.kind == KIND_NO_PRINTABLE
        assert (verdict.window_lo, verdict.window_hi) == (0, 3)

    def test_whitespace_only_window_is_no_printable(self) -> None:
        verdict = _evaluate("   ")
        assert verdict.kind == KIND_NO_PRINTABLE
        assert (verdict.window_lo, verdict.window_hi) == (3, 3)

    def test_letter_alone_satisfies_printable(self) -> None:
        """Kills ``or`` -> ``and`` in the letter/digit disjunction."""
        assert _evaluate("abc").kind == KIND_OK

    def test_digit_alone_satisfies_printable(self) -> None:
        """Kills ``or`` -> ``and`` from the digit side."""
        assert _evaluate("123").kind == KIND_OK

    def test_printable_scan_step_mutant_is_caught(self) -> None:
        """Kills ``j = j + 1`` -> ``j = j + 2`` in the printable scan.

        '-' (index 0) is not letter/digit; 'a' (index 1) is. A +2 step never
        sees the letter and flips the verdict to NO_PRINTABLE.
        """
        assert _evaluate("-a").kind == KIND_OK

    def test_has_flag_reset_mutant_is_caught(self) -> None:
        """Kills ``has = True`` deletion — a letter must flip the flag."""
        verdict = _evaluate("  x  ")
        assert verdict.kind == KIND_OK
        assert (verdict.window_lo, verdict.window_hi) == (2, 3)


class TestCategoryCode:
    def test_letter(self) -> None:
        assert _category_code("a") == CAT_LETTER
        assert _category_code("Z") == CAT_LETTER
        assert _category_code("ä") == CAT_LETTER

    def test_digit(self) -> None:
        assert _category_code("1") == CAT_DIGIT

    def test_control(self) -> None:
        assert _category_code("\x00") == CAT_CONTROL
        assert _category_code("\x1b") == CAT_CONTROL

    def test_separator(self) -> None:
        assert _category_code(" ") == CAT_SEPARATOR

    def test_other(self) -> None:
        assert _category_code("-") == CAT_OTHER
        assert _category_code("+") == CAT_OTHER

    def test_mapping_agrees_with_unicodedata_oracle(self) -> None:
        """Pins the first-letter dispatch against the trusted unicode oracle."""
        expected = {
            "L": CAT_LETTER,
            "N": CAT_DIGIT,
            "C": CAT_CONTROL,
            "Z": CAT_SEPARATOR,
        }
        for ch in ("a", "5", "\x07", "\u00a0", "!"):
            first = unicodedata.category(ch)[0]
            if first in expected:
                assert _category_code(ch) == expected[first]
