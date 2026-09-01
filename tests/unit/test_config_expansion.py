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
Unit tests for src/config_expansion module.

Tests expand_env and expand_env_in_obj functions.
"""


from src.config_expansion import expand_env, expand_env_in_obj


class TestExpandEnv:
    """Tests for expand_env function."""

    def test_no_env_var_returns_empty_string(self):
        """Unset var with no default returns empty string."""
        result = expand_env("{env:MISSING_VAR}", {"OTHER": "value"})
        assert result == ""

    def test_no_env_var_with_default(self):
        """Unset var with default returns the default."""
        result = expand_env("{env:MISSING_VAR:-fallback}", {})
        assert result == "fallback"

    def test_unset_var_with_empty_default(self):
        """Unset var with :- returns empty string."""
        result = expand_env("{env:MISSING_VAR:-}", {})
        assert result == ""

    def test_set_var_returns_value(self):
        """Set var returns its value."""
        result = expand_env("{env:MY_VAR}", {"MY_VAR": "hello"})
        assert result == "hello"

    def test_set_var_ignores_default(self):
        """Set var ignores the default."""
        result = expand_env("{env:MY_VAR:-ignored}", {"MY_VAR": "actual"})
        assert result == "actual"

    def test_set_var_empty_string(self):
        """Set but empty var returns empty string (not default)."""
        result = expand_env("{env:MY_VAR:-default}", {"MY_VAR": ""})
        assert result == ""

    def test_multiple_vars_in_string(self):
        """Multiple vars in one string are all expanded."""
        result = expand_env(
            "{env:A:-a}/{env:B:-b}/{env:C}",
            {"A": "x", "B": "y", "C": "z"}
        )
        assert result == "x/y/z"

    def test_var_at_start(self):
        """Var at start of string works."""
        result = expand_env("{env:PREFIX:-default}suffix", {"PREFIX": "pre"})
        assert result == "presuffix"

    def test_var_at_end(self):
        """Var at end of string works."""
        result = expand_env("prefix{env:SUFFIX:-default}", {"SUFFIX": "suf"})
        assert result == "prefixsuf"

    def test_multiple_vars_adjacent(self):
        """Adjacent vars work."""
        result = expand_env("{env:A}{env:B}", {"A": "x", "B": "y"})
        assert result == "xy"

    def test_literal_braces_not_expanded(self):
        """Literal braces without env: prefix are untouched."""
        result = expand_env("just {some} text", {})
        assert result == "just {some} text"

    def test_empty_string(self):
        """Empty string returns empty string."""
        result = expand_env("", {})
        assert result == ""

    def test_no_placeholders(self):
        """String without placeholders returns unchanged."""
        result = expand_env("no placeholders here", {"VAR": "val"})
        assert result == "no placeholders here"


class TestExpandEnvInObj:
    """Tests for expand_env_in_obj function."""

    def test_dict_string_values_expanded(self):
        """String values in dict are expanded."""
        obj = {"key": "{env:VAR:-default}"}
        result = expand_env_in_obj(obj, {"VAR": "expanded"})
        assert result == {"key": "expanded"}

    def test_nested_dict_expanded(self):
        """Nested dicts are expanded recursively."""
        obj = {"outer": {"inner": "{env:DEEP:-original}"}}
        result = expand_env_in_obj(obj, {"DEEP": "deep_value"})
        assert result == {"outer": {"inner": "deep_value"}}

    def test_list_expanded(self):
        """String values in lists are expanded."""
        obj = ["{env:A:-a}", "{env:B:-b}"]
        result = expand_env_in_obj(obj, {"A": "x", "B": "y"})
        assert result == ["x", "y"]

    def test_list_in_dict_expanded(self):
        """Lists inside dicts are expanded."""
        obj = {"items": ["{env:ITEM:-default}"]}
        result = expand_env_in_obj(obj, {"ITEM": "value"})
        assert result == {"items": ["value"]}

    def test_non_string_values_unchanged(self):
        """Non-string values (int, float, bool, None) returned as-is."""
        obj = {"int": 42, "float": 3.14, "bool": True, "none": None}
        result = expand_env_in_obj(obj, {})
        assert result == {"int": 42, "float": 3.14, "bool": True, "none": None}

    def test_mixed_structure(self):
        """Complex nested structure with mixed types."""
        obj = {
            "provider": "{env:GENERATOR_PROVIDER:-openai}",
            "config": {
                "model": "{env:GENERATOR_MODEL:-gpt-4o-mini}",
                "api_key": "{env:GENERATOR_API_KEY}",
                "temperature": 0.1,
                "enabled": True,
            }
        }
        result = expand_env_in_obj(obj, {
            "GENERATOR_PROVIDER": "minimax",
            "GENERATOR_MODEL": "MiniMax-M2.7",
            "GENERATOR_API_KEY": "sk-secret",
        })
        assert result == {
            "provider": "minimax",
            "config": {
                "model": "MiniMax-M2.7",
                "api_key": "sk-secret",
                "temperature": 0.1,
                "enabled": True,
            }
        }

    def test_empty_dict(self):
        """Empty dict returns empty dict."""
        result = expand_env_in_obj({}, {})
        assert result == {}

    def test_empty_list(self):
        """Empty list returns empty list."""
        result = expand_env_in_obj([], {})
        assert result == []

    def test_dict_with_only_numeric_values(self):
        """Dict with only numeric values returns unchanged."""
        obj = {"count": 5, "ratio": 0.5}
        result = expand_env_in_obj(obj, {"COUNT": "100"})
        assert result == {"count": 5, "ratio": 0.5}

    def test_nested_list_of_dicts(self):
        """Nested list containing dicts is expanded."""
        obj = [{"key": "{env:VAR:-default}"}]
        result = expand_env_in_obj(obj, {"VAR": "found"})
        assert result == [{"key": "found"}]
