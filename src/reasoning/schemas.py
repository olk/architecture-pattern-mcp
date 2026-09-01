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
Schemas for the server-side reasoning integration (Plan v5).

ThoughtDraft is the tool-agnostic schema the reasoning LLM fills per step;
tool-specific casings (shannonthinking camelCase, code-reasoning snake_case)
are applied by the adapters in tools.py so the LLM never sees tool wire
formats. ReasoningStep / ReasoningTrace are the structured output injected
into the phase prompts as <reasoning_context>.
"""

from pydantic import BaseModel, Field

from src.reasoning.config import ReasoningTool

PHASE_TAGS: tuple[str, ...] = (
    "problem_definition",
    "constraints",
    "model",
    "proof",
    "implementation",
)


class ThoughtDraft(BaseModel):
    """One reasoning step authored by the reasoning LLM (tool-agnostic).

    The client assigns the step numbering (thoughtNumber / thought_number) —
    the LLM never emits numbers, preventing drift against the loop counter.
    """

    thought: str = Field(
        ...,
        min_length=1,
        description="The actual reasoning content for this step.",
    )
    phase_tag: str = Field(
        "problem_definition",
        description=f"One of: {', '.join(PHASE_TAGS)}.",
    )
    uncertainty: float = Field(0.3, ge=0.0, le=1.0)
    assumptions: list[str] = Field(default_factory=list)
    dependencies: list[int] = Field(default_factory=list)
    next_needed: bool = Field(
        True,
        description="False when the trace is sufficient and the loop may stop.",
    )
    is_revision: bool = False
    revises: int | None = Field(
        default=None,
        ge=1,
        description="Step number this draft supersedes (when is_revision).",
    )
    branch_id: str | None = Field(
        default=None,
        description="Branch identifier for alternative lines of reasoning (code tool).",
    )


class ReasoningStep(BaseModel):
    """One recorded step of a completed reasoning trace."""

    tool: ReasoningTool
    step_number: int = Field(..., ge=1)
    phase_tag: str | None = None
    branch_id: str | None = None
    is_revision: bool = False
    revises: int | None = None
    thought: str
    assumptions: list[str] = Field(default_factory=list)
    dependencies: list[int] = Field(default_factory=list)
    uncertainty: float | None = None
    tool_response: str = Field(
        "",
        description="Truncated structured-feedback text returned by the tool.",
    )


class ReasoningTrace(BaseModel):
    """Completed reasoning trace for one phase call."""

    phase: str
    steps: list[ReasoningStep] = Field(default_factory=list)
    aborted_reason: str | None = Field(
        default=None,
        description=(
            "Set when the trace is incomplete (tool unavailable, timeout, "
            "validation failure). Empty/None = clean completion."
        ),
    )
    duration_ms: float = 0.0
    tool_call_counts: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Successful call count per tool from the originating run, keyed by "
            "MCP tool name ('shannonthinking' / 'code-reasoning')."
        ),
    )
    cached: bool = Field(
        default=False,
        description=(
            "True when served from the trace cache; counts and duration "
            "describe the original run, not the current request."
        ),
    )

    def render_lines(self) -> list[str]:
        """Render the trace as prompt lines for the <reasoning_context> block."""
        lines: list[str] = []
        for step in self.steps:
            meta = [str(step.step_number), step.tool]
            if step.phase_tag:
                meta.append(step.phase_tag)
            if step.branch_id:
                meta.append(f"branch={step.branch_id}")
            if step.uncertainty is not None:
                meta.append(f"u={step.uncertainty:.1f}")
            prefix = "REVISION of " + str(step.revises) + " | " if step.is_revision else ""
            lines.append(f"  [{'|'.join(meta)}] {prefix}{step.thought}")
            if step.assumptions:
                lines.append(f"      assumptions: {'; '.join(step.assumptions)}")
            if step.tool_response:
                lines.append(f"      tool: {step.tool_response}")
        return lines
