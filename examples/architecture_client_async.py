# Copyright (c) 2026 Oliver Kowarke
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
Architecture Pattern MCP — Async Job Trio Demo

Demonstrates the start_design_architecture + get_design_status + cancel_design
async job pattern. Unlike the synchronous `design_architecture` tool (which
blocks for 5-10 minutes), the async trio returns a job_id immediately and
lets you poll for the result.

This pattern works with ALL MCP clients, including those with hardcoded
short idle timeouts (Claude Desktop, Cursor, etc.) where the synchronous
tool would fail.

Usage:
    # Terminal 1: start the server
    $ python -m src.main

    # Terminal 2: run the client
    $ uv run python examples/architecture_client_async.py

Requires:
    - MCP server running on http://localhost:8050/mcp (default)
    - Valid LLM credentials in the server's config
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

import aiohttp

SERVER_URL = os.environ.get("ARCHITECTURE_CLIENT_URL", "http://localhost:8050/mcp")

POLL_EVERY = int(os.environ.get("ARCHITECTURE_CLIENT_POLL_SECONDS", "15"))

REQUIREMENTS = """
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


async def _call_mcp(session: aiohttp.ClientSession, method: str, params: dict[str, Any]) -> Any:
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    async with session.post(SERVER_URL, json=payload) as resp:
        resp.raise_for_status()
        data = await resp.json()
        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        return data["result"]


async def start_design(session: aiohttp.ClientSession) -> str:
    result = await _call_mcp(
        session,
        "tools/call",
        {
            "name": "start_design_architecture",
            "arguments": {"requirements": REQUIREMENTS, "domain": DOMAIN},
        },
    )
    content = result["content"]
    if isinstance(content, list):
        content = content[0]
    job_id = content["data"]["job_id"]
    return job_id


async def poll_status(session: aiohttp.ClientSession, job_id: str) -> dict[str, Any]:
    result = await _call_mcp(
        session,
        "tools/call",
        {"name": "get_design_status", "arguments": {"job_id": job_id}},
    )
    content = result["content"]
    if isinstance(content, list):
        content = content[0]
    return content["data"]


async def cancel_design(session: aiohttp.ClientSession, job_id: str) -> dict[str, Any]:
    result = await _call_mcp(
        session,
        "tools/call",
        {"name": "cancel_design", "arguments": {"job_id": job_id}},
    )
    content = result["content"]
    if isinstance(content, list):
        content = content[0]
    return content["data"]


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


async def amain() -> int:
    print(f"Connecting to {SERVER_URL}", file=sys.stderr)

    async with aiohttp.ClientSession() as session:
        try:
            # Step 1: start the job
            print("Starting design job...", file=sys.stderr)
            job_id = await start_design(session)
            print(f"Job ID: {job_id}", file=sys.stderr)
            print(f"Polling every {POLL_EVERY} seconds. Press Ctrl+C to cancel.\n", file=sys.stderr)

            # Step 2: poll until terminal state
            start_time = time.monotonic()
            while True:
                await asyncio.sleep(POLL_EVERY)
                status_data = await poll_status(session, job_id)
                elapsed = time.monotonic() - start_time

                status = status_data["status"]
                print(
                    f"[{elapsed:6.0f}s] status={status:10s}  message={status_data['message']}",
                    file=sys.stderr,
                )

                if status == "completed":
                    print("\n=== Design result ===", file=sys.stderr)
                    print_json(status_data["result"])
                    return 0

                if status == "failed":
                    print("\n=== Job failed ===", file=sys.stderr)
                    print(f"Error: {status_data.get('error', 'unknown')}", file=sys.stderr)
                    return 1

                if status == "cancelled":
                    print("\n=== Job cancelled ===", file=sys.stderr)
                    return 130

        except aiohttp.ClientError as exc:
            print(f"HTTP error: {exc}", file=sys.stderr)
            print(
                f"\nIs the MCP server running?\n  Start it with:  python -m src.main\n  Expected URL:   {SERVER_URL}",
                file=sys.stderr,
            )
            return 1


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())
