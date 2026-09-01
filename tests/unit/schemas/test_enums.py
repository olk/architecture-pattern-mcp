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
Unit tests for schema enumerations: PatternCategory, ArchitectureDomain, ArchitectureStyle.

Validates: FR-19 (PatternCategory), FR-31 (ArchitectureDomain), FR-32 (ArchitectureStyle)
"""

from src.schemas.enums import ArchitectureDomain, ArchitectureStyle, PatternCategory


class TestPatternCategory:
    """
    Test suite for PatternCategory enum.

    Validates: FR-19, IC-12, AC-19
    Scenario: SCEN-5 - PatternCategory has exactly 10 values
    """

    def test_has_exactly_10_values(self):
        """Verify PatternCategory enum contains exactly 10 values."""
        actual_values = len(PatternCategory)
        assert actual_values == 10, f"Expected 10 values, got {actual_values}"

    def test_all_categories_present(self):
        """Verify all required categories are present."""
        expected_categories = {
            "messaging",
            "structural",
            "cloud",
            "data",
            "ai_cognitive",
            "specialized",
            "api_gateway",
            "coordination",
            "dataflow",
            "presentation",
        }
        actual_categories = {item.value for item in PatternCategory}
        assert actual_categories == expected_categories

    def test_is_str_enum(self):
        """Verify PatternCategory is a str Enum for JSON serialization compatibility."""
        for item in PatternCategory:
            assert isinstance(item.value, str), f"{item.name} value is not a string"

    def test_enum_member_accessible(self):
        """Verify enum members are accessible by name."""
        assert PatternCategory.MESSAGING.value == "messaging"
        assert PatternCategory.STRUCTURAL.value == "structural"
        assert PatternCategory.CLOUD.value == "cloud"
        assert PatternCategory.DATA.value == "data"
        assert PatternCategory.AI_COGNITIVE.value == "ai_cognitive"
        assert PatternCategory.SPECIALIZED.value == "specialized"
        assert PatternCategory.API_GATEWAY.value == "api_gateway"
        assert PatternCategory.COORDINATION.value == "coordination"
        assert PatternCategory.DATAFLOW.value == "dataflow"
        assert PatternCategory.PRESENTATION.value == "presentation"


class TestArchitectureStyle:
    """
    Test suite for ArchitectureStyle enum.

    ArchitectureStyle contains canonical architectural approach names used as
    Pattern.name and ArchitectureDesign.overview.style values.
    Values match Pattern.name from pattern/*.json files exactly.
    Distinct from ArchitectureDomain which describes the problem space.
    """

    def test_has_40_values(self):
        """Verify ArchitectureStyle enum contains exactly 40 values (matching pattern JSON files)."""
        actual_values = len(ArchitectureStyle)
        assert actual_values == 40, f"Expected 40 values, got {actual_values}"

    def test_pattern_names_from_json_files(self):
        """Verify ArchitectureStyle values match Pattern.name from all 36 JSON files."""
        import glob, json
        expected = set()
        for path in glob.glob("pattern/*-architecture.json"):
            with open(path) as f:
                expected.add(json.load(f)["name"])
        actual_styles = {item.value for item in ArchitectureStyle}
        assert actual_styles == expected, (
            f"Mismatch: ArchitectureStyle={actual_styles}, JSON names={expected}, "
            f"only in Style: {expected - actual_styles}, only in enum: {actual_styles - expected}"
        )

    def test_is_str_enum(self):
        """Verify ArchitectureStyle is a str Enum for JSON serialization compatibility."""
        for item in ArchitectureStyle:
            assert isinstance(item.value, str), f"{item.name} value is not a string"

    def test_key_pattern_names_accessible(self):
        """Verify key ArchitectureStyle members are accessible by name."""
        assert ArchitectureStyle.MICROSERVICES.value == "microservices"
        assert ArchitectureStyle.HEXAGONAL.value == "hexagonal"
        assert ArchitectureStyle.SERVERLESS.value == "serverless"
        assert ArchitectureStyle.ACTOR_BASED.value == "actor-based"
        assert ArchitectureStyle.SAGA.value == "saga"
        assert ArchitectureStyle.LAYERED_MONOLITH.value == "layered-monolith"
        assert ArchitectureStyle.MODULAR_MONOLITH.value == "modular-monolith"


class TestArchitectureDomain:
    """
    Test suite for ArchitectureDomain enum.

    ArchitectureDomain contains 372 problem-space domain descriptors used for
    Pattern.suitable_domains and Pattern.unsuitable_domains filtering.
    Source corpus for DomainVectorIndex (FAISS) and DomainBM25Index.
    Distinct from ArchitectureStyle which describes the architectural approach.
    """

    def test_has_372_values(self):
        """Verify ArchitectureDomain enum contains exactly 372 values."""
        actual_values = len(ArchitectureDomain)
        assert actual_values == 372, f"Expected 372 values, got {actual_values}"

    def test_all_key_domains_present(self):
        """Verify all key problem-space domains are present."""
        key_domains = {
            "e-commerce",
            "fintech",
            "healthcare",
            "iot",
            "microservices",
            "cloud-native",
            "enterprise",
            "ai-agent-orchestration",
            "high-frequency-trading",
            "real-time-systems",
        }
        actual_domains = {item.value for item in ArchitectureDomain}
        for domain in key_domains:
            assert domain in actual_domains, f"Expected domain '{domain}' not found in ArchitectureDomain"

    def test_is_str_enum(self):
        """Verify ArchitectureDomain is a str Enum for JSON serialization compatibility."""
        for item in ArchitectureDomain:
            assert isinstance(item.value, str), f"{item.name} value is not a string"

    def test_domain_values_are_lowercase(self):
        """Verify all ArchitectureDomain values are lowercase strings."""
        for item in ArchitectureDomain:
            assert item.value == item.value.lower(), (
                f"ArchitectureDomain value '{item.value}' should be lowercase"
            )

    def test_sample_domains_match_pattern_files(self):
        """Verify ArchitectureDomain values match the problem-space domains used in pattern JSON files."""
        expected_from_patterns = {
            "enterprise-applications",
            "cloud-native-applications",
            "e-commerce-platforms",
            "ci-cd-environments",
            "multi-team-organizations",
            "platform-ecosystems",
            "polyglot-persistence-needs",
            "event-driven-architectures",
            "domain-driven-design",
            "high-concurrency",
        }
        actual_domains = {item.value for item in ArchitectureDomain}
        for domain in expected_from_patterns:
            assert domain in actual_domains, f"Pattern file domain '{domain}' not in ArchitectureDomain enum"
