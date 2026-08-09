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
Pure transformations on ArchitectureDesign for spec §4.11 denormalization.

See docs/implementation-guide.md §4.14 for the full rule table.
"""

from src.schemas import (
    ApiContract,
    ArchitectureDesign,
    DataModel,
    EventContract,
)


def denormalize_contracts(design: ArchitectureDesign) -> ArchitectureDesign:
    """Flatten component.api_contract and component.data_models (is_shared=True)
    into top-level lists. event_contracts deduped by event_name.

    Precedence rules:
      1. Existing top-level entries are preserved (LLM's explicit choice wins).
      2. component.api_contract promoted if its component_id not yet present.
      3. component.data_models entries with is_shared=True promoted if their
         (name, is_shared) tuple is not already present at top level.
      4. event_contracts deduped by event_name; order preserved.

    Idempotent. Uses model_copy(update=..., deep=True). Caller must treat
    the returned design as immutable — list fields are references to trusted
    input.
    """
    seen_ids: set[str] = set()
    promoted_apis: list[ApiContract] = []
    for ac in design.api_contracts:
        if ac.component_id not in seen_ids:
            promoted_apis.append(ac)
            seen_ids.add(ac.component_id)
    for comp in design.components:
        if comp.api_contract is not None and comp.api_contract.component_id not in seen_ids:
            promoted_apis.append(comp.api_contract)
            seen_ids.add(comp.api_contract.component_id)

    seen_models: set[tuple[str, bool]] = set()
    promoted_models: list[DataModel] = []
    for m in design.shared_data_models:
        key = (m.name, m.is_shared)
        if key not in seen_models:
            promoted_models.append(m)
            seen_models.add(key)
    for comp in design.components:
        for model in comp.data_models:
            if not model.is_shared:
                continue
            key = (model.name, model.is_shared)
            if key not in seen_models:
                promoted_models.append(model)
                seen_models.add(key)

    seen_events: set[str] = set()
    promoted_events: list[EventContract] = []
    for ec in design.event_contracts:
        if ec.event_name not in seen_events:
            promoted_events.append(ec)
            seen_events.add(ec.event_name)

    return design.model_copy(
        update={
            "api_contracts": promoted_apis,
            "shared_data_models": promoted_models,
            "event_contracts": promoted_events,
        },
        deep=True,
    )
