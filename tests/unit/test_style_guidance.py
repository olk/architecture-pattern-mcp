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

"""Tests for the per-style canonical-shape guidance injected into the
GENERATE-phase system prompt.

Guards the contract that every ArchitectureStyle enum value has explicit
guidance and that no entry can balloon the prompt size.
"""

import pytest

from src.prompts.style_guidance import (
    DEFAULT_STYLE_GUIDANCE,
    STYLE_GUIDANCE,
    get_style_guidance,
)
from src.schemas.enums import ArchitectureStyle


class TestStyleGuidanceCoverage:
    """Every enum style must have explicit guidance."""

    def test_every_architecture_style_has_explicit_guidance(self):
        missing = [s.value for s in ArchitectureStyle if s.value not in STYLE_GUIDANCE]
        assert missing == []

    def test_guidance_count_matches_enum_count(self):
        assert len(STYLE_GUIDANCE) == len(ArchitectureStyle)

    def test_no_extra_keys_beyond_enum_values(self):
        enum_values = {s.value for s in ArchitectureStyle}
        extra = set(STYLE_GUIDANCE) - enum_values
        assert extra == set()


@pytest.mark.parametrize("style", list(ArchitectureStyle), ids=lambda s: s.value)
class TestStyleGuidanceEntryQuality:
    """Per-entry quality gates, reported per style."""

    def test_entry_is_meaningful(self, style: ArchitectureStyle):
        guidance = STYLE_GUIDANCE[style.value]
        assert len(guidance) >= 50, f"{style.value}: guidance too short ({len(guidance)} chars)"

    def test_entry_within_size_bound(self, style: ArchitectureStyle):
        guidance = STYLE_GUIDANCE[style.value]
        assert len(guidance) <= 800, f"{style.value}: guidance too long ({len(guidance)} chars)"

    def test_entry_has_no_placeholders(self, style: ArchitectureStyle):
        guidance = STYLE_GUIDANCE[style.value].upper()
        for placeholder in ("TODO", "XXX", "TBD", "PLACEHOLDER", "FILL ME"):
            assert placeholder not in guidance, f"{style.value}: contains {placeholder}"


class TestDefaultFallback:
    def test_default_fallback_is_meaningful(self):
        assert 50 <= len(DEFAULT_STYLE_GUIDANCE) <= 800

    def test_default_fallback_has_no_placeholders(self):
        upper = DEFAULT_STYLE_GUIDANCE.upper()
        for placeholder in ("TODO", "XXX", "TBD", "PLACEHOLDER"):
            assert placeholder not in upper


class TestGetStyleGuidance:
    def test_known_style_returns_exact_entry(self):
        for style in ArchitectureStyle:
            assert get_style_guidance(style.value) is STYLE_GUIDANCE[style.value]

    def test_unknown_style_returns_default(self):
        assert get_style_guidance("definitely-not-a-style") is DEFAULT_STYLE_GUIDANCE

    def test_empty_string_returns_default(self):
        assert get_style_guidance("") is DEFAULT_STYLE_GUIDANCE
