# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
L2 oracles for configuration decision surfaces
(src/config_expansion.py — mutmut-scoped, previously L1-only; and the
src/config.py Field/validator boundaries).

  CE-1  no-op on absence: strings without a ``{env:`` occurrence pass
        through ``expand_env`` unchanged.
  CE-2  env-wins: ``{env:VAR}`` expands to the environ value when set —
        including the empty string.
  CE-3  default-wins-when-unset: ``{env:VAR:-d}`` expands to ``d`` when
        VAR is unset; the empty default ``{env:VAR:-}`` expands to "".
  CE-4  idempotence: re-expanding an expanded string is the identity
        (environ values are drawn brace-free).
  CE-5  structural recursion: ``expand_env_in_obj`` expands exactly the
        string leaves of a generated JSON-like tree; scalars pass through.
  CE-6  malformed placeholders are untouched (lowercase var, digit-led
        var, truncated forms).
  CV-*  config validator Field boundaries (ValidationConfig retries,
        RetrievalConfig alpha / blend-weight domains).

Vacuity (P2): CE-2/CE-3/CE-6 kill regex-group and default-branch mutants
in the scoped module (baseline: 30/30 killed at L1 — the L2 layer must
hold the ratio); CV-* kill Field-bound mutants.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from src.config import RetrievalConfig, ValidationConfig
from src.config_expansion import expand_env, expand_env_in_obj

_env_name = st.from_regex(r"[A-Z][A-Z0-9_]{0,11}", fullmatch=True)
# Brace-free payload: guarantees the idempotence fixed point (CE-4).
_brace_free_text = st.text(
    alphabet=st.characters(exclude_characters="{}/\\"),
    max_size=60,
)


class TestCE1NoOpOnAbsence:
    @given(value=st.text(max_size=120).filter(lambda s: "{env:" not in s))
    @settings(max_examples=40, deadline=None)
    def test_pattern_free_string_unchanged(self, value: str) -> None:
        assert expand_env(value, {}) == value


class TestCE2EnvWins:
    @given(var=_env_name, value=st.text(max_size=60))
    @settings(max_examples=40, deadline=None)
    def test_set_var_expands_to_its_value(self, var: str, value: str) -> None:
        assert expand_env("{env:" + var + "}", {var: value}) == value

    @given(var=_env_name, prefix=st.text(max_size=20), suffix=st.text(max_size=20))
    @settings(max_examples=25, deadline=None)
    def test_expansion_is_inplace_in_larger_string(
        self, var: str, prefix: str, suffix: str
    ) -> None:
        env_value = "ENVVALUE"
        raw = prefix + "{env:" + var + "}" + suffix
        expected = prefix + env_value + suffix
        assert expand_env(raw, {var: env_value}) == expected


class TestCE3DefaultWhenUnset:
    # The placeholder grammar bounds the default with `[^}]*` — defaults are
    # therefore brace-free by construction, and the strategies below mirror
    # that domain exactly.
    @given(var=_env_name, default=_brace_free_text)
    @settings(max_examples=40, deadline=None)
    def test_unset_var_expands_to_default(self, var: str, default: str) -> None:
        raw = "{env:" + var + ":-" + default + "}"
        assert expand_env(raw, {}) == default

    @given(var=_env_name)
    @settings(max_examples=15, deadline=None)
    def test_bare_placeholder_expands_to_empty(self, var: str) -> None:
        assert expand_env("{env:" + var + "}", {}) == ""

    @given(var=_env_name, default=_brace_free_text)
    @settings(max_examples=15, deadline=None)
    def test_empty_string_env_value_wins_over_default(
        self, var: str, default: str
    ) -> None:
        raw = "{env:" + var + ":-" + default + "}"
        assert expand_env(raw, {var: ""}) == "", "set-but-empty must win"


class TestCE4Idempotence:
    @given(
        value=_brace_free_text,
        environ=st.dictionaries(_env_name, _brace_free_text, max_size=4),
    )
    @settings(max_examples=40, deadline=None)
    def test_reexpansion_is_identity(
        self, value: str, environ: dict[str, str]
    ) -> None:
        once = expand_env(value, environ)
        assert expand_env(once, environ) == once


class TestCE5StructuralRecursion:
    @given(
        tree=st.recursive(
            st.one_of(
                st.integers(),
                st.floats(allow_nan=False, allow_infinity=False),
                st.booleans(),
                st.none(),
                _brace_free_text,
            ),
            lambda children: st.one_of(
                st.lists(children, max_size=3),
                st.dictionaries(_env_name, children, max_size=3),
            ),
            max_leaves=8,
        ),
        var=_env_name,
    )
    @settings(max_examples=30, deadline=None)
    def test_only_string_leaves_expand(self, tree: Any, var: str) -> None:
        environ = {var: "EXPANDED"}
        result = expand_env_in_obj(tree, environ)

        def _walk(original: Any, expanded: Any) -> None:
            """Shadow walker: dict/list recursion + scalar identity + leaf law."""
            if isinstance(original, str):
                assert expanded == expand_env(original, environ), (
                    f"string leaf diverged: {original!r} → {expanded!r}"
                )
            elif isinstance(original, dict):
                assert isinstance(expanded, dict)
                assert list(expanded) == list(original), "keys must be preserved"
                for key in original:
                    _walk(original[key], expanded[key])
            elif isinstance(original, list):
                assert isinstance(expanded, list)
                assert len(expanded) == len(original)
                for orig_item, exp_item in zip(
                    original, expanded, strict=len(original) == len(expanded)
                ):
                    _walk(orig_item, exp_item)
            else:
                assert expanded == original, f"scalar mutated: {original!r}"

        _walk(tree, result)

    @given(payload=st.one_of(st.integers(), st.booleans(), st.none()))
    @settings(max_examples=10, deadline=None)
    def test_scalars_pass_through_untouched(self, payload: Any) -> None:
        assert expand_env_in_obj(payload, {"A": "x"}) == payload


class TestCE6MalformedUntouched:
    @given(
        garbage=st.sampled_from(
            [
                "{env:lowercase_var}",
                "{env:1LEADING_DIGIT}",
                "{env:",
                "{env",
                "env:VAR}",
                "{ENV:VAR}",
                "{env:VAR:-",  # unterminated default
            ]
        )
    )
    @settings(max_examples=15, deadline=None)
    def test_malformed_placeholders_pass_through(self, garbage: str) -> None:
        assert expand_env(garbage, {"LOWERCASE_VAR": "x", "VAR": "x"}) == garbage


class TestCVValidatorBoundaries:
    @given(max_retries=st.integers(min_value=0, max_value=10))
    @settings(max_examples=15, deadline=None)
    def test_validation_config_retries_domain(self, max_retries: int) -> None:
        vc = ValidationConfig(max_retries=max_retries)
        assert vc.max_retries == max_retries

    @given(max_retries=st.sampled_from([-1, 11, 100]))
    @settings(max_examples=5, deadline=None)
    def test_validation_config_rejects_out_of_domain(self, max_retries: int) -> None:
        with pytest.raises(ValidationError):
            ValidationConfig(max_retries=max_retries)

    @given(
        alpha=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=15, deadline=None)
    def test_smoothing_alpha_domain(self, alpha: float) -> None:
        assert RetrievalConfig(weight_smoothing_alpha=alpha) is not None

    @given(
        alpha=st.sampled_from([-0.001, 1.001, float("nan")]),
    )
    @settings(max_examples=5, deadline=None)
    def test_smoothing_alpha_rejects_out_of_domain(self, alpha: float) -> None:
        with pytest.raises(ValidationError):
            RetrievalConfig(weight_smoothing_alpha=alpha)

    @given(
        analysis=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=15, deadline=None)
    def test_blend_weight_field_bounds(self, analysis: float) -> None:
        # Inside [0,1]^2 the sum-to-1 validator decides (covered by S-3);
        # outside the Field bounds rejection is unconditional.
        with pytest.raises(ValidationError):
            RetrievalConfig(analysis_blend_weight=analysis, fusion_blend_weight=2.0 - analysis)
