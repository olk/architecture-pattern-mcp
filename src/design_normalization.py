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

Pydantic adapter: the verified precedence/dedup decision core lives in
src/design_normalization_core.py (plain key lists, Nagini target, L5); this
module extracts the keys from the Pydantic design, delegates the decisions,
and maps the returned keys back onto the original objects with a
first-occurrence scan.  The scan reproduces the historical algorithm's object
identity and order semantics exactly (top level first, then components;
first occurrence wins), so the single model_copy(update=..., deep=True)
behaves identically to the pre-verification implementation.

See docs/implementation-guide.md §4.14 for the full rule table.
"""

from collections.abc import Callable, Hashable, Sequence

from src.design_normalization_core import (
    dedupe_event_names,
    promote_api_contract_ids,
    promote_shared_model_keys,
)
from src.schemas import ArchitectureDesign

def _select_first[T, K: Hashable](
    primary: Sequence[T],
    secondary: Sequence[T],
    wanted: set[K],
    key: Callable[[T], K],
) -> list[T]:
    """First-occurrence selection: scan primary then secondary, emitting each
    object whose key is wanted the first time it is seen.

    The emitted key sequence equals ``wanted`` restricted to scan order, so
    object identity (the first object per key) and order semantics match the
    historical promotion loops exactly.
    """
    result: list[T] = []
    seen: set[K] = set()
    for obj in (*primary, *secondary):
        k = key(obj)
        if k in wanted and k not in seen:
            result.append(obj)
            seen.add(k)
    return result


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
    top_api_ids = [ac.component_id for ac in design.api_contracts]
    comp_api_ids = [
        c.api_contract.component_id if c.api_contract is not None else None
        for c in design.components
    ]
    api_ids = promote_api_contract_ids(top_api_ids, comp_api_ids)
    api_contracts = _select_first(
        design.api_contracts,
        [c.api_contract for c in design.components if c.api_contract is not None],
        set(api_ids),
        lambda ac: ac.component_id,
    )

    top_model_keys = [(m.name, m.is_shared) for m in design.shared_data_models]
    comp_model_keys = [
        (m.name, m.is_shared) for c in design.components for m in c.data_models
    ]
    model_keys = promote_shared_model_keys(top_model_keys, comp_model_keys)
    shared_data_models = _select_first(
        design.shared_data_models,
        [m for c in design.components for m in c.data_models],
        set(model_keys),
        lambda m: (m.name, m.is_shared),
    )

    event_names = [e.event_name for e in design.event_contracts]
    kept_event_names = dedupe_event_names(event_names)
    event_contracts = _select_first(
        design.event_contracts,
        [],
        set(kept_event_names),
        lambda e: e.event_name,
    )

    return design.model_copy(
        update={
            "api_contracts": api_contracts,
            "shared_data_models": shared_data_models,
            "event_contracts": event_contracts,
        },
        deep=True,
    )
