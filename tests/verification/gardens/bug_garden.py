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
L3 planted-bug garden (testing-strategies §3.4).

The vacuity authority: >= 30 hand-planted mutants across the six documented
classes (off-by-one, none-deref, unbounded loop, shape/KeyError,
arithmetic-flip, boundary-tolerance) applied to pure functions mirroring the
verified families (text length discipline, printable-content check, jobs
automaton guards, normalization dedup, retry bounding, score blending,
weight-sum tolerance).

Each mutant carries a ``kill`` oracle — an executable property that must PASS
on the mutant's reference implementation and FAIL (raise) on the mutant. The
harness (test_bug_garden.py) asserts both directions; every later oracle layer
(.fizz assertions, Hypothesis properties) that claims one of
these properties must kill the same mutant IDs or be rejected as vacuous.

Unbounded-loop mutants are modeled deterministically: loop skeletons cap at
MAX_STEPS and raise ``NonTermination`` — the executable stand-in for a
timeout kill, so the garden can never hang the suite.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

MAX_STEPS = 1_000


class NonTermination(RuntimeError):
    """Raised when a loop exceeds MAX_STEPS — models non-termination."""


def _bounded_steps(n: int) -> range:
    return range(min(n, MAX_STEPS))


# ---------------------------------------------------------------- reference families


def ref_clamp_length(value: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    stripped = value.strip()
    if len(stripped) > max_length:
        raise ValueError(f"exceeds {max_length}")
    return stripped


def ref_count_visible(text: str) -> int:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return sum(1 for ch in text if ch.isalnum())


def ref_can_transition(current: str, new: str) -> bool:
    guards: dict[str, set[str]] = {
        "running": {"pending"},
        "completed": {"running"},
        "failed": {"running"},
        "cancelled": {"pending", "running"},
    }
    return current in guards[new]


def ref_dedupe_by_key(items: list[dict[str, str]], key: str) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in items:
        k = item[key]
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out


def ref_bounded_retry(steps: int, succeed_at: int) -> str:
    if steps <= 0:
        raise ValueError("steps must be positive")
    for attempt in range(steps):
        if attempt == succeed_at:
            return f"ok-{attempt}"
    raise RuntimeError("exhausted")


def ref_blend(scores: list[float], weights: list[float]) -> float:
    if len(scores) != len(weights):
        raise ValueError("shape mismatch")
    total = sum(weights)
    if total == 0:
        raise ValueError("zero weights")
    return sum(s * w for s, w in zip(scores, weights)) / total


def ref_within_tolerance(values: list[float], target: float = 1.0, tol: float = 1e-3) -> bool:
    """Mirror of the config weight-sum validators
    (src/config.py::_check_score_blend_weights / _check_leg_weights_sum_to_one):
    the sum must land within ``tol`` of ``target`` — boundary semantics the
    server refuses to start without.
    """
    total = sum(values)
    return abs(total - target) <= tol


# ---------------------------------------------------------------- kill oracles
# Each oracle takes the implementation under test and raises AssertionError
# when the implementation violates the family property.


def kill_clamp_discipline(fn: Callable[..., object]) -> None:
    assert fn("  ab  ", 10) == "ab"
    assert fn("x" * 10, 10) == "x" * 10, "boundary: exactly max_length is accepted"
    try:
        fn("x" * 11, 10)
    except ValueError:
        pass
    else:
        raise AssertionError("must reject input longer than max_length")


def kill_clamp_totality(fn: Callable[..., object]) -> None:
    """Totality: non-str input raises a declared validation error (TypeError) —
    never AttributeError (an unguarded attribute deref) and never silence."""
    for bad in (None, 42):
        try:
            fn(bad, 10)  # type: ignore[arg-type]
        except TypeError:
            continue
        except AttributeError as exc:
            raise AssertionError(f"unguarded deref leaked AttributeError: {exc}") from exc
        else:
            raise AssertionError(f"invalid input {bad!r} passed silently")


def kill_count_visible(fn: Callable[..., object]) -> None:
    assert cast(int, fn("a1")) == 2
    assert cast(int, fn("a b")) == 2
    assert cast(int, fn("")) == 0
    assert cast(int, fn("??")) == 0
    try:
        fn(None)  # type: ignore[arg-type]
    except TypeError:
        pass
    except AttributeError as exc:
        raise AssertionError(f"unguarded deref leaked AttributeError: {exc}") from exc
    else:
        raise AssertionError("None input passed silently")


def kill_transition_matrix(fn: Callable[..., object]) -> None:
    allowed = {
        ("pending", "running"),
        ("running", "completed"),
        ("running", "failed"),
        ("pending", "cancelled"),
        ("running", "cancelled"),
    }
    for current in ("pending", "running", "completed", "failed", "cancelled", None):
        for new in ("running", "completed", "failed", "cancelled"):
            got = cast(bool, fn(current, new))
            expected = current is not None and (current, new) in allowed
            assert got == expected, (current, new, got)


def kill_dedupe_discipline(fn: Callable[..., object]) -> None:
    items = [{"k": "a", "v": "1"}, {"k": "b", "v": "2"}]
    assert fn(items, "k") == items
    dupes = [{"k": "a"}, {"k": "a", "v": "x"}, {"k": "b"}]
    assert fn(dupes, "k") == [{"k": "a"}, {"k": "b"}]


_KNOWN: list[dict[str, str]] = [{"k": "a", "v": "1"}, {"k": "b", "v": "2"}]


def kill_dedupe_missing_key(fn: Callable[..., object]) -> None:
    try:
        fn([{"v": "1"}], "k")
    except KeyError:
        pass
    else:
        raise AssertionError("missing key must raise KeyError, not pass silently")
    try:
        fn([{"k": "a"}], None)  # type: ignore[arg-type]
    except (KeyError, TypeError):
        pass
    except AttributeError as exc:
        raise AssertionError(f"unguarded deref leaked AttributeError: {exc}") from exc
    else:
        raise AssertionError("None key passed silently")


def kill_dedupe_value_discipline(fn: Callable[..., object]) -> None:
    """Non-str key values flow through untouched — no deref on item values."""
    odd: list[dict[str, str]] = [cast("dict[str, str]", {"k": 5})]
    assert fn(odd, "k") == odd


def kill_retry_bounds(fn: Callable[..., object]) -> None:
    assert fn(3, 1) == "ok-1"
    assert fn(3, 0) == "ok-0"
    try:
        fn(0, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("non-positive steps must raise")
    try:
        fn(3, 99)
    except RuntimeError as exc:
        assert type(exc) is RuntimeError, f"expected plain exhaustion, got {type(exc).__name__}"
        assert "exhausted" in str(exc)
    else:
        raise AssertionError("unreachable succeed_at must exhaust")


def kill_blend_discipline(fn: Callable[..., object]) -> None:
    assert abs(cast(float, fn([1.0, 2.0], [1.0, 3.0])) - 1.75) < 1e-9
    try:
        fn([1.0], [1.0, 2.0])
    except ValueError:
        return
    raise AssertionError("shape mismatch must raise")


def kill_tolerance_discipline(fn: Callable[..., object]) -> None:
    """Boundary-tolerance kill oracle (mirrors the config weight validators).

    Each case is chosen so exactly one mutant class flips it:
    - the 0.01-over case kills a widened tolerance constant;
    - the diff==tol case kills ``<=`` -> ``<`` (boundary must be inclusive);
    - the negative-diff case kills a dropped ``abs`` (signed compare);
    - the within-tolerance multi-value case kills a wrong reduction (min/sum);
    - the exact case kills ``<=`` -> ``>=``.
    """
    assert fn([0.7, 0.3]) is True                      # exact hit
    assert fn([0.7, 0.3001]) is True                   # within default 1e-3
    assert fn([0.7, 0.31]) is False                    # 0.01 over — outside
    assert fn([1.0]) is True
    assert fn([0.5, 0.5], target=2.0) is False         # wrong target
    assert fn([0.5], target=1.0, tol=0.5) is True      # diff == tol: inclusive
    assert fn([0.5], target=0.6, tol=0.05) is False    # negative diff: abs is load-bearing


# ---------------------------------------------------------------- mutants


@dataclass
class Mutant:
    id: str
    klass: str
    description: str
    reference: Callable[..., object]
    func: Callable[..., object]
    kill: Callable[[Callable[..., object]], None]


def _m01_clamp_ge(value: str, max_length: int) -> str:
    stripped = value.strip()
    if len(stripped) >= max_length:
        raise ValueError("off-by-one")
    return stripped


def _m02_clamp_no_strip(value: str, max_length: int) -> str:
    if len(value) > max_length:
        raise ValueError("len")
    return value


def _m03_clamp_none_deref(value: str | None, max_length: int) -> str:
    return value.strip()  # type: ignore[union-attr]


def _m04_clamp_truncate(value: str, max_length: int) -> str:
    return value.strip()[:max_length]


def _m05_clamp_strip_loop(value: str, max_length: int) -> str:
    stripped = value.strip()
    for _step in _bounded_steps(MAX_STEPS):
        stripped = stripped.strip()
    raise NonTermination("M-15 never terminates")


def _m06_count_skip_first(text: str) -> int:
    return sum(1 for ch in text[1:] if ch.isalnum())


def _m07_count_none_deref(text: str | None) -> int:
    return sum(1 for ch in text.items())  # type: ignore[union-attr]


def _m08_count_dict_lookup(text: str) -> int:
    table = {"a": 1, "1": 1}
    return sum(table[ch] for ch in text)


def _m09_count_endless_mirror(text: str) -> int:
    count = 0
    i = 0
    for _step in _bounded_steps(MAX_STEPS):
        count += 1 if text[i % len(text)].isalnum() else 0
        i += 1
    raise NonTermination("M-14 never terminates")


def _m10_trans_cancel_from_completed(current: str, new: str) -> bool:
    guards: dict[str, set[str]] = {
        "running": {"pending"},
        "completed": {"running"},
        "failed": {"running"},
        "cancelled": {"pending", "running", "completed"},
    }
    return current in guards[new]


def _m11_trans_completed_from_pending(current: str, new: str) -> bool:
    guards: dict[str, set[str]] = {
        "running": {"pending"},
        "completed": {"pending", "running"},
        "failed": {"running"},
        "cancelled": {"pending", "running"},
    }
    return current in guards[new]


def _m12_trans_none_deref(current: str | None, new: str) -> bool:
    guards: dict[str, set[str]] = {
        "running": {"pending"},
        "completed": {"running"},
        "failed": {"running"},
        "cancelled": {"pending", "running"},
    }
    return current.strip() in guards[new]  # type: ignore[union-attr]


def _m24_dedupe_value_strip(items: list[dict[str, str]], key: str) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in items:
        k = item[key].strip()
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out


def _m13_dedupe_silent_get(items: list[dict[str, str]], key: str) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in items:
        k = item.get(key, "")
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out


def _m14_dedupe_decrement_index(items: list[dict[str, str]], key: str) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    i = 0
    for _step in _bounded_steps(len(items) * MAX_STEPS):
        k = items[i][key]
        if k not in seen:
            seen.add(k)
            out.append(items[i])
        i -= 1
    raise NonTermination("M-11 never terminates")


def _m15_dedupe_drop_last(items: list[dict[str, str]], key: str) -> list[dict[str, str]]:
    return ref_dedupe_by_key(items[:-1], key)


def _m16_dedupe_none_key(items: list[dict[str, str]], key: str | None) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in items:
        k = item[key.lower()]  # type: ignore[union-attr]
        if k not in seen:
            seen.add(k)
            out.append(item)
    return out


def _m17_retry_shifted(steps: int, succeed_at: int) -> str:
    if steps <= 0:
        raise ValueError("steps must be positive")
    for attempt in range(steps):
        if attempt + 1 == succeed_at:
            return f"ok-{attempt}"
    raise RuntimeError("exhausted")


def _m18_retry_endless(steps: int, succeed_at: int) -> str:
    if steps <= 0:
        raise ValueError("steps must be positive")
    n = 0
    for _step in _bounded_steps(MAX_STEPS):
        if n == succeed_at:
            return f"ok-{n}"
        n += 1
    raise NonTermination("M-12 never terminates")


def _m19_blend_silent_zip(scores: list[float], weights: list[float]) -> float:
    total = sum(weights)
    return sum(s * w for s, w in zip(scores, weights)) / total


def _m20_blend_bad_normalizer(scores: list[float], weights: list[float]) -> float:
    total = sum(weights)
    return sum(s * w for s, w in zip(scores, weights)) / (total - len(weights))


def _m21_blend_endless(scores: list[float], weights: list[float]) -> float:
    result = 0.0
    i = 0
    for _step in _bounded_steps(MAX_STEPS):
        if i >= len(scores):
            return result / sum(weights)
        result += scores[i] * weights[i % len(weights)]
        i += 1
    raise NonTermination("M-13 never terminates")


# --- arithmetic-flip class (added 2026-09-11 plan R8) -----------------------


def _m22_blend_mul_to_div(scores: list[float], weights: list[float]) -> float:
    total = sum(weights)
    if total == 0:
        raise ValueError("zero weights")
    return sum(s / w for s, w in zip(scores, weights)) / total


def _m23_blend_total_sign_flip(scores: list[float], weights: list[float]) -> float:
    total = -sum(weights)
    return sum(s * w for s, w in zip(scores, weights)) / total


def _m24_count_sign_flip(text: str) -> int:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return sum(-1 for ch in text if ch.isalnum())


def _m25_retry_result_offset(scores: int, succeed_at: int) -> str:
    if scores <= 0:
        raise ValueError("steps must be positive")
    for attempt in range(scores):
        if attempt == succeed_at:
            return f"ok-{attempt - 1}"
    raise RuntimeError("exhausted")


def _m26_clamp_off_by_one_len(value: str, max_length: int) -> str:
    stripped = value.strip()
    if len(stripped) - 1 > max_length:
        raise ValueError("arithmetic off-by-one accepts one extra character")
    return stripped


# --- boundary-tolerance class (added 2026-09-11 plan R8) --------------------


def _m27_tolerance_widened(values: list[float], target: float = 1.0, tol: float = 1e-1) -> bool:
    total = sum(values)
    return abs(total - target) <= tol


def _m28_tolerance_exclusive(values: list[float], target: float = 1.0, tol: float = 1e-3) -> bool:
    total = sum(values)
    return abs(total - target) < tol


def _m29_tolerance_signed(values: list[float], target: float = 1.0, tol: float = 1e-3) -> bool:
    total = sum(values)
    return total - target <= tol


def _m30_tolerance_min_reduction(values: list[float], target: float = 1.0, tol: float = 1e-3) -> bool:
    total = min(values)
    return abs(total - target) <= tol


def _m31_tolerance_inverted(values: list[float], target: float = 1.0, tol: float = 1e-3) -> bool:
    total = sum(values)
    return abs(total - target) >= tol


# --- off-by-one fold-ins (comparison/slice boundary flips) ------------------


def _m32_retry_comparison_inverted(steps: int, succeed_at: int) -> str:
    if steps <= 0:
        raise ValueError("steps must be positive")
    for attempt in range(steps):
        if attempt != succeed_at:
            return f"ok-{attempt}"
    raise RuntimeError("exhausted")


def _m33_count_first_slice_only(text: str) -> int:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return sum(1 for ch in text[:1] if ch.isalnum())


MUTANTS: list[Mutant] = [
    Mutant("M-01", "off-by-one", "clamp length check uses >= (rejects equal-to-max)",
           ref_clamp_length, _m01_clamp_ge, kill_clamp_discipline),
    Mutant("M-02", "off-by-one", "clamp lost the strip (normalisation dropped)",
           ref_clamp_length, _m02_clamp_no_strip, kill_clamp_discipline),
    Mutant("M-03", "off-by-one", "visible-count skips the first character",
           ref_count_visible, _m06_count_skip_first, kill_count_visible),
    Mutant("M-04", "off-by-one", "retry range shifted by one (attempt 0 unreachable)",
           ref_bounded_retry, _m17_retry_shifted, kill_retry_bounds),
    Mutant("M-05", "off-by-one", "blend normalizer off by len(weights)",
           ref_blend, _m20_blend_bad_normalizer, kill_blend_discipline),
    Mutant("M-06", "none-deref", "clamp dereferences None before validation",
           ref_clamp_length, _m03_clamp_none_deref, kill_clamp_totality),
    Mutant("M-07", "none-deref", "visible-count iterates attributes of None",
           ref_count_visible, _m07_count_none_deref, kill_count_visible),
    Mutant("M-08", "none-deref", "transition guard dereferences None status",
           ref_can_transition, _m12_trans_none_deref, kill_transition_matrix),
    Mutant("M-09", "none-deref", "dedupe lowercases a None key name",
           ref_dedupe_by_key, _m16_dedupe_none_key, kill_dedupe_missing_key),
    Mutant("M-10", "none-deref", "dedupe strips item values (deref on non-str value)",
           ref_dedupe_by_key, _m24_dedupe_value_strip, kill_dedupe_value_discipline),
    Mutant("M-11", "unbounded-loop", "dedupe decrements the index (never reaches end)",
           ref_dedupe_by_key, _m14_dedupe_decrement_index, kill_dedupe_discipline),
    Mutant("M-12", "unbounded-loop", "retry counter increments past the bound",
           ref_bounded_retry, _m18_retry_endless, kill_retry_bounds),
    Mutant("M-13", "unbounded-loop", "blend walks past the score list forever",
           ref_blend, _m21_blend_endless, kill_blend_discipline),
    Mutant("M-14", "unbounded-loop", "visible-count walks an endless mirror range",
           ref_count_visible, _m09_count_endless_mirror, kill_count_visible),
    Mutant("M-15", "unbounded-loop", "clamp strip loop never terminates",
           ref_clamp_length, _m05_clamp_strip_loop, kill_clamp_discipline),
    Mutant("M-16", "shape-keyerror", "cancel allowed from completed (guard drop, J-1)",
           ref_can_transition, _m10_trans_cancel_from_completed, kill_transition_matrix),
    Mutant("M-17", "shape-keyerror", "completed allowed from pending (transition swap)",
           ref_can_transition, _m11_trans_completed_from_pending, kill_transition_matrix),
    Mutant("M-18", "shape-keyerror", "dedupe uses .get (missing key passes silently)",
           ref_dedupe_by_key, _m13_dedupe_silent_get, kill_dedupe_missing_key),
    Mutant("M-19", "shape-keyerror", "blend zips mismatched shapes silently",
           ref_blend, _m19_blend_silent_zip, kill_blend_discipline),
    Mutant("M-20", "shape-keyerror", "visible-count dict lookup without fallback",
           ref_count_visible, _m08_count_dict_lookup, kill_count_visible),
    Mutant("M-21", "shape-keyerror", "clamp silently truncates instead of rejecting",
           ref_clamp_length, _m04_clamp_truncate, kill_clamp_discipline),
    Mutant("M-22", "arithmetic-flip", "blend multiplies where it must divide (s * w -> s / w)",
           ref_blend, _m22_blend_mul_to_div, kill_blend_discipline),
    Mutant("M-23", "arithmetic-flip", "blend normalizer sign-flipped (sum -> -sum)",
           ref_blend, _m23_blend_total_sign_flip, kill_blend_discipline),
    Mutant("M-24", "arithmetic-flip", "visible-count sign-flipped (adds -1 per char)",
           ref_count_visible, _m24_count_sign_flip, kill_count_visible),
    Mutant("M-25", "arithmetic-flip", "retry result reports attempt - 1",
           ref_bounded_retry, _m25_retry_result_offset, kill_retry_bounds),
    Mutant("M-26", "arithmetic-flip", "clamp length check loses one char (len - 1 > max)",
           ref_clamp_length, _m26_clamp_off_by_one_len, kill_clamp_discipline),
    Mutant("M-27", "boundary-tolerance", "weight tolerance widened 1e-3 -> 1e-1",
           ref_within_tolerance, _m27_tolerance_widened, kill_tolerance_discipline),
    Mutant("M-28", "boundary-tolerance", "tolerance boundary exclusive (<= -> <)",
           ref_within_tolerance, _m28_tolerance_exclusive, kill_tolerance_discipline),
    Mutant("M-29", "boundary-tolerance", "abs dropped — signed compare accepts undershoot",
           ref_within_tolerance, _m29_tolerance_signed, kill_tolerance_discipline),
    Mutant("M-30", "boundary-tolerance", "sum reduced with min instead of sum",
           ref_within_tolerance, _m30_tolerance_min_reduction, kill_tolerance_discipline),
    Mutant("M-31", "boundary-tolerance", "tolerance comparison inverted (<= -> >=)",
           ref_within_tolerance, _m31_tolerance_inverted, kill_tolerance_discipline),
    Mutant("M-32", "off-by-one", "retry equality inverted (== -> !=)",
           ref_bounded_retry, _m32_retry_comparison_inverted, kill_retry_bounds),
    Mutant("M-33", "off-by-one", "visible-count scans only the first character ([:1])",
           ref_count_visible, _m33_count_first_slice_only, kill_count_visible),
]


def mutants_by_class() -> dict[str, int]:
    counts: dict[str, int] = {}
    for m in MUTANTS:
        counts[m.klass] = counts.get(m.klass, 0) + 1
    return counts
