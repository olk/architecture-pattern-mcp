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

"""Performance benchmark for generate() prompt/schema size and subphase timing.

Skipped unless RUN_PERF=1. Measures deterministic cost (prompt/schema sizes) and
local CPU subphase timings (pattern_context, validate_patterns, construct, denormalize).
Opt-in live LLM timing via ARCHITECTURE_LIVE_BENCH=1 with a real config.
"""

import json
import os
import time
from typing import Any, cast

import pytest

from src.config import ConfigManager, RerankerConfig, RetrievalConfig, ServerConfig
from src.schemas.architecture import ArchitectureDesignResponse, ArchitectureDesignResponseWire
from src.schemas.patterns import Pattern
from src.schemas.enums import PatternCategory, ArchitectureDomain


@pytest.mark.perf
@pytest.mark.skipif(not os.getenv("RUN_PERF", ""), reason="RUN_PERF=1 to run performance benchmarks")
def test_generate_schema_sizes() -> None:
    """Measure response schema JSON sizes (baseline vs slimmed)."""
    full_schema = ArchitectureDesignResponse.model_json_schema()
    lean_schema = ArchitectureDesignResponseWire.model_json_schema()

    full_chars = len(json.dumps(full_schema))
    lean_chars = len(json.dumps(lean_schema))

    print(f"\n{'Schema size (chars)':<40} {'Baseline':>12} {'Slimmed':>12} {'Savings':>12}")
    print(f"{'=' * 76}")
    print(f"{'Response schema':<40} {full_chars:>12,} {lean_chars:>12,} {full_chars - lean_chars:>12,}")

    full_tokens_approx = full_chars // 4
    lean_tokens_approx = lean_chars // 4
    print(f"{'Estimated tokens (÷4)':<40} {full_tokens_approx:>12,} {lean_tokens_approx:>12,} {full_tokens_approx - lean_tokens_approx:>12,}")

    savings_pct = (full_chars - lean_chars) / full_chars * 100
    print(f"\nSchema slimming saves ~{savings_pct:.1f}% characters (~{full_tokens_approx - lean_tokens_approx} tokens)")

    assert lean_chars < full_chars, "Lean schema should be smaller"


@pytest.mark.perf
@pytest.mark.skipif(not os.getenv("RUN_PERF", ""), reason="RUN_PERF=1 to run performance benchmarks")
def test_generate_example_sizes() -> None:
    """Measure few-shot example sizes (currently slimmed)."""
    from src.prompts import ARCHITECTURE_DESIGN_EXAMPLE, ARCHITECTURE_EVALUATION_EXAMPLE, ANALYSIS_RESULT_EXAMPLE

    example_chars = len(ARCHITECTURE_DESIGN_EXAMPLE)
    eval_example_chars = len(ARCHITECTURE_EVALUATION_EXAMPLE)
    analysis_example_chars = len(ANALYSIS_RESULT_EXAMPLE)

    total_chars = example_chars + eval_example_chars + analysis_example_chars

    print(f"\n{'Few-shot examples (chars)':<40} {'Size':>12}")
    print(f"{'=' * 52}")
    print(f"{'ARCHITECTURE_DESIGN_EXAMPLE':<40} {example_chars:>12,}")
    print(f"{'ARCHITECTURE_EVALUATION_EXAMPLE':<40} {eval_example_chars:>12,}")
    print(f"{'ANALYSIS_RESULT_EXAMPLE':<40} {analysis_example_chars:>12,}")
    print(f"{'Total':<40} {total_chars:>12,}")

    total_tokens = total_chars // 4
    print(f"\nEstimated tokens in examples: ~{total_tokens:,}")


@pytest.mark.perf
@pytest.mark.skipif(not os.getenv("RUN_PERF", ""), reason="RUN_PERF=1 to run performance benchmarks")
def test_generate_prompt_sizes() -> None:
    """Measure assembled prompt sizes (system + user prompts) using a test pipeline."""
    try:
        from tests.unit.test_pipeline import create_test_pipeline
    except Exception as e:
        pytest.skip(f"Cannot import test utilities: {e}")

    pipeline = create_test_pipeline()

    system_prompt = pipeline._build_generate_system_prompt(style="event-driven")
    user_prompt = pipeline._build_generate_user_prompt(
        requirements="Build an event-driven system",
        domain="e-commerce",
        style="event-driven",
        pattern_context="Pattern 1: event-driven\n\nContext: Async communication...",
        analysis_result=None,
    )

    system_chars = len(system_prompt)
    user_chars = len(user_prompt)
    total_chars = system_chars + user_chars

    print(f"\n{'Assembled prompts (chars)':<40} {'Size':>12}")
    print(f"{'=' * 52}")
    print(f"{'System prompt':<40} {system_chars:>12,}")
    print(f"{'User prompt':<40} {user_chars:>12,}")
    print(f"{'Total':<40} {total_chars:>12,}")

    total_tokens = total_chars // 4
    print(f"\nEstimated tokens in prompts: ~{total_tokens:,}")


@pytest.mark.perf
@pytest.mark.skipif(not os.getenv("RUN_PERF", ""), reason="RUN_PERF=1 to run performance benchmarks")
def test_generate_subphase_timings_mocked() -> None:
    """Measure local CPU subphase timings with a mocked agent (no real LLM call)."""
    try:
        from tests.unit.test_pipeline import create_test_pipeline
    except Exception as e:
        pytest.skip(f"Cannot import test utilities: {e}")

    import asyncio

    pipeline = create_test_pipeline()
    selected_patterns = [
        Pattern(
            name="event-driven",
            context="Async communication system",
            category=PatternCategory.MESSAGING,
            benefits=["Loose coupling", "Independent scaling"],
            tradeoffs=["Eventual consistency"],
            quality_attributes={"scalability": 9, "maintainability": 7, "reliability": 7, "security": 6, "performance": 9},
            suitable_domains=[ArchitectureDomain.E_COMMERCE],
            use_cases=["High throughput"],
            avoid_when=["Strong consistency required"],
            component_types=["Message Broker", "Event Handler"],
            technology_stack=["Kafka", "FastAPI"],
            anti_patterns=["Chatty APIs"],
            migration_from=["Monolith"],
            migration_to=["Event-driven"],
            design_principles=["Idempotency", "Schema registry"],
            best_practices=["Dead-letter queues"],
        )
    ]

    async def mock_generate_structured(system_prompt: str, user_prompt: str, response_schema: type) -> Any:
        """Return a minimal valid design response quickly."""
        from src.schemas.design import ArchitectureOverview
        from src.schemas.enums import ArchitectureStyle, PatternCategory
        from src.schemas.components import Component

        from src.schemas.architecture import ArchitectureDesignResponse

        return ArchitectureDesignResponse(
            overview=ArchitectureOverview(
                style=ArchitectureStyle.EVENT_DRIVEN,
                category=PatternCategory.MESSAGING,
                principles=["async-first"],
                constraints=["10k tps"],
            ),
            components=[
                Component(
                    id="test",
                    name="Test",
                    type="service",
                    description="Test component",
                    responsibilities=["test"],
                    interfaces=["REST"],
                    technology_stack=["FastAPI"],
                ),
            ],
            relationships=[],
            patterns=[],
            quality_attributes={"maintainability": "8/10"},
            api_contracts=[],
            shared_data_models=[],
            event_contracts=[],
        )

    pipeline._agent.generate_structured = mock_generate_structured

    timings: dict[str, float] = {}

    async def timed_phase(phase: str, coro):
        start = time.monotonic()
        result = await coro
        timings[phase] = time.monotonic() - start
        return result

    async def run():
        return await pipeline.generate(
            requirements="Test requirements",
            domain="test-domain",
            style="event-driven",
            selected_patterns=[p.model_dump() for p in selected_patterns],
        )

    result = asyncio.run(timed_phase("generate_total", run()))

    print(f"\n{'Local CPU subphase timings (ms)':<40} {'Duration':>12}")
    print(f"{'=' * 52}")
    for phase, duration in sorted(timings.items()):
        print(f"{phase:<40} {duration * 1000:>12.2f}")

    total_ms = timings["generate_total"] * 1000
    print(f"\nTotal local CPU time: {total_ms:.2f} ms (should be negligible vs LLM decode)")


@pytest.mark.perf
@pytest.mark.skipif(
    not os.getenv("ARCHITECTURE_LIVE_BENCH", ""),
    reason="ARCHITECTURE_LIVE_BENCH=1 to run live LLM benchmarks (requires real config)",
)
def test_generate_live_llm_timing() -> None:
    """End-to-end timing against a real LLM (opt-in, requires config and API key)."""
    import asyncio
    from src.pipeline import ArchitecturePipeline
    from src.patterns.loader import PatternLoader
    from src.patterns.vector_index import DomainVectorIndex
    from src.patterns.bm25_index import DomainBM25Index
    from src.agent import SoftwareArchitectAgent

    try:
        cfg = ConfigManager.load_config()
    except Exception as e:
        pytest.skip(f"Cannot load config: {e}")

    agent = SoftwareArchitectAgent(ServerConfig.model_validate(cfg))
    loader = PatternLoader()
    vector_idx = DomainVectorIndex()
    bm25_idx = DomainBM25Index()
    retrieval = RetrievalConfig(**cfg.get("retrieval", {}))
    reranker = RerankerConfig(**cfg.get("reranker", {}))

    pipeline = ArchitecturePipeline(
        agent=agent,
        pattern_loader=loader,
        vector_index=vector_idx,
        bm25_index=bm25_idx,
        retrieval_config=retrieval,
        reranker_config=reranker,
    )

    timings: dict[str, float] = {}

    async def timed_phase(phase: str, coro):
        start = time.monotonic()
        result = await coro
        timings[phase] = time.monotonic() - start
        return result

    async def run():
        analysis = await pipeline.analyze(
            requirements="Build a simple event-driven system for order processing",
            domain="e-commerce",
        )
        return await pipeline.generate(
            requirements="Build a simple event-driven system for order processing",
            domain="e-commerce",
            style=analysis.recommended_style,
            selected_patterns=analysis.selected_patterns,
        )

    result = asyncio.run(timed_phase("generate_total", run()))

    print(f"\n{'End-to-end timing with live LLM (s)':<40} {'Duration':>12}")
    print(f"{'=' * 52}")
    for phase, duration in sorted(timings.items()):
        print(f"{phase:<40} {duration:>12.2f}")

    total_s = timings["generate_total"]
    print(f"\nTotal generate() time: {total_s:.2f} s")
    print("Compare with local CPU subphase timings (mocked) to isolate LLM decode cost.")