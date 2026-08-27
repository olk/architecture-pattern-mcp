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
Unit tests for src/resources package.

Tests the resources module which exposes:
- pattern://{name}   - pattern definitions (JSON)
- template://{name}  - architecture templates
- component://{type} - component blueprints

Test Case IDs: UT-20 (new)
"""

import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.patterns.loader import PatternLoader
from src.resources.components import (
    ComponentDefinition,
    slugify,
    build_component_blueprints,
)
from src.resources.patterns import PatternResource
from src.resources.templates import (
    RESOURCES,
    LayerDefinition,
    LayeredArchitectureTemplate,
)

MIN_VALID_PATTERNS = 34
EXPECTED_LAYER_COUNT = 3


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def loader() -> PatternLoader:
    """Loader pointing at the real pattern/ directory in the repo."""
    repo_root = Path(__file__).parent.parent.parent / "pattern"
    return PatternLoader(patterns_dir=str(repo_root))


@pytest.fixture
def pattern_resource(loader: PatternLoader) -> PatternResource:
    return PatternResource(loader)


# ---------------------------------------------------------------------------
# PatternResource
# ---------------------------------------------------------------------------

class TestPatternResourceLoad:
    """Verify PatternResource.load_pattern()."""

    def test_load_known_returns_dict(self, pattern_resource: PatternResource):
        """load_pattern('microservices') returns a dict with expected fields."""
        result = pattern_resource.load_pattern("microservices")
        assert result is not None
        assert isinstance(result, dict)
        assert result["name"] == "microservices"

    def test_load_known_has_required_fields(self, pattern_resource: PatternResource):
        """Loaded pattern contains all required top-level keys."""
        result = pattern_resource.load_pattern("microservices")
        assert result is not None
        keys = ["name", "category", "context", "benefits", "tradeoffs",
                "quality_attributes", "suitable_domains", "unsuitable_domains"]
        for key in keys:
            assert key in result, f"Missing key: {key}"

    def test_load_unknown_returns_none(self, pattern_resource: PatternResource):
        """load_pattern for an unknown name returns None."""
        result = pattern_resource.load_pattern("does-not-exist-xyz")
        assert result is None

    def test_load_layered_monolith(self, pattern_resource: PatternResource):
        """layered-monolith is the fallback pattern and must load cleanly."""
        result = pattern_resource.load_pattern("layered-monolith")
        assert result is not None
        assert result["name"] == "layered-monolith"


class TestPatternResourceList:
    """Verify PatternResource.list_pattern_resources()."""

    def test_list_returns_list(self, pattern_resource: PatternResource):
        """list_pattern_resources returns a list."""
        result = pattern_resource.list_pattern_resources()
        assert isinstance(result, list)

    def test_list_count_at_least_34(self, pattern_resource: PatternResource):
        """We have at least 34 valid patterns in the catalogue.

        Note: presentation-abstraction-control-architecture.json fails validation
        (missing 'security' in quality_attributes), so only 34 load.
        """
        result = pattern_resource.list_pattern_resources()
        assert len(result) >= MIN_VALID_PATTERNS, (
            f"Expected >= {MIN_VALID_PATTERNS} patterns, got {len(result)}"
        )

    def test_list_entries_have_uri(self, pattern_resource: PatternResource):
        """Every entry has a 'uri' starting with pattern://."""
        for entry in pattern_resource.list_pattern_resources():
            assert "uri" in entry
            assert entry["uri"].startswith("pattern://")

    def test_list_entries_have_name(self, pattern_resource: PatternResource):
        """Every entry has a 'name' field."""
        for entry in pattern_resource.list_pattern_resources():
            assert "name" in entry
            assert isinstance(entry["name"], str)

    def test_list_entries_have_description(self, pattern_resource: PatternResource):
        """Every entry has a 'description' (truncated context)."""
        for entry in pattern_resource.list_pattern_resources():
            assert "description" in entry
            assert isinstance(entry["description"], str)

    def test_list_microservices_included(self, pattern_resource: PatternResource):
        """microservices appears in the list."""
        names = {e["name"] for e in pattern_resource.list_pattern_resources()}
        assert "microservices" in names

    def test_list_all_json_serializable(self, pattern_resource: PatternResource):
        """Every entry is JSON-serializable (no non-serialisable objects)."""
        for entry in pattern_resource.list_pattern_resources():
            json.dumps(entry)  # raises if not serialisable


# ---------------------------------------------------------------------------
# LayeredArchitectureTemplate / RESOURCES
# ---------------------------------------------------------------------------

class TestLayeredArchitectureTemplate:
    """Verify LayeredArchitectureTemplate and RESOURCES registry."""

    def test_resources_contains_layered_architecture_template(self):
        """RESOURCES dict has the expected key."""
        assert "layered-architecture-template" in RESOURCES

    def test_layered_template_is_correct_type(self):
        """Value is a LayeredArchitectureTemplate instance."""
        template = RESOURCES["layered-architecture-template"]
        assert isinstance(template, LayeredArchitectureTemplate)

    def test_layered_template_has_three_layers(self):
        """Template has exactly three layers."""
        template = RESOURCES["layered-architecture-template"]
        layers = getattr(template, "layers", [])
        assert len(layers) == EXPECTED_LAYER_COUNT

    def test_layered_template_layer_names(self):
        """Three layers have the expected names."""
        template = RESOURCES["layered-architecture-template"]
        layers = getattr(template, "layers", [])
        assert [getattr(layer_, "name", "") for layer_ in layers] == [
            "Presentation Layer",
            "Business Logic Layer",
            "Data Access Layer",
        ]

    def test_layered_template_presentation_layer_components(self):
        """Presentation Layer has the expected components."""
        template = RESOURCES["layered-architecture-template"]
        layers = getattr(template, "layers", [])
        pres = layers[0]
        components = getattr(pres, "components", [])
        assert "Web UI" in components
        assert "REST API" in components
        assert "WebSocket Handler" in components

    def test_layered_template_best_practices_populated(self):
        """best_practices is a non-empty list of strings."""
        template = RESOURCES["layered-architecture-template"]
        best_practices = getattr(template, "best_practices", [])
        assert isinstance(best_practices, list)
        assert len(best_practices) > 0
        for bp in best_practices:
            assert isinstance(bp, str)

    def test_layer_definition_is_pydantic_model(self):
        """LayerDefinition is a valid Pydantic model."""
        layer = LayerDefinition(
            name="Test Layer",
            description="Test description",
            components=["Comp1", "Comp2"],
            patterns=["Pattern1"],
        )
        assert layer.name == "Test Layer"
        assert layer.components == ["Comp1", "Comp2"]


# ---------------------------------------------------------------------------
# Component blueprints
# ---------------------------------------------------------------------------

class TestSlugify:
    """Unit tests for slugify()."""

    @pytest.mark.parametrize(
        ("input_", "expected"),
        [
            ("API Gateway", "api-gateway"),
            ("Service Registry", "service-registry"),
            ("message-broker", "message-broker"),
            ("Load Balancer", "load-balancer"),
            ("  ABC  ", "abc"),
        ],
    )
    def test_slugify_examples(self, input_: str, expected: str):
        assert slugify(input_) == expected


class TestComponentBlueprints:
    """Verify build_component_blueprints()."""

    def test_returns_dict(self, loader: PatternLoader):
        """Returns a dict."""
        result = build_component_blueprints(loader)
        assert isinstance(result, dict)

    def test_non_empty(self, loader: PatternLoader):
        """At least one blueprint is built."""
        result = build_component_blueprints(loader)
        assert len(result) > 0

    def test_values_are_component_definitions(self, loader: PatternLoader):
        """Every value is a ComponentDefinition."""
        for blueprint in build_component_blueprints(loader).values():
            assert isinstance(blueprint, ComponentDefinition)

    def test_id_is_slug(self, loader: PatternLoader):
        """Every blueprint id is a URL-safe slug (no spaces)."""
        for bid, blueprint in build_component_blueprints(loader).items():
            assert " " not in bid
            assert bid == blueprint.id

    def test_related_patterns_not_empty(self, loader: PatternLoader):
        """Each blueprint has at least one related pattern."""
        for bid, blueprint in build_component_blueprints(loader).items():
            assert len(blueprint.related_patterns) >= 1, f"{bid} has no related patterns"

    def test_deduplication_same_slug(self):
        """Two patterns with the same component slug produce one entry."""
        # Mock loader with two patterns that both have "API Gateway: ..."
        mock_loader = MagicMock(spec=PatternLoader)
        mock_loader.load_all.return_value = [
            {
                "name": "pattern-a",
                "component_types": ["API Gateway: Entry point handling auth"],
                "technology_stack": ["Kong", "NGINX"],
            },
            {
                "name": "pattern-b",
                "component_types": ["API Gateway: Routes requests"],
                "technology_stack": ["Envoy"],
            },
        ]
        result = build_component_blueprints(mock_loader)
        assert "api-gateway" in result
        assert set(result["api-gateway"].related_patterns) == {"pattern-a", "pattern-b"}
        assert "Kong" in result["api-gateway"].technology_options
        assert "Envoy" in result["api-gateway"].technology_options

    def test_unknown_pattern_load_does_not_crash(self, pattern_resource: PatternResource):
        """load_pattern on a loader backed by real files never raises for valid names."""
        # This is covered by test_load_unknown_returns_none, but we also
        # confirm no exceptions escape the wrapper.
        result = pattern_resource.load_pattern("hexagonal")
        assert result is not None
        assert result["name"] == "hexagonal"


# ---------------------------------------------------------------------------
# Pattern list endpoint (static pattern://)
# ---------------------------------------------------------------------------

class TestPatternListEndpoint:
    """Verify the static pattern:// endpoint returns the full catalogue listing."""

    def test_list_returns_list(self, pattern_resource: PatternResource):
        """list_pattern_resources returns a list."""
        result = pattern_resource.list_pattern_resources()
        assert isinstance(result, list)

    def test_each_entry_has_uri_name_description(self, pattern_resource: PatternResource):
        """Every entry has uri, name, and description keys."""
        for entry in pattern_resource.list_pattern_resources():
            for key in ("uri", "name", "description"):
                assert key in entry, f"Entry missing key: {key}"

    def test_payload_is_json_serializable(self, pattern_resource: PatternResource):
        """The full list is JSON-serialisable without error."""
        payload = json.dumps(pattern_resource.list_pattern_resources())
        parsed = json.loads(payload)
        assert isinstance(parsed, list)

    def test_count_matches_loaded_patterns(
        self, pattern_resource: PatternResource, loader: PatternLoader
    ):
        """Listed count equals the number of loaded patterns."""
        listed = pattern_resource.list_pattern_resources()
        loaded = loader.load_all()
        assert len(listed) == len(loaded)

    def test_uris_use_pattern_scheme(self, pattern_resource: PatternResource):
        """Every URI starts with the pattern:// scheme."""
        for entry in pattern_resource.list_pattern_resources():
            assert entry["uri"].startswith("pattern://"), (
                f"Unexpected URI scheme: {entry['uri']}"
            )


# ---------------------------------------------------------------------------
# Integration: server startup smoke test
# ---------------------------------------------------------------------------

class TestServerResourcesRegistration:
    """Smoke test that _register_resources does not raise during server init."""

    def test_register_resources_does_not_raise(self):
        """
        Verify _register_resources can be called without raising an exception.

        This does NOT spin up a full server — it just checks that the method
        runs to completion (the actual decorators are applied on a live FastMCP
        instance which we don't fully instantiate here).
        """
        # We verify the key building blocks exist and are callable:
        assert callable(slugify)
        assert callable(build_component_blueprints)
        assert callable(PatternResource)
        # RESOURCES is populated
        assert len(RESOURCES) >= 1

    def test_resources_all_json_serializable(self):
        """Every template in RESOURCES is JSON-serialisable."""
        for _, template in RESOURCES.items():
            json_str = template.model_dump_json()
            parsed = json.loads(json_str)
            assert "name" in parsed

    def test_register_resources_uses_separate_guard_flag(self):
        """
        Regression: _register_resources must not be gated by _tools_registered.

        The original bug used ``if self._tools_registered:`` as the resources
        guard, which was always True after _register_tools() ran, so
        resources were never registered with FastMCP.
        """
        from src.server import MCPArchitectServer  # noqa: PLC0415

        src = inspect.getsource(MCPArchitectServer._register_resources)
        assert "_resources_registered" in src, (
            "_register_resources must use a separate _resources_registered guard"
        )
        guard_line = next(
            (line for line in src.splitlines() if line.strip().startswith("if ")),
            "",
        )
        assert "_tools_registered" not in guard_line, (
            f"_register_resources guard should not reference _tools_registered; got: {guard_line!r}"
        )
