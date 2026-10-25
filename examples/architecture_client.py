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
Architecture Pattern MCP — client demo

Connects to a running MCP server over HTTP and calls one tool with a
pipes-and-filters requirements string, then pretty-prints the JSON result:

- analyze_architecture (default) — ANALYZE phase only: recommended style,
  selected patterns with scores, matched domains. Fast; no design generated.
- design_architecture (--tool design) — full design artifact: analyze →
  generate → evaluate → refine. Long-running (minutes).

Usage:
    # Terminal 1: start the server
    $ python -m src.main

    # Terminal 2: run the client
    $ uv run python examples/architecture_client.py                  # analyze (fast)
    $ uv run python examples/architecture_client.py --tool design    # full design

Or pipe the JSON output:
    $ uv run python examples/architecture_client.py 2>/dev/null | jq '.recommended_style'
    $ uv run python examples/architecture_client.py --tool design 2>/dev/null | jq '.design.overview'

Requires:
    - MCP server running on http://localhost:8050/mcp (default)
    - Valid LLM credentials in the server's config
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import click
from fastmcp import Client  # type: ignore[attr-defined]

SERVER_URL = os.environ.get("ARCHITECTURE_CLIENT_URL", "http://localhost:8050/mcp")

PIPES_AND_FILTERS_REQUIREMENTS = """
Build a real-time ETL pipeline that ingests raw IoT sensor data from a Kafka
topic, parses JSON messages, validates schema conformance against a registered
Avro schema, transforms readings into a normalized time-series format,
enriches each record with geolocation data from a side lookup, and writes the
results to both an InfluxDB time-series store and an S3 data lake. Target
throughput: 10,000 events per second with independent horizontal scaling of
each filter stage. Must support backpressure, per-filter retry, and exactly-
once delivery to sinks.
""".strip()

DOMAIN = "data-processing"


TOOL_NAMES: dict[str, str] = {
    "analyze": "analyze_architecture",
    "design": "design_architecture",
}


async def call_architecture_tool(server_url: str, tool: str) -> dict[str, Any]:
    """Connect to the MCP server and call the selected architecture tool."""
    tool_name = TOOL_NAMES[tool]
    client = Client(server_url)

    async with client:
        tools = await client.list_tools()
        print(f"Connected to {server_url}", file=sys.stderr)
        print(f"Available tools: {[t.name for t in tools]}", file=sys.stderr)

        print(f"Calling {tool_name}(domain='{DOMAIN}')...", file=sys.stderr)
        result = await client.call_tool(
            tool_name,
            {
                "requirements": PIPES_AND_FILTERS_REQUIREMENTS,
                "domain": DOMAIN,
            },
        )
        data: dict[str, Any] = result.data
        return data


def print_json(result: dict[str, Any]) -> None:
    """Pretty-print the tool result to stdout as JSON."""
    print(json.dumps(result, indent=2, ensure_ascii=False))


async def amain(tool: str) -> int:
    try:
        result = await call_architecture_tool(SERVER_URL, tool)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print(
            f"\nIs the MCP server running?\n  Start it with:  python -m src.main\n  Expected URL:   {SERVER_URL}",
            file=sys.stderr,
        )
        return 1

    print_json(result)
    return 0


@click.command()
@click.option(
    "--tool",
    type=click.Choice(tuple(TOOL_NAMES)),
    default="analyze",
    show_default=True,
    help="architecture tool to call (design runs the full pipeline)",
)
def cli(tool: str) -> None:
    """Call analyze_architecture (default) or design_architecture on a running MCP server."""
    exit_code = asyncio.run(amain(tool))
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    cli()
