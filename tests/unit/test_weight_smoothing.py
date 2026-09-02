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

"""Tests for convex smoothing of RequirementWeights (w' = alpha*w + (1-alpha)/n).

Smoothing prevents the LLM from fully zeroing any quality attribute while
preserving the relative priority ordering from the LLM.
"""

from unittest.mock import MagicMock

from src.config import RetrievalConfig
from src.pipeline import ArchitecturePipeline, RequirementWeights

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


class TestWeightSmoothing:
    """Weight smoothing: w' = alpha*w + (1-alpha)*(1/n)."""

    def test_smoothing_no_op_at_alpha_1(self):
        """alpha=1.0: raw LLM weights pass through unchanged."""
        pipeline = _make_pipeline(
            retrieval_config=RetrievalConfig(weight_smoothing_alpha=1.0)
        )
        raw = RequirementWeights(scalability=1.0, reliability=0.9)
        out = pipeline._smooth_weights(raw)
        assert out.scalability == 1.0
        assert out.reliability == 0.9  # noqa: PLR2004

    def test_smoothing_zeroes_no_attribute_at_alpha_07(self):
        """alpha=0.7 (default): all-zero weights lift to uniform 1/n > 0."""
        pipeline = _make_pipeline(
            retrieval_config=RetrievalConfig(weight_smoothing_alpha=0.7)
        )
        raw = RequirementWeights(scalability=1.0)  # all others default 0.0
        out = pipeline._smooth_weights(raw)
        for attr in _QA_KEYS:
            assert getattr(out, attr) > 0.0, f"{attr} should not be zero"

    def test_smoothing_preserves_relative_ordering(self):
        """Smoothing never reverses the LLM's priority ordering."""
        pipeline = _make_pipeline(
            retrieval_config=RetrievalConfig(weight_smoothing_alpha=0.7)
        )
        raw = RequirementWeights(
            scalability=1.0, performance=0.5, maintainability=0.0
        )
        out = pipeline._smooth_weights(raw)
        assert out.scalability > out.performance > out.maintainability

    def test_smoothing_alpha_0_yields_uniform_weights(self):
        """alpha=0.0: all attributes collapse to uniform 1/n."""
        pipeline = _make_pipeline(
            retrieval_config=RetrievalConfig(weight_smoothing_alpha=0.0)
        )
        raw = RequirementWeights(scalability=1.0, reliability=0.9)
        out = pipeline._smooth_weights(raw)
        expected = 1.0 / len(_QA_KEYS)
        for attr in _QA_KEYS:
            assert abs(getattr(out, attr) - expected) < 1e-4  # noqa: PLR2004
