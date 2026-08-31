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
ReasoningClient — server-side MCP client for shannonthinking / code-reasoning.

The two reasoning MCP servers are structured SCRATCHPADS: they validate,
number, branch, and record thoughts that a CALLER authors. This client
implements the ThoughtGenerator loop that authors each step with this
server's own LLM (one bounded ``generate_structured`` call per step), then
submits the thought to each configured tool via fastmcp's stdio transport
(``keep_alive=False`` → process-per-call isolation).

Contract: each thought = exactly 1 LLM completion + >=1 MCP tool call,
bounded by ``pre_llm_thoughts <= max_total_steps``.

Failure policy (Plan v5): per-call silent degradation — any spawn, timeout,
or tool error becomes a WARNING and an (optionally partial) trace; run_pre_llm
never raises. Startup is LOUD: ``health_check()`` probes both tools and its
result is logged at ERROR by the server lifespan when unreachable.

Traces for the ``analyze`` and ``generate`` phases are cached by content key
and reused across design_loop attempts (their inputs are constant within a
loop); ``evaluate`` / ``retry`` traces are attempt-specific and uncached.
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from collections import OrderedDict, defaultdict
from typing import Any, TextIO

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from src.agent import SoftwareArchitectAgent
from src.reasoning.config import (
    CODE_REASONING_EMBEDDED_CMD,
    CODE_REASONING_NPX_CMD,
    SHANNON_EMBEDDED_CMD,
    SHANNON_NPX_CMD,
    ReasoningConfig,
    ReasoningTool,
)
from src.reasoning.prompts import (
    REASONING_STEP_SYSTEM_PROMPT,
    build_step_user_prompt,
)
from src.reasoning.schemas import ReasoningStep, ReasoningTrace, ThoughtDraft
from src.reasoning.tools import TOOL_CONTRACTS, draft_to_params

logger = logging.getLogger(__name__)

_CACHEABLE_PHASES: frozenset[str] = frozenset({"analyze", "generate"})
_CACHE_MAX_ENTRIES: int = 64

_TOOL_RESPONSE_CAP: int = 300
_SUBPROCESS_ENV_KEYS: tuple[str, ...] = ("PATH", "HOME", "LANG", "LC_ALL")

_MCP_STDIO_LOGGER_NAME = "mcp.client.stdio"
_BANNER_PARSE_NOISE_MSG = "Failed to parse JSONRPC message from server"

# code-reasoning 0.7.x/0.8.x prints these plain-text startup banners on
# stdout — its MCP protocol channel — so the mcp SDK's stdout reader logs
# each one as an ERROR with a full traceback, once per subprocess spawn.
# Every occurrence recovers cleanly, so matching records are dropped; any
# other parse failure still surfaces at ERROR.
_BANNER_MARKERS: tuple[str, ...] = (
    "Using config directory",
    "Created main config",
    "PromptManager initialized",
    "Prompt values will be stored",
)


class BannerParseNoiseFilter(logging.Filter):
    """Drop known code-reasoning stdout-banner parse errors entirely.

    Downgrading the level is not enough: the mcp SDK logs these records via
    ``logger.error(...)`` and handlers without an explicit level (root
    handler default NOTSET) still emit DEBUG-mutated records. Dropping is
    safe — the banner lines carry no information (the cause is known and the
    session recovers), while genuine protocol corruption does not match the
    markers and still surfaces at ERROR.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage() != _BANNER_PARSE_NOISE_MSG:
            return True
        exc = record.exc_info[1] if record.exc_info else None
        if exc is not None and any(marker in str(exc) for marker in _BANNER_MARKERS):
            return False  # known-benign banner line — drop
        return True


async def _noop_log_handler(*_args: Any, **_kwargs: Any) -> None:
    """Swallow MCP server-initiated log notifications (fastmcp client channel).

    code-reasoning relays its 🚀 ready notice and every 💭 Thought through
    the protocol's logging notifications, which fastmcp re-logs at INFO.
    The thought content is already captured in the reasoning trace, so
    re-logging it doubles the output for no value. Must be a coroutine
    function — fastmcp 3.x awaits the handler (a sync callable fails with
    "object NoneType can't be used in 'await' expression").
    """


def _install_banner_noise_filter() -> None:
    """Idempotently attach the noise filter to the mcp stdio client logger."""
    stdio_logger = logging.getLogger(_MCP_STDIO_LOGGER_NAME)
    if not any(isinstance(f, BannerParseNoiseFilter) for f in stdio_logger.filters):
        stdio_logger.addFilter(BannerParseNoiseFilter())


_devnull_stream: TextIO | None = None


def _devnull() -> TextIO:
    """Lazily-opened shared devnull stream for subprocess stderr routing."""
    global _devnull_stream  # noqa: PLW0603 — module-lifetime singleton, opened once
    if _devnull_stream is None:
        _devnull_stream = open(os.devnull, "w")  # noqa: SIM115 — process lifetime
    return _devnull_stream


def _subprocess_env() -> dict[str, str]:
    """Minimal env for stdio subprocesses (they inherit nothing by default)."""
    return {key: os.environ[key] for key in _SUBPROCESS_ENV_KEYS if os.environ.get(key)}


def _extract_tool_text(result: Any) -> str:
    """Best-effort text extraction from a fastmcp CallToolResult."""
    data = getattr(result, "data", None)
    if isinstance(data, str) and data.strip():
        return data.strip()[:_TOOL_RESPONSE_CAP]
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return " ".join(parts)[:_TOOL_RESPONSE_CAP]


class ReasoningClient:
    """Author-and-submit reasoning loop over the embedded reasoning MCPs.

    Attributes:
        _config: ReasoningConfig (enabled flag, commands, timeouts, strategies).
        _agent: SoftwareArchitectAgent used for thought generation (the main
            generator agent, or a dedicated one when ``config.model`` is set).
    """

    def __init__(self, config: ReasoningConfig, agent: SoftwareArchitectAgent) -> None:
        self._config = config
        self._agent = agent
        self._trace_cache: OrderedDict[tuple[str, str], ReasoningTrace] = OrderedDict()
        self._cache_lock = asyncio.Lock()
        self._inflight: dict[tuple[str, str], asyncio.Task[ReasoningTrace]] = {}
        _install_banner_noise_filter()

    # ──────────────────────────────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────────────────────────────

    @property
    def config(self) -> ReasoningConfig:
        return self._config

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    # ──────────────────────────────────────────────────────────────────────
    # Command resolution: user override → embedded → npx fallback
    # ──────────────────────────────────────────────────────────────────────

    def _resolve_cmd(self, kind: ReasoningTool) -> list[str]:
        """Resolve the invocation command for a reasoning tool.

        Order:
          1. A configured command that differs from the embedded default is a
             user override and is used as-is.
          2. The Docker-embedded entry point, when its script file exists.
          3. ``npx -y <pkg>@<pinned>`` fallback (downloads on first use).
        """
        if kind == "shannon":
            configured, embedded, npx = (
                list(self._config.shannonthinking_cmd),
                SHANNON_EMBEDDED_CMD,
                SHANNON_NPX_CMD,
            )
        else:
            configured, embedded, npx = (
                list(self._config.code_reasoning_cmd),
                CODE_REASONING_EMBEDDED_CMD,
                CODE_REASONING_NPX_CMD,
            )

        if configured != embedded:
            return configured

        if embedded[0] == "node" and os.path.isfile(embedded[1]):
            return embedded

        logger.info(
            "Reasoning MCP '%s' embedded binary not found; falling back to npx",
            kind,
            extra={"tool": kind, "fallback_cmd": npx},
        )
        return npx

    # ──────────────────────────────────────────────────────────────────────
    # Tool invocation (process-per-call via fastmcp StdioTransport)
    # ──────────────────────────────────────────────────────────────────────

    async def _call_tool(self, kind: ReasoningTool, payload: dict[str, Any]) -> str:
        """Invoke one tool call in a fresh subprocess; returns response text.

        Raises whatever fastmcp raises (spawn failure, timeout, tool error) —
        callers translate failures into silent degradation.
        """
        cmd = self._resolve_cmd(kind)
        contract = TOOL_CONTRACTS[kind]
        budget = self._config.spawn_timeout_seconds + self._config.step_timeout_seconds
        transport = StdioTransport(
            command=cmd[0],
            args=cmd[1:],
            env=_subprocess_env(),
            keep_alive=False,
            log_file=_devnull() if self._config.quiet_stderr else None,
        )
        async with Client(transport, log_handler=_noop_log_handler) as client:
            result = await asyncio.wait_for(
                client.call_tool(contract.name, payload), timeout=budget
            )
        return _extract_tool_text(result)

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    async def run_pre_llm(self, phase: str, task_inputs: dict[str, str]) -> ReasoningTrace:
        """Run the ThoughtGenerator loop for a phase; never raises.

        Args:
            phase: "analyze" | "generate" | "evaluate" | "retry".
            task_inputs: Phase-specific named input blocks (e.g.
                ``{"requirements": ...}``), rendered into each step prompt.

        Returns:
            A ReasoningTrace — possibly empty/partial under silent degradation.
        """
        if not self._config.enabled:
            return ReasoningTrace(phase=phase, aborted_reason="reasoning disabled")

        if phase in _CACHEABLE_PHASES:
            return await self._run_cached(phase, task_inputs)
        return await self._generate_trace(phase, task_inputs)

    async def health_check(self) -> dict[str, str]:
        """Probe each reasoning tool once with a minimal payload.

        Returns a per-tool status map: "ok" or "unreachable: <reason>".
        Never raises; used by the server lifespan for LOUD startup reporting.
        """
        statuses: dict[str, str] = {}
        if not self._config.enabled:
            return {contract.name: "disabled" for contract in TOOL_CONTRACTS.values()}
        for kind, contract in TOOL_CONTRACTS.items():
            try:
                await self._call_tool(kind, contract.probe_payload)
                statuses[contract.name] = "ok"
            except Exception as exc:  # noqa: BLE001 — deliberate: report, don't raise
                statuses[contract.name] = f"unreachable: {exc}"
        return statuses

    async def close(self) -> None:
        """No persistent subprocesses (keep_alive=False); cancel in-flight work."""
        for task in list(self._inflight.values()):
            task.cancel()
        self._inflight.clear()
        self._trace_cache.clear()

    # ──────────────────────────────────────────────────────────────────────
    # ThoughtGenerator loop
    # ──────────────────────────────────────────────────────────────────────

    async def _generate_trace(self, phase: str, task_inputs: dict[str, str]) -> ReasoningTrace:
        strategy = self._config.get_strategy(phase)
        total = min(strategy.pre_llm_thoughts, self._config.max_total_steps)
        agenda = strategy.step_agenda or [f"Reason about the {phase} task."]
        steps: list[ReasoningStep] = []
        counts: defaultdict[str, int] = defaultdict(int)  # keyed by MCP tool name
        aborted: str | None = None
        started = time.perf_counter()

        for step_number in range(1, total + 1):
            focus = agenda[min(step_number - 1, len(agenda) - 1)]
            rendered = _render_steps(steps)
            try:
                draft = await self._agent.generate_structured(
                    system_prompt=REASONING_STEP_SYSTEM_PROMPT,
                    user_prompt=build_step_user_prompt(
                        phase, strategy.system_directive, agenda_focus=focus,
                        trace_rendered=rendered, task_inputs=task_inputs,
                        step_number=step_number, total=total,
                    ),
                    response_schema=ThoughtDraft,
                )
                draft = _validate_draft(draft, step_number)
            except Exception as exc:  # noqa: BLE001 — silent degradation contract
                logger.warning(
                    "Thought generation failed; trace ends here",
                    extra={"phase": phase, "step": step_number, "error": str(exc)},
                )
                aborted = f"thought generation failed at step {step_number}: {exc}"
                break

            for tool_kind in strategy.tools:
                contract = TOOL_CONTRACTS[tool_kind]
                payload = draft_to_params(tool_kind, draft, step_number, total)
                tool_response = ""
                call_started = time.perf_counter()
                logger.debug(
                    "calling reasoning tool '%s' (phase=%s step=%d/%d)",
                    contract.name,
                    phase,
                    step_number,
                    total,
                    extra={
                        "tool": contract.name,
                        "phase": phase,
                        "step": step_number,
                        "total": total,
                        "payload_keys": sorted(payload),
                        "thought": draft.thought,
                    },
                )
                try:
                    tool_response = await self._call_tool(tool_kind, payload)
                    counts[contract.name] += 1
                    elapsed_ms = round((time.perf_counter() - call_started) * 1000.0, 1)
                    logger.debug(
                        "reasoning tool '%s' responded in %.1f ms (%d chars)",
                        contract.name,
                        elapsed_ms,
                        len(tool_response),
                        extra={
                            "tool": contract.name,
                            "phase": phase,
                            "step": step_number,
                            "duration_ms": elapsed_ms,
                            "response_chars": len(tool_response),
                            "tool_response": tool_response,
                            "ok": True,
                        },
                    )
                except Exception as exc:  # noqa: BLE001 — silent degradation contract
                    elapsed_ms = round((time.perf_counter() - call_started) * 1000.0, 1)
                    logger.debug(
                        "reasoning tool '%s' failed in %.1f ms",
                        contract.name,
                        elapsed_ms,
                        extra={
                            "tool": contract.name,
                            "phase": phase,
                            "step": step_number,
                            "duration_ms": elapsed_ms,
                            "ok": False,
                            "error": str(exc),
                        },
                    )
                    logger.warning(
                        "Reasoning tool call failed; continuing without its feedback",
                        extra={
                            "phase": phase,
                            "step": step_number,
                            "tool": contract.name,
                            "error": str(exc),
                        },
                    )
                steps.append(
                    ReasoningStep(
                        tool=tool_kind,
                        step_number=step_number,
                        phase_tag=draft.phase_tag,
                        branch_id=draft.branch_id,
                        is_revision=draft.is_revision,
                        revises=draft.revises,
                        thought=draft.thought,
                        assumptions=list(draft.assumptions),
                        dependencies=list(draft.dependencies),
                        uncertainty=draft.uncertainty,
                        tool_response=tool_response,
                    )
                )

            if not draft.next_needed:
                break

        duration_ms = round((time.perf_counter() - started) * 1000.0, 1)
        return ReasoningTrace(
            phase=phase,
            steps=steps,
            aborted_reason=aborted,
            duration_ms=duration_ms,
            tool_call_counts=dict(counts),
        )

    # ──────────────────────────────────────────────────────────────────────
    # Trace cache (analyze / generate): LRU + single-flight
    # ──────────────────────────────────────────────────────────────────────

    async def _run_cached(self, phase: str, task_inputs: dict[str, str]) -> ReasoningTrace:
        key = (phase, _cache_key(task_inputs))
        async with self._cache_lock:
            cached = self._trace_cache.get(key)
            if cached is not None:
                self._trace_cache.move_to_end(key)
                logger.debug(
                    "reasoning trace served from cache (phase=%s)",
                    phase,
                    extra={"phase": phase, "cached": True},
                )
                # model_copy keeps the shared cache entry pristine.
                return cached.model_copy(update={"cached": True})
            inflight = self._inflight.get(key)
            if inflight is None:
                inflight = asyncio.create_task(self._generate_trace(phase, task_inputs))
                self._inflight[key] = inflight
        try:
            trace = await asyncio.shield(inflight)
        except asyncio.CancelledError:
            async with self._cache_lock:
                self._inflight.pop(key, None)
            raise
        except Exception:
            async with self._cache_lock:
                self._inflight.pop(key, None)
            return ReasoningTrace(phase=phase, aborted_reason="trace generation failed")
        async with self._cache_lock:
            self._inflight.pop(key, None)
            if trace.steps:
                self._trace_cache[key] = trace
                while len(self._trace_cache) > _CACHE_MAX_ENTRIES:
                    self._trace_cache.popitem(last=False)
        return trace


def _validate_draft(draft: ThoughtDraft, step_number: int) -> ThoughtDraft:
    """Clamp client-owned invariants: numbering and revision targets."""
    if draft.revises is not None and draft.revises >= step_number:
        draft = draft.model_copy(update={"revises": None, "is_revision": False})
    if draft.is_revision and draft.revises is None:
        draft = draft.model_copy(update={"is_revision": False})
    return draft


def _render_steps(steps: list[ReasoningStep]) -> str:
    """Render recorded steps as trace lines for the next step prompt."""
    lines: list[str] = []
    for step in steps:
        meta = [str(step.step_number), step.tool]
        if step.phase_tag:
            meta.append(step.phase_tag)
        line = f"  [{'|'.join(meta)}] {step.thought}"
        if step.assumptions:
            line += f" (assumptions: {'; '.join(step.assumptions)})"
        lines.append(line)
    return "\n".join(lines)


def _cache_key(task_inputs: dict[str, str]) -> str:
    canonical = json.dumps(task_inputs, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
