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

The precedence/dedup decision logic operates on plain keys extracted from the
Pydantic design (component_ids, (name, is_shared) tuples, event names); the
returned keys are mapped back onto the original objects with a first-occurrence
scan.  The scan reproduces the historical algorithm's object identity and
order semantics exactly (top level first, then components; first occurrence
wins), so the single model_copy(update=..., deep=True) behaves identically to
the pre-verification implementation.

Spec §4.11 rule set (unchanged — see docs/implementation-guide.md §4.14):
  1. Existing top-level entries are preserved (LLM's explicit choice wins).
  2. component.api_contract promoted if its component_id not yet present.
  3. component.data_models entries with is_shared=True promoted if their
     (name, is_shared) tuple is not already present at top level.
  4. event_contracts deduped by event_name; order preserved.

Properties (pinned by tests/unit/test_normalization.py and the L2 Hypothesis
oracle tests/verification/test_normalization_idempotence.py):

- **N-2 dedup**: the result contains no duplicate keys;
- **N-2 coverage**: every eligible input key appears in the result (no loss);
- **N-2 subset**: every result key comes from the inputs (no hallucination);
- **bounds**: the result is no longer than the inputs;
- **N-1 idempotence**: re-running the promotion over an already-promoted key
  list yields the same list;
- **N-3/N-4 order preservation**: first-occurrence order by construction.
"""

from collections.abc import Callable, Hashable, Sequence

from src.schemas import ArchitectureDesign

StrList = list[str]
ModelKeys = list[tuple[str, bool]]


def promote_api_contract_ids(top: list[str], comp: list[str | None]) -> StrList:
    """First-occurrence dedupe of component_ids: top level first, then components.

    ``comp`` entries may be None (components without an api_contract); they
    contribute nothing.  Top-level ids win on collisions (rule 1/2).
    """
    out = []  # type: list[str]
    i = 0
    while i < len(top):
        if top[i] not in out:
            out.append(top[i])
        i = i + 1
    j = 0
    while j < len(comp):
        c = comp[j]
        if c is not None and c not in out:
            out.append(c)
        j = j + 1
    return out


def promote_shared_model_keys(
    top_keys: list[tuple[str, bool]],
    comp_keys: list[tuple[str, bool]],
) -> ModelKeys:
    """First-occurrence dedupe of (name, is_shared) model keys.

    Top-level keys all count; component keys count only when their
    is_shared flag is True (rule 3).  Top-level keys win on collisions.
    """
    out = []  # type: list[tuple[str, bool]]
    i = 0
    while i < len(top_keys):
        if top_keys[i] not in out:
            out.append(top_keys[i])
        i = i + 1
    j = 0
    while j < len(comp_keys):
        c = comp_keys[j]
        if c[1] and c not in out:
            out.append(c)
        j = j + 1
    return out


def dedupe_event_names(names: list[str]) -> StrList:
    """First-occurrence dedupe of event names (rule 4, N-3)."""
    out = []  # type: list[str]
    i = 0
    while i < len(names):
        if names[i] not in out:
            out.append(names[i])
        i = i + 1
    return out


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
