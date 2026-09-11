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
Direct unit tests for src.patterns.embedder._normalize — the L2-normalisation
decision that lets a FAISS ``IndexFlatIP`` inner product equal cosine
similarity (module contract, src/patterns/embedder.py docstring).

The zero-vector guard is the kill class: a division by zero here produces
NaN embeddings, and NaN inner products poison retrieval ranking silently.
Each test names the mutation class it kills (axis swap, dropped guard,
wrong dtype, reshape loss).
"""

import math

import pytest

from src.patterns.embedder import _normalize


def _row_norm(row: list[float]) -> float:
    return math.sqrt(sum(v * v for v in row))


class TestNormalize:
    def test_unit_length_after_normalization(self) -> None:
        """Kills dropped division (raw vectors would keep their magnitude)."""
        result = _normalize([[3.0, 4.0], [1.0, 0.0]])
        assert len(result) == 2
        for row in result:
            assert _row_norm(row) == pytest.approx(1.0, abs=1e-6)

    def test_known_direction_is_preserved(self) -> None:
        """3-4-5 triangle: direction survives, magnitude becomes 1.

        float32 rounding (the module casts via ``dtype=np.float32``) is part
        of the pinned contract — exact 0.6/0.8 do not survive the cast.
        """
        result = _normalize([[3.0, 4.0]])
        assert result[0] == pytest.approx([0.6, 0.8], abs=1e-6)

    def test_zero_vector_passes_through_unchanged(self) -> None:
        """Kills deletion of the ``norms == 0 -> 1`` guard: without it the
        division yields NaN, and NaN propagates into the FAISS index."""
        result = _normalize([[0.0, 0.0, 0.0]])
        assert result == [[0.0, 0.0, 0.0]]
        for value in result[0]:
            assert not math.isnan(value)
            assert not math.isinf(value)

    def test_mixed_rows_independent_norms(self) -> None:
        """Kills axis=0 / whole-array normalisation mutants: each ROW must be
        unit length independently, not the matrix as one flat vector."""
        result = _normalize([[3.0, 4.0], [0.0, 2.0]])
        assert result[0] == pytest.approx([0.6, 0.8], abs=1e-6)
        assert result[1] == pytest.approx([0.0, 1.0], abs=1e-6)
        assert _row_norm(result[0]) == pytest.approx(1.0, abs=1e-6)
        assert _row_norm(result[1]) == pytest.approx(1.0, abs=1e-6)

    def test_negative_components_normalized(self) -> None:
        """Sign flips must survive normalisation (direction, not magnitude)."""
        result = _normalize([[-3.0, 4.0]])
        assert result[0] == pytest.approx([-0.6, 0.8], abs=1e-6)

    def test_already_unit_length_is_stable(self) -> None:
        """Idempotence on the fixed point (no drift from float rounding)."""
        result = _normalize([[1.0, 0.0], [0.0, 1.0]])
        assert result[0] == pytest.approx([1.0, 0.0], abs=1e-6)
        assert result[1] == pytest.approx([0.0, 1.0], abs=1e-6)

    def test_empty_input_returns_single_empty_row(self) -> None:
        """Pins the 1-D reshape branch: ``np.asarray([])`` has ndim 1, so the
        empty input is reshaped to one (empty) row and passes through."""
        result = _normalize([])
        assert result == [[]]

    def test_single_component_rows(self) -> None:
        result = _normalize([[5.0], [-2.0]])
        assert result == [[1.0], [-1.0]]

    def test_output_is_plain_float_lists(self) -> None:
        """The FAISS contract consumes nested Python floats, not numpy types."""
        result = _normalize([[3.0, 4.0]])
        assert isinstance(result, list)
        assert all(isinstance(v, float) for row in result for v in row)
