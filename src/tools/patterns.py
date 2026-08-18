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
Pattern access tools - MCP tools for listing and retrieving architecture patterns.

These tools provide direct access to the pattern catalog without going through the
LLM-based pipeline. They are reliable alternatives to the MCP Resources, especially
in clients that have trouble with custom URI schemes (e.g. OpenCode's @-mention
handling of pattern:// URIs, see opencode#30928).

Architecture:
- DP-4: Factory Pattern - Consistent tool initialization
- DP-5: Dependency Injection - Constructor injection of PatternLoader
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from fastmcp.tools.base import ToolAnnotations
from pydantic import Field

from src.resources.patterns import PatternResource

logger = logging.getLogger(__name__)


ERROR_PATTERN_CATALOG = "ERR_013"

_VALID_CATEGORIES = (
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
)


class ListArchitecturePatternsTool:
    """
    MCP tool that lists architecture patterns known to the server.

    Returns a minimal view (name + description) of each pattern, optionally
    filtered by category and/or domain. This is a read-only, low-latency
    alternative to the ``pattern://`` MCP resource that works reliably in all
    MCP clients (including OpenCode, where custom URI scheme @-mentions may
    fail due to opencode#30928).
    """

    def __init__(self, pattern_loader: Any) -> None:
        self._pattern_resource = PatternResource(pattern_loader)
        logger.debug("ListArchitecturePatternsTool initialized")

    @tool(
        name="list_architecture_patterns",
        description=(
            "List all available architecture patterns known to the server. "
            "Returns a minimal view with 'name' and 'description' for each pattern. "
            "Optional filters: 'category' (one of: messaging, structural, cloud, "
            "data, ai_cognitive, specialized, api_gateway, coordination, dataflow, "
            "presentation) and 'domain' (matches against pattern.suitable_domains)."
        ),
        tags={"architecture", "patterns", "read"},
        annotations=ToolAnnotations(
            title="List Architecture Patterns",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_architecture_patterns(
        self,
        category: Annotated[
            str | None,
            Field(
                description=(
                    "Optional category filter. Valid values: "
                    + ", ".join(_VALID_CATEGORIES)
                    + ". Unknown values return an empty list."
                ),
            ),
        ] = None,
        domain: Annotated[
            str | None,
            Field(description="Optional domain filter. Matches against pattern.suitable_domains."),
        ] = None,
        _ctx: Any = None,
    ) -> list[dict[str, str]]:
        """
        List architecture patterns, optionally filtered by category and/or domain.

        Args:
            category: Optional category filter (e.g. 'structural').
            domain: Optional domain filter (e.g. 'microservices').
            ctx: FastMCP context (unused; present for protocol conformance).

        Returns:
            List of minimal pattern descriptors: [{name, description}, ...].
        """
        try:
            category_lc = category.lower().strip() if category else None
            if category_lc and category_lc not in _VALID_CATEGORIES:
                return []

            all_patterns = self._pattern_resource._loader.load_all()

            if category_lc:
                all_patterns = [p for p in all_patterns if p.get("category") == category_lc]

            domain_lc = domain.lower().strip() if domain else None
            if domain_lc:
                all_patterns = [
                    p for p in all_patterns
                    if domain_lc in [d.lower() for d in p.get("suitable_domains", [])]
                ]

            return [
                {
                    "name": p.get("name", ""),
                    "description": (p.get("context", "") or "")[:120],
                }
                for p in all_patterns
            ]
        except Exception as e:
            raise ToolError(
                f"{ERROR_PATTERN_CATALOG}: Failed to load pattern catalog: {e}"
            ) from e


class GetArchitecturePatternTool:
    """
    MCP tool that retrieves the full JSON of a single architecture pattern.

    Look up by pattern name (e.g. 'microservices', 'pipe-and-filter'). Raises a
    ToolError if the pattern does not exist. Read-only, low-latency alternative
    to the ``pattern://{name}`` MCP resource.
    """

    def __init__(self, pattern_loader: Any) -> None:
        self._pattern_resource = PatternResource(pattern_loader)
        logger.debug("GetArchitecturePatternTool initialized")

    @tool(
        name="get_architecture_pattern",
        description=(
            "Get the full JSON of a single architecture pattern by its name "
            "(e.g. 'microservices', 'pipe-and-filter', 'hexagonal'). "
            "Returns the complete pattern object including context, benefits, "
            "tradeoffs, quality_attributes, suitable_domains, component_types, "
            "technology_stack, and best_practices. Raises an error if not found."
        ),
        tags={"architecture", "patterns", "read"},
        annotations=ToolAnnotations(
            title="Get Architecture Pattern",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def get_architecture_pattern(
        self,
        name: Annotated[
            str,
            Field(
                description="Pattern name (e.g. 'microservices', 'pipe-and-filter')",
                min_length=1,
            ),
        ],
        _ctx: Any = None,
    ) -> dict[str, Any]:
        """
        Retrieve the full JSON of an architecture pattern by name.

        Args:
            name: Pattern name to look up.
            ctx: FastMCP context (unused; present for protocol conformance).

        Returns:
            The full pattern dict.

        Raises:
            ToolError: If no pattern with the given name exists.
        """
        try:
            data = self._pattern_resource.load_pattern(name)
            if data is None:
                raise ToolError(f"Pattern not found: {name}")
            return data
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(
                f"{ERROR_PATTERN_CATALOG}: Failed to load pattern: {e}"
            ) from e


def list_architecture_patterns_tool(pattern_loader: Any) -> ListArchitecturePatternsTool:
    """Factory: create ListArchitecturePatternsTool instance."""
    return ListArchitecturePatternsTool(pattern_loader=pattern_loader)


def get_architecture_pattern_tool(pattern_loader: Any) -> GetArchitecturePatternTool:
    """Factory: create GetArchitecturePatternTool instance."""
    return GetArchitecturePatternTool(pattern_loader=pattern_loader)
