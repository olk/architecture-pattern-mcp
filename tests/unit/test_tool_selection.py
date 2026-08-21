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
Deterministic tool-selection eval harness (CI-fast, no LLM required).

Tests that tool metadata (name + description-head) routes each explicit-name
prompt to the correct tool, and that the deprecated alias never wins routing.

Mechanism:
- Head = substring of description before the first "do not" / "don't" (case-insensitive).
  Trigger conditions live in the head; exclusion clauses live in the tail.
  An empty head (description starts with "do not") scores name-only.
- Score(prompt, tool) = overlap(prompt_tokens, name_tokens)
                       + overlap(prompt_tokens, head_tokens)
  where overlap = cardinality of token-set intersection.
"""

import re
from collections import Counter

import pytest

from src.server import MCPArchitectServer
from src.tools.jobs import JobsStore


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_-]*", text)}


def _head(description: str) -> str:
    m = re.search(r"\bdo\s*not\b", description, re.IGNORECASE)
    if m is None:
        return description
    return description[: m.start()]


def _overlap(a: set[str], b: set[str]) -> int:
    return len(a & b)


def _score(prompt_tokens: set[str], name_tokens: set[str], head_tokens: set[str]) -> int:
    return _overlap(prompt_tokens, name_tokens) * 3 + _overlap(prompt_tokens, head_tokens)


def _argmax(prompt_tokens: set[str], tools: list[dict]) -> str:
    best_score = -1
    best_name = None
    for t in tools:
        s = _score(prompt_tokens, t["name_tokens"], t["head_tokens"])
        if s > best_score:
            best_score = s
            best_name = t["name"]
    return best_name


def _build_catalog(server: MCPArchitectServer) -> list[dict]:
    components = server._mcp.local_provider._components
    tools = []
    for key, comp in components.items():
        if not key.startswith("tool:"):
            continue
        tool_name = key.split(":")[1].split("@")[0]
        desc = comp.description
        name_tokens = _tokenize(tool_name)
        head_tokens = _tokenize(_head(desc))
        tools.append({
            "name": tool_name,
            "name_tokens": name_tokens,
            "head_tokens": head_tokens,
            "description": desc,
        })
    return tools


def _prompt_for(tool_name: str) -> str:
    return f"Call {tool_name} with requirements 'x' domain 'y'"


class TestToolSelectionEval:
    """Deterministic tool-selection harness — no LLM required."""

    @pytest.fixture
    async def catalog(self) -> list[dict]:
        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_tools(server._mcp)
            return _build_catalog(server)

    @pytest.mark.asyncio
    async def test_prompt_naming_tool_routes_to_that_tool(self, catalog: list[dict]) -> None:
        unambiguous = {
            "design_architecture",
            "submit_design_job",
            "get_design_status",
            "cancel_design",
            "analyze_architecture",
        }
        for tool in catalog:
            if tool["name"] not in unambiguous:
                continue
            if tool["name"] == "start_design_architecture":
                continue  # deprecated alias — tested separately
            prompt = _prompt_for(tool["name"])
            prompt_tokens = _tokenize(prompt)
            winner = _argmax(prompt_tokens, catalog)
            scores = [
                (t["name"], _score(prompt_tokens, t["name_tokens"], t["head_tokens"]))
                for t in catalog
            ]
            assert winner == tool["name"], (
                f"Prompt {prompt!r} → routed to {winner!r}, expected {tool['name']!r}. "
                f"Scores: {scores}"
            )

    @pytest.mark.asyncio
    async def test_known_name_collisions_allowlisted(self, catalog: list[dict]) -> None:
        names = [t["name"] for t in catalog]
        colliding: list[tuple[str, str]] = []
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if a in b or b in a:
                    colliding.append((a, b))
        assert colliding == [
            ("design_architecture", "start_design_architecture")
        ], f"Unexpected collisions: {colliding}"

    @pytest.mark.asyncio
    async def test_design_family_has_negative_constraints(self, catalog: list[dict]) -> None:
        for t in catalog:
            if t["name"] in ("submit_design_job", "design_architecture"):
                assert re.search(
                    r"\bdo\s*not\b", t["description"], re.IGNORECASE
                ), f"{t['name']!r} description lacks a 'do not' exclusion clause"

    @pytest.mark.asyncio
    async def test_sibling_reference_only_in_exclusion(self, catalog: list[dict]) -> None:
        t = next(t for t in catalog if t["name"] == "submit_design_job")
        head = _head(t["description"])
        assert "design_architecture" not in _tokenize(head), (
            f"submit_design_job head contains 'design_architecture' outside exclusion clause: {head!r}"
        )

    @pytest.mark.asyncio
    async def test_deprecated_alias_never_wins_argmax(self, catalog: list[dict]) -> None:
        DEPRECATED = "start_design_architecture"
        for tool in catalog:
            if tool["name"] == DEPRECATED:
                continue
            prompt_tokens = _tokenize(_prompt_for(tool["name"]))
            winner = _argmax(prompt_tokens, catalog)
            scores = [
                (t["name"], _score(prompt_tokens, t["name_tokens"], t["head_tokens"]))
                for t in catalog
            ]
            assert winner != DEPRECATED, (
                f"Deprecated alias won argmax for prompt {tool['name']!r}. Scores: {scores}"
            )

    @pytest.mark.asyncio
    async def test_descriptions_pairwise_distinct(self, catalog: list[dict]) -> None:
        heads = [_head(t["description"]) for t in catalog]
        for i, a in enumerate(heads):
            for b in heads[i + 1:]:
                assert a != b, f"Duplicate description head: {a!r}"

    @pytest.mark.asyncio
    async def test_deprecated_alias_returns_rename_notice(
        self, tmp_path, monkeypatch
    ) -> None:
        db = tmp_path / "jobs.db"
        monkeypatch.setenv("ARCHITECTURE_PATTERN_JOBS_DB", str(db))
        await JobsStore.reset_for_test()

        from src.tools.start_design import _deprecated_start_design_alias

        result = await _deprecated_start_design_alias(
            requirements="x",
            domain="y",
            override_style=None,
            ctx=None,
        )
        assert result["deprecated"] is True
        assert result["renamed_to"] == "submit_design_job"
        assert "start_design_architecture" in result["message"]
        assert "submit_design_job" in result["message"]

    @pytest.mark.asyncio
    async def test_deprecated_alias_accepts_invalid_input(
        self, tmp_path, monkeypatch
    ) -> None:
        db = tmp_path / "jobs.db"
        monkeypatch.setenv("ARCHITECTURE_PATTERN_JOBS_DB", str(db))
        await JobsStore.reset_for_test()

        from src.tools.start_design import _deprecated_start_design_alias

        result = await _deprecated_start_design_alias(
            requirements="",
            domain="",
            override_style=None,
            ctx=None,
        )
        assert result["deprecated"] is True
