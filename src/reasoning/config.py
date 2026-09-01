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
Reasoning configuration for the server-side shannonthinking / code-reasoning
integration (Plan v5).

The architecture-pattern-mcp server acts as an MCP CLIENT of two structured
reasoning scratchpads before each LLM phase call:

  - shannonthinking  (npm: server-shannon-thinking@0.1.1, tool "shannonthinking",
    camelCase params)
  - code-reasoning   (npm: @mettamatt/code-reasoning@0.8.1, tool "code-reasoning",
    snake_case params)

Both tools are scratchpads, not reasoning engines: a caller must AUTHOR each
thought. The ReasoningClient's ThoughtGenerator loop does that with this
server's own LLM (see client.py), then submits each thought to the tool for
structuring.

Docker deployments embed both packages at /usr/local/lib/node_modules and
invoke them directly via ``node <pkg>/dist/index.js``. Outside Docker, an
auto-fallback to ``npx -y <pkg>`` kicks in when the embedded path is absent
(see client._resolve_cmd).

Env vars are flat, matching the existing RETRIEVAL_*/GENERATOR_* convention,
and are wired through config.json {env:...} expansion:

    REASONING_ENABLED                        (default: true)
    REASONING_SHANNONTHINKING_CMD            (JSON list)
    REASONING_CODE_REASONING_CMD             (JSON list)
    REASONING_SPAWN_TIMEOUT_SECONDS          (default: 10)
    REASONING_STEP_TIMEOUT_SECONDS           (default: 20)
    REASONING_MAX_TOTAL_STEPS                (default: 8)
    REASONING_FAIL_FAST                      (default: false)
"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Embedded entry points baked into the production Docker image by the
# build-mcps stage (docker/Dockerfile). Version pins verified on npm
# 2026-08-31: server-shannon-thinking@0.1.1, @mettamatt/code-reasoning@0.8.1.
SHANNON_EMBEDDED_CMD: list[str] = [
    "node",
    "/usr/local/lib/node_modules/server-shannon-thinking/dist/index.js",
]
CODE_REASONING_EMBEDDED_CMD: list[str] = [
    "node",
    "/usr/local/lib/node_modules/@mettamatt/code-reasoning/dist/index.js",
]

SHANNON_NPX_CMD: list[str] = ["npx", "-y", "server-shannon-thinking@0.1.1"]
CODE_REASONING_NPX_CMD: list[str] = ["npx", "-y", "@mettamatt/code-reasoning@0.8.1"]

ReasoningTool = Literal["shannon", "code"]


class ReasoningStrategy(BaseModel):
    """Per-phase reasoning strategy driving the ThoughtGenerator loop."""

    model_config = ConfigDict(extra="forbid")

    pre_llm_thoughts: int = Field(
        3, ge=1, le=20,
        description="Maximum reasoning steps before the phase's main LLM call.",
    )
    tools: list[ReasoningTool] = Field(
        default_factory=lambda: ["shannon"],
        description=(
            "Reasoning tools used for this phase. Each thought is submitted to "
            "every listed tool in order (the tools alternate per step when more "
            "than one is configured)."
        ),
    )
    step_agenda: list[str] = Field(
        default_factory=list,
        description=(
            "Per-step focus prompts (one per thought). When shorter than "
            "pre_llm_thoughts, the last agenda item repeats for the remaining "
            "steps. This is the external-trace counterpart of the degraded "
            "in-prompt thinking scaffold."
        ),
    )
    system_directive: str = Field(
        "",
        description="Phase-level directive prepended to every step prompt.",
    )

    @field_validator("tools")
    @classmethod
    def _non_empty_tools(cls, v: list[ReasoningTool]) -> list[ReasoningTool]:
        if not v:
            raise ValueError("tools must contain at least one reasoning tool")
        return v


def _default_per_phase() -> dict[str, ReasoningStrategy]:
    return {
        "analyze": ReasoningStrategy(
            pre_llm_thoughts=4,
            tools=["code", "shannon"],
            step_agenda=[
                (
                    "Decompose the requirements into individual sub-claims; quote each "
                    "verbatim fragment and tag the quality attributes it signals."
                ),
                (
                    "Classify the sub-claims per quality attribute and note the evidence "
                    "strength of each tag."
                ),
                (
                    "Calibrate per-attribute strengths against the 0.0-1.0 anchors and "
                    "resolve conflicts (numeric SLOs outrank vague adjectives)."
                ),
                (
                    "Verify: would the resulting priority ordering match the sub-claims? "
                    "State the final normalised ordering (max = 1.0)."
                ),
            ],
            system_directive=(
                "You are preparing a requirement-priority analysis. Reason only from "
                "evidence in the requirements text; never apply industry priors or "
                "infer from the domain label."
            ),
        ),
        "generate": ReasoningStrategy(
            pre_llm_thoughts=3,
            tools=["code"],
            step_agenda=[
                "Map every stated requirement to concrete component candidates.",
                (
                    "Sketch two or three alternative component decompositions with their "
                    "key trade-offs."
                ),
                (
                    "Commit to one decomposition and justify the trade-offs against the "
                    "requirement priorities."
                ),
            ],
            system_directive=(
                "You are preparing a component-design plan. Prefer proven technologies; "
                "every claim must trace to a stated requirement or a selected pattern "
                "practice."
            ),
        ),
        "evaluate": ReasoningStrategy(
            pre_llm_thoughts=3,
            tools=["shannon"],
            step_agenda=[
                (
                    "Enumerate which evaluation criteria the architecture demonstrably "
                    "meets and which it does not, citing component ids."
                ),
                (
                    "Score the architecture against the rubric anchors and record the "
                    "evidence per score."
                ),
                (
                    "Flag ambiguous requirements, scoring-honesty discrepancies, and any "
                    "anti-patterns present."
                ),
            ],
            system_directive=(
                "You are preparing an architecture audit. Differentiate blocking "
                "critical findings from non-blocking weaknesses; no floating "
                "assertions."
            ),
        ),
        "retry": ReasoningStrategy(
            pre_llm_thoughts=2,
            tools=["code", "shannon"],
            step_agenda=[
                (
                    "From the evaluation findings, identify the most critical sub-problem "
                    "to fix first and why."
                ),
                (
                    "Check which praised strengths risk regression while fixing that "
                    "sub-problem, and how to preserve them."
                ),
            ],
            system_directive=(
                "You are preparing a refinement plan. Address critical findings "
                "without regressing verified strengths."
            ),
        ),
    }


class ReasoningConfig(BaseModel):
    """Server-side reasoning MCP integration configuration.

    enabled defaults to True (opt-out): Docker images embed the reasoning
    MCP packages at build time, so the feature is self-contained there.
    Outside Docker the client auto-falls back to npx per tool.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        True,
        description="Master switch. Opt out via REASONING_ENABLED=false.",
    )
    shannonthinking_cmd: str | list[str] = Field(
        default_factory=lambda: list(SHANNON_EMBEDDED_CMD),
        description=(
            "Command list for the shannonthinking MCP server (stdio). Defaults to "
            "the Docker-embedded entry point; set to a JSON list to override "
            "(e.g. '[\"npx\", \"-y\", \"server-shannon-thinking@latest\"]')."
        ),
    )
    code_reasoning_cmd: str | list[str] = Field(
        default_factory=lambda: list(CODE_REASONING_EMBEDDED_CMD),
        description=(
            "Command list for the code-reasoning MCP server (stdio). Defaults to "
            "the Docker-embedded entry point; set to a JSON list to override."
        ),
    )
    spawn_timeout_seconds: float = Field(10.0, gt=0)
    step_timeout_seconds: float = Field(20.0, gt=0)
    max_total_steps: int = Field(8, ge=1, le=20)
    quiet_stderr: bool = Field(
        True,
        description=(
            "Route reasoning-subprocess stderr to os.devnull. The shannonthinking "
            "server prints large ASCII progress boxes and code-reasoning prints "
            "[info] startup lines on stderr — silencing them keeps docker logs "
            "clean. Tool responses remain captured in the reasoning trace; set "
            "false (REASONING_QUIET_STDERR=false) to see subprocess stderr for "
            "debugging (e.g. a Node stack trace on spawn failure)."
        ),
    )
    fail_fast: bool = Field(
        False,
        description=(
            "If True, server startup FAILS when a reasoning tool is unreachable. "
            "Default False: startup logs a loud ERROR and degrades to the "
            "in-prompt thinking scaffold."
        ),
    )
    per_phase: dict[str, ReasoningStrategy] = Field(default_factory=_default_per_phase)

    @field_validator("shannonthinking_cmd", "code_reasoning_cmd", mode="before")
    @classmethod
    def _parse_cmd(cls, v: object, info: object) -> object:
        # Empty string = env var unset ({env:REASONING_*_CMD:-}) → embedded default.
        if isinstance(v, str):
            if not v.strip():
                return list(
                    SHANNON_EMBEDDED_CMD
                    if getattr(info, "field_name", "") == "shannonthinking_cmd"
                    else CODE_REASONING_EMBEDDED_CMD
                )
            return json.loads(v)
        return v

    @field_validator("shannonthinking_cmd", "code_reasoning_cmd")
    @classmethod
    def _validate_cmd(cls, v: list[str]) -> list[str]:
        if not v or not all(isinstance(part, str) and part for part in v):
            raise ValueError("reasoning command must be a non-empty list of strings")
        return v

    def get_strategy(self, phase: str) -> ReasoningStrategy:
        """Return the strategy for a phase, falling back to the first entry."""
        strategy = self.per_phase.get(phase)
        if strategy is not None:
            return strategy
        return next(iter(self.per_phase.values()))
