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
Architecture Pattern MCP — Async Job Trio Demo

Demonstrates the submit_architecture_design_job + get_architecture_design_status + cancel_architecture_design
async job pattern using the FastMCP Client. Unlike the synchronous
`design_architecture` tool (which blocks 5-10 minutes), the async trio
returns a job_id immediately and lets you poll for the result.

Usage:
    # Terminal 1: start the server
    $ docker compose -f docker/docker-compose.yml up --build

    # Terminal 2: run the client
    $ ARCHITECTURE_CLIENT_URL=http://localhost:8060/mcp \\
        uv run python examples/architecture_client_async.py

Requires:
    - MCP server running at ARCHITECTURE_CLIENT_URL (default http://localhost:8050/mcp)
    - Valid LLM credentials in the server's config
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

from fastmcp import Client

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


async def amain() -> int:
    print(f"Connecting to {SERVER_URL}", file=sys.stderr)

    client = Client(SERVER_URL)
    async with client:
        try:
            # Step 1: start the job
            print("Starting design job...", file=sys.stderr)
            result = await client.call_tool(
                "submit_architecture_design_job",
                {
                    "requirements": REQUIREMENTS,
                    "domain": DOMAIN,
                },
            )
            data = result.data
            job_id = data["job_id"]
            print(f"Job ID: {job_id}", file=sys.stderr)
            print(
                f"Polling every {POLL_EVERY} seconds. Press Ctrl+C to cancel.\n",
                file=sys.stderr,
            )

            # Step 2: poll until terminal state
            start_time = time.monotonic()
            while True:
                await asyncio.sleep(POLL_EVERY)
                status_result = await client.call_tool("get_architecture_design_status", {"job_id": job_id})
                status_data = status_result.data
                elapsed = time.monotonic() - start_time

                status = status_data["status"]
                print(
                    f"[{elapsed:6.0f}s] status={status:10s}  message={status_data['message']}",
                    file=sys.stderr,
                )

                if status == "completed":
                    print("\n=== Design result ===", file=sys.stderr)
                    result_json = json.dumps(status_data.get("result") if status_data.get("result") else {}, indent=2)
                    print(result_json)
                    return 0

                if status == "failed":
                    print("\n=== Job failed ===", file=sys.stderr)
                    print(f"Error: {status_data.get('error', 'unknown')}", file=sys.stderr)
                    return 1

                if status == "cancelled":
                    print("\n=== Job cancelled ===", file=sys.stderr)
                    return 130

        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            print(
                f"\nIs the MCP server running?\n"
                f"  Start it with:  docker compose -f docker/docker-compose.yml up\n"
                f"  Expected URL:   {SERVER_URL}",
                file=sys.stderr,
            )
            return 1


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())
