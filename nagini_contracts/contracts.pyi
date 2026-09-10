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
Typed signatures for the Nagini contract vocabulary (runtime no-ops).

This stub file is what mypy (CI and the zuban LSP) type-checks; the runtime
implementations in ``contracts.py`` are inert.  ``Result()`` is deliberately
typed ``object`` instead of ``Any`` (the upstream library uses ``Any``) so the
project's strict mypy settings stay clean — call sites that need a typed
result use the two-argument ``Ensures(Type, lambda v: ...)`` form instead.
"""

from typing import Callable, Iterable, TypeVar, overload

T = TypeVar("T")

def Requires(expr: bool) -> bool: ...

@overload
def Ensures(expr: bool) -> bool: ...

@overload
def Ensures(t: type[T], expr: Callable[[T], bool]) -> bool: ...

def Exsures(exception: type, expr: bool) -> bool: ...

def Invariant(expr: bool) -> bool: ...

def Assert(expr: bool) -> bool: ...

def Implies(p: bool, q: bool) -> bool: ...

def Forall(domain: Iterable[T] | type[T], predicate: Callable[[T], bool]) -> bool: ...

def Exists(domain: Iterable[T] | type[T], predicate: Callable[[T], bool]) -> bool: ...

def Old(expr: T) -> T: ...

def Result() -> object: ...

def Acc(expr: object, amount: float | None = None) -> bool: ...

def list_pred(expr: object) -> bool: ...

def Pure(func: T) -> T: ...

def Predicate(func: T) -> T: ...

def Decreases(expr: int | None, condition: bool = True) -> bool: ...

def Unfold(expr: object) -> bool: ...
