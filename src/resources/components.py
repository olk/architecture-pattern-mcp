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
src/resources/components.py - Component blueprint definitions.

Implements §9.1 (component://{type}) by deriving blueprints from pattern JSON files.
Each blueprint is built at startup by scanning all component_types across patterns.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from src.patterns.loader import PatternLoader

MAX_TECHNOLOGY_LENGTH = 60


class ComponentDefinition(BaseModel):
    id: str = Field(..., description="URL-safe slug identifier, e.g. 'api-gateway'")
    name: str = Field(..., description="Human-readable name, e.g. 'API Gateway'")
    category: str = Field(default="general", description="Component category")
    responsibilities: list[str] = Field(
        default_factory=list,
        description="List of responsibilities for this component type",
    )
    technology_options: list[str] = Field(
        default_factory=list,
        description="Technology choices commonly associated with this component",
    )
    related_patterns: list[str] = Field(
        default_factory=list,
        description="Pattern names that use this component type",
    )
    quality_impact: dict[str, float] = Field(
        default_factory=dict,
        description="Quality attribute impact scores (placeholder, empty for now)",
    )


def slugify(text: str) -> str:
    """Convert a string to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[_\s]+", "-", text).strip("-")


def _parse_component_type_entry(entry: str) -> tuple[str, str]:
    """Parse a 'Name: Description' component_types string into (name, description)."""
    if ":" in entry:
        name, _, desc = entry.partition(":")
        return name.strip(), desc.strip()
    return entry.strip(), ""


def build_component_blueprints(loader: PatternLoader) -> dict[str, ComponentDefinition]:
    """
    Scan all loaded patterns and build a deduplicated registry of ComponentDefinition.

    Parses each pattern's component_types field (format: "Component Name: description")
    and merges entries with the same slugified name, accumulating related_patterns
    and technology_options.

    Args:
        loader: PatternLoader with patterns already loaded (or lazily loaded on first call).

    Returns:
        Dict mapping slugified component id -> ComponentDefinition.
    """
    blueprints: dict[str, ComponentDefinition] = {}

    for pattern in loader.load_all():
        pattern_name = pattern.get("name", "")

        for entry in pattern.get("component_types", []):
            if not isinstance(entry, str):
                continue
            name, description = _parse_component_type_entry(entry)
            if not name:
                continue

            slug = slugify(name)
            responsibilities = [description] if description else []

            tech_options: list[str] = []
            for tech in pattern.get("technology_stack", []):
                if isinstance(tech, str) and len(tech) < MAX_TECHNOLOGY_LENGTH:
                    tech_options.append(tech)

            if slug in blueprints:
                existing = blueprints[slug]
                if description and description not in existing.responsibilities:
                    existing.responsibilities.append(description)
                if pattern_name not in existing.related_patterns:
                    existing.related_patterns.append(pattern_name)
                for opt in tech_options:
                    if opt not in existing.technology_options:
                        existing.technology_options.append(opt)
            else:
                blueprints[slug] = ComponentDefinition(
                    id=slug,
                    name=name,
                    category="general",
                    responsibilities=responsibilities,
                    technology_options=tech_options,
                    related_patterns=[pattern_name],
                    quality_impact={},
                )

    return blueprints
