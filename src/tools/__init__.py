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
Tool factory functions for MCP tools.

DP-4: Factory Pattern - Consistent tool creation with proper initialization
DP-5: Dependency Injection - Constructor injection of dependencies

Each factory function creates a tool instance with the appropriate dependencies.
"""

from src.tools.analyze import analyze_architecture_tool
from src.tools.cancel_architecture_design import cancel_architecture_design_tool
from src.tools.design import design_architecture_tool
from src.tools.evaluate import evaluate_architecture_tool
from src.tools.generate import generate_architecture_tool
from src.tools.get_architecture_design_status import get_architecture_design_status_tool
from src.tools.patterns import (
    get_architecture_pattern_tool,
    list_architecture_patterns_tool,
)
from src.tools.submit_architecture_design import (
    submit_architecture_design_job_tool,
)

__all__ = [
    "analyze_architecture_tool",
    "cancel_architecture_design_tool",
    "design_architecture_tool",
    "evaluate_architecture_tool",
    "generate_architecture_tool",
    "get_architecture_design_status_tool",
    "get_architecture_pattern_tool",
    "list_architecture_patterns_tool",
    "submit_architecture_design_job_tool",
]


def create_all_tools(
    agent,
    pipeline,
    pattern_loader,
    tasks_config=None,
    *,
    job_tasks: dict[str, tuple] | None = None,
):
    """
    Factory function to create all MCP tool instances.

    DP-4: Factory Pattern - Consistent tool creation with proper dependencies

    Args:
        agent: SoftwareArchitectAgent instance for LLM interactions.
        pipeline: ArchitecturePipeline instance for orchestrating design pipeline.
        pattern_loader: PatternLoader instance for direct pattern catalog access.
        tasks_config: TasksConfig instance for heartbeat settings (None = defaults applied).
        job_tasks: Shared {job_id: (task, cancellation_token)} registry for
                   the submit/get_status/cancel tool trio.

    Returns:
        dict: Dictionary mapping tool names to tool instances.
    """
    jt = job_tasks if job_tasks is not None else {}
    return {
        "design_architecture": design_architecture_tool(agent, pipeline, tasks_config=tasks_config),
        "analyze_architecture": analyze_architecture_tool(agent, pipeline, tasks_config=tasks_config),
        "generate_architecture": generate_architecture_tool(agent, pipeline, tasks_config=tasks_config),
        "evaluate_architecture": evaluate_architecture_tool(agent, pipeline, tasks_config=tasks_config),
        "list_architecture_patterns": list_architecture_patterns_tool(pattern_loader),
        "get_architecture_pattern": get_architecture_pattern_tool(pattern_loader),
        "submit_architecture_design_job": submit_architecture_design_job_tool(agent, pipeline, job_tasks=jt),
        "get_architecture_design_status": get_architecture_design_status_tool(),
        "cancel_architecture_design": cancel_architecture_design_tool(job_tasks=jt),
    }
