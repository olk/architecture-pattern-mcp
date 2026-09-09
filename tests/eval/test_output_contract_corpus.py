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
L9 output-contract corpus harness (testing-strategies.md §3.9a).

Two test classes:

- TestCorpusAgainstRealPipeline: each corpus entry runs through the REAL
  pipeline and the design is asserted against the structural invariants.
  Opt-in via the ``llm`` marker + ARCH_BENCH_LLM=1 (requires config +
  endpoint) — never in default CI. Structural failures block the triggering
  change (prompt/model/pipeline) until triaged.

- TestInvariantsCanFail (offline, always-on): vacuity guard (P2) — the
  invariant set must FAIL on deliberately broken designs. An invariant set
  that passes a known-bad design certifies nothing.
"""

import os

import pytest

from tests.eval.corpus import CORPUS
from tests.eval.invariants import catalogue_pattern_names, check_invariants

pytestmark = pytest.mark.llm


def _build_live_pipeline():
    """Real ArchitecturePipeline from the deployed config (same construction
    as tests/regression/test_generate_quality.py::_build_live_pipeline)."""
    from src.agent import SoftwareArchitectAgent
    from src.config import ConfigManager, RetrievalConfig, RerankerConfig, ServerConfig
    from src.patterns.loader import PatternLoader
    from src.pipeline import ArchitecturePipeline

    cfg = ConfigManager.load_config()
    server_cfg = ServerConfig.model_validate(cfg)
    agent = SoftwareArchitectAgent(server_cfg)
    retrieval = RetrievalConfig(**cfg.get("retrieval", {}))
    reranker = RerankerConfig(**cfg.get("reranker", {}))
    return ArchitecturePipeline(
        agent=agent,
        pattern_loader=PatternLoader(),
        embedder_config=server_cfg.embedder,
        retrieval_config=retrieval,
        reranker_config=reranker,
    )


class TestCorpusAgainstRealPipeline:
    @pytest.fixture(autouse=True)
    def _require_llm(self) -> None:
        if not os.environ.get("ARCH_BENCH_LLM"):
            pytest.skip("L9 corpus requires ARCH_BENCH_LLM=1 (live LLM)")

    @pytest.mark.parametrize("entry", CORPUS, ids=[e.note for e in CORPUS])
    def test_design_is_well_formed(self, entry) -> None:
        import asyncio

        from src.tools.design import pipeline_result_to_output

        pipeline = _build_live_pipeline()
        refined = asyncio.run(
            pipeline.run_design(
                requirements=entry.requirements, domain=entry.domain, style=None
            )
        )
        payload = pipeline_result_to_output(refined).model_dump()

        violations = check_invariants(payload)
        assert not violations, (
            f"structural drift for corpus entry {entry.note!r}: {violations} — "
            "triage: prompt bug vs corpus staleness"
        )


class TestInvariantsCanFail:
    """Offline vacuity guard: every invariant family detects its bug class."""

    def _valid_design(self) -> dict[str, object]:
        names = sorted(catalogue_pattern_names())
        return {
            "overview": {"style": names[0] if names else "layered", "score": 87.5},
            "components": [
                {"id": "ingest", "name": "Ingest"},
                {"id": "worker", "name": "Worker"},
            ],
            "relationships": [{"source": "ingest", "target": "worker", "type": "async"}],
            "api_contracts": [{"component_id": "ingest", "base_path": "/api", "endpoints": []}],
            "event_contracts": [
                {
                    "event_name": "job.done",
                    "published_by": "worker",
                    "consumed_by": ["ingest"],
                }
            ],
            "quality_attributes": {"reliability": "high"},
        }

    def test_valid_design_has_no_violations(self) -> None:
        assert check_invariants(self._valid_design()) == []

    def test_dangling_relationship_detected(self) -> None:
        design = self._valid_design()
        design["relationships"].append({"source": "ingest", "target": "ghost", "type": "x"})
        assert any("INV-3" in v for v in check_invariants(design))

    def test_consumerless_event_detected(self) -> None:
        design = self._valid_design()
        design["event_contracts"][0]["consumed_by"] = []
        assert any("INV-4" in v for v in check_invariants(design))

    def test_unknown_pattern_detected(self) -> None:
        design = self._valid_design()
        design["overview"]["style"] = "quantum-blockchain-mesh"
        assert any("INV-6" in v for v in check_invariants(design))

    def test_out_of_range_score_detected(self) -> None:
        design = self._valid_design()
        design["overview"]["score"] = 142.0
        assert any("INV-7" in v for v in check_invariants(design))

    def test_missing_sections_detected(self) -> None:
        design = self._valid_design()
        del design["quality_attributes"]
        assert any("INV-1" in v for v in check_invariants(design))
