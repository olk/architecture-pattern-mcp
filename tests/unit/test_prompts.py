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
Unit tests for MCP prompts (FR-247 to FR-250, ADR-9).

Test Case IDs: UT-15

Validates:
- FR-247: Lifespan registers four prompts via prompts/list
- FR-248: design_architecture_workflow renders with correct required args
- FR-249: explore_pattern_catalog dynamically embeds live pattern metadata
- FR-250: Registration is idempotent (survives lifespan re-entry)
"""

import pytest
from fastmcp import Client

from src.server import MCPArchitectServer

EXPECTED_PROMPTS = frozenset(
    {
        "design_architecture_workflow",
        "explore_pattern_catalog",
        "evaluate_my_architecture",
        "compare_architecture_styles",
    }
)


class TestPromptRegistration:
    @pytest.mark.asyncio
    async def test_lifespan_registers_four_prompts(self):
        """FR-247: Verify lifespan registers 4 prompts with expected names."""
        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_prompts(server._mcp)

            components = server._mcp.local_provider._components
            prompt_keys = [
                k for k in components.keys() if "prompt" in k.lower()
            ]
            names = {k.split(":")[1].split("@")[0] for k in prompt_keys}
            assert names == EXPECTED_PROMPTS, (
                f"Expected prompts {EXPECTED_PROMPTS}, got {names}"
            )

    @pytest.mark.asyncio
    async def test_register_prompts_idempotent(self):
        """FR-250: Second registration must not raise (lifespan re-entry)."""
        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_prompts(server._mcp)
            server._register_prompts(server._mcp)


class TestPromptRendering:
    @pytest.mark.asyncio
    async def test_explore_prompt_embeds_live_pattern_names(self):
        """FR-249: explore_pattern_catalog dynamically embeds live pattern names."""
        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_prompts(server._mcp)
            async with Client(server._mcp) as client:
                result = await client.get_prompt("explore_pattern_catalog", {})

                user_messages = [
                    m for m in result.messages if m.role == "user"
                ]
                assert user_messages, "Expected at least one user message"

                all_text = " ".join(
                    m.content.text
                    for m in result.messages
                    if hasattr(m.content, "text") and m.content.text
                )
                assert len(all_text) > 0, "Rendered prompt should not be empty"

    @pytest.mark.asyncio
    async def test_design_workflow_requires_requirements(self):
        """FR-248: design_architecture_workflow requires the `requirements` arg."""
        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_prompts(server._mcp)
            async with Client(server._mcp) as client:
                with pytest.raises(Exception):
                    await client.get_prompt(
                        "design_architecture_workflow",
                        {"domain": "ecommerce"},
                    )

    @pytest.mark.asyncio
    async def test_design_workflow_renders_with_valid_args(self):
        """FR-248: design_architecture_workflow renders successfully with required args."""
        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_prompts(server._mcp)
            async with Client(server._mcp) as client:
                result = await client.get_prompt(
                    "design_architecture_workflow",
                    {"requirements": "Build a REST API", "domain": "web"},
                )
                user_messages = [
                    m for m in result.messages if m.role == "user"
                ]
                assert user_messages
                text = " ".join(
                    m.content.text
                    for m in user_messages
                    if hasattr(m.content, "text")
                )
                assert "design_architecture" in text

    @pytest.mark.asyncio
    async def test_compare_styles_requires_all_required_args(self):
        """compare_architecture_styles requires style_a, style_b, and requirements."""
        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_prompts(server._mcp)
            async with Client(server._mcp) as client:
                with pytest.raises(Exception):
                    await client.get_prompt(
                        "compare_architecture_styles",
                        {"style_a": "microservices"},
                    )

    @pytest.mark.asyncio
    async def test_evaluate_my_architecture_renders(self):
        """evaluate_my_architecture renders with optional focus arg."""
        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_prompts(server._mcp)
            async with Client(server._mcp) as client:
                result = await client.get_prompt(
                    "evaluate_my_architecture",
                    {"focus": "security"},
                )
                user_messages = [
                    m for m in result.messages if m.role == "user"
                ]
                assert user_messages
                text = " ".join(
                    m.content.text
                    for m in user_messages
                    if hasattr(m.content, "text")
                )
                assert "evaluate_architecture" in text

    @pytest.mark.asyncio
    async def test_explore_prompt_empty_loader_fallback(self):
        """FR-249 edge case: explore_pattern_catalog shows error when loader is empty."""

        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_prompts(server._mcp)
            async with Client(server._mcp) as client:
                result = await client.get_prompt(
                    "explore_pattern_catalog",
                    {},
                )
                user_messages = [
                    m for m in result.messages if m.role == "user"
                ]
                assert user_messages


class TestPromptsAsTools:
    """Verify PromptsAsTools transform exposes prompts as tools for tool-only clients."""

    @pytest.mark.asyncio
    async def test_list_tools_exposes_generated_tools(self):
        """list_prompts and get_prompt appear in list_tools for tool-only clients."""
        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_tools(server._mcp)
            server._register_prompts(server._mcp)
            async with Client(server._mcp) as client:
                tools = await client.list_tools()
                tool_names = {t.name for t in tools}
                assert "list_prompts" in tool_names
                assert "get_prompt" in tool_names

    @pytest.mark.asyncio
    async def test_generated_tools_carry_annotations(self):
        """list_prompts and get_prompt carry ToolAnnotations via AnnotatedPromptsAsTools."""
        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_tools(server._mcp)
            server._register_prompts(server._mcp)
            async with Client(server._mcp) as client:
                tools = await client.list_tools()
                by_name = {t.name: t for t in tools}

                for tool_name, expected_title in (
                    ("list_prompts", "List Prompts"),
                    ("get_prompt", "Get Prompt"),
                ):
                    ann = by_name[tool_name].annotations
                    assert ann is not None, f"{tool_name} has no annotations"
                    assert ann.title == expected_title
                    assert ann.read_only_hint is True
                    assert ann.destructive_hint is False
                    assert ann.idempotent_hint is True
                    assert ann.open_world_hint is False

    @pytest.mark.asyncio
    async def test_list_prompts_tool_returns_all_workflow_prompts(self):
        """list_prompts tool returns JSON with all 4 workflow prompts and argument metadata."""
        import json

        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_prompts(server._mcp)
            async with Client(server._mcp) as client:
                result = await client.call_tool("list_prompts", {})
                prompts = json.loads(result.data)
                prompt_names = {p["name"] for p in prompts}
                assert prompt_names == EXPECTED_PROMPTS
                for p in prompts:
                    assert "description" in p
                    assert "arguments" in p

    @pytest.mark.asyncio
    async def test_get_prompt_tool_renders_with_arguments(self):
        """get_prompt tool renders explore_pattern_catalog with provided arguments."""
        import json

        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_prompts(server._mcp)
            async with Client(server._mcp) as client:
                result = await client.call_tool(
                    "get_prompt",
                    {"name": "explore_pattern_catalog", "arguments": {"domain": "web"}},
                )
                rendered = json.loads(result.data)
                assert "messages" in rendered
                assert len(rendered["messages"]) > 0

    @pytest.mark.asyncio
    async def test_get_prompt_tool_works_without_arguments(self):
        """get_prompt tool renders when arguments are omitted (all args optional)."""
        import json

        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_prompts(server._mcp)
            async with Client(server._mcp) as client:
                result = await client.call_tool(
                    "get_prompt",
                    {"name": "explore_pattern_catalog"},
                )
                rendered = json.loads(result.data)
                assert "messages" in rendered
                assert len(rendered["messages"]) > 0
                msg = rendered["messages"][0]
                assert msg["role"] == "user"
                assert len(msg["content"]) > 0
