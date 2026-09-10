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
Runtime no-op stubs for nagini_contracts.contracts (verification-only vocabulary).

See the package docstring in ``nagini_contracts/__init__.py`` for the
rationale.  Typed signatures live in ``contracts.pyi``.
"""


def Requires(expr: bool) -> bool:
    return True


def Ensures(*args: object) -> bool:
    return True


def Exsures(exception: type, expr: bool) -> bool:
    return True


def Invariant(expr: bool) -> bool:
    return True


def Assert(expr: bool) -> bool:
    return True


def Implies(p: bool, q: bool) -> bool:
    """Logical implication p ==> q (real semantics: runtime-evaluated
    quantifier predicates in the verified cores use it)."""
    return (not p) or q


def _iterable_domain(domain: object) -> bool:
    return hasattr(domain, "__iter__") and not isinstance(domain, type)


def _closure_bound(predicate: object) -> int:
    """Largest length among the list cells captured by a quantifier lambda.

    Int-domain quantifiers in the verified cores only ever index the lists
    captured in the lambda's closure (all reads are guarded by
    ``0 <= i < len(l)``); scanning [0, bound) is therefore complete.
    """
    closure = getattr(predicate, "__closure__", None)
    if not closure:
        return 0
    bound = 0
    for cell in closure:
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if isinstance(value, list):
            bound = max(bound, len(value))
    return bound


def Forall(*args: object) -> bool:
    """Quantifier over the given domain.

    Int-domain Foralls appear only in contract positions (invariants,
    postconditions) in the verified cores, where the result is discarded;
    they are no-ops at runtime.  Iterable-domain quantifiers implement the
    real semantics (all elements satisfy the predicate).
    """
    if len(args) >= 2 and _iterable_domain(args[0]):
        domain, predicate = args[0], args[1]
        for elem in domain:
            if not predicate(elem):
                return False
    return True


def Exists(*args: object) -> bool:
    """Existential quantifier over the given domain.

    Int-domain Exists is the runtime decision operator of the verified
    cores (``if not Exists(int, lambda p: ... l[p] == x)`` membership
    tests); it must evaluate for real.  The lambda only ever indexes the
    lists captured in its closure with in-bounds guards, so scanning
    [0, bound) over the closure lists is complete; out-of-range indices
    (IndexError) satisfy no membership test and count as False.
    """
    if len(args) >= 2:
        domain, predicate = args[0], args[1]
        if _iterable_domain(domain):
            for elem in domain:
                if predicate(elem):
                    return True
            return False
        bound = _closure_bound(predicate)
        for p in range(bound):
            try:
                if predicate(p):
                    return True
            except IndexError:
                continue
        return False
    return True


def Old(expr: object) -> object:
    return expr


def Result() -> object:
    return None


def Acc(expr: object, amount: object = None) -> bool:
    return True


def list_pred(expr: object) -> bool:
    return True


def Pure(func: object) -> object:
    return func


def Predicate(func: object) -> object:
    return func


def Decreases(expr: object, condition: bool = True) -> bool:
    return True


def Unfold(expr: object) -> bool:
    return True
