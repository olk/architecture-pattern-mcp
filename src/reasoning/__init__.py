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

"""src/reasoning — server-side reasoning MCP integration (Plan v5).

Makes architecture-pattern-mcp an MCP CLIENT of two structured reasoning
scratchpads (shannonthinking, code-reasoning) and injects their traces into
the ANALYZE / GENERATE / EVALUATE / RETRY phase prompts as
<reasoning_context>. Silent per-call degradation + loud startup health check.

Modules:
    config: ReasoningConfig / ReasoningStrategy (REASONING_* env wiring).
    schemas: ThoughtDraft, ReasoningStep, ReasoningTrace.
    tools: pinned tool contracts + ThoughtDraft adapters (per-tool casings).
    prompts: step prompts + <reasoning_context> renderers (incl. degraded).
    client: ReasoningClient (ThoughtGenerator loop, cache, health check).

Import note: ``client`` is exported lazily (PEP 562). Importing it eagerly
here would create a cycle (client → src.agent → src.config → this package).
"""

from typing import TYPE_CHECKING

from src.reasoning.config import (
    ReasoningConfig,
    ReasoningPhase,
    ReasoningStrategy,
    ReasoningTool,
)
from src.reasoning.schemas import ReasoningStep, ReasoningTrace, ThoughtDraft

if TYPE_CHECKING:
    from src.reasoning.client import ReasoningClient

__all__ = [
    "ReasoningClient",
    "ReasoningConfig",
    "ReasoningPhase",
    "ReasoningStep",
    "ReasoningStrategy",
    "ReasoningTool",
    "ReasoningTrace",
    "ThoughtDraft",
]


def __getattr__(name: str) -> object:
    if name == "ReasoningClient":
        from src.reasoning import client as _client

        return getattr(_client, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
