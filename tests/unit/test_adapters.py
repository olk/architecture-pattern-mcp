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
Unit tests for src/tools/_adapters.py.

Verifies that adapter helpers raise MalformedArchitectureOverviewError (ERR_012)
on malformed input instead of silently synthesising placeholder values.
"""

import pytest

from src.errors import ERROR_INVALID_ARCHITECTURE, MalformedArchitectureOverviewError
from src.schemas.enums import ArchitectureStyle, PatternCategory
from src.tools._adapters import _parse_overview, design_from_dict


class TestParseOverviewValidInput:
    """Happy-path: valid overview dicts are accepted unchanged."""

    def test_accepts_valid_overview_dict(self):
        """Valid input returns a typed ArchitectureOverview."""
        data = {
            "style": "actor-based",
            "category": "structural",
            "principles": ["principle1", "principle2"],
            "constraints": ["constraint1"],
        }
        result = _parse_overview(data)

        assert result.style == ArchitectureStyle.ACTOR_BASED
        assert result.category == PatternCategory.STRUCTURAL
        assert result.principles == ["principle1", "principle2"]
        assert result.constraints == ["constraint1"]

    def test_preserves_exact_style_from_input(self):
        """The style value from the input is preserved when valid."""
        for style_value in ["microservices", "layered-monolith", "event-driven"]:
            data = {
                "style": style_value,
                "category": "structural",
                "principles": ["p1"],
                "constraints": [],
            }
            result = _parse_overview(data)
            assert result.style.value == style_value

    def test_accepts_minimal_valid_overview(self):
        """Only required fields (style, category, principles[min=1]) are needed."""
        data = {
            "style": "hexagonal",
            "category": "structural",
            "principles": ["p1"],
        }
        result = _parse_overview(data)
        assert result.style == ArchitectureStyle.HEXAGONAL
        assert result.category == PatternCategory.STRUCTURAL
        assert result.principles == ["p1"]


class TestParseOverviewInvalidInput:
    """Malformed input raises MalformedArchitectureOverviewError (ERR_012)."""

    def _assert_rejects(self, data: dict, expected_locator: str = "overview"):
        """Helper: asserts that _parse_overview rejects data with ERR_012."""
        with pytest.raises(MalformedArchitectureOverviewError) as exc_info:
            _parse_overview(data)
        exc = exc_info.value
        assert exc.code == ERROR_INVALID_ARCHITECTURE
        assert exc.locator == expected_locator
        assert exc.errors is not None
        assert len(exc.errors) > 0

    def test_rejects_unknown_style(self):
        """Unknown style string raises ERR_012, NOT actor-based placeholder."""
        self._assert_rejects({
            "style": "completely-unknown-style",
            "category": "structural",
            "principles": ["p1"],
        })

    def test_rejects_missing_style(self):
        """Missing 'style' field raises ERR_012."""
        self._assert_rejects({
            "category": "structural",
            "principles": ["p1"],
        })

    def test_rejects_missing_category(self):
        """Missing 'category' field raises ERR_012."""
        self._assert_rejects({
            "style": "microservices",
            "principles": ["p1"],
        })

    def test_rejects_invalid_category(self):
        """Non-existent category value raises ERR_012."""
        self._assert_rejects({
            "style": "microservices",
            "category": "not-a-real-category",
            "principles": ["p1"],
        })

    def test_rejects_empty_principles(self):
        """Empty principles list violates min_length=1 and raises ERR_012."""
        self._assert_rejects({
            "style": "microservices",
            "category": "structural",
            "principles": [],
        })

    def test_rejects_missing_principles(self):
        """Missing 'principles' field raises ERR_012."""
        self._assert_rejects({
            "style": "microservices",
            "category": "structural",
        })

    def test_rejects_null_overview(self):
        """None/null overview raises ERR_012."""
        self._assert_rejects({})

    def test_does_not_silently_default_to_actor_based(self, caplog):
        """
        When validation fails the error is raised, not silently replaced
        with ACTOR_BASED + STRUCTURAL + principle_placeholder.
        """
        import logging
        with caplog.at_level(logging.WARNING):
            with pytest.raises(MalformedArchitectureOverviewError):
                _parse_overview({
                    "style": "unknown",
                    "category": "structural",
                    "principles": [],
                })
        # Warning must have been logged
        assert any("Malformed architecture overview" in r.message for r in caplog.records)


class TestDesignFromDict:
    """design_from_dict propagates _parse_overview errors."""

    def _assert_rejects(self, data: dict):
        with pytest.raises(MalformedArchitectureOverviewError) as exc_info:
            design_from_dict(data)
        exc = exc_info.value
        assert exc.code == ERROR_INVALID_ARCHITECTURE

    def test_rejects_malformed_overview_in_design(self):
        """An overview that fails validation surfaces ERR_012."""
        self._assert_rejects({
            "overview": {
                "style": "not-a-valid-style",
                "category": "structural",
                "principles": ["p1"],
            },
            "components": [
                {
                    "id": "c1",
                    "name": "Component 1",
                    "type": "service",
                    "description": "A component",
                    "responsibilities": ["test"],
                }
            ],
        })

    def test_accepts_valid_architecture_design(self):
        """Full valid architecture dict is accepted."""
        data = {
            "overview": {
                "style": "actor-based",
                "category": "structural",
                "principles": ["p1"],
                "constraints": [],
            },
            "components": [
                {
                    "id": "api-gateway",
                    "name": "API Gateway",
                    "type": "gateway",
                    "description": "Gateway component",
                    "responsibilities": ["routing"],
                }
            ],
        }
        result = design_from_dict(data)
        assert result.overview.style == ArchitectureStyle.ACTOR_BASED
        assert len(result.components) == 1
