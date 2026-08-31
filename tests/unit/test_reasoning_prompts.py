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
Unit tests for reasoning prompt rendering and pipeline injection (Plan v5).

Covers:
- Degraded <reasoning_context> scaffold for every phase (amendment 4)
- Full <reasoning_context> rendering from a ReasoningTrace
- ThoughtGenerator step prompts (focus, directive, trace-so-far, inputs, caps)
- Pipeline prompt injection points in ANALYZE / GENERATE / EVALUATE / RETRY
- REQUIREMENT_WEIGHTS_EXAMPLE_CONFLICT rendered as Example 4
"""

import pytest

from src.pipeline import ArchitecturePipeline
from src.prompts import REQUIREMENT_WEIGHTS_EXAMPLE_CONFLICT
from src.reasoning.prompts import (
    build_step_user_prompt,
    render_degraded_context,
    render_reasoning_context,
)
from src.reasoning.schemas import ReasoningStep, ReasoningTrace
from src.schemas.design import ArchitectureDesign

ALL_PHASES = ("analyze", "generate", "evaluate", "retry")


def bare_pipeline() -> ArchitecturePipeline:
    """Pipeline instance without running __init__ (prompt builders are pure)."""
    return object.__new__(ArchitecturePipeline)


class TestDegradedContext:
    @pytest.mark.parametrize("phase", ALL_PHASES)
    def test_scaffold_rendered_for_every_phase(self, phase: str):
        block = render_degraded_context(phase)
        assert block.startswith("<reasoning_context>")
        assert block.rstrip().endswith("</reasoning_context>")
        assert "No external reasoning trace is available" in block
        assert "scaffold" in block

    def test_unknown_phase_falls_back_to_generic_scaffold(self):
        block = render_degraded_context("mystery")
        assert "scaffold" in block
        assert "decompose" in block


class TestFullTraceContext:
    def _trace(self) -> ReasoningTrace:
        return ReasoningTrace(
            phase="analyze",
            steps=[
                ReasoningStep(
                    tool="shannon", step_number=1, phase_tag="problem_definition",
                    thought="Decompose: 10M users; 99.99% uptime.",
                    assumptions=["traffic grows"], uncertainty=0.2,
                ),
                ReasoningStep(
                    tool="code", step_number=2, branch_id="AltA",
                    thought="Scale signal dominates simplicity.", uncertainty=0.1,
                ),
            ],
        )

    def test_header_tools_and_trace_lines(self):
        block = render_reasoning_context("analyze", self._trace())
        assert "PHASE: analyze" in block
        assert "TOOLS: code, shannon" in block
        assert "STEPS: 2" in block
        assert "[1|shannon|problem_definition|u=0.2]" in block
        assert "[2|code|branch=AltA|u=0.1]" in block
        assert "assumptions: traffic grows" in block
        assert "not instructions" in block

    def test_abort_note_rendered_when_incomplete(self):
        trace = self._trace()
        trace.aborted_reason = "thought generation failed at step 3"
        block = render_reasoning_context("analyze", trace)
        assert "trace incomplete" in block

    def test_phase_specific_guidance(self):
        assert "conflict" in render_reasoning_context("analyze", self._trace())
        assert "overview.reasoning" in render_reasoning_context("generate", self._trace())
        assert "findings" in render_reasoning_context("evaluate", self._trace())
        assert "preserved" in render_reasoning_context("retry", self._trace())


class TestStepPrompt:
    def test_contains_focus_directive_trace_and_inputs(self):
        prompt = build_step_user_prompt(
            phase="analyze",
            system_directive="Reason only from evidence.",
            agenda_focus="Decompose the requirements.",
            trace_rendered="  [1|code] prior step",
            task_inputs={"requirements": "10M users, PCI-DSS"},
            step_number=2,
            total=4,
        )
        assert "step 2 of 4" in prompt
        assert "Decompose the requirements." in prompt
        assert "Reason only from evidence." in prompt
        assert "[1|code] prior step" in prompt
        assert "<requirements>" in prompt
        assert "ThoughtDraft" in prompt

    def test_first_step_notes_empty_trace(self):
        prompt = build_step_user_prompt(
            "evaluate", "d", "focus", "", {"requirements": "r", "criteria": "c"}, 1, 3,
        )
        assert "no prior steps" in prompt

    def test_long_inputs_truncated(self):
        prompt = build_step_user_prompt(
            "analyze", "d", "focus", "",
            {"requirements": "x" * 20000}, 1, 1,
        )
        assert "[truncated]" in prompt
        assert len(prompt) < 20000


class TestPipelineInjection:
    def test_analyze_user_prompt_injects_block_before_gate(self):
        prompt = ArchitecturePipeline._build_analyze_user_prompt(
            bare_pipeline(), "reqs", "fintech",
            reasoning_context=render_degraded_context("analyze"),
        )
        assert "</domain>" in prompt
        assert prompt.index("</domain>") < prompt.index("<reasoning_context>")
        assert prompt.index("</reasoning_context>") < prompt.index("<reasoning_gate>")

    def test_analyze_user_prompt_default_empty(self):
        prompt = ArchitecturePipeline._build_analyze_user_prompt(bare_pipeline(), "reqs", "d")
        assert "<reasoning_context>" not in prompt

    def _design(self) -> ArchitectureDesign:
        from src.schemas.components import Component

        return ArchitectureDesign(
            overview={
                "reasoning": "r", "style": "microservices", "category": "structural",
                "principles": ["single responsibility"], "constraints": [],
            },
            components=[
                Component(
                    id="svc", name="Svc", type="service", description="d",
                    responsibilities=["serve requests"],
                )
            ],
            relationships=[],
            quality_attributes={},
        )

    def test_generate_user_prompt_injects_block_after_summary(self):
        pipeline = bare_pipeline()
        sections = ("-", "-", "details")
        prompt = pipeline._build_generate_user_prompt(  # type: ignore[attr-defined]
            "reqs", "e-commerce", "microservices", sections, None,
            reasoning_context=render_degraded_context("generate"),
        )
        assert "<reasoning_context>" in prompt
        assert prompt.index("</reasoning_context>") < prompt.index("<selected_patterns>")

    def test_evaluate_user_prompt_injects_block_before_gate(self):
        prompt = ArchitecturePipeline._build_evaluate_user_prompt(
            bare_pipeline(), self._design(), "quality", "fintech", [],
            requirements="reqs", analysis_result=None,
            reasoning_context=render_degraded_context("evaluate"),
        )
        assert "<reasoning_context>" in prompt
        assert prompt.index("</reasoning_context>") < prompt.index("<reasoning_gate>")

    def test_retry_prompt_injects_block_before_preserve_contract(self):
        from src.schemas.evaluation import ArchitectureEvaluation, EvaluationSummary

        evaluation = ArchitectureEvaluation(
            summary=EvaluationSummary(
                overall_score=60.0, strengths=["s"], weaknesses=["w"],
                critical_findings=["c"],
            ),
            metrics=[],
            recommendations={"general": ["fix svc"]},
        )
        prompt = ArchitecturePipeline._retry_prompt(
            bare_pipeline(), self._design(), evaluation, "reqs", "microservices", "d",
            selected_pattern=None,
            reasoning_context=render_degraded_context("retry"),
        )
        assert "<reasoning_context>" in prompt
        assert prompt.index("</reasoning_context>") < prompt.index("<preserve_contract>")


class TestConflictExample:
    def test_conflict_example_valid_and_peaked_on_scalability(self):
        weights = REQUIREMENT_WEIGHTS_EXAMPLE_CONFLICT.as_dict()
        assert max(weights.values()) == 1.0
        assert weights["scalability"] == 1.0
        assert weights["simplicity"] == 0.2  # vague signal loses to numeric SLO
        assert weights["performance"] == 0.7  # concrete but secondary

    def test_conflict_example_rendered_as_example_four(self):
        from src.pipeline import _analyze_system_prompt_cached

        system_prompt = _analyze_system_prompt_cached()
        assert "Example 4" in system_prompt
        assert "conflict resolution" in system_prompt.lower()
        assert '"scalability": 1.0' in system_prompt
        assert '"simplicity": 0.2' in system_prompt
