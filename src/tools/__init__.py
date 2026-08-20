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

from src.tools.analyze import AnalyzeArchitectureTool, analyze_architecture_tool
from src.tools.cancel_design import CancelDesignTool, cancel_design_tool
from src.tools.design import DesignArchitectureTool, design_architecture_tool
from src.tools.evaluate import EvaluateArchitectureTool, evaluate_architecture_tool
from src.tools.generate import GenerateArchitectureTool, generate_architecture_tool
from src.tools.get_design_status import GetDesignStatusTool, get_design_status_tool
from src.tools.patterns import (
    GetArchitecturePatternTool,
    ListArchitecturePatternsTool,
    get_architecture_pattern_tool,
    list_architecture_patterns_tool,
)
from src.tools.start_design import StartDesignArchitectureTool, start_design_architecture_tool

__all__ = [
    "AnalyzeArchitectureTool",
    "CancelDesignTool",
    "DesignArchitectureTool",
    "EvaluateArchitectureTool",
    "GenerateArchitectureTool",
    "GetDesignStatusTool",
    "GetArchitecturePatternTool",
    "ListArchitecturePatternsTool",
    "StartDesignArchitectureTool",
    "analyze_architecture_tool",
    "cancel_design_tool",
    "design_architecture_tool",
    "evaluate_architecture_tool",
    "generate_architecture_tool",
    "get_design_status_tool",
    "get_architecture_pattern_tool",
    "list_architecture_patterns_tool",
    "start_design_architecture_tool",
]


def create_all_tools(agent, pipeline, pattern_loader, tasks_config=None):
    """
    Factory function to create all MCP tool instances.

    DP-4: Factory Pattern - Consistent tool creation with proper dependencies

    Args:
        agent: SoftwareArchitectAgent instance for LLM interactions.
        pipeline: ArchitecturePipeline instance for orchestrating design pipeline.
        pattern_loader: PatternLoader instance for direct pattern catalog access.
        tasks_config: TasksConfig instance for heartbeat settings (None = defaults applied).

    Returns:
        dict: Dictionary mapping tool names to tool instances.
    """
    return {
        "design_architecture": design_architecture_tool(agent, pipeline, tasks_config=tasks_config),
        "analyze_architecture": analyze_architecture_tool(agent, pipeline, tasks_config=tasks_config),
        "generate_architecture": generate_architecture_tool(agent, pipeline, tasks_config=tasks_config),
        "evaluate_architecture": evaluate_architecture_tool(agent, pipeline, tasks_config=tasks_config),
        "list_architecture_patterns": list_architecture_patterns_tool(pattern_loader),
        "get_architecture_pattern": get_architecture_pattern_tool(pattern_loader),
        "start_design_architecture": start_design_architecture_tool(agent, pipeline),
        "get_design_status": get_design_status_tool(),
        "cancel_design": cancel_design_tool(),
    }
