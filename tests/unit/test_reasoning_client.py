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
Unit tests for the server-side reasoning integration (Plan v5).

Covers:
- ReasoningConfig defaults (enabled=True, embedded commands, env expansion)
- Pinned tool contracts (shannonthinking camelCase, code-reasoning snake_case)
- ThoughtDraft adapters (per-tool casings, client-assigned numbering)
- ReasoningClient._resolve_cmd (override → embedded → npx fallback)
- ThoughtGenerator loop (happy path, tool failure, agent failure, disabled)
- Trace cache (analyze/generate cached, evaluate/retry not)
- health_check statuses (ok / unreachable)
- ReasoningConfig hard-removes the model field (generator LLM always used)
"""

import asyncio
import logging

import pytest
from pydantic import ValidationError

from src.reasoning.client import ReasoningClient
from src.reasoning.config import (
    CODE_REASONING_EMBEDDED_CMD,
    CODE_REASONING_NPX_CMD,
    SHANNON_EMBEDDED_CMD,
    SHANNON_NPX_CMD,
    ReasoningConfig,
)
from src.reasoning.schemas import ReasoningStep, ReasoningTrace, ThoughtDraft
from src.reasoning.tools import (
    CODE_TOOL,
    SHANNON_TOOL,
    draft_to_code_params,
    draft_to_params,
    draft_to_shannon_params,
)


class ScriptedReasoningAgent:
    """Mock SoftwareArchitectAgent returning scripted ThoughtDrafts."""

    def __init__(self, drafts: list[ThoughtDraft] | None = None, fail: bool = False):
        self._drafts = list(drafts or [])
        self._fail = fail
        self.calls = 0

    async def generate_structured(self, system_prompt, user_prompt, response_schema):
        self.calls += 1
        if self._fail:
            raise RuntimeError("reasoning LLM unavailable")
        if self._drafts:
            return self._drafts.pop(0)
        return ThoughtDraft(thought="fallback thought", next_needed=False)


def make_config(**overrides) -> ReasoningConfig:
    defaults = {
        "per_phase": {
            "analyze": ReasoningConfig().get_strategy("analyze"),
            "evaluate": ReasoningConfig().get_strategy("evaluate"),
        }
    }
    defaults.update(overrides)
    return ReasoningConfig(**defaults)


def make_client(agent=None, config: ReasoningConfig | None = None, tool_text: str = "ok") -> ReasoningClient:
    client = ReasoningClient(config or make_config(), agent or ScriptedReasoningAgent())
    async def fake_call_tool(kind, payload):
        return tool_text
    client._call_tool = fake_call_tool  # type: ignore[method-assign]
    return client


class TestReasoningConfig:
    def test_enabled_by_default_with_embedded_commands(self):
        config = ReasoningConfig()
        assert config.enabled is True
        assert list(config.shannonthinking_cmd) == SHANNON_EMBEDDED_CMD
        assert list(config.code_reasoning_cmd) == CODE_REASONING_EMBEDDED_CMD

    def test_empty_string_cmd_resolves_to_embedded_default(self):
        config = ReasoningConfig.model_validate(
            {"shannonthinking_cmd": "", "code_reasoning_cmd": ""}
        )
        assert list(config.shannonthinking_cmd) == SHANNON_EMBEDDED_CMD
        assert list(config.code_reasoning_cmd) == CODE_REASONING_EMBEDDED_CMD

    def test_json_string_override_is_parsed(self):
        config = ReasoningConfig.model_validate(
            {"code_reasoning_cmd": '["npx", "-y", "@mettamatt/code-reasoning"]'}
        )
        assert config.code_reasoning_cmd == ["npx", "-y", "@mettamatt/code-reasoning"]

    def test_invalid_cmd_rejected(self):
        with pytest.raises(Exception):
            ReasoningConfig.model_validate({"shannonthinking_cmd": []})

    def test_all_four_default_strategies_present(self):
        config = ReasoningConfig()
        for phase in ("analyze", "generate", "evaluate", "retry"):
            strategy = config.get_strategy(phase)
            assert strategy.pre_llm_thoughts >= 1
            assert strategy.tools
            assert strategy.step_agenda

    def test_model_field_removed(self):
        assert "model" not in ReasoningConfig.model_fields

    def test_stale_model_key_rejected(self):
        with pytest.raises(ValidationError):
            ReasoningConfig.model_validate({"model": "openai/gpt-4o-mini"})


class TestToolContracts:
    def test_tool_names_pinned(self):
        assert SHANNON_TOOL.name == "shannonthinking"
        assert CODE_TOOL.name == "code-reasoning"

    def test_shannon_adapter_uses_camel_case(self):
        draft = ThoughtDraft(
            thought="step", phase_tag="constraints",
            is_revision=True, revises=1,
        )
        params = draft_to_shannon_params(draft, step_number=2, total=4)
        assert params["thoughtType"] == "constraints"
        assert params["thoughtNumber"] == 2
        assert params["totalThoughts"] == 4
        assert params["nextThoughtNeeded"] is True
        assert "thought_type" not in params
        # Cross-thought references are stripped at the wire: a fresh
        # subprocess cannot resolve them (empty thoughtHistory).
        assert "isRevision" not in params
        assert "revisesThought" not in params

    def test_code_adapter_uses_snake_case(self):
        draft = ThoughtDraft(
            thought="step", branch_id="AltA", branch_from=1,
        )
        params = draft_to_code_params(draft, step_number=1, total=3)
        assert params["thought_number"] == 1
        assert params["total_thoughts"] == 3
        assert params["next_thought_needed"] is True
        assert "thoughtNumber" not in params
        # Branch references are stripped at the wire: ensureBranchIsValid
        # rejects any branch_from_thought > 0 on an empty tracker.
        assert "branch_id" not in params
        assert "branch_from_thought" not in params

    def test_adapter_dispatch(self):
        draft = ThoughtDraft(thought="s")
        assert draft_to_params("shannon", draft, 1, 1)["thoughtType"]
        assert draft_to_params("code", draft, 1, 1)["next_thought_needed"]


class TestShannonPhaseTagCoercion:
    """Deterministic guarantee that shannon accepts every draft regardless
    of LLM phase_tag drift: normalize → alias map → documented fallback.
    Coercion is wire-only — the trace keeps the raw authored value."""

    def test_valid_values_pass_through_unchanged(self):
        for tag in ("problem_definition", "constraints", "model", "proof", "implementation"):
            draft = ThoughtDraft(thought="t", phase_tag=tag)
            assert draft_to_shannon_params(draft, 1, 1)["thoughtType"] == tag

    def test_case_and_whitespace_normalized(self):
        draft = ThoughtDraft(thought="t", phase_tag="  Model ")
        assert draft_to_shannon_params(draft, 1, 1)["thoughtType"] == "model"

    def test_pipeline_phase_echoes_mapped(self):
        cases = {
            "analysis": "problem_definition",
            "generation": "model",
            "evaluation": "proof",
            "retry": "implementation",
        }
        for tag, expected in cases.items():
            draft = ThoughtDraft(thought="t", phase_tag=tag)
            assert draft_to_shannon_params(draft, 1, 1)["thoughtType"] == expected

    def test_arbitrary_unknown_value_falls_back(self):
        # The fallback (not the alias table) is what closes the class:
        # any unforeseen LLM string must still yield a valid enum value.
        # ("Analysis" normalizes to "analysis" and is alias-mapped above.)
        for tag in ("analysis_phase", "requirement-analysis", "stage-x", ""):
            draft = ThoughtDraft(thought="t", phase_tag=tag)
            assert draft_to_shannon_params(draft, 1, 1)["thoughtType"] == "model"

    def test_thought_truncated_to_code_server_limit(self):
        from src.reasoning.tools import _CODE_MAX_THOUGHT_LENGTH

        draft = ThoughtDraft(thought="x" * (_CODE_MAX_THOUGHT_LENGTH + 500))
        params = draft_to_code_params(draft, 1, 1)
        assert len(params["thought"]) == _CODE_MAX_THOUGHT_LENGTH

    @pytest.mark.asyncio
    async def test_trace_keeps_raw_phase_tag(self):
        # Wire-only coercion: ReasoningStep records what the LLM authored
        # (drift stays observable), only the payload is coerced.
        drafts = [ThoughtDraft(thought="step", phase_tag="analysis", next_needed=False)]
        client = make_client(ScriptedReasoningAgent(drafts))
        trace = await client.run_pre_llm("evaluate", {"requirements": "r", "criteria": "c"})
        assert len(trace.steps) == 1  # evaluate strategy: shannon only
        assert trace.steps[0].phase_tag == "analysis"


class TestCrossThoughtReferenceStripping:
    """Wire payloads must not carry references a fresh scratchpad cannot resolve.

    keep_alive=False means every tool call spawns a subprocess with an empty
    thoughtHistory — dependencies, revisions, and branches can never be
    resolved there and the servers reject them. Stripping lives in the
    adapters so the ReasoningStep trace keeps the LLM-authored fields.
    """

    def test_shannon_dependencies_key_present_but_empty(self):
        draft = ThoughtDraft(thought="t", phase_tag="model", dependencies=[1, 2])
        params = draft_to_shannon_params(draft, 3, 4)
        # Key must be present (shannonthinking validates Array.isArray) but
        # empty (any reference fails against the empty thoughtHistory).
        assert params["dependencies"] == []

    def test_shannon_omits_revision_fields(self):
        draft = ThoughtDraft(thought="t", is_revision=True, revises=1)
        params = draft_to_shannon_params(draft, 3, 4)
        assert "isRevision" not in params
        assert "revisesThought" not in params

    def test_code_payload_is_exactly_four_fields(self):
        draft = ThoughtDraft(
            thought="t", is_revision=True, revises=1,
            branch_id="alt", branch_from=1,
        )
        params = draft_to_code_params(draft, 2, 3)
        assert set(params) == {
            "thought", "thought_number", "total_thoughts", "next_thought_needed",
        }

    def test_validate_draft_preserves_dependencies(self):
        # Placement guard: stripping belongs in the wire adapters, NOT in
        # _validate_draft — the trace keeps the LLM-authored references.
        from src.reasoning.client import _validate_draft

        draft = ThoughtDraft(thought="t", dependencies=[1])
        assert _validate_draft(draft, 2).dependencies == [1]


class TestResolveCmd:
    def test_user_override_wins(self, monkeypatch):
        config = ReasoningConfig(shannonthinking_cmd=["node", "/custom/shannon.js"])
        client = ReasoningClient(config, ScriptedReasoningAgent())
        monkeypatch.setattr("os.path.isfile", lambda p: False)
        assert client._resolve_cmd("shannon") == ["node", "/custom/shannon.js"]

    def test_embedded_used_when_file_exists(self, monkeypatch):
        config = ReasoningConfig()  # defaults == embedded
        client = ReasoningClient(config, ScriptedReasoningAgent())
        monkeypatch.setattr("os.path.isfile", lambda p: True)
        assert client._resolve_cmd("code") == CODE_REASONING_EMBEDDED_CMD

    def test_npx_fallback_when_embedded_missing(self, monkeypatch):
        config = ReasoningConfig()
        client = ReasoningClient(config, ScriptedReasoningAgent())
        monkeypatch.setattr("os.path.isfile", lambda p: False)
        assert client._resolve_cmd("shannon") == SHANNON_NPX_CMD
        assert client._resolve_cmd("code") == CODE_REASONING_NPX_CMD


class TestThoughtGeneratorLoop:
    @pytest.mark.asyncio
    async def test_happy_path_records_steps_per_tool(self):
        drafts = [
            ThoughtDraft(thought="step one", phase_tag="problem_definition"),
            ThoughtDraft(thought="step two", phase_tag="constraints", next_needed=False),
        ]
        agent = ScriptedReasoningAgent(drafts)
        client = make_client(agent)
        trace = await client.run_pre_llm("analyze", {"requirements": "10M users"})
        # 2 steps x 2 tools (analyze strategy: code + shannon)
        assert len(trace.steps) == 4
        assert {s.step_number for s in trace.steps} == {1, 2}
        assert all(s.tool_response == "ok" for s in trace.steps)
        assert trace.aborted_reason is None
        assert trace.cached is False
        assert trace.tool_call_counts == {"shannonthinking": 2, "code-reasoning": 2}
        assert agent.calls == 2

    @pytest.mark.asyncio
    async def test_max_total_steps_caps_loop(self):
        drafts = [
            ThoughtDraft(thought="keep going 1", next_needed=True),
            ThoughtDraft(thought="keep going 2", next_needed=True),
            ThoughtDraft(thought="never reached", next_needed=True),
        ]
        agent = ScriptedReasoningAgent(drafts)
        config = make_config(max_total_steps=2)
        client = make_client(agent, config)
        trace = await client.run_pre_llm("evaluate", {"requirements": "r", "criteria": "c"})
        # evaluate strategy has 1 tool → steps == cap (pre_llm_thoughts=3 > cap=2)
        assert len(trace.steps) == 2
        assert agent.calls == 2

    @pytest.mark.asyncio
    async def test_tool_failure_degrades_silently(self):
        drafts = [ThoughtDraft(thought="only step", next_needed=False)]
        client = make_client(ScriptedReasoningAgent(drafts))

        async def failing_call_tool(kind, payload):
            raise FileNotFoundError("node not found")

        client._call_tool = failing_call_tool  # type: ignore[method-assign]
        trace = await client.run_pre_llm("evaluate", {"requirements": "r", "criteria": "c"})
        assert len(trace.steps) == 1
        assert trace.steps[0].tool_response == ""
        assert trace.aborted_reason is None  # step still recorded

    @pytest.mark.asyncio
    async def test_agent_failure_aborts_trace_without_raising(self):
        client = make_client(ScriptedReasoningAgent(fail=True))
        trace = await client.run_pre_llm("evaluate", {"requirements": "r", "criteria": "c"})
        assert trace.steps == []
        assert trace.aborted_reason is not None
        assert "thought generation failed" in (trace.aborted_reason or "")

    @pytest.mark.asyncio
    async def test_disabled_returns_empty_trace_without_llm_calls(self):
        agent = ScriptedReasoningAgent()
        config = make_config(enabled=False)
        client = make_client(agent, config)
        trace = await client.run_pre_llm("analyze", {"requirements": "r"})
        assert trace.steps == []
        assert trace.aborted_reason == "reasoning disabled"
        assert agent.calls == 0

    @pytest.mark.asyncio
    async def test_revision_target_ahead_is_dropped(self):
        drafts = [
            ThoughtDraft(thought="bad revision", is_revision=True, revises=5, next_needed=False),
        ]
        client = make_client(ScriptedReasoningAgent(drafts))
        trace = await client.run_pre_llm("evaluate", {"requirements": "r", "criteria": "c"})
        assert trace.steps[0].is_revision is False
        assert trace.steps[0].revises is None


class TestPerCallLogging:
    """DEBUG lines must fire around every tool call so operators can see
    shannonthinking / code-reasoning invocations (and failures) per step."""

    @pytest.mark.asyncio
    async def test_call_and_response_debug_records(self, caplog):
        drafts = [ThoughtDraft(thought="only step", next_needed=False)]
        client = make_client(ScriptedReasoningAgent(drafts))
        with caplog.at_level(logging.DEBUG, logger="src.reasoning.client"):
            trace = await client.run_pre_llm(
                "evaluate", {"requirements": "r", "criteria": "c"}
            )
        calls = [r for r in caplog.records if "calling reasoning tool" in r.getMessage()]
        responses = [r for r in caplog.records if "responded in" in r.getMessage()]
        # evaluate strategy: 1 thought x 1 tool (shannon only)
        assert trace.tool_call_counts == {"shannonthinking": 1}
        assert len(calls) == 1
        assert len(responses) == 1
        assert calls[0].tool == "shannonthinking"
        assert calls[0].phase == "evaluate"
        assert calls[0].step == 1
        assert "thoughtType" in calls[0].payload_keys
        assert responses[0].ok is True
        assert responses[0].response_chars == len("ok")
        assert calls[0].thought == "only step"
        assert responses[0].tool_response == "ok"

    @pytest.mark.asyncio
    async def test_failure_debug_record_carries_ok_false(self, caplog):
        drafts = [ThoughtDraft(thought="only step", next_needed=False)]
        client = make_client(ScriptedReasoningAgent(drafts))

        async def failing_call_tool(kind, payload):
            raise FileNotFoundError("node not found")

        client._call_tool = failing_call_tool  # type: ignore[method-assign]
        with caplog.at_level(logging.DEBUG, logger="src.reasoning.client"):
            await client.run_pre_llm("evaluate", {"requirements": "r", "criteria": "c"})
        failures = [r for r in caplog.records if "failed in" in r.getMessage()]
        assert len(failures) == 1
        assert failures[0].ok is False
        assert failures[0].tool == "shannonthinking"
        assert "node not found" in failures[0].error
        assert not [r for r in caplog.records if "responded in" in r.getMessage()]
        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING
            and "Reasoning tool call failed" in r.getMessage()
        ]
        assert len(warnings) == 1

    @pytest.mark.asyncio
    async def test_cache_hit_emits_debug_and_marks_trace(self, caplog):
        drafts = [ThoughtDraft(thought="one", next_needed=False)]
        client = make_client(ScriptedReasoningAgent(drafts))
        await client.run_pre_llm("analyze", {"requirements": "same"})
        with caplog.at_level(logging.DEBUG, logger="src.reasoning.client"):
            cached_trace = await client.run_pre_llm("analyze", {"requirements": "same"})
        assert cached_trace.cached is True
        assert any("served from cache" in r.getMessage() for r in caplog.records)


class TestTraceCache:
    @pytest.mark.asyncio
    async def test_analyze_cached_across_calls(self):
        drafts = [ThoughtDraft(thought="one", next_needed=False)]
        agent = ScriptedReasoningAgent([*drafts, ThoughtDraft(thought="should-not-be-used")])
        client = make_client(agent)
        first = await client.run_pre_llm("analyze", {"requirements": "same"})
        second = await client.run_pre_llm("analyze", {"requirements": "same"})
        assert agent.calls == 1
        assert first.steps == second.steps
        assert first.cached is False
        assert second.cached is True
        assert second.tool_call_counts == first.tool_call_counts == {
            "shannonthinking": 1,
            "code-reasoning": 1,
        }

    @pytest.mark.asyncio
    async def test_different_inputs_bypass_cache(self):
        drafts = [
            ThoughtDraft(thought="one", next_needed=False),
            ThoughtDraft(thought="two", next_needed=False),
        ]
        agent = ScriptedReasoningAgent(drafts)
        client = make_client(agent)
        await client.run_pre_llm("analyze", {"requirements": "a"})
        await client.run_pre_llm("analyze", {"requirements": "b"})
        assert agent.calls == 2

    @pytest.mark.asyncio
    async def test_evaluate_not_cached(self):
        drafts = [
            ThoughtDraft(thought="one", next_needed=False),
            ThoughtDraft(thought="two", next_needed=False),
        ]
        agent = ScriptedReasoningAgent(drafts)
        client = make_client(agent)
        await client.run_pre_llm("evaluate", {"requirements": "r", "criteria": "c"})
        await client.run_pre_llm("evaluate", {"requirements": "r", "criteria": "c"})
        assert agent.calls == 2


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_all_ok(self):
        client = make_client(tool_text="probe ok")
        statuses = await client.health_check()
        assert statuses == {"shannonthinking": "ok", "code-reasoning": "ok"}

    @pytest.mark.asyncio
    async def test_unreachable_reported_not_raised(self):
        client = ReasoningClient(make_config(), ScriptedReasoningAgent())

        async def failing(kind, payload):
            if kind == "shannon":
                raise TimeoutError("spawn timed out")
            return "ok"

        client._call_tool = failing  # type: ignore[method-assign]
        statuses = await client.health_check()
        assert statuses["shannonthinking"].startswith("unreachable")
        assert statuses["code-reasoning"] == "ok"

    @pytest.mark.asyncio
    async def test_disabled_reports_disabled(self):
        client = ReasoningClient(make_config(enabled=False), ScriptedReasoningAgent())
        statuses = await client.health_check()
        assert set(statuses.values()) == {"disabled"}


class TestLogNoise:
    """code-reasoning stdout banners must not surface as ERROR stack traces."""

    def _error_record(self, banner: str | None):
        import logging as logging_mod

        exc = None
        if banner is not None:
            exc = ValueError(
                f"Invalid JSON: expected value at line 1 column 1 "
                f"[type=json_invalid, input_value='{banner}', input_type=str]"
            )
        record = logging_mod.LogRecord(
            name="mcp.client.stdio", level=logging_mod.ERROR,
            pathname=__file__, lineno=1,
            msg="Failed to parse JSONRPC message from server", args=(),
            exc_info=(ValueError, exc, None) if exc else None,
        )
        return record

    def test_known_banner_dropped(self):
        from src.reasoning.client import BannerParseNoiseFilter

        f = BannerParseNoiseFilter()
        for banner in (
            "Using config directory: /home/x",
            "Created main config directory: /home/mcpuser/.code-reasoning",
            "PromptManager initialized with 5 prompts",
        ):
            record = self._error_record(banner)
            assert f.filter(record) is False  # dropped entirely

    def test_unknown_payload_stays_error(self):
        from src.reasoning.client import BannerParseNoiseFilter

        f = BannerParseNoiseFilter()
        record = self._error_record("DEFINITELY NOT A BANNER: corrupt frame")
        assert f.filter(record) is True
        assert record.levelno == 40
        assert record.levelname == "ERROR"

    def test_non_parse_error_records_pass_through(self):
        from src.reasoning.client import BannerParseNoiseFilter

        f = BannerParseNoiseFilter()
        record = self._error_record(None)
        record.msg = "Some other stdio failure"
        assert f.filter(record) is True
        assert record.levelno == 40

    def test_filter_installed_once_on_client_init(self):
        from src.reasoning.client import BannerParseNoiseFilter
        import logging as logging_mod

        stdio_logger = logging_mod.getLogger("mcp.client.stdio")
        before = len([f for f in stdio_logger.filters if isinstance(f, BannerParseNoiseFilter)])
        make_client()  # constructs ReasoningClient
        make_client()
        after = len([f for f in stdio_logger.filters if isinstance(f, BannerParseNoiseFilter)])
        assert after == before + (0 if before else 1)

    @pytest.mark.asyncio
    async def test_client_suppresses_protocol_log_notifications(self):
        """fastmcp re-logs server-initiated MCP log notifications (🚀 / 💭);
        the client must pass a no-op log_handler to silence them."""
        from src.reasoning import client as client_module

        captured: dict = {}

        class FakeTransport:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        class FakeClient:
            def __init__(self, transport, **kwargs):
                captured.update(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def call_tool(self, name, payload):
                return "ok"

        monkey_local = pytest.MonkeyPatch()
        monkey_local.setattr(client_module, "StdioTransport", FakeTransport)
        monkey_local.setattr(client_module, "Client", FakeClient)
        try:
            client = ReasoningClient(make_config(), ScriptedReasoningAgent())
            await client._call_tool("code", {"thought": "probe"})
            assert captured["log_file"] is client_module._devnull()
            assert captured["keep_alive"] is False
            handler = captured["log_handler"]
            assert asyncio.iscoroutinefunction(handler)  # fastmcp 3.x awaits it
        finally:
            monkey_local.undo()

    @pytest.mark.asyncio
    async def test_quiet_stderr_keeps_default_routing(self):
        from src.reasoning import client as client_module

        captured: dict = {}

        class FakeTransport:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        class FakeClient:
            def __init__(self, transport, **kwargs):
                captured.update(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def call_tool(self, name, payload):
                return "ok"

        monkey_local = pytest.MonkeyPatch()
        monkey_local.setattr(client_module, "StdioTransport", FakeTransport)
        monkey_local.setattr(client_module, "Client", FakeClient)
        try:
            config = make_config(quiet_stderr=False)
            client = ReasoningClient(config, ScriptedReasoningAgent())
            await client._call_tool("code", {"thought": "probe"})
            assert captured["log_file"] is None
        finally:
            monkey_local.undo()


class TestPipelineReasoningSummaryLog:
    """The phase summary INFO must expose per-tool call counts and the cache
    flag so a cache hit is not misread as fresh tool calls."""

    @pytest.mark.asyncio
    async def test_reasoning_trace_ready_extra_carries_counts_and_cached(
        self, caplog
    ):
        from src.pipeline import ArchitecturePipeline

        class StubClient:
            enabled = True

            async def run_pre_llm(self, phase, task_inputs):
                return ReasoningTrace(
                    phase=phase,
                    steps=[
                        ReasoningStep(tool="shannon", step_number=1, thought="t")
                    ],
                    duration_ms=1.0,
                    tool_call_counts={"shannonthinking": 1},
                )

        pipeline = ArchitecturePipeline.__new__(ArchitecturePipeline)
        pipeline._reasoning = StubClient()  # type: ignore[assignment]
        with caplog.at_level(logging.INFO, logger="src.pipeline"):
            await pipeline._reasoning_block(
                "evaluate", {"requirements": "r", "criteria": "c"}
            )
        records = [
            r for r in caplog.records if r.getMessage() == "Reasoning trace ready"
        ]
        assert len(records) == 1
        assert records[0].tools_called == {"shannonthinking": 1}
        assert records[0].cached is False
