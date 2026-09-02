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

"""Tests for the two-stage blended scoring (analysis_score + fusion_score_normalized).

Issue addressed: stage-2 ranking purely by requirements-weighted quality_attributes
discarded the domain-relevance signal from recall, causing canonical-fit patterns
(e.g. pipe-and-filter for data-processing) to be dropped from selection.
Default config (0.7/0.3) blends both signals so domain-relevant patterns survive.
"""

from unittest.mock import MagicMock

from src.config import RetrievalConfig
from src.pipeline import ArchitecturePipeline, RequirementWeights

# Canonical quality-attribute keys — must match the pipeline's own definition.
_QA_KEYS = (
    "scalability",
    "maintainability",
    "reliability",
    "security",
    "performance",
    "simplicity",
)


def _make_pipeline(retrieval_config=None):
    agent = MagicMock()
    loader = MagicMock()
    loader._loaded = True
    cfg = retrieval_config if retrieval_config is not None else RetrievalConfig(
        analysis_blend_weight=0.7,
        fusion_blend_weight=0.3,
        weight_smoothing_alpha=0.7,
    )
    return ArchitecturePipeline(
        agent=agent,
        pattern_loader=loader,
        embedder_config=MagicMock(),
        retrieval_config=cfg,
    )


def _uniform_qa(score=5):
    return dict.fromkeys(_QA_KEYS, score)


def _uniform_weights():
    return RequirementWeights(**dict.fromkeys(_QA_KEYS, 1.0))


class TestBlendedScoring:
    """Blended scoring: 0.7 analysis_score + 0.3 fusion_normalized."""

    def test_blended_score_uses_default_config(self):
        """Defaults (0.7/0.3): blended = 0.7*analysis + 0.3*fusion_normalized."""
        pipeline = _make_pipeline()
        patterns = [
            {"name": "p1", "quality_attributes": _uniform_qa(8), "fusion_score": 0.10},
            {"name": "p2", "quality_attributes": _uniform_qa(6), "fusion_score": 0.05},
        ]
        scored = pipeline._score_patterns(patterns, _uniform_weights())
        assert scored[0]["name"] == "p1"
        assert scored[0]["blended_score"] == round(
            0.7 * scored[0]["analysis_score"] + 0.3 * 100.0, 2
        )

    def test_minmax_normalization_handles_single_pattern(self):
        """Range=0 → fusion_normalized=0; blended = 0.7 * analysis."""
        pipeline = _make_pipeline()
        patterns = [
            {"name": "p1", "quality_attributes": _uniform_qa(5), "fusion_score": 0.05}
        ]
        scored = pipeline._score_patterns(patterns, _uniform_weights())
        assert scored[0]["fusion_score_normalized"] == 0.0
        assert scored[0]["blended_score"] == round(
            0.7 * scored[0]["analysis_score"], 2
        )

    def test_minmax_normalization_handles_uniform_fusion_scores(self):
        """All fusion_scores equal → all normalize to 0 (no relative signal)."""
        pipeline = _make_pipeline()
        patterns = [
            {"name": f"p{i}", "quality_attributes": _uniform_qa(5), "fusion_score": 0.05}
            for i in range(3)
        ]
        scored = pipeline._score_patterns(patterns, _uniform_weights())
        for s in scored:
            assert s["fusion_score_normalized"] == 0.0

    def test_blend_disabled_when_fusion_blend_weight_is_zero(self):
        """f_w=0 → sort by analysis_score; blended == analysis; no ranking change."""
        pipeline = _make_pipeline(
            retrieval_config=RetrievalConfig(
                analysis_blend_weight=1.0, fusion_blend_weight=0.0
            )
        )
        patterns = [
            {
                "name": "high_qa",
                "quality_attributes": _uniform_qa(9),
                "fusion_score": 0.01,
            },
            {
                "name": "high_fusion",
                "quality_attributes": _uniform_qa(5),
                "fusion_score": 0.10,
            },
        ]
        scored = pipeline._score_patterns(patterns, _uniform_weights())
        assert scored[0]["name"] == "high_qa"
        assert scored[0]["blended_score"] == scored[0]["analysis_score"]

    def test_blend_enabled_lifts_low_qa_high_fusion_pattern(self):
        """With defaults, a low-QA high-fusion pattern enters top 2."""
        pipeline = _make_pipeline()
        patterns = [
            {
                "name": "high_qa",
                "quality_attributes": _uniform_qa(9),
                "fusion_score": 0.01,
            },
            {
                "name": "high_fusion",
                "quality_attributes": _uniform_qa(5),
                "fusion_score": 0.10,
            },
        ]
        scored = pipeline._score_patterns(patterns, _uniform_weights())
        assert "high_fusion" in [s["name"] for s in scored[:2]]

    def test_blended_score_within_0_to_100(self):
        pipeline = _make_pipeline()
        patterns = [
            {
                "name": "p",
                "quality_attributes": _uniform_qa(10),
                "fusion_score": 0.10,
            }
        ]
        scored = pipeline._score_patterns(patterns, _uniform_weights())
        assert 0 <= scored[0]["blended_score"] <= 100
