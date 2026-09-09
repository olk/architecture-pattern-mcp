# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
Typed runtime no-op shim mirroring the ``nagini_contracts.contracts`` surface.

The nagini-contracts package is not installable in the current environment
(docs/phase-0-decisions.md, "Environment provisioning notes"). The twins
import the contract surface from here so the swap to the real package is a
one-line import change per file. Semantics:

- Every function call evaluates its arguments (like the real package) and
  discards them — contracts are runtime no-ops, verified and shipped code
  stay identical.
- ``Result()`` returns a ghost placeholder supporting the operations contract
  expressions use (``len()``, comparisons, arithmetic) so expressions such as
  ``Ensures(len(Result()) <= n)`` stay harmless at runtime. Under the real
  verifier, Result() is the ghost post-state value.
- ``@Pure`` / ``@Predicate`` / ``@Inline`` are identity decorators.

This module must never be imported from src/ — verification machinery stays
out of the shipped tree (nagini plan §3.1 principle 3, §3.9).
"""

from typing import Any


class _GhostResult:
    """Placeholder for the ghost post-state value in Ensures expressions."""

    def __len__(self) -> int:
        return 0

    def __getattr__(self, _name: str) -> "_GhostResult":
        return _GhostResult()

    def __getitem__(self, _key: Any) -> "_GhostResult":
        return _GhostResult()

    def __eq__(self, other: object) -> bool:
        return self is other or isinstance(other, _GhostResult)

    def __le__(self, _other: object) -> bool:
        return True

    def __ge__(self, _other: object) -> bool:
        return True

    def __lt__(self, _other: object) -> bool:
        return True

    def __gt__(self, _other: object) -> bool:
        return True

    def __hash__(self) -> int:
        return hash("_GhostResult")


def Result() -> _GhostResult:
    """Ghost handle to the function's return value (post-state)."""
    return _GhostResult()


def Old(__expr: Any) -> Any:
    """Ghost handle to a pre-state value."""
    return __expr


def Requires(*_conditions: object) -> None:
    """Precondition (runtime no-op)."""


def Ensures(*_conditions: object) -> None:
    """Postcondition (runtime no-op)."""


def Exsures(*_exceptions: object) -> None:
    """Exceptional postcondition (runtime no-op)."""


def Invariant(_condition: object) -> None:
    """Loop invariant (runtime no-op)."""


def Assert(_condition: object) -> None:
    """Verification-only assertion (runtime no-op)."""


def Assume(_condition: object) -> None:
    """Assumption for the verifier (runtime no-op)."""


def Decreases(*_expressions: object) -> None:
    """Termination measure (runtime no-op)."""


def MustTerminate(_level: int) -> None:
    """Termination obligation (runtime no-op)."""


def _identity[Widget](cls: Widget) -> Widget:
    return cls


Pure = _identity
Predicate = _identity
Inline = _identity
Opaque = _identity
