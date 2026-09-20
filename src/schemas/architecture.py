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
ArchitectureDesignResponse - Pydantic wire schema for LLM structured output.

This module provides a Pydantic model used as the response schema for LLM
structured generation. All subfields are typed so the LLM sees the full JSON-schema
field constraints (including Relationship.source, Component.id regex, etc.) at
generation time — enabling self-healing retry on ValidationError for any field.

``ArchitectureOverviewWire`` requires a non-empty ``overview.reasoning`` so the
model emits its design rationale before committing to components (reason-before-
commit). The base ``design.ArchitectureOverview`` keeps ``reasoning`` optional
for external tool callers.

Both response schemas additionally run the DIV-2..5 cross-reference integrity
gate (``src/design_validation.py``) in a ``model_validator(mode="after")``: a
design with duplicate component ids or dangling relationship/event/contract
references is rejected with the violating path (``relationships[3].target``),
and the self-healing retry in ``src/validation.py`` feeds that back to the
model. The lean wire schema carries no contract lists, so DIV-4/DIV-5 are
vacuous there; DIV-2/DIV-3 still gate. External designs (``evaluate_architecture``)
are checked softly instead — see ``src/tools/_adapters.py::design_integrity_findings``.

For the fully-typed spec schema used at FastMCP tool I/O boundaries,
see design.ArchitectureDesign and design.ArchitectureOverview.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from src.design_validation import evaluate_design_integrity, format_integrity_error
from src.schemas.contracts import (
    ApiContract,
    DataModel,
    EventContract,
)
from src.schemas.design import ArchitectureOverview
from src.schemas.components import Component, Relationship


def _require_closed_references(
    components: list[Component],
    relationships: list[Relationship],
    api_contracts: list[ApiContract],
    event_contracts: list[EventContract],
) -> None:
    """Reject a generated design whose cross-references do not close (DIV-2..5).

    Raises ValueError rendering every violation with its path-level locator, so
    the self-healing retry prompt in src/validation.py names the exact field to
    fix. Empty contract lists (lean wire schema) make DIV-4/DIV-5 vacuous.
    """
    verdict = evaluate_design_integrity(
        components, relationships, api_contracts, event_contracts
    )
    if verdict.violations:
        raise ValueError(format_integrity_error(verdict))


class ArchitectureOverviewWire(ArchitectureOverview):
    """
    LLM-facing overview with ``reasoning`` REQUIRED.

    Overrides the base schema's optional ``reasoning`` with a required,
    non-empty field so structured generation always emits the design rationale
    first (reason-before-commit: reasoning tokens precede the committed
    component/relationship fields). External tool callers keep validating
    against the base ArchitectureOverview, whose ``reasoning`` defaults to "".
    """

    reasoning: str = Field(
        ...,
        min_length=1,
        description=(
            "Design rationale written BEFORE defining components: which "
            "requirements drive which components, which selected patterns "
            "apply, which anti-patterns were avoided, and the key trade-offs "
            "accepted. Must be a non-empty concrete plan, not a platitude."
        ),
    )


class ArchitectureDesignResponse(BaseModel):
    """
    Pydantic response schema for LLM structured generation.

    All subfields are typed Pydantic models so the JSON schema sent to the LLM
    includes field names and constraints.  Relationship items are validated against
    Relationship (requiring source/target/type/description), and Component items
    are validated against Component (including the id regex ^[a-z][a-z0-9_-]*$).
    """

    overview: ArchitectureOverviewWire = Field(
        description="Architecture overview with style, category, and principles"
    )
    components: list[Component] = Field(
        default_factory=list,
        description="List of architecture components"
    )
    relationships: list[Relationship] = Field(
        default_factory=list,
        description="List of component relationships"
    )
    quality_attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Quality attribute annotations"
    )
    api_contracts: list[ApiContract] = Field(
        default_factory=list,
        description="API contract definitions"
    )
    shared_data_models: list[DataModel] = Field(
        default_factory=list,
        description="Shared data model definitions"
    )
    event_contracts: list[EventContract] = Field(
        default_factory=list,
        description="Event contract definitions"
    )

    @model_validator(mode="after")
    def _check_reference_integrity(self) -> ArchitectureDesignResponse:
        """DIV-2..5 gate: dangling source/target/consumer/contract refs are rejected
        here so the self-healing retry re-generates with the violation named."""
        _require_closed_references(
            self.components,
            self.relationships,
            self.api_contracts,
            self.event_contracts,
        )
        return self


class ArchitectureDesignResponseWire(BaseModel):
    """
    Lean wire schema for LLM structured generation.

    Omits patterns (overridden by pipeline) and top-level contract lists (prefers component-level placement).
    Saves ~15KB schema + 1-3K output tokens per call when enabled via retrieval.use_lean_wire_schema.
    The pipeline converts omitted fields to [] when constructing ArchitectureDesign.
    """

    overview: ArchitectureOverviewWire = Field(
        description="Architecture overview with style, category, and principles"
    )
    components: list[Component] = Field(
        default_factory=list,
        description="List of architecture components"
    )
    relationships: list[Relationship] = Field(
        default_factory=list,
        description="List of component relationships"
    )
    quality_attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Quality attribute annotations"
    )
    # Note: api_contracts, shared_data_models, event_contracts omitted;
    # pipeline defaults to [] when constructing ArchitectureDesign.
    # patterns omitted; pipeline injects selected_patterns instead.

    @model_validator(mode="after")
    def _check_reference_integrity(self) -> ArchitectureDesignResponseWire:
        """DIV-2/DIV-3 gate (DIV-4/DIV-5 are vacuous here — the contract lists
        this schema omits default to empty at the pipeline boundary)."""
        _require_closed_references(
            self.components,
            self.relationships,
            [],
            [],
        )
        return self
