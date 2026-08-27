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
MCPArchitectServer - FastMCP server entry point with lifespan management and tool registration.

FR-240: The system SHALL provide an MCPArchitectServer class
FR-241: The system SHALL expose nine MCP tools via list_tools handler
FR-242: The system SHALL route tool calls via call_tool handler
FR-247: The system SHALL expose four MCP prompts via prompts/list handler
FR-248: Prompt design_architecture_workflow SHALL guide analyze -> generate -> evaluate -> refine
FR-249: Prompt explore_pattern_catalog SHALL dynamically embed live pattern metadata
FR-250: Prompts SHALL be idempotently registered (survive lifespan re-entry)

Implementation Constraints:
- IC-37: Lifespan function SHALL use yield statement
- IC-38: Cleanup code SHALL be wrapped in finally blocks
- IC-39: Context dictionary SHALL be accessible via ctx.lifespan_context
- IC-40: ctx.transport property SHALL return stdio or streamable-http

Architecture Decisions:
- ADR-1: Python 3.12+ with FastMCP for MCP Protocol Implementation
- ADR-3: MCP Tool-Based API with Four Core Tools
- ADR-9: User-Invoked Workflow Prompts as Slash-Command Templates
- DP-4: Factory Pattern for tool creation
- DP-7: Adapter Pattern for protocol interface adaptation

Error Handling:
- E-11: ERR_011 - Server initialization failed (HTTP 500, severity: critical)
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from collections.abc import Sequence
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.transforms import GetToolNext, PromptsAsTools, Transform, VersionSpec
from fastmcp.tools.base import Tool, ToolAnnotations

from src.agent import SoftwareArchitectAgent
from src.tools.jobs import JobsStore
from src.config import ConfigManager, ServerConfig
from src.patterns.loader import PatternLoader
from src.patterns.vector_index import DomainVectorIndex
from src.pipeline import ArchitecturePipeline, CancellationToken
from src.resources.components import build_component_blueprints, slugify
from src.resources.patterns import PatternResource
from src.resources.templates import RESOURCES
from src.tools import create_all_tools


async def server_main(
    config_path: str | None = None,
    *,
    transport: str | None = None,
    host: str | None = None,
    port: int | None = None,
) -> None:
    """
    Main function for the MCP server.

    This function serves as the entry point for the MCP server,
    initializing all components through the lifespan context,
    setting up the stdio transport, and handling any startup errors gracefully.

    Args:
        config_path: Optional path to config file
        transport: Optional transport override ("stdio" or "streamable-http")
        host: Optional host override for HTTP transport
        port: Optional port override for HTTP transport
    """
    import logging
    import os
    import sys

    logger = logging.getLogger(__name__)

    resolved_config = os.environ.get("CONFIG_PATH") or config_path or "~/.config/architecture-pattern-mcp/config.json"
    resolved_config = os.path.abspath(os.path.expanduser(resolved_config))

    try:
        logger.info(f"Starting MCPArchitectServer, using config: {resolved_config}")

        server = MCPArchitectServer(
            config_path=resolved_config,
            transport=transport,
            host=host,
            port=port,
        )
        await server.run()
    except ValueError as e:
        logger.critical(f"Invalid configuration: {e}")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Failed to start MCP server: {e}")
        print(f"Error: Failed to start MCP server: {e}", file=sys.stderr)
        sys.exit(1)


# Error code for E-11
ERROR_SERVER_INIT = "ERR_011"

logger = logging.getLogger(__name__)


def configure_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """
    Configure library logging to redirect to stderr.

    FR-246: The system SHALL redirect library logs to stderr
    IC-29: Library logs redirected to stderr, stdout clean for MCP

    This ensures stdout remains clean for MCP stdio protocol communication.

    Args:
        log_level: Logging level (DEBUG|INFO|WARNING|ERROR|CRITICAL)
        log_format: Logging format (json|text)
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    stderr_handler = logging.StreamHandler(sys.stderr)

    if log_format.lower() == "json":
        import json

        class JSONFormatter(logging.Formatter):
            # Standard LogRecord attributes — always present on every record;
            # exclude from extra detection so they don't leak into the output.
            _STANDARD_ATTRS = frozenset({
                "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                "created", "msecs", "relativeCreated", "thread", "threadName",
                "processName", "process", "taskName", "message", "asctime",
            })

            def format(self, record: logging.LogRecord) -> str:
                log_entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),  # noqa: UP017
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
                # Merge any extra fields attached via extra={...}
                for key, value in record.__dict__.items():
                    if key not in self._STANDARD_ATTRS and not key.startswith("_"):
                        log_entry[key] = value
                if record.exc_info:
                    log_entry["exception"] = self.formatException(record.exc_info)
                return json.dumps(log_entry, default=str)

        stderr_handler.setFormatter(JSONFormatter())
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        stderr_handler.setFormatter(formatter)

    root_logger.addHandler(stderr_handler)


_PROMPTS_AS_TOOLS_HINTS: dict[str, ToolAnnotations] = {
    "list_prompts": ToolAnnotations(
        title="List Prompts",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    "get_prompt": ToolAnnotations(
        title="Get Prompt",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
}


class AnnotatedPromptsAsTools(PromptsAsTools):
    """PromptsAsTools that injects ToolAnnotations on the generated tools.

    Works around PrefectHQ/fastmcp#3459 (still open for PromptsAsTools as of 3.4.4):
    the upstream transform emits list_prompts / get_prompt with annotations=None,
    so MCP clients must assume worst-case. Both generated tools are pure reads of
    server-internal prompt metadata, so we declare readOnlyHint=True post-hoc via
    the public Transform API instead of touching upstream's underscore-prefixed factories.
    """

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        result = await super().list_tools(tools)
        return [_with_prompts_as_tools_annotations(t) for t in result]

    async def get_tool(
        self, name: str, call_next: GetToolNext, *, version: VersionSpec | None = None
    ) -> Tool | None:
        tool = await super().get_tool(name, call_next, version=version)
        return _with_prompts_as_tools_annotations(tool) if tool else None


def _with_prompts_as_tools_annotations(tool: Tool) -> Tool:
    """Return a copy of `tool` with injected ToolAnnotations if it matches a known
    transform-generated tool name. Otherwise return the tool unchanged. Idempotent:
    once FastMCP upstream adds annotations to PromptsAsTools, this becomes a no-op."""
    hints = _PROMPTS_AS_TOOLS_HINTS.get(tool.name)
    if hints is None or tool.annotations is not None:
        return tool
    return tool.model_copy(update={"annotations": hints})


class MCPArchitectServer:
    """
    FastMCP server providing architecture design, analysis, generation, and evaluation tools.

    FR-240: MCPArchitectServer class implemented with FastMCP
    AC-240: Verify MCPArchitectServer class exists, accepts optional config_path parameter

    This server exposes nine MCP tools:

    Synchronous (may take minutes):
      - design_architecture: Full pipeline: analyse → generate → evaluate → refine (up to 3 attempts)
      - analyze_architecture: Analyzes requirements and derives architecture recommendations
      - generate_architecture: Generates new architecture design based on requirements
      - evaluate_architecture: Evaluates an architecture design against quality attributes

    Manual async job pattern (submit/get_status/cancel — for timeout-constrained clients):
      - submit_architecture_design_job: Starts a design job and returns a job_id immediately
      - get_architecture_design_status: Polls job status; returns full design output when completed
      - cancel_architecture_design: Cancels a running job (best-effort; exits at next stage boundary)

    Read-only pattern catalogue:
      - list_architecture_patterns: Lists all 40 patterns; filter by category and/or domain
      - get_architecture_pattern: Returns the full JSON spec for a specific pattern

    Attributes:
        _config_path: Optional path to configuration file
        _config: ServerConfig instance
        _mcp: FastMCP server instance
        _agent: SoftwareArchitectAgent instance
        _pipeline: ArchitecturePipeline instance

    # ADR-1: FastMCP for MCP Protocol Implementation
    # DP-4: Factory Pattern for tool creation
    # DP-7: Adapter Pattern for protocol interface adaptation
    """

    def __init__(
        self,
        config_path: str | None = None,
        *,
        transport: str | None = None,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        """
        Initialize MCPArchitectServer.

        AC-240: Verify MCPArchitectServer class exists, accepts optional config_path parameter

        Args:
            config_path: Optional path to configuration file.
                       Defaults to ~/.config/architecture-pattern-mcp/config.json
            transport: Optional transport override ("stdio" or "streamable-http").
                      Defaults to value in config file or "streamable-http".
            host: Optional host override for HTTP transport.
            port: Optional port override for HTTP transport.

        Raises:
            FileNotFoundError: If configuration file does not exist
            ValueError: If configuration is invalid
        """
        self._config_path = config_path

        # Load configuration synchronously since it's needed before run()
        config_dict = ConfigManager.load_config(self._config_path)

        # CLI overrides — these take precedence over config file values
        if transport is not None:
            config_dict["transport"] = transport
        if host is not None:
            config_dict["host"] = host
        if port is not None:
            config_dict["port"] = port

        self._config = ServerConfig.model_validate(config_dict)

        # Configure logging
        configure_logging(
            log_level=self._config.logging_level,
            log_format=self._config.logging_format
        )

        self._mcp = FastMCP(
            "Architecture Pattern MCP Server",
            lifespan=self.lifespan,
            on_duplicate="error",
        )
        # add_transform is once-per-instance; do NOT move into lifespan without an
        # idempotency guard — add_transform appends, it does not replace.
        self._mcp.add_transform(AnnotatedPromptsAsTools(self._mcp))
        self._agent: SoftwareArchitectAgent | None = None
        self._pipeline: ArchitecturePipeline | None = None
        self._tools: dict[str, Any] = {}
        self._tools_registered: set[str] = set()
        self._resources_registered: bool = False
        self._prompts_registered: bool = False
        self._job_tasks: dict[str, tuple[asyncio.Task[None], CancellationToken]] = {}

        logger.debug(
            "MCPArchitectServer instance created",
            extra={"config_path": self._config_path}
        )

    async def _initialize(self) -> None:
        """
        Initialize server resources: agent, pipeline, and tools.

        IC-37: Lifespan function uses yield statement - initialization in yield body
        IC-39: Context dictionary accessible via ctx.lifespan_context

        Note: Config is loaded in __init__ since it's needed before run()

        Raises:
            LLMError: If LLM initialization fails (E-9)
        """
        try:
            logger.info(
                "Configuration already loaded",
                extra={"config_path": self._config_path}
            )

            # Initialize SoftwareArchitectAgent
            self._agent = SoftwareArchitectAgent(self._config)

            logger.info("SoftwareArchitectAgent initialized")

            # Initialize PatternLoader and DomainVectorIndex
            # Stored on self so resource handlers can reach it via lifespan_context
            self._pattern_loader = PatternLoader(
                patterns_dir=os.path.expanduser(self._config.pattern_directory)
            )

            vector_index = DomainVectorIndex.from_embedder_config(self._config.embedder)

            from src.patterns.bm25_index import DomainBM25Index
            bm25_index = DomainBM25Index()

            logger.info("PatternLoader, DomainVectorIndex, and DomainBM25Index initialized")

            # Initialize ArchitecturePipeline
            self._pipeline = ArchitecturePipeline(
                agent=self._agent,
                pattern_loader=self._pattern_loader,
                vector_index=vector_index,
                bm25_index=bm25_index,
                retrieval_config=self._config.retrieval,
                reranker_config=self._config.reranker,
            )

            logger.info("ArchitecturePipeline initialized")

            # Warm retrieval indexes at startup so a misconfigured TEI sidecar
            # fails fast (orchestrator restart loop) instead of breaking the
            # user's first design request.  asyncio.to_thread avoids blocking
            # the event loop while the (sync) build makes its TEI HTTP call.
            logger.info("Warming up retrieval indexes...")
            await asyncio.to_thread(self._pipeline.warmup_indexes)
            logger.info("Retrieval indexes ready")

            self._pipeline.validate()

            # Create all tool instances using factory pattern
            # DP-4: Factory Pattern - consistent tool creation
            if self._agent and self._pipeline:
                self._tools = create_all_tools(
                    self._agent, self._pipeline, self._pattern_loader,
                    tasks_config=self._config.tasks,
                    job_tasks=self._job_tasks,
                )

                logger.info(
                    "All tools initialized",
                    extra={"tool_count": len(self._tools)}
                )

        except FileNotFoundError as e:
            # E-11: ERR_011 - Server initialization failed
            logger.error(
                "Configuration file not found during initialization",
                extra={
                    "error": ERROR_SERVER_INIT,
                    "config_path": self._config_path,
                    "details": str(e)
                }
            )
            raise

        except ValueError as e:
            # E-11: ERR_011 - Server initialization failed (invalid config)
            logger.error(
                "Configuration validation failed during initialization",
                extra={
                    "error": ERROR_SERVER_INIT,
                    "details": str(e)
                }
            )
            raise

        except Exception as e:
            # E-11: ERR_011 - Server initialization failed
            logger.error(
                "Server initialization failed",
                extra={
                    "error": ERROR_SERVER_INIT,
                    "details": str(e)
                }
            )
            raise

    async def _cleanup(self) -> None:
        """
        Cleanup server resources.

        IC-38: Cleanup wrapped in finally blocks
        """
        try:
            # Cleanup agent resources if needed
            if self._agent:
                logger.debug("Cleaning up SoftwareArchitectAgent")

            # Cleanup pipeline resources if needed
            if self._pipeline:
                logger.debug("Cleaning up ArchitecturePipeline")

            # Cancel in-flight submit_architecture_design_job background tasks
            for job_id, (task, _tok) in list(self._job_tasks.items()):
                task.cancel()
                logger.debug("Cancelled background design task: %s", job_id)
            if self._job_tasks:
                await asyncio.gather(
                    *(t for t, _ in self._job_tasks.values()),
                    return_exceptions=True,
                )
                logger.debug("Gathered %d cancelled background design tasks", len(self._job_tasks))
            self._job_tasks.clear()

            # Close JobsStore singleton
            try:
                store = await JobsStore.get_instance()
                await store.close()
            except Exception as exc:
                logger.debug("JobsStore cleanup", extra={"error": str(exc)})

            # Clear tools
            self._tools.clear()

            logger.info("Server resources cleanup completed")

        except Exception as e:
            logger.warning(
                "Error during cleanup",
                extra={"details": str(e)}
            )

    @asynccontextmanager
    async def lifespan(self, server: FastMCP):
        """
        Lifespan context manager for FastMCP server.

        IC-37: Lifespan function SHALL use yield statement
        IC-38: Cleanup code SHALL be wrapped in finally blocks
        IC-39: Context dictionary SHALL be accessible via ctx.lifespan_context

        This async generator yields after initialization, allowing the server
        to use the initialized resources during its lifetime. The finally block
        ensures cleanup occurs regardless of whether the server shuts down
        normally or due to an error.

        Args:
            server: FastMCP server instance

        Yields:
            dict: Dictionary containing initialized agent, pipeline, and tools
        """
        logger.info("Starting MCPArchitectServer lifespan")

        try:
            # Initialize resources
            await self._initialize()

            # Pre-initialise the JobsStore singleton (job trio)
            await JobsStore.get_instance()

            # Register tools with FastMCP using @tool-decorated bound methods
            self._register_tools(server)

            # Register MCP Resources (pattern://, template://, component://)
            self._register_resources(server)

            # Register MCP Prompts (user-invoked workflow templates)
            self._register_prompts(server)

            # Build component blueprints once so resource handlers can read them
            component_blueprints = build_component_blueprints(self._pattern_loader)

            # Create lifespan context with initialized resources
            # IC-39: ctx.lifespan_context will be a dictionary with agent, pipeline, tools
            lifespan_context = {
                "agent": self._agent,
                "pipeline": self._pipeline,
                "tools": self._tools,
                "config": self._config,
                "pattern_loader": self._pattern_loader,
                "component_blueprints": component_blueprints,
            }

            logger.debug(
                "Lifespan context initialized",
                extra={"has_agent": self._agent is not None, "has_pipeline": self._pipeline is not None}
            )

            # IC-37: Yield statement separates startup and shutdown
            # IC-39: Context dictionary accessible via ctx.lifespan_context
            yield lifespan_context

        finally:
            # IC-38: Cleanup code wrapped in finally blocks
            logger.info("Shutting down MCPArchitectServer lifespan")
            await self._cleanup()

    _TOOL_METHOD_MAP: dict[str, str] = {
        "design_architecture": "design",
        "analyze_architecture": "analyze",
        "generate_architecture": "generate",
        "evaluate_architecture": "evaluate",
        "list_architecture_patterns": "list_architecture_patterns",
        "get_architecture_pattern": "get_architecture_pattern",
        "submit_architecture_design_job": "submit_job",
        "get_architecture_design_status": "get_status",
        "cancel_architecture_design": "cancel",
    }

    def _register_tools(self, server: FastMCP) -> None:
        """
        Register tools with FastMCP using the standalone @tool decorator pattern.

        Idempotent: each tool is individually skipped if already registered with
        this FastMCP instance (handles lifespan re-entry when Client connects).
        """
        for tool_key, method_name in self._TOOL_METHOD_MAP.items():
            if tool_key in self._tools_registered:
                continue
            tool_instance = self._tools[tool_key]
            method = getattr(tool_instance, method_name)
            server.add_tool(method)
            self._tools_registered.add(tool_key)
            logger.debug("Registered tool: %s", tool_key)

    def _register_resources(self, server: FastMCP) -> None:
        """
        Register MCP Resources with FastMCP: pattern://, template://, component://.

        Resource handlers read their state from ctx.request_context.lifespan_context,
        which is built in lifespan() before being yielded to FastMCP.

        Idempotent: skips re-registering resources already registered with the given
        FastMCP instance (handles lifespan re-entry when Client connects).

        Args:
            server: FastMCP server instance
        """
        if self._resources_registered:
            return

        pattern_resource = PatternResource(self._pattern_loader)
        component_blueprints = build_component_blueprints(self._pattern_loader)

        @server.resource(
            "pattern://",
            name="architecture-pattern-list",
            mime_type="application/json",
        )
        async def _list_patterns() -> str:
            return json.dumps(pattern_resource.list_pattern_resources(), indent=2)

        @server.resource(
            "pattern://{name}",
            name="architecture-pattern",
            mime_type="application/json",
        )
        async def _get_pattern(name: str, ctx: Context) -> str:
            data = pattern_resource.load_pattern(name)
            if data is None:
                raise ToolError(f"Pattern not found: {name}")
            return json.dumps(data, indent=2)

        @server.resource(
            "template://{name}",
            name="architecture-template",
            mime_type="application/json",
        )
        async def _get_template(name: str, ctx: Context) -> str:
            template = RESOURCES.get(name)
            if template is None:
                raise ToolError(f"Template not found: {name}")
            return template.model_dump_json(indent=2)

        @server.resource(
            "component://{type}",
            name="component-blueprint",
            mime_type="application/json",
        )
        async def _get_component(type: str, ctx: Context) -> str:
            blueprints = ctx.request_context.lifespan_context.get(
                "component_blueprints", {}
            )

            slug = slugify(type)
            blueprint = blueprints.get(slug)
            if blueprint is None:
                raise ToolError(f"Component blueprint not found: {type}")
            return blueprint.model_dump_json(indent=2)

        logger.info(
            "MCP Resources registered",
            extra={
                "patterns": len(pattern_resource.list_pattern_resources()),
                "templates": len(RESOURCES),
                "components": len(component_blueprints),
            },
        )
        self._resources_registered = True

    def _register_prompts(self, server: FastMCP) -> None:
        """
        Register MCP Prompts with FastMCP: user-invoked workflow templates.

        FR-247, FR-250. ADR-9.

        Idempotent: skips re-registration on lifespan re-entry. Mirrors
        _register_resources structure exactly.
        """
        if self._prompts_registered:
            return

        from src.mcp_prompts import register_prompts

        count = register_prompts(server, self._pattern_loader)

        logger.info(
            "MCP Prompts registered",
            extra={"prompt_count": count},
        )
        self._prompts_registered = True

    async def run(self) -> None:
        """Run the FastMCP server asynchronously using FastMCP's built-in dispatcher."""
        logger.info("Starting MCPArchitectServer", extra={"transport": self._config.transport})
        transport = self._config.transport
        if transport not in ("stdio", "streamable-http"):
            raise ValueError(
                f"Invalid transport value: {transport!r}. "
                "Must be one of: 'stdio', 'streamable-http'. "
                "Note: 'sse' was deprecated in FastMCP 2.3 and is no longer supported."
            )
        await self._mcp.run_async(
            transport=transport,  # type: ignore[arg-type]
            host=self._config.host,
            port=self._config.port,
        )
