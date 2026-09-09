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
L3 garden harness (testing-strategies §3.4).

Asserts both directions of every planted mutant:
  1. the kill oracle PASSES on the reference implementation (the oracle is
     satisfiable — no impossible oracles);
  2. the kill oracle FAILS on the mutant (every planted bug is caught).

Vacuity rule (P2): the garden itself must be able to fail — deleting a kill
assertion or weakening a mutant makes these tests red. The same mutant IDs
are the acceptance set for later oracle layers (contracts, .fizz assertions).
"""

from collections.abc import Callable
from typing import Any

import pytest

from tests.verification.gardens.bug_garden import MUTANTS, NonTermination, mutants_by_class

MIN_MUTANTS = 20
REQUIRED_CLASSES = {"off-by-one", "none-deref", "unbounded-loop", "shape-keyerror"}


def _run_safely(kill: Callable[[Callable[..., object]], None], fn: Callable[..., object]) -> Any:
    """Execute a kill oracle; returns None on pass, the exception on failure."""
    try:
        kill(fn)
    except (
        AssertionError,
        NonTermination,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
    ) as exc:
        return exc
    return None


@pytest.mark.parametrize("mutant", MUTANTS, ids=lambda m: m.id)
def test_mutant_is_killed(mutant) -> None:
    reference_failure = _run_safely(mutant.kill, mutant.reference)
    assert reference_failure is None, (
        f"{mutant.id}: kill oracle fails on the REFERENCE — the oracle itself "
        f"is broken: {reference_failure!r}"
    )
    mutant_failure = _run_safely(mutant.kill, mutant.func)
    assert mutant_failure is not None, (
        f"{mutant.id} ({mutant.klass}: {mutant.description}) SURVIVED — a "
        "planted bug was not caught; oracles are vacuous for this class"
    )


def test_garden_covers_documented_classes() -> None:
    counts = mutants_by_class()
    assert set(counts) == REQUIRED_CLASSES
    assert all(count >= 5 for count in counts.values()), counts


def test_garden_size_contract() -> None:
    assert len(MUTANTS) >= MIN_MUTANTS
    assert len({m.id for m in MUTANTS}) == len(MUTANTS), "mutant IDs must be unique"
