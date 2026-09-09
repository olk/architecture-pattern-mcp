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
Pure denormalization core over plain data — Nagini verification target
(nagini plan §3.4/§3.8: design_normalization is NOT Pydantic-free, so the
pure core operates on structural protocols and the Pydantic adapter in
src/design_normalization.py performs the single model_copy).

Spec §4.11 rule set (unchanged — see docs/implementation-guide.md §4.14):
  1. Existing top-level entries are preserved (LLM's explicit choice wins).
  2. component.api_contract promoted if its component_id not yet present.
  3. component.data_models entries with is_shared=True promoted if their
     (name, is_shared) tuple is not already present at top level.
  4. event_contracts deduped by event_name; order preserved.

Machine-checkable properties: idempotence, dedup invariants, order
preservation (N-1..N-4, tests/verification/test_normalization_idempotence.py).
"""

from collections.abc import Sequence
from typing import Protocol


class IdentifiedContract(Protocol):
    """Duck-typed view of ApiContract.component_id."""

    @property
    def component_id(self) -> str: ...


class SharedModel(Protocol):
    """Duck-typed view of DataModel identity."""

    @property
    def name(self) -> str: ...

    @property
    def is_shared(self) -> bool: ...


class NamedEvent(Protocol):
    """Duck-typed view of EventContract.event_name."""

    @property
    def event_name(self) -> str: ...


class ComponentContracts(Protocol):
    """Duck-typed view of Component contract slots."""

    @property
    def api_contract(self) -> IdentifiedContract | None: ...

    @property
    def data_models(self) -> Sequence[SharedModel]: ...


class DesignData(Protocol):
    """Duck-typed view of the ArchitectureDesign fields under normalization."""

    @property
    def api_contracts(self) -> Sequence[IdentifiedContract]: ...

    @property
    def components(self) -> Sequence[ComponentContracts]: ...

    @property
    def shared_data_models(self) -> Sequence[SharedModel]: ...

    @property
    def event_contracts(self) -> Sequence[NamedEvent]: ...


def promote_api_contracts(
    top_level: Sequence[IdentifiedContract],
    components: Sequence[ComponentContracts],
) -> list[IdentifiedContract]:
    """Top-level contracts win on component_id collisions; then component
    contracts fill the unseen ids in component order."""
    promoted: list[IdentifiedContract] = []
    seen_ids: set[str] = set()
    for ac in top_level:
        if ac.component_id not in seen_ids:
            promoted.append(ac)
            seen_ids.add(ac.component_id)
    for comp in components:
        contract = comp.api_contract
        if contract is not None and contract.component_id not in seen_ids:
            promoted.append(contract)
            seen_ids.add(contract.component_id)
    return promoted


def promote_shared_models(
    top_level: Sequence[SharedModel],
    components: Sequence[ComponentContracts],
) -> list[SharedModel]:
    """Top-level models win on (name, is_shared) collisions; then component
    models with is_shared=True fill unseen keys in component order."""
    promoted: list[SharedModel] = []
    seen_models: set[tuple[str, bool]] = set()
    for m in top_level:
        key = (m.name, m.is_shared)
        if key not in seen_models:
            promoted.append(m)
            seen_models.add(key)
    for comp in components:
        for model in comp.data_models:
            if not model.is_shared:
                continue
            key = (model.name, model.is_shared)
            if key not in seen_models:
                promoted.append(model)
                seen_models.add(key)
    return promoted


def dedupe_events(events: Sequence[NamedEvent]) -> list[NamedEvent]:
    """Dedupe by event_name, first occurrence wins, order preserved."""
    promoted: list[NamedEvent] = []
    seen_events: set[str] = set()
    for ec in events:
        if ec.event_name not in seen_events:
            promoted.append(ec)
            seen_events.add(ec.event_name)
    return promoted


def denormalize_core(design: DesignData) -> dict[str, list[object]]:
    """Compute the three denormalized lists over plain data.

    Returns a dict with keys ``api_contracts``, ``shared_data_models`` and
    ``event_contracts``; the caller (Pydantic adapter) applies them via
    model_copy. Pure: reads only, no mutation, no Pydantic calls.
    """
    return {
        "api_contracts": list(
            promote_api_contracts(design.api_contracts, design.components)
        ),
        "shared_data_models": list(
            promote_shared_models(design.shared_data_models, design.components)
        ),
        "event_contracts": list(dedupe_events(design.event_contracts)),
    }
