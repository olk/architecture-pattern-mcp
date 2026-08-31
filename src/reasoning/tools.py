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
Pinned tool contracts for the reasoning MCP servers (Plan v5 amendment 6).

Verified 2026-08-31 against the upstream sources:
  - shannonthinking: tool name "shannonthinking", camelCase params
    (thoughtNumber, totalThoughts, nextThoughtNeeded, revisesThought) —
    npm server-shannon-thinking@0.1.1.
  - code-reasoning: tool name "code-reasoning" (renamed from
    "sequentialthinking" upstream), snake_case params (thought_number,
    total_thoughts, next_thought_needed, revises_thought) —
    npm @mettamatt/code-reasoning@0.8.1.

A wrong tool name or param casing fails the startup health check LOUDLY
(server.py lifespan) instead of silently disabling reasoning forever behind
per-call silent degradation.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from src.reasoning.config import ReasoningTool
from src.reasoning.schemas import PHASE_TAGS, ThoughtDraft

logger = logging.getLogger(__name__)

# shannonthinking validates thoughtType against its five-value enum, but the
# LLM tends to echo the pipeline phase name instead (e.g. "analysis" for the
# 'analyze' phase). Coercion below is deliberately approximate: server-side,
# the stage only affects enum validation and stderr formatting, never
# semantics. Follow-up design note: assigning the stage client-side (like
# step numbering) would remove LLM dependence entirely — see the
# ThoughtDraft numbering docstring in schemas.py for the precedent.
_PHASE_TAG_ALIASES: dict[str, str] = {
    "analyze": "problem_definition",
    "analysis": "problem_definition",
    "analyzing": "problem_definition",
    "generate": "model",
    "generation": "model",
    "design": "model",
    "evaluate": "proof",
    "evaluation": "proof",
    "review": "proof",
    "retry": "implementation",
    "refinement": "implementation",
}
_DEFAULT_SHANNON_STAGE = "model"

# code-reasoning rejects thoughts beyond 20000 chars server-side
# (MAX_THOUGHT_LENGTH); the draft schema leaves thought length unbounded.
_CODE_MAX_THOUGHT_LENGTH = 20000


def _coerce_shannon_stage(phase_tag: str) -> str:
    """Map a draft phase_tag onto shannonthinking's five-value enum.

    Normalizes case/whitespace, translates known pipeline-phase echoes, and
    falls back to a valid default for anything unrecognized — an invalid
    value would otherwise be rejected by the server, degrading the step.
    Never raises and never skips the call.
    """
    tag = phase_tag.strip().lower()
    if tag in PHASE_TAGS:
        return tag
    alias = _PHASE_TAG_ALIASES.get(tag)
    if alias is not None:
        return alias
    logger.debug(
        "phase_tag %r not in shannonthinking enum; coercing to %r",
        phase_tag,
        _DEFAULT_SHANNON_STAGE,
    )
    return _DEFAULT_SHANNON_STAGE


@dataclass(frozen=True)
class ToolContract:
    """Static description of one reasoning tool's MCP surface."""

    kind: ReasoningTool
    name: str
    probe_payload: dict[str, Any] = field(default_factory=dict)


SHANNON_TOOL = ToolContract(
    kind="shannon",
    name="shannonthinking",
    probe_payload={
        "thought": "startup probe",
        "thoughtType": "problem_definition",
        "thoughtNumber": 1,
        "totalThoughts": 1,
        "uncertainty": 0.0,
        "dependencies": [],
        "assumptions": [],
        "nextThoughtNeeded": False,
    },
)

CODE_TOOL = ToolContract(
    kind="code",
    name="code-reasoning",
    probe_payload={
        "thought": "startup probe",
        "thought_number": 1,
        "total_thoughts": 1,
        "next_thought_needed": False,
    },
)

TOOL_CONTRACTS: dict[ReasoningTool, ToolContract] = {
    "shannon": SHANNON_TOOL,
    "code": CODE_TOOL,
}


def _common_draft_params(draft: ThoughtDraft) -> dict[str, Any]:
    return {
        "thought": draft.thought,
        "assumptions": list(draft.assumptions),
        # Key MUST be present (shannonthinking validates Array.isArray) but
        # value MUST be empty: every call runs in a fresh subprocess
        # (keep_alive=False), so the server's thoughtHistory is empty and any
        # reference to a prior thought is rejected.
        "dependencies": [],
    }


def draft_to_shannon_params(draft: ThoughtDraft, step_number: int, total: int) -> dict[str, Any]:
    """Map a ThoughtDraft to shannonthinking's camelCase parameter schema.

    The tool validates thoughtType against its five-value enum and clamps
    thoughtNumber/totalThoughts; numbering is assigned here, by the client.
    phase_tag is coerced onto the enum (normalization, pipeline-phase alias
    map, documented fallback) — an unknown tag never fails the call. The
    draft's raw phase_tag remains recorded in the ReasoningStep trace; only
    the wire payload is coerced.

    Cross-thought references (dependencies, isRevision/revisesThought) are
    deliberately NOT sent: a fresh subprocess cannot resolve them
    ("Invalid dependency/revision: thought N does not exist"). The draft's
    fields remain recorded in the ReasoningStep trace; only the wire
    payload is stripped.
    """
    return {
        **_common_draft_params(draft),
        "thoughtType": _coerce_shannon_stage(draft.phase_tag),
        "thoughtNumber": step_number,
        "totalThoughts": total,
        "uncertainty": draft.uncertainty,
        "nextThoughtNeeded": draft.next_needed,
    }


def draft_to_code_params(draft: ThoughtDraft, step_number: int, total: int) -> dict[str, Any]:
    """Map a ThoughtDraft to code-reasoning's snake_case parameter schema.

    Revision and branch fields are deliberately NOT sent: with an empty
    tracker, ensureBranchIsValid rejects any branch_from_thought > 0, and a
    revision of a thought absent from this subprocess's history is
    semantically void. The 4-field payload is proven sufficient by the
    startup probe (health checks pass with exactly these fields).

    thought is truncated to the server's MAX_THOUGHT_LENGTH (20000 chars) —
    the draft schema leaves it unbounded and an over-long thought would
    degrade the step with a validation error.
    """
    thought = draft.thought
    if len(thought) > _CODE_MAX_THOUGHT_LENGTH:
        logger.debug(
            "thought truncated for code-reasoning: %d -> %d chars",
            len(thought),
            _CODE_MAX_THOUGHT_LENGTH,
        )
        thought = thought[:_CODE_MAX_THOUGHT_LENGTH]
    return {
        "thought": thought,
        "thought_number": step_number,
        "total_thoughts": total,
        "next_thought_needed": draft.next_needed,
    }


def draft_to_params(
    kind: ReasoningTool, draft: ThoughtDraft, step_number: int, total: int
) -> dict[str, Any]:
    """Adapter dispatch: ThoughtDraft -> tool-specific call payload."""
    if kind == "shannon":
        return draft_to_shannon_params(draft, step_number, total)
    return draft_to_code_params(draft, step_number, total)
