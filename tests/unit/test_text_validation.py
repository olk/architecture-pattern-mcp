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
Unit tests for src.text_validation.

Tests ensure_printable_text() and the PrintableText / DomainName / PatternName
Annotated types against empty, whitespace-only, tab-only, mixed-whitespace,
zero-width, BOM, and control-character inputs.
"""

import pytest
from pydantic import ValidationError

from src.text_validation import (
    DOMAIN_MAX_LENGTH,
    FREETEXT_MAX_LENGTH,
    PATTERN_NAME_MAX_LENGTH,
    DomainName,
    PatternName,
    PrintableText,
    ensure_printable_text,
)


class TestEnsurePrintableTextFreeText:
    """Tests for ensure_printable_text with allow_line_breaks=True (free-text mode)."""

    @pytest.mark.parametrize(
        ("value", "expected_msg_contains"),
        [
            ("", "visible letter or digit"),
            (" ", "whitespace-only"),
            ("\t", "whitespace-only"),
            ("\n", "whitespace-only"),
            ("  \t  ", "whitespace-only"),
            (" \t\n ", "whitespace-only"),
            (
                "\u00a0",
                "whitespace-only",
            ),  # NBSP
            (
                "\u200b",
                "disallowed character",
            ),  # zero-width space (Cf, not whitespace)
            (
                "\u200c",
                "disallowed character",
            ),  # zero-width non-joiner (Cf)
            (
                "\ufeff",
                "disallowed character",
            ),  # BOM (Cf)
            ("\x00", "disallowed character"),  # null
            ("\x07", "disallowed character"),  # bell
            ("\x1b", "disallowed character"),  # escape
            ("\x85", "disallowed character"),  # C1 control NEL
            ("\u200b" * 10, "disallowed character"),  # zero-width only
            ("---", "visible letter or digit"),  # punctuation only
            ("___", "visible letter or digit"),  # underscore only
        ],
    )
    def test_rejects_bad_inputs(self, value: str, expected_msg_contains: str) -> None:
        with pytest.raises(ValueError, match=expected_msg_contains):
            ensure_printable_text(value, field="test_field", allow_line_breaks=True)

    @pytest.mark.parametrize(
        ("value", "expected_stripped"),
        [
            ("foo", "foo"),
            ("  foo  ", "foo"),
            ("\tbar\t", "bar"),
            ("foo bar", "foo bar"),
            ("foo\nbar", "foo\nbar"),  # newlines allowed
            ("foo\rbar", "foo\rbar"),  # CR allowed
            ("foo\tbar", "foo\tbar"),  # tab allowed
            (
                "Requirements:\n- scalable\n- secure",
                "Requirements:\n- scalable\n- secure",
            ),  # multi-line requirements
            ("Zahlungsverarbeitung", "Zahlungsverarbeitung"),  # German umlauts
            ("データ処理", "データ処理"),  # Japanese
            ("e-commerce-platform", "e-commerce-platform"),
            ("Payment  Gateway", "Payment  Gateway"),  # double space preserved
        ],
    )
    def test_accepts_valid_inputs(self, value: str, expected_stripped: str) -> None:
        result = ensure_printable_text(value, field="test_field", allow_line_breaks=True)
        assert result == expected_stripped
        assert result == result.strip()  # never has outer whitespace

    def test_field_name_in_control_char_error(self) -> None:
        with pytest.raises(ValueError, match="my_field"):
            ensure_printable_text("test\x00field", field="my_field", allow_line_breaks=True)

    def test_max_length_enforced_after_strip(self) -> None:
        long_value = "a" * (FREETEXT_MAX_LENGTH + 10)
        with pytest.raises(ValueError, match="exceeds maximum length"):
            ensure_printable_text(
                "  " + long_value + "  ", field="test_field", allow_line_breaks=True
            )

    def test_max_length_respected(self) -> None:
        value = "a" * FREETEXT_MAX_LENGTH
        result = ensure_printable_text(value, field="test_field")
        assert result == value


class TestEnsurePrintableTextDomain:
    """Tests for ensure_printable_text with allow_line_breaks=False (domain mode)."""

    @pytest.mark.parametrize(
        "value",
        [
            "foo\nbar",
            "foo\rbar",
            "foo\n",
            "foo\r",
        ],
    )
    def test_rejects_line_breaks_in_domain(self, value: str) -> None:
        with pytest.raises(ValueError, match="disallowed character"):
            ensure_printable_text(value, field="domain", allow_line_breaks=False)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("microservices", "microservices"),
            ("  e-commerce  ", "e-commerce"),
            ("\tdata-platform\t", "data-platform"),
            ("API-Gateway", "API-Gateway"),
            ("Payment Processing", "Payment Processing"),
        ],
    )
    def test_accepts_valid_domains(self, value: str, expected: str) -> None:
        result = ensure_printable_text(value, field="domain", allow_line_breaks=False)
        assert result == expected

    def test_max_length_enforced(self) -> None:
        long_domain = "a" * (DOMAIN_MAX_LENGTH + 10)
        with pytest.raises(ValueError, match="exceeds maximum length"):
            ensure_printable_text(
                long_domain, field="domain", allow_line_breaks=False, max_length=DOMAIN_MAX_LENGTH
            )


class TestAnnotatedTypes:
    """Test PrintableText / DomainName / PatternName Annotated types via pydantic TypeAdapter."""

    @pytest.mark.parametrize(
        ("type_adapter_cls", "invalid_value"),
        [
            (PrintableText, ""),
            (PrintableText, "   "),
            (PrintableText, "\t\t"),
            (PrintableText, "\u200b"),
            (PrintableText, "\ufeff"),
            (PrintableText, "---"),
            (DomainName, ""),
            (DomainName, "  "),
            (DomainName, "foo\nbar"),
            (PatternName, ""),
            (PatternName, "\u200b"),
        ],
    )
    def test_rejects_invalid_via_pydantic(
        self, type_adapter_cls: type, invalid_value: str
    ) -> None:
        from pydantic import TypeAdapter

        ta = TypeAdapter(type_adapter_cls)
        with pytest.raises(ValidationError):
            ta.validate_python(invalid_value)

    @pytest.mark.parametrize(
        ("type_adapter_cls", "valid_value", "expected"),
        [
            (PrintableText, "build a scalable API gateway", "build a scalable API gateway"),
            (PrintableText, "  multi-line\nreq  ", "multi-line\nreq"),  # outer stripped
            (DomainName, "microservices", "microservices"),
            (DomainName, "  e-commerce  ", "e-commerce"),  # outer stripped
            (PatternName, "pipe-and-filter", "pipe-and-filter"),
            (PatternName, "  cqrs  ", "cqrs"),  # outer stripped
        ],
    )
    def test_accepts_valid_via_pydantic(
        self, type_adapter_cls: type, valid_value: str, expected: str
    ) -> None:
        from pydantic import TypeAdapter

        ta = TypeAdapter(type_adapter_cls)
        result = ta.validate_python(valid_value)
        assert result == expected

    def test_printable_text_max_length(self) -> None:
        from pydantic import TypeAdapter

        ta = TypeAdapter(PrintableText)
        with pytest.raises(ValidationError):
            ta.validate_python("a" * (FREETEXT_MAX_LENGTH + 1))

    def test_domain_name_max_length(self) -> None:
        from pydantic import TypeAdapter

        ta = TypeAdapter(DomainName)
        with pytest.raises(ValidationError):
            ta.validate_python("a" * (DOMAIN_MAX_LENGTH + 1))

    def test_pattern_name_max_length(self) -> None:
        from pydantic import TypeAdapter

        ta = TypeAdapter(PatternName)
        with pytest.raises(ValidationError):
            ta.validate_python("a" * (PATTERN_NAME_MAX_LENGTH + 1))
