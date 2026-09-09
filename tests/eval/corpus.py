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
L9 output-contract corpus (testing-strategies.md §3.9a).

Recorded (requirements, domain) pairs covering the pattern catalogue's major
domains. Each entry runs through the REAL pipeline (opt-in via the
ARCH_BENCH_LLM marker — never in default CI) and the output design is
asserted against the structural invariants (invariants.py). The tracked
structural pass-rate is the drift signal for prompt/model/pipeline changes;
corpus entries are added per catalogue domain, never per individual design.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CorpusEntry:
    requirements: str
    domain: str
    note: str


CORPUS: tuple[CorpusEntry, ...] = (
    CorpusEntry(
        requirements=(
            "Build a data processing platform that ingests raw events from web "
            "trackers, validates and transforms them, aggregates user sessions, "
            "and serves the results through a REST API. The pipeline must handle "
            "late-arriving data and tolerate upstream schema drift."
        ),
        domain="data processing",
        note="dataflow / pipe-and-filter family",
    ),
    CorpusEntry(
        requirements=(
            "Design a collaborative document editing backend where thousands of "
            "editors process inbound documents concurrently, workers may fail "
            "independently, and results must be exchanged through messages. "
            "Include delivery guarantees for document state updates."
        ),
        domain="distributed systems",
        note="actor-based / message-passing family",
    ),
    CorpusEntry(
        requirements=(
            "Architecture for an ML inference service: accept model requests "
            "over HTTP, apply feature preprocessing, route to one of several "
            "model backends, enforce per-tenant rate limits, and log predictions "
            "for audit. Latency budget 200 ms p99."
        ),
        domain="api gateway",
        note="api-gateway / microservices family",
    ),
    CorpusEntry(
        requirements=(
            "Design an image analysis workbench where user uploads flow through "
            "a fixed sequence of processing steps: resize, feature extraction, "
            "classification, and report generation. Each step is independent and "
            "steps can be re-run individually."
        ),
        domain="image processing",
        note="layered monolith / pipeline family",
    ),
    CorpusEntry(
        requirements=(
            "Backend for a real-time collaboration suite: presence, shared "
            "whiteboards, chat, and notifications. Components must communicate "
            "through published events; each event needs at least one consumer, "
            "and consumer outages must not lose events."
        ),
        domain="event-driven",
        note="event-driven family (producer/consumer closure)",
    ),
)
