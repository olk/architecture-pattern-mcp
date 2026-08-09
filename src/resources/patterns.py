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
src/resources/patterns.py - Pattern resource wrapper.

Thin wrapper around PatternLoader that provides list/load for MCP resource handlers.
JSON-only payload — no markdown loading.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.patterns.loader import PatternLoader


class PatternResource:
    """
    Loads and exposes pattern resources for MCP resource handlers.

    Wraps a PatternLoader instance (which owns the in-memory cache of all
    pattern JSON files) and provides the flat dict interface expected by
    the FastMCP resource handlers.

    Attributes:
        _loader: PatternLoader instance (lazy-loaded on first access).
    """

    def __init__(self, loader: PatternLoader) -> None:
        self._loader = loader

    def load_pattern(self, name: str) -> dict[str, Any] | None:
        """
        Look up a single pattern by its 'name' field.

        Args:
            name: The pattern name (e.g. 'microservices', 'hexagonal').

        Returns:
            The pattern dict if found, otherwise None.
        """
        return self._loader.get_by_name(name)

    def list_pattern_resources(self) -> list[dict[str, Any]]:
        """
        List all available pattern resources as minimal metadata dicts.

        Returns:
            List of dicts, each with 'uri', 'name', and 'description' keys.
        """
        return [
            {
                "uri": f"pattern://{p['name']}",
                "name": p["name"],
                "description": p.get("context", "")[:120],
            }
            for p in self._loader.load_all()
        ]
