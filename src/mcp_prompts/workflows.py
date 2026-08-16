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

"""Workflow prompt definitions for MCP prompts/list and prompts/get.

FR-247 to FR-250. ADR-9: User-invoked workflow prompts.

Each prompt is a tested tool-orchestration recipe. Rendered messages instruct
the LLM to invoke existing tools in a defined sequence.
"""

from fastmcp import FastMCP
from fastmcp.prompts import Message

from src.patterns.loader import PatternLoader
from src.resources.patterns import PatternResource


def register_prompts(server: FastMCP, pattern_loader: PatternLoader) -> int:
    """Register all workflow prompts with the server. Returns count registered."""
    pattern_resource = PatternResource(pattern_loader)
    all_patterns = pattern_resource.list_pattern_resources()

    @server.prompt(name="design_architecture_workflow")
    def design_architecture_workflow(
        requirements: str,
        domain: str = "general",
        style: str | None = None,
    ) -> list[Message]:
        """FR-248: Guided end-to-end design workflow.

        Steps: 1) call design_architecture with the user's requirements,
        domain, and optional style override, 2) interpret the returned
        quality attribute scores, 3) list tradeoffs from selected patterns,
        4) if any quality score is below 75, suggest a specific refinement.
        """
        style_arg = f", style='{style}'" if style else ""
        body = (
            f"You are guiding a user through the architecture design workflow. "
            f"Follow these steps precisely:\n"
            f"1. Call design_architecture with these arguments: "
            f"requirements='{requirements}', domain='{domain}'{style_arg}\n"
            f"2. Review the returned quality attribute scores "
            f"(maintainability, scalability, reliability, security, performance).\n"
            f"3. List the top tradeoffs from the selected patterns.\n"
            f"4. If any quality score is below 75, propose a concrete refinement "
            f"using the evaluate_architecture tool with adjusted component choices."
        )
        return [Message(body)]

    @server.prompt(name="explore_pattern_catalog")
    def explore_pattern_catalog(
        domain: str | None = None,
        category: str | None = None,
    ) -> list[Message]:
        """FR-249: Discovery workflow over the live pattern catalog.

        Dynamically embeds available pattern names from the loaded catalog.
        Guides the user through list_architecture_patterns and
        get_architecture_pattern, then references the pattern:// resources
        for full JSON detail.
        """
        if not all_patterns:
            return [
                Message(
                    "The pattern directory appears to be empty or is misconfigured. "
                    "Verify the pattern_directory config value points to a directory "
                    "containing pattern JSON files, then retry. "
                    "Use list_architecture_patterns to confirm the catalog state."
                )
            ]

        names = [p["name"] for p in all_patterns]
        names_str = ", ".join(sorted(names))

        filter_note = ""
        if domain or category:
            filtered = [
                p["name"]
                for p in all_patterns
                if (not domain or domain.lower() in p.get("description", "").lower())
                or (not category or category.lower() in p.get("name", "").lower())
            ]
            if filtered:
                filter_note = (
                    f"\nMatching '{domain or category}': {', '.join(sorted(filtered))}."
                )
            else:
                filter_note = (
                    f"\nNo patterns matched '{domain or category}' — showing all instead."
                )
                names_str = ", ".join(sorted(names))

        body = (
            f"The loaded pattern catalog contains {len(names)} pattern(s): "
            f"{names_str}.{filter_note}\n\n"
            "Guide the user as follows:\n"
            "1. Ask which pattern they want to explore.\n"
            "2. Call list_architecture_patterns to show all patterns "
            "(optionally filtered by domain or category).\n"
            "3. Call get_architecture_pattern for the chosen pattern name.\n"
            "4. Reference pattern:// resources for additional detail: "
            "e.g. mcp_read_resource(uri='pattern://event-driven')."
        )
        return [Message(body)]

    @server.prompt(name="evaluate_my_architecture")
    def evaluate_my_architecture(focus: str | None = None) -> list[Message]:
        """Guide the user through evaluating an existing architecture design.

        Steps: 1) help the user structure their architecture as the required
        dict, 2) call evaluate_architecture, 3) prioritise critical findings
        (score < 70), 4) list recommendations grouped by quality attribute.
        The optional focus argument narrows attention to a specific attribute
        (e.g. 'security', 'scalability').
        """
        focus_note = (
            f" Give extra attention to the '{focus}' quality attribute."
            if focus
            else ""
        )
        body = (
            "You are guiding a user through an architecture evaluation.\n"
            f"{focus_note}\n\n"
            "1. Help the user express their architecture as a structured dict "
            "with keys: overview (style, category, principles, constraints), "
            "components (id, name, type, description, interfaces, technology_stack), "
            "relationships (source, target, type, description), "
            "quality_attributes (maintainability, scalability, reliability, "
            "security, performance as string scores or numbers).\n"
            "2. Call evaluate_architecture with the architecture dict.\n"
            "3. Flag critical findings (any score below 70) as urgent.\n"
            "4. Group recommendations by quality attribute."
        )
        return [Message(body)]

    @server.prompt(name="compare_architecture_styles")
    def compare_architecture_styles(
        style_a: str,
        style_b: str,
        requirements: str,
    ) -> list[Message]:
        """Generate two designs with different styles and compare tradeoffs.

        COST NOTE: this prompt triggers two generate_architecture calls
        (one per style) — approximately 2x token cost and latency
        compared to other prompts.
        """
        body = (
            "The user wants to compare two architecture styles for the same "
            f"requirements: '{requirements}'.\n\n"
            "1. Call generate_architecture with style_a='{style_a}' "
            f"and the given requirements.\n"
            "2. Call generate_architecture with style_b='{style_b}' "
            "and the same requirements.\n"
            "3. Present a structured comparison:\n"
            "   - Quality attribute scores side-by-side table\n"
            "   - Pattern used in each design\n"
            "   - Top 3 tradeoffs per style\n"
            "   - Which style fits the requirements better and why\n"
            "4. If both scores are within 5 points, note that either style works."
        ).format(style_a=style_a, style_b=style_b, requirements=requirements)
        return [Message(body)]

    return 4
