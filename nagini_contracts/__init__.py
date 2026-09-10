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
Runtime no-op stubs for the Nagini contract vocabulary (L5, verification.md).

Nagini recognises contract calls (``Requires``, ``Ensures``, ``Invariant``,
``Forall``, ``Pure``, ...) purely by call-site *name*; the module that provides
the names is irrelevant to the verifier.  The real ``nagini_contracts``
distribution is not installable in this project's environment (it pins
``mypy==1.5.0``, conflicting with the dev group, see docs/verification.md),
so this package mirrors the contract vocabulary as inert, runtime-safe stubs:

- every contract call evaluates to ``True`` and does nothing (the argument
  expression still evaluates, exactly as with the real library, whose bodies
  are also ``pass``);
- ``Pure``/``Predicate`` are identity decorators.

The typed signatures live in ``contracts.pyi`` and are checked by mypy; this
module is only the runtime implementation (mypy ignores it in favour of the
stub).  The Nagini toolchain skips analysis of any module named
``nagini_contracts.contracts`` and uses its own bundled contract definitions.
"""
