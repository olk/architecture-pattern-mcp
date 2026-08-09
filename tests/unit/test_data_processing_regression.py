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

"""Regression test: pipe-and-filter enters selection for data-processing.

Before this change, pipe-and-filter (canonical fit for 'data-processing',
listed first in suitable_domains) was dropped from selection because
stage-2 ranked purely on requirements-weighted quality_attributes.
After: blended scoring (0.7/0.3) + weight smoothing (alpha=0.7)
lifts it into the top-5 selected_patterns.
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


def _make_pipeline():
    agent = MagicMock()
    loader = MagicMock()
    loader._loaded = True
    vi = MagicMock()
    vi.is_built = True
    vi.domains = ["x"]
    bm = MagicMock()
    bm.is_built = True
    bm.domains = ["x"]
    return ArchitecturePipeline(
        agent=agent,
        pattern_loader=loader,
        vector_index=vi,
        bm25_index=bm,
        retrieval_config=RetrievalConfig(
            analysis_blend_weight=0.7,
            fusion_blend_weight=0.3,
            weight_smoothing_alpha=0.7,
        ),
    )


class TestPipeAndFilterRegression:
    """The canonical-fit data-processing pattern must enter top-5."""

    def test_pipe_and_filter_enters_top_5_for_data_processing(self):
        """pipe-and-filter (top recall match) enters selection with default blend.

        Before: excluded at rank 6+ despite having the highest fusion_score.
        After: blended scoring (0.7/0.3) + smoothing (0.7) gives blended score ~82,
        ranking it at position 2.
        """
        pipeline = _make_pipeline()
        # Realistic quality_attributes from the catalogue JSON files.
        # fusion_scores from the original recall log (RRF, k=60).
        patterns = [
            {
                "name": "pipe-and-filter",
                "quality_attributes": {
                    "scalability": 8,
                    "maintainability": 9,
                    "reliability": 7,
                    "security": 6,
                    "performance": 7,
                    "simplicity": 8,
                },
                "fusion_score": 0.0333,  # highest — rank 1 in both retrievers
            },
            {
                "name": "kappa-architecture",
                "quality_attributes": {
                    "scalability": 9,
                    "maintainability": 7,
                    "reliability": 8,
                    "security": 6,
                    "performance": 9,
                    "simplicity": 7,
                },
                "fusion_score": 0.0328,
            },
            {
                "name": "reactive-architecture",
                "quality_attributes": {
                    "scalability": 9,
                    "maintainability": 6,
                    "reliability": 9,
                    "security": 7,
                    "performance": 8,
                    "simplicity": 4,
                },
                "fusion_score": 0.0276,
            },
            {
                "name": "space-based",
                "quality_attributes": {
                    "scalability": 9,
                    "maintainability": 4,
                    "reliability": 8,
                    "security": 5,
                    "performance": 9,
                    "simplicity": 3,
                },
                "fusion_score": 0.0131,  # lowest
            },
            {
                "name": "lambda-architecture",
                "quality_attributes": {
                    "scalability": 9,
                    "maintainability": 4,
                    "reliability": 8,
                    "security": 6,
                    "performance": 8,
                    "simplicity": 3,
                },
                "fusion_score": 0.0296,
            },
            {
                "name": "actor-based",
                "quality_attributes": {
                    "scalability": 9,
                    "maintainability": 6,
                    "reliability": 9,
                    "security": 6,
                    "performance": 7,
                    "simplicity": 3,
                },
                "fusion_score": 0.0272,
            },
        ]
        # RequirementWeights from the original bug-report log
        weights = RequirementWeights(
            scalability=1.0,
            reliability=0.9,
            performance=0.5,
        )

        scored = pipeline._score_patterns(patterns, weights)
        top5 = {s["name"] for s in scored[:5]}

        assert "pipe-and-filter" in top5, (
            f"pipe-and-filter (top recall match) must enter top-5. "
            f"Got top-5: {top5}"
        )
