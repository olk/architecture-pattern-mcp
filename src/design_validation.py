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
Design cross-reference integrity gate — runtime enforcement of the INV-2..5 family.

The GENERATE phase's dominant defect class is reference breakage: dangling
``relationship.source``/``.target`` ids, duplicate component ids, event
contracts without a resolvable producer/consumer, API contracts referencing
undeclared components. The prompts warn about it and the eval layer measures it
(``tests/eval/invariants.py`` INV-2..5), but until this module nothing in
``src/`` enforced it at runtime.

This module is the pure, synchronous decision engine behind two enforcement
seams (both in ``src/schemas/architecture.py`` and ``src/tools/_adapters.py``):

- the LLM wire schemas (``ArchitectureDesignResponse``,
  ``ArchitectureDesignResponseWire``) run it inside a ``model_validator`` so a
  broken design is rejected → Pydantic ``ValidationError`` → the existing
  self-healing correction-prompt retry in ``src/validation.py``;
- the external design-input adapter runs it as a soft check: caller-authored
  designs keep their transport contract and receive the violations as findings.

Rules (IDs align with the eval-layer INV numbering they promote — same bug
classes, runtime instead of corpus):

- **DIV-2** duplicate ``Component.id`` (regex well-formedness stays in the schema).
- **DIV-3** every ``relationship.source``/``.target`` resolves to a declared component.
- **DIV-4** every ``EventContract.published_by`` and each ``consumed_by`` entry
  resolves to a declared component; at least one consumer is declared.
- **DIV-5** every top-level ``ApiContract.component_id`` resolves to a declared
  component.

Out of scope by design: INV-1 completeness (schema ``min_length`` where
applicable), INV-6 catalogue membership of the cited style, INV-7 score ranges
(Pydantic ``Field`` constraints). Contract fields the lean wire schema omits
are passed as empty sequences — DIV-4/DIV-5 are then vacuously true there,
DIV-2/DIV-3 still gate.

Deliberate non-delegation: ``tests/eval/invariants.py`` keeps its own dict-based
implementation of the same bug classes. The duplication is the price of oracle
independence — the eval layer is a regression oracle for the product, not a
consumer of the product's runtime gate. A divergence between the two shows up
as a corpus failure on one side, which is the intended alarm.

Determinism: violations are returned sorted by ``(rule_id, path)``. The mutmut
stability and corpus diffing depend on this ordering — do not make it
insertion-dependent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

# Type-only imports: this module is the pure decision engine and must stay
# importable from src.schemas.architecture without an import cycle (the
# response schemas call it from the model validator). The functions only
# read attributes, so no runtime reference to the model classes is needed.
if TYPE_CHECKING:
    from src.schemas.components import Component, Relationship
    from src.schemas.contracts import ApiContract, EventContract

__all__ = [
    "DesignIntegrityVerdict",
    "IntegrityViolation",
    "evaluate_design_integrity",
    "format_integrity_error",
    "render_integrity_violation",
]

# Rule identifiers (INV-family alignment documented in the module docstring).
DIV_DUPLICATE_COMPONENT_ID = "DIV-2"
DIV_UNRESOLVED_RELATIONSHIP_ENDPOINT = "DIV-3"
DIV_UNRESOLVED_EVENT_REFERENCE = "DIV-4"
DIV_UNRESOLVED_API_CONTRACT_REFERENCE = "DIV-5"


@dataclass(frozen=True)
class IntegrityViolation:
    """One cross-reference defect with a stable, path-level locator.

    Attributes:
        rule_id: ``DIV-2`` | ``DIV-3`` | ``DIV-4`` | ``DIV-5``.
        path: stable locator into the design payload, e.g.
            ``relationships[3].target`` — this is what the correction prompt
            names and what tests pin.
        message: human-readable defect description.
    """

    rule_id: str
    path: str
    message: str


@dataclass(frozen=True)
class DesignIntegrityVerdict:
    """Outcome of one integrity evaluation over one design payload.

    ``violations`` is deterministically ordered by ``(rule_id, path)``; an
    empty tuple means the reference graph is closed.
    """

    violations: tuple[IntegrityViolation, ...]


def evaluate_design_integrity(
    components: Sequence[Component],
    relationships: Sequence[Relationship],
    api_contracts: Sequence[ApiContract] = (),
    event_contracts: Sequence[EventContract] = (),
) -> DesignIntegrityVerdict:
    """Evaluate the DIV-2..DIV-5 reference-closure rules for one design.

    Pure and synchronous: no LLM, no I/O, no mutation of the inputs.

    Args:
        components: Declared components (their ``id`` values are the
            reference targets).
        relationships: Directed component relationships.
        api_contracts: Top-level API contracts (empty for the lean wire
            schema, which omits them).
        event_contracts: Event contracts (empty for the lean wire schema).

    Returns:
        DesignIntegrityVerdict with violations sorted by ``(rule_id, path)``.
    """
    component_ids = [component.id for component in components]
    known_ids = set(component_ids)

    violations = [
        *_duplicate_id_violations(component_ids),
        *_relationship_violations(relationships, known_ids),
        *_event_violations(event_contracts, known_ids),
        *_api_contract_violations(api_contracts, known_ids),
    ]
    violations.sort(key=lambda violation: (violation.rule_id, violation.path))
    return DesignIntegrityVerdict(violations=tuple(violations))


def _duplicate_id_violations(component_ids: Sequence[str]) -> list[IntegrityViolation]:
    """DIV-2: duplicate component ids — a violation per repeat occurrence,
    each naming the first declaration."""
    violations: list[IntegrityViolation] = []
    first_index: dict[str, int] = {}
    for index, component_id in enumerate(component_ids):
        if component_id in first_index:
            violations.append(
                IntegrityViolation(
                    rule_id=DIV_DUPLICATE_COMPONENT_ID,
                    path=f"components[{index}].id",
                    message=(
                        f"duplicate component id {component_id!r}; first declared "
                        f"at components[{first_index[component_id]}].id"
                    ),
                )
            )
        else:
            first_index[component_id] = index
    return violations


def _relationship_violations(
    relationships: Sequence[Relationship], known_ids: set[str]
) -> list[IntegrityViolation]:
    """DIV-3: every relationship endpoint resolves to a declared component."""
    violations: list[IntegrityViolation] = []
    for index, relationship in enumerate(relationships):
        if relationship.source not in known_ids:
            violations.append(
                IntegrityViolation(
                    rule_id=DIV_UNRESOLVED_RELATIONSHIP_ENDPOINT,
                    path=f"relationships[{index}].source",
                    message=f"unresolved component id {relationship.source!r}",
                )
            )
        if relationship.target not in known_ids:
            violations.append(
                IntegrityViolation(
                    rule_id=DIV_UNRESOLVED_RELATIONSHIP_ENDPOINT,
                    path=f"relationships[{index}].target",
                    message=f"unresolved component id {relationship.target!r}",
                )
            )
    return violations


def _event_violations(
    event_contracts: Sequence[EventContract], known_ids: set[str]
) -> list[IntegrityViolation]:
    """DIV-4: every event names a resolvable producer AND at least one
    consumer, all declared components."""
    violations: list[IntegrityViolation] = []
    for index, event in enumerate(event_contracts):
        if event.published_by not in known_ids:
            violations.append(
                IntegrityViolation(
                    rule_id=DIV_UNRESOLVED_EVENT_REFERENCE,
                    path=f"event_contracts[{index}].published_by",
                    message=(
                        f"event {event.event_name!r} has unresolved producer "
                        f"{event.published_by!r}"
                    ),
                )
            )
        if not event.consumed_by:
            violations.append(
                IntegrityViolation(
                    rule_id=DIV_UNRESOLVED_EVENT_REFERENCE,
                    path=f"event_contracts[{index}].consumed_by",
                    message=f"event {event.event_name!r} has no consumer",
                )
            )
        for consumer_index, consumer in enumerate(event.consumed_by):
            if consumer not in known_ids:
                violations.append(
                    IntegrityViolation(
                        rule_id=DIV_UNRESOLVED_EVENT_REFERENCE,
                        path=f"event_contracts[{index}].consumed_by[{consumer_index}]",
                        message=(
                            f"event {event.event_name!r} has unresolved consumer "
                            f"{consumer!r}"
                        ),
                    )
                )
    return violations


def _api_contract_violations(
    api_contracts: Sequence[ApiContract], known_ids: set[str]
) -> list[IntegrityViolation]:
    """DIV-5: every top-level API contract resolves to a declared component."""
    violations: list[IntegrityViolation] = []
    for index, api_contract in enumerate(api_contracts):
        if api_contract.component_id not in known_ids:
            violations.append(
                IntegrityViolation(
                    rule_id=DIV_UNRESOLVED_API_CONTRACT_REFERENCE,
                    path=f"api_contracts[{index}].component_id",
                    message=(
                        f"api contract for unresolved component "
                        f"{api_contract.component_id!r}"
                    ),
                )
            )
    return violations


def render_integrity_violation(violation: IntegrityViolation) -> str:
    """Render one violation as ``RULE: path: message`` (the retry-prompt form)."""
    return f"{violation.rule_id}: {violation.path}: {violation.message}"


def format_integrity_error(verdict: DesignIntegrityVerdict) -> str:
    """Render the full correction-prompt message for a non-clean verdict.

    Callers must only call this for verdicts with at least one violation
    (the empty case has no rejection to explain).
    """
    header = (
        f"Design cross-reference integrity failed: "
        f"{len(verdict.violations)} violation(s)"
    )
    lines = [header]
    lines.extend(render_integrity_violation(v) for v in verdict.violations)
    return "\n".join(lines)
