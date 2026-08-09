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
Unit tests for PatternLoader class.

Test Case IDs: UT-10
Validates Requirements: FR-99, FR-183, FR-186, FR-189, FR-193, FR-197

Test Scenarios:
- SCEN-12: PatternLoader loads all *-architecture.json files
- SCEN-13: filter_by_domain normalizes domain

Acceptance Criteria:
- AC-183: PatternLoader class exists, accepts optional patterns_dir parameter
- AC-186: load_all method loads all JSON files
- AC-189: filter_by_domain method accepts domain string, returns filtered list
- AC-197: select_top_patterns method accepts domain and top_k, returns top-K candidates

Note: PatternLoader.score_by_quality was removed in the two-stage pipeline
refactor (issue #6, dead code). The new two-stage scoring lives in
ArchitecturePipeline._score_patterns, which uses RequirementWeights (0-1)
and 6 quality attributes.
"""

import json
import tempfile
from pathlib import Path

# Import the PatternLoader class
from src.patterns.loader import (
    QUALITY_ATTRIBUTES,
    PatternLoader,
)


class TestPatternLoaderInit:
    """AC-183: Verify PatternLoader class exists, accepts optional patterns_dir parameter"""

    def test_pattern_loader_class_exists(self):
        """Verify PatternLoader class can be instantiated"""
        # FR-183: PatternLoader class exists
        loader = PatternLoader()
        assert loader is not None
        assert isinstance(loader, PatternLoader)

    def test_pattern_loader_accepts_custom_patterns_dir(self):
        """Verify PatternLoader accepts optional patterns_dir parameter"""
        # AC-183: accepts optional patterns_dir parameter
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = PatternLoader(patterns_dir=tmpdir)
            assert loader._patterns_dir == Path(tmpdir)

    def test_pattern_loader_default_patterns_dir(self):
        """Verify PatternLoader uses default path when no patterns_dir provided"""
        loader = PatternLoader()
        expected = Path(__file__).parent.parent.parent / "pattern"
        assert loader._patterns_dir == expected


class TestLoadAll:
    """AC-186: Verify load_all method exists, loads all JSON files"""

    def test_load_all_returns_list(self):
        """Verify load_all returns a list of patterns"""
        loader = PatternLoader()
        patterns = loader.load_all()
        assert isinstance(patterns, list)

    def test_load_all_loads_architecture_json_files(self):
        """SCEN-12: PatternLoader loads all *-architecture.json files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test pattern files matching *-architecture.json pattern
            test_pattern = {
                "name": "test-pattern",
                "context": "test context",
                "category": "messaging",
                "suitable_domains": ["test-domain"],
                "quality_attributes": {
                    "performance": 8,
                    "scalability": 7,
                    "reliability": 9,
                    "maintainability": 6,
                    "simplicity": 5,
                    "security": 7
                }
            }

            pattern_file = Path(tmpdir) / "test-architecture.json"
            with open(pattern_file, 'w') as f:
                json.dump(test_pattern, f)

            loader = PatternLoader(patterns_dir=tmpdir)
            patterns = loader.load_all()

            assert len(patterns) == 1
            assert patterns[0]["name"] == "test-pattern"

    def test_load_all_lazy_loading(self):
        """Verify lazy loading - patterns loaded only on first call"""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = PatternLoader(patterns_dir=tmpdir)

            # Before load_all, cache should be empty
            assert loader._loaded is False
            assert loader._patterns_cache == []

            # Create a pattern file
            test_pattern = {
                "name": "test-pattern",
                "context": "test context",
                "category": "messaging",
                "suitable_domains": ["test-domain"],
                "quality_attributes": {
                    "performance": 8,
                    "scalability": 7,
                    "reliability": 9,
                    "maintainability": 6,
                    "simplicity": 5,
                    "security": 7
                }
            }
            pattern_file = Path(tmpdir) / "test-architecture.json"
            with open(pattern_file, 'w') as f:
                json.dump(test_pattern, f)

            # Call load_all
            patterns = loader.load_all()

            # After load_all, cache should be populated and flag set
            assert loader._loaded is True
            assert len(loader._patterns_cache) == 1

            # Second call should return cached data
            patterns2 = loader.load_all()
            assert patterns2 == patterns

    def test_load_all_empty_directory(self):
        """Verify load_all handles empty directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = PatternLoader(patterns_dir=tmpdir)
            patterns = loader.load_all()
            assert patterns == []

    def test_load_all_nonexistent_directory(self):
        """Verify load_all handles nonexistent directory gracefully"""
        loader = PatternLoader(patterns_dir="/nonexistent/path")
        patterns = loader.load_all()
        assert patterns == []


class TestFilterByDomain:
    """AC-189: Verify filter_by_domain method accepts domain string, returns filtered list"""

    def test_filter_by_domain_returns_list(self):
        """Verify filter_by_domain returns a list"""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = PatternLoader(patterns_dir=tmpdir)
            result = loader.filter_by_domain("test-domain")
            assert isinstance(result, list)

    def test_filter_by_domain_normalizes_domain(self):
        """SCEN-13: filter_by_domain normalizes domain (IC-31: lowercase + hyphens)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create pattern with hyphenated domain
            test_pattern = {
                "name": "test-pattern",
                "context": "test context",
                "category": "messaging",
                "suitable_domains": ["cloud-native", "microservices"],
                "quality_attributes": {
                    "performance": 8,
                    "scalability": 7,
                    "reliability": 9,
                    "maintainability": 6,
                    "simplicity": 5,
                    "security": 7
                }
            }

            pattern_file = Path(tmpdir) / "test-architecture.json"
            with open(pattern_file, 'w') as f:
                json.dump(test_pattern, f)

            loader = PatternLoader(patterns_dir=tmpdir)

            # Test domain normalization: "Cloud Native" -> "cloud-native"
            # IC-31: Domain normalization SHALL convert to lowercase and replace spaces with hyphens
            result = loader.filter_by_domain("Cloud Native")

            assert len(result) == 1
            assert result[0]["name"] == "test-pattern"

    def test_filter_by_domain_lowercase_conversion(self):
        """IC-31: Domain normalization converts to lowercase"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_pattern = {
                "name": "test-pattern",
                "context": "test context",
                "category": "messaging",
                "suitable_domains": ["telecom-and-real-time-messaging"],
                "quality_attributes": {
                    "performance": 8,
                    "scalability": 7,
                    "reliability": 9,
                    "maintainability": 6,
                    "simplicity": 5,
                    "security": 7
                }
            }

            pattern_file = Path(tmpdir) / "test-architecture.json"
            with open(pattern_file, 'w') as f:
                json.dump(test_pattern, f)

            loader = PatternLoader(patterns_dir=tmpdir)

            # Test lowercase: "Telecom and Real Time Messaging" -> "telecom and real time messaging"
            result = loader.filter_by_domain("TELECOM AND REAL TIME MESSAGING")

            assert len(result) == 1

    def test_filter_by_domain_spaces_to_hyphens(self):
        """IC-31: Domain normalization replaces spaces with hyphens"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_pattern = {
                "name": "test-pattern",
                "context": "test context",
                "category": "messaging",
                "suitable_domains": ["financial-trading-platforms"],
                "quality_attributes": {
                    "performance": 8,
                    "scalability": 7,
                    "reliability": 9,
                    "maintainability": 6,
                    "simplicity": 5,
                    "security": 7
                }
            }

            pattern_file = Path(tmpdir) / "test-architecture.json"
            with open(pattern_file, 'w') as f:
                json.dump(test_pattern, f)

            loader = PatternLoader(patterns_dir=tmpdir)

            # Test spaces to hyphens: "financial trading platforms" -> "financial-trading-platforms"
            result = loader.filter_by_domain("financial trading platforms")

            assert len(result) == 1

    def test_filter_by_domain_no_match(self):
        """Verify filter_by_domain returns empty list when no patterns match"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_pattern = {
                "name": "test-pattern",
                "context": "test context",
                "category": "messaging",
                "suitable_domains": ["cloud-native"],
                "quality_attributes": {
                    "performance": 8,
                    "scalability": 7,
                    "reliability": 9,
                    "maintainability": 6,
                    "simplicity": 5,
                    "security": 7
                }
            }

            pattern_file = Path(tmpdir) / "test-architecture.json"
            with open(pattern_file, 'w') as f:
                json.dump(test_pattern, f)

            loader = PatternLoader(patterns_dir=tmpdir)

            result = loader.filter_by_domain("monolith")

            assert len(result) == 0

    def test_filter_by_domain_excludes_unsuitable(self):
        """Verify filter_by_domain excludes patterns whose unsuitable_domains contains the normalized domain"""
        with tempfile.TemporaryDirectory() as tmpdir:
            suitable_pattern = {
                "name": "suitable-pattern",
                "context": "suitable context",
            "category": "messaging",
                "suitable_domains": ["e-commerce", "healthcare-integration"],
                "unsuitable_domains": ["simple-crud"],
                "quality_attributes": {
                    "performance": 8,
                    "scalability": 7,
                    "reliability": 9,
                    "maintainability": 6,
                    "simplicity": 5,
                    "security": 7
                }
            }
            unsuitable_pattern = {
                "name": "unsuitable-pattern",
                "context": "unsuitable context",
            "category": "messaging",
                "suitable_domains": ["healthcare-integration"],
                "unsuitable_domains": ["simple-crud", "e-commerce"],
                "quality_attributes": {
                    "performance": 8,
                    "scalability": 7,
                    "reliability": 9,
                    "maintainability": 6,
                    "simplicity": 5,
                    "security": 7
                }
            }

            for p in [suitable_pattern, unsuitable_pattern]:
                pf = Path(tmpdir) / f"{p['name']}-architecture.json"
                with open(pf, 'w') as f:
                    json.dump(p, f)

            loader = PatternLoader(patterns_dir=tmpdir)

            result = loader.filter_by_domain("e-commerce")
            names = [p["name"] for p in result]

            assert "suitable-pattern" in names
            assert "unsuitable-pattern" not in names

    def test_filter_by_domain_unsuitable_normalized(self):
        """Verify unsuitable_domains is normalized like suitable_domains"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pattern = {
                "name": "test-pattern",
                "context": "test context",
                "category": "messaging",
                "suitable_domains": ["cloud-native"],
                "unsuitable_domains": ["Simple CRUD Applications"],
                "quality_attributes": {
                    "performance": 8,
                    "scalability": 7,
                    "reliability": 9,
                    "maintainability": 6,
                    "simplicity": 5,
                    "security": 7
                }
            }

            pattern_file = Path(tmpdir) / "test-architecture.json"
            with open(pattern_file, 'w') as f:
                json.dump(pattern, f)

            loader = PatternLoader(patterns_dir=tmpdir)

            result = loader.filter_by_domain("cloud-native")
            assert len(result) == 1
            assert result[0]["name"] == "test-pattern"

            result2 = loader.filter_by_domain("simple crud applications")
            assert len(result2) == 0


class TestIntegration:
    """Integration tests for full PatternLoader workflow"""

    def test_full_workflow_load_filter_score(self):
        """Test complete workflow: load -> filter -> score"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test patterns matching real structure
            patterns = [
                {
                    "name": "api-gateway",
                    "context": "API gateway pattern",
                    "category": "api_gateway",
                    "suitable_domains": [
                        "microservices-architectures-with-multiple-backend-services",
                        "cloud-native-applications-on-kubernetes"
                    ],
                    "quality_attributes": {
                        "performance": 7,
                        "scalability": 8,
                        "reliability": 7,
                        "maintainability": 6,
                        "security": 8,
                        "simplicity": 5,
                    }
                },
                {
                    "name": "event-driven",
                    "context": "Event-driven pattern",
                    "category": "messaging",
                    "suitable_domains": [
                        "microservices-architectures-with-multiple-backend-services",
                        "distributed-data-pipelines"
                    ],
                    "quality_attributes": {
                        "performance": 8,
                        "scalability": 9,
                        "reliability": 8,
                        "maintainability": 7,
                        "security": 6,
                        "simplicity": 5,
                    }
                },
                {
                    "name": "monolith",
                    "context": "Monolith pattern",
                    "category": "structural",
                    "suitable_domains": ["simple-crud-applications"],
                    "quality_attributes": {
                        "performance": 6,
                        "scalability": 3,
                        "reliability": 5,
                        "maintainability": 4,
                        "security": 5,
                        "simplicity": 5,
                    }
                }
            ]

            for i, pattern in enumerate(patterns):
                pattern_file = Path(tmpdir) / f"pattern{i}-architecture.json"
                with open(pattern_file, 'w') as f:
                    json.dump(pattern, f)

            loader = PatternLoader(patterns_dir=tmpdir)

            # Step 1: Load all
            all_patterns = loader.load_all()
            assert len(all_patterns) == 3

            # Step 2: Filter by domain
            filtered = loader.filter_by_domain("microservices architectures with multiple backend services")
            # IC-31 normalization: lowercase, spaces to hyphens
            assert len(filtered) == 2

            # (Step 3 removed: PatternLoader.score_by_quality is gone —
            # see header note. Requirements-aware scoring now lives in
            # ArchitecturePipeline._score_patterns.)

    def test_domain_normalization_integration(self):
        """Test domain normalization works in full workflow"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pattern = {
                "name": "test-pattern",
                "context": "test context",
                "category": "cloud",
                "suitable_domains": ["cloud-native-applications-on-kubernetes"],
                "quality_attributes": {
                    "performance": 8,
                    "scalability": 8,
                    "reliability": 8,
                    "maintainability": 8,
                    "simplicity": 5,
                    "security": 8
                }
            }

            pattern_file = Path(tmpdir) / "test-architecture.json"
            with open(pattern_file, 'w') as f:
                json.dump(pattern, f)

            loader = PatternLoader(patterns_dir=tmpdir)

            # Test various domain input formats
            # Should all normalize to "cloud-native-applications-on-kubernetes"
            result1 = loader.filter_by_domain("cloud native applications on kubernetes")
            result2 = loader.filter_by_domain("Cloud Native Applications on Kubernetes")
            result3 = loader.filter_by_domain("CLOUD-NATIVE-APPLICATIONS-ON-KUBERNETES")

            assert len(result1) == 1
            assert len(result2) == 1
            assert len(result3) == 1
            assert result1[0]["name"] == result2[0]["name"] == result3[0]["name"]
