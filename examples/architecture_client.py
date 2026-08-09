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
Architecture Pattern MCP — Client Demo

Connects to a running MCP server over HTTP, calls design_architecture
with a pipes-and-filters requirements string, and pretty-prints the
returned JSON to stdout.

Usage:
    # Terminal 1: start the server
    $ python -m src.main

    # Terminal 2: run the client
    $ uv run python examples/architecture_client.py

Or pipe the JSON output:
    $ uv run python examples/architecture_client.py 2>/dev/null | jq '.design.overview'

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


async def call_design_architecture(server_url: str) -> dict[str, Any]:
    """Connect to the MCP server and call the design_architecture tool."""
    client = Client(server_url)

    async with client:
        tools = await client.list_tools()
        print(f"Connected to {server_url}", file=sys.stderr)
        print(f"Available tools: {[t.name for t in tools]}", file=sys.stderr)

        print(f"Calling design_architecture(domain='{DOMAIN}')...", file=sys.stderr)
        result = await client.call_tool(
            "design_architecture",
            {
                "requirements": PIPES_AND_FILTERS_REQUIREMENTS,
                "domain": DOMAIN,
            },
        )
        return result.data


def print_json(result: dict[str, Any]) -> None:
    """Pretty-print the tool result to stdout as JSON."""
    print(json.dumps(result, indent=2, ensure_ascii=False))


async def amain() -> int:
    try:
        result = await call_design_architecture(SERVER_URL)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print(
            f"\nIs the MCP server running?\n"
            f"  Start it with:  python -m src.main\n"
            f"  Expected URL:   {SERVER_URL}",
            file=sys.stderr,
        )
        return 1

    print_json(result)
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())
