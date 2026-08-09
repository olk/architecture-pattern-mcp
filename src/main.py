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
FR-241: The system SHALL expose four MCP tools via list_tools handler
FR-242: The system SHALL route tool calls via call_tool handler

Implementation Constraints:
- IC-37: Lifespan function SHALL use yield statement
- IC-38: Cleanup code SHALL be wrapped in finally blocks
- IC-39: Context dictionary SHALL be accessible via ctx.lifespan_context
- IC-40: ctx.transport property SHALL return stdio or streamable-http

Architecture Decisions:
- ADR-1: Python 3.12+ with FastMCP for MCP Protocol Implementation
- ADR-3: MCP Tool-Based API with Four Core Tools
- DP-4: Factory Pattern for tool creation
- DP-7: Adapter Pattern for protocol interface adaptation

Error Handling:
- E-11: ERR_011 - Server initialization failed (HTTP 500, severity: critical)
"""

import asyncio
import logging
import sys

import click

from src.server import server_main

app = server_main  # ASGI server compatibility: Uvicorn/Gunicorn look for 'app' variable


@click.command()
@click.option(
    "--config-path",
    default=None,
    help="Path to config file (default: ~/.config/architecture-pattern-mcp/config.json)",
)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "streamable-http"]),
    default=None,
    help="Transport mode: 'stdio' for Claude Code/Codex subprocess, 'streamable-http' for HTTP (default from config)",
)
@click.option(
    "--host",
    default=None,
    help="Host to bind for HTTP transport (default: 0.0.0.0)",
)
@click.option(
    "--port",
    type=int,
    default=None,
    help="Port to bind for HTTP transport (default: 8050)",
)
@click.option(
    "--health",
    is_flag=True,
    default=False,
    help="Run health check and exit",
)
def cli(
    config_path: str | None,
    transport: str | None,
    host: str | None,
    port: int | None,
    health: bool,
) -> None:
    """Architecture Pattern MCP Server."""
    if health:
        click.echo("OK")
        sys.exit(0)

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
        force=True,
    )

    asyncio.run(server_main(
        config_path=config_path,
        transport=transport,
        host=host,
        port=port,
    ))


if __name__ == "__main__":
    cli()
