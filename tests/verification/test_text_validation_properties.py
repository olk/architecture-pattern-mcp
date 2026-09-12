# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
L2 Hypothesis oracle for the Tier-A text_validation decision engine
(testing-strategies.md §3.3; module docstring of src/text_validation.py is
the property spec).

Property IDs (new, keyed to the six documented decision properties):

  V-1  totality:           ``evaluate_printable_text`` returns a verdict on
                           every precomputed char model; the only failure
                           mode of ``ensure_printable_text`` is ValueError
                           with one of the three documented messages.
  V-2  verdict well-formed: kind ∈ {OK, DISALLOWED, TOO_LONG, NO_PRINTABLE};
                           error_index ∈ [0, n) for DISALLOWED;
                           window_lo ≤ window_hi ∈ [0, n] otherwise.
  V-3  strip-window maximality: for non-DISALLOWED verdicts the window is
                           exactly the maximal str.strip() window (reference:
                           lstrip/rstrip length arithmetic — str.isspace and
                           str.strip share the same whitespace set).
  V-4  TOO_LONG iff:       kind == TOO_LONG ⇔ window length > max_length.
  V-5  NO_PRINTABLE iff:   kind == NO_PRINTABLE ⇔ the window contains no
                           isalnum() character (same L*/N* set the garden's
                           ref_count_visible uses).
  V-6  first-disallowed:   DISALLOWED ⇔ some character violates the
                           control/format rule, and error_index points at
                           the FIRST violation (unicodedata reference scan).

Vacuity (P2, testing-strategies §3.4): V-3..V-5 kill the clamp/count garden
classes (M-01..M-09); V-1/V-6 are totality/discipline nets. The wrappers
(PrintableText/DomainName/PatternName) are pinned through pydantic
TypeAdapter at their Field boundaries.

Direction of the implication: the L1 unit suite (test_text_validation.py,
behavioral oracle) pins chosen inputs; this oracle samples the input space —
same property IDs, decorrelated generation.
"""

from __future__ import annotations

import unicodedata

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

from src.text_validation import (
    DOMAIN_MAX_LENGTH,
    FREETEXT_MAX_LENGTH,
    KIND_DISALLOWED,
    KIND_NO_PRINTABLE,
    KIND_OK,
    KIND_TOO_LONG,
    DomainName,
    PatternName,
    PrintableText,
    ensure_printable_text,
    evaluate_printable_text,
)

from tests.verification.strategies import (
    any_text,
    clean_text,
    clean_visible_text,
    disallowed_somewhere,
)

_printable_text_adapter: TypeAdapter[str] = TypeAdapter(PrintableText)
_domain_name_adapter: TypeAdapter[str] = TypeAdapter(DomainName)
_pattern_name_adapter: TypeAdapter[str] = TypeAdapter(PatternName)


def _char_model(value: str, allow_line_breaks: bool) -> tuple[list[int], list[bool], list[bool]]:
    """Mirror the per-character facts ensure_printable_text precomputes."""
    from src.text_validation import _category_code

    categories = [_category_code(ch) for ch in value]
    strip_ws = [ch.isspace() for ch in value]
    allowed_ws = [ch == "\t" or (allow_line_breaks and ch in ("\n", "\r")) for ch in value]
    return categories, strip_ws, allowed_ws


def _first_violation(value: str, allow_line_breaks: bool) -> int | None:
    """Reference scan: first index where the control/format rule breaks.

    The allowed-whitespace rule mirrors ``_char_model``'s ``allowed_ws``
    expression EXACTLY: ``\\t`` is always allowed, ``\\n``/``\\r`` only when
    ``allow_line_breaks``. (An earlier version whitelisted ``\\n``/``\\r``
    unconditionally via ``ch not in _ALLOWED_WHITESPACE`` — with
    ``allow_line_breaks=False`` the reference then disagreed with the SUT on
    any line-break-bearing draw; found 2026-09-12 by the mutmut clean-test
    run on value='\\n'.)
    """
    for i, ch in enumerate(value):
        if not unicodedata.category(ch).startswith("C"):
            continue
        if ch == "\t" or (allow_line_breaks and ch in ("\n", "\r")):
            continue
        return i
    return None


class TestV1Totality:
    @given(
        value=any_text(300),
        max_length=st.integers(min_value=0, max_value=10_000),
        allow_line_breaks=st.booleans(),
    )
    @settings(max_examples=50)
    def test_evaluate_never_raises_on_any_char_model(
        self, value: str, max_length: int, allow_line_breaks: bool
    ) -> None:
        categories, strip_ws, allowed_ws = _char_model(value, allow_line_breaks)
        verdict = evaluate_printable_text(
            value, categories, strip_ws, allowed_ws, max_length=max_length
        )
        assert verdict is not None

    @given(value=any_text(300), max_length=st.integers(min_value=0, max_value=10_000))
    @settings(max_examples=50)
    def test_ensure_raises_only_documented_value_errors(self, value: str, max_length: int) -> None:
        try:
            ensure_printable_text(value, field="v", max_length=max_length)
        except ValueError as exc:
            message = str(exc)
            assert any(
                needle in message
                for needle in (
                    "contains disallowed character",
                    "exceeds maximum length",
                    "must contain at least one visible",
                )
            ), f"undocumented ValueError message: {message!r}"


class TestV2VerdictWellFormed:
    @given(value=any_text(300), max_length=st.integers(min_value=0, max_value=10_000))
    @settings(max_examples=50)
    def test_kind_and_index_invariants(self, value: str, max_length: int) -> None:
        categories, strip_ws, allowed_ws = _char_model(value, allow_line_breaks=True)
        verdict = evaluate_printable_text(
            value, categories, strip_ws, allowed_ws, max_length=max_length
        )
        assert verdict.kind in (KIND_OK, KIND_DISALLOWED, KIND_TOO_LONG, KIND_NO_PRINTABLE)
        n = len(value)
        if verdict.kind == KIND_DISALLOWED:
            assert 0 <= verdict.error_index < n
        else:
            assert 0 <= verdict.window_lo <= verdict.window_hi <= n


class TestV3StripWindowMaximality:
    @given(value=clean_text(300), max_length=st.integers(min_value=0, max_value=10_000))
    @settings(max_examples=50)
    def test_window_equals_maximal_strip_window(self, value: str, max_length: int) -> None:
        categories, strip_ws, allowed_ws = _char_model(value, allow_line_breaks=True)
        verdict = evaluate_printable_text(
            value, categories, strip_ws, allowed_ws, max_length=max_length
        )
        assert verdict.kind != KIND_DISALLOWED
        expected_lo = len(value) - len(value.lstrip())
        # Half-open window [lo, hi): for ALL-whitespace input the rstrip length
        # is 0, but the well-formed window is (n, n) — exactly what
        # compute_strip_window's ``while hi > lo`` clamp yields and what the L1
        # pin test_all_whitespace_window_is_empty_at_n locks in. A bare
        # len(value.rstrip()) here would assert an inverted interval (n, 0),
        # violating V-2's own lo <= hi invariant (found 2026-09-12 by the
        # mutmut clean-test run drawing value=' ', max_length=0).
        expected_hi = max(expected_lo, len(value.rstrip()))
        assert (verdict.window_lo, verdict.window_hi) == (expected_lo, expected_hi), (
            f"window mismatch for {value!r}"
        )

    def test_all_whitespace_window_is_well_formed_empty_at_n(self) -> None:
        """Deterministic pin for the degenerate corner the property test can
        only sample rarely: all-whitespace input must yield the empty,
        well-formed (n, n) window regardless of draw luck."""
        for value in ("", " ", "   \t\n  "):
            categories, strip_ws, allowed_ws = _char_model(value, allow_line_breaks=True)
            verdict = evaluate_printable_text(
                value, categories, strip_ws, allowed_ws, max_length=0
            )
            n = len(value)
            assert (verdict.window_lo, verdict.window_hi) == (n, n)


class TestV4TooLongIff:
    @given(
        value=st.one_of(clean_text(300), clean_visible_text(300)),
        max_length=st.integers(min_value=0, max_value=10_000),
    )
    @settings(max_examples=50)
    def test_too_long_equivalent_to_window_bound(self, value: str, max_length: int) -> None:
        categories, strip_ws, allowed_ws = _char_model(value, allow_line_breaks=True)
        verdict = evaluate_printable_text(
            value, categories, strip_ws, allowed_ws, max_length=max_length
        )
        assert verdict.kind != KIND_DISALLOWED
        window_len = verdict.window_hi - verdict.window_lo
        assert (verdict.kind == KIND_TOO_LONG) == (window_len > max_length)


class TestV5NoPrintableIff:
    @given(
        value=st.one_of(clean_text(300), clean_visible_text(300)),
        max_length=st.integers(min_value=0, max_value=10_000),
    )
    @settings(max_examples=50)
    def test_no_printable_matches_window_scan(self, value: str, max_length: int) -> None:
        categories, strip_ws, allowed_ws = _char_model(value, allow_line_breaks=True)
        verdict = evaluate_printable_text(
            value, categories, strip_ws, allowed_ws, max_length=max_length
        )
        assert verdict.kind != KIND_DISALLOWED
        if verdict.kind == KIND_TOO_LONG:
            return
        window = value[verdict.window_lo : verdict.window_hi]
        has_visible = any(ch.isalnum() for ch in window)
        assert (verdict.kind == KIND_NO_PRINTABLE) == (not has_visible)


class TestV6FirstDisallowed:
    @given(
        value=any_text(300),
        allow_line_breaks=st.booleans(),
    )
    @settings(max_examples=50)
    def test_disallowed_iff_violation_and_index_is_first(
        self, value: str, allow_line_breaks: bool
    ) -> None:
        categories, strip_ws, allowed_ws = _char_model(value, allow_line_breaks)
        verdict = evaluate_printable_text(
            value, categories, strip_ws, allowed_ws, max_length=10_000
        )
        reference_index = _first_violation(value, allow_line_breaks)
        assert (verdict.kind == KIND_DISALLOWED) == (reference_index is not None)
        if reference_index is not None:
            assert verdict.error_index == reference_index

    def test_line_break_mode_matrix_sut_matches_reference(self) -> None:
        """Deterministic pin for the (\\n, \\r, \\t) × (True, False) matrix the
        property test can only sample rarely: \\t allowed in BOTH modes;
        \\n/\\r allowed only with allow_line_breaks. Locks SUT⇔reference
        agreement and the reference's index choice at index 0."""
        for ch in ("\n", "\r", "\t"):
            for allow_line_breaks in (True, False):
                categories, strip_ws, allowed_ws = _char_model(
                    ch, allow_line_breaks=allow_line_breaks
                )
                verdict = evaluate_printable_text(
                    ch, categories, strip_ws, allowed_ws, max_length=10_000
                )
                reference_index = _first_violation(ch, allow_line_breaks)
                assert (verdict.kind == KIND_DISALLOWED) == (
                    reference_index is not None
                ), (ch, allow_line_breaks)
        assert _first_violation("\t", False) is None
        assert _first_violation("\t", True) is None
        assert _first_violation("\n", True) is None
        assert _first_violation("\r", True) is None
        assert _first_violation("\n", False) == 0
        assert _first_violation("\r", False) == 0


class TestKnownCorners:
    """Deterministic pins for the highest-value adversarial characters."""

    def test_bom_prefix_is_disallowed(self) -> None:
        with pytest.raises(ValueError, match="contains disallowed character"):
            ensure_printable_text("\ufeffhello", field="v", max_length=100)

    def test_zwsp_suffix_is_disallowed(self) -> None:
        with pytest.raises(ValueError, match="contains disallowed character"):
            ensure_printable_text("hello\u200b", field="v", max_length=100)

    def test_whitespace_only_has_no_printable(self) -> None:
        with pytest.raises(ValueError, match="at least one visible"):
            ensure_printable_text("   \t\n  ", field="v", max_length=100)

    def test_clean_baseline_is_ok(self) -> None:
        assert ensure_printable_text("hello", field="v", max_length=100) == "hello"

    def test_zl_zp_separators_are_allowed_but_strip_away(self) -> None:
        """Discovered by this oracle: U+2028/U+2029 are Zl/Zp (allowed chars,
        not C-class) — alone they yield NO_PRINTABLE, never DISALLOWED."""
        for sep in ("\u2028", "\u2029"):
            with pytest.raises(ValueError, match="at least one visible"):
                ensure_printable_text(sep, field="v", max_length=100)

    def test_disallowed_strategy_always_rejected(self) -> None:
        @given(value=disallowed_somewhere(50))
        @settings(max_examples=20)
        def _property(value: str) -> None:
            with pytest.raises(ValueError, match="contains disallowed character"):
                ensure_printable_text(value, field="v", max_length=1000)

        _property()


class TestAnnotatedTypeBoundaries:
    """The three AfterValidator wrappers, pinned at their Field boundaries.

    pydantic wraps the raw ValueError of the AfterValidator into
    ValidationError (a ValueError subclass), so both layers are covered.
    """

    @given(
        text=clean_visible_text(40),
    )
    @settings(max_examples=20)
    def test_pattern_name_within_bound_accepted(self, text: str) -> None:
        assert len(_pattern_name_adapter.validate_python(text)) <= 100

    @given(
        length=st.integers(min_value=101, max_value=180),
        filler=st.sampled_from(["a", "Z", "9"]),
    )
    @settings(max_examples=10)
    def test_pattern_name_over_bound_rejected(self, length: int, filler: str) -> None:
        with pytest.raises(ValidationError):
            _pattern_name_adapter.validate_python(filler * length)

    @given(
        length=st.integers(min_value=DOMAIN_MAX_LENGTH + 1, max_value=DOMAIN_MAX_LENGTH + 60),
        filler=st.sampled_from(["a", "Z", "9"]),
    )
    @settings(max_examples=10)
    def test_domain_over_bound_rejected(self, length: int, filler: str) -> None:
        with pytest.raises(ValidationError):
            _domain_name_adapter.validate_python(filler * length)

    @given(
        overshoot=st.integers(min_value=1, max_value=60),
        filler=st.sampled_from(["a", "Z", "9"]),
    )
    @settings(max_examples=5)
    def test_freetext_over_bound_rejected(self, overshoot: int, filler: str) -> None:
        with pytest.raises(ValidationError):
            _printable_text_adapter.validate_python(filler * (FREETEXT_MAX_LENGTH + overshoot))
