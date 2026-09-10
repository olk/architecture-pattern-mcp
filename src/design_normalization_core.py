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
Pure denormalization decision core over plain data — Nagini verification
target (nagini plan §3.4/§3.8; docs/verification.md L5).

The Pydantic object graphs cannot be translated by Nagini (duck-typed
protocols and model instances are outside its subset), so this core operates
on *plain keys* extracted by the adapter in ``src/design_normalization.py``:

- ``promote_api_contract_ids``: dedupe component_ids of the top-level
  api_contracts followed by the component api_contracts (top level wins on
  collisions).
- ``promote_shared_model_keys``: dedupe (name, is_shared) keys of the
  top-level shared_data_models followed by the component data_models with
  ``is_shared=True`` (top level wins; non-shared component models are skipped).
- ``dedupe_event_names``: dedupe event_contracts by event_name.

Spec §4.11 rule set (unchanged — see docs/implementation-guide.md §4.14):
  1. Existing top-level entries are preserved (LLM's explicit choice wins).
  2. component.api_contract promoted if its component_id not yet present.
  3. component.data_models entries with is_shared=True promoted if their
     (name, is_shared) tuple is not already present at top level.
  4. event_contracts deduped by event_name; order preserved.

Verified properties (machine-checked on ALL inputs):

- **N-2 dedup**: the result contains no duplicate keys;
- **N-2 coverage**: every eligible input key appears in the result (no loss);
- **N-2 subset**: every result key comes from the inputs (no hallucination);
- **bounds**: the result is no longer than the inputs.

The result ORDER is first-occurrence order by construction of the algorithm
(the same two-phase scan as the historical implementation); order preservation
(N-3/N-4) is asserted by the property-based oracle
``tests/verification/test_normalization_idempotence.py`` against the adapter's
output, and idempotence (N-1) holds because re-running the promotion over an
already-promoted key list yields the same list.

The adapter maps the returned keys back onto the original objects with a
first-occurrence scan, so object identity and order semantics are preserved
exactly (tests/unit/test_normalization.py is the behavioral oracle).
"""

from nagini_contracts.contracts import (
    Ensures,
    Exists,
    Forall,
    Implies,
    Invariant,
    Pure,
    Requires,
    Result,
    list_pred,
)

StrList = list[str]
ModelKeys = list[tuple[str, bool]]


@Pure
def no_dup(l: list[str]) -> bool:
    """True iff l contains no duplicate elements (N-2)."""
    Requires(list_pred(l))
    Ensures(
        Result()
        == Forall(
            int,
            lambda p: Forall(
                int,
                lambda q: Implies(p >= 0 and p < q < len(l), l[p] != l[q]),
            ),
        )
    )
    return Forall(
        int,
        lambda p: Forall(
            int,
            lambda q: Implies(p >= 0 and p < q < len(l), l[p] != l[q]),
        ),
    )


@Pure
def no_dup_keys(l: list[tuple[str, bool]]) -> bool:
    """True iff l contains no duplicate (name, is_shared) keys (N-4)."""
    Requires(list_pred(l))
    Ensures(
        Result()
        == Forall(
            int,
            lambda p: Forall(
                int,
                lambda q: Implies(
                    p >= 0 and p < q < len(l),
                    l[p][0] != l[q][0] or l[p][1] != l[q][1],
                ),
            ),
        )
    )
    return Forall(
        int,
        lambda p: Forall(
            int,
            lambda q: Implies(
                p >= 0 and p < q < len(l),
                l[p][0] != l[q][0] or l[p][1] != l[q][1],
            ),
        ),
    )


def promote_api_contract_ids(top: list[str], comp: list[str | None]) -> StrList:
    """First-occurrence dedupe of component_ids: top level first, then components.

    ``comp`` entries may be None (components without an api_contract); they
    contribute nothing.  Top-level ids win on collisions (rule 1/2).
    """
    Requires(list_pred(top) and list_pred(comp))
    Ensures(
        StrList,
        lambda v: (
            list_pred(v)
            and list_pred(top)
            and list_pred(comp)
            and no_dup(v)
            and len(v) <= len(top) + len(comp)
            and Forall(
                int,
                lambda k: Implies(
                    k >= 0 and k < len(top),
                    Exists(
                        int,
                        lambda p: Implies(p >= 0 and p < len(v), v[p] == top[k]),
                    ),
                ),
            )
            and Forall(
                int,
                lambda k: Implies(
                    k >= 0 and k < len(comp) and comp[k] is not None,
                    Exists(
                        int,
                        lambda p: Implies(p >= 0 and p < len(v), v[p] == comp[k]),
                    ),
                ),
            )
            and Forall(
                int,
                lambda p: Implies(
                    p >= 0 and p < len(v),
                    Exists(
                        int,
                        lambda k: Implies(k >= 0 and k < len(top), top[k] == v[p]),
                    )
                    or Exists(
                        int,
                        lambda k: Implies(
                            k >= 0 and k < len(comp) and comp[k] is not None,
                            comp[k] == v[p],
                        ),
                    ),
                ),
            )
        ),
    )
    out = []  # type: list[str]
    i = 0
    while i < len(top):
        Invariant(
            list_pred(out)
            and list_pred(top)
            and no_dup(out)
            and i >= 0
            and i <= len(top)
            and len(out) <= i
            and Forall(
                int,
                lambda k: Implies(
                    k >= 0 and k < i,
                    Exists(
                        int,
                        lambda p: Implies(p >= 0 and p < len(out), out[p] == top[k]),
                    ),
                ),
            )
            and Forall(
                int,
                lambda p: Implies(
                    p >= 0 and p < len(out),
                    Exists(
                        int,
                        lambda k: Implies(k >= 0 and k < i, top[k] == out[p]),
                    ),
                ),
            )
        )
        if not Exists(
            int, lambda p: Implies(p >= 0 and p < len(out), out[p] == top[i])
        ):
            out.append(top[i])
        i = i + 1
    j = 0
    while j < len(comp):
        Invariant(
            list_pred(out)
            and list_pred(top)
            and list_pred(comp)
            and no_dup(out)
            and j >= 0
            and j <= len(comp)
            and len(out) <= len(top) + j
            and Forall(
                int,
                lambda k: Implies(
                    k >= 0 and k < len(top),
                    Exists(
                        int,
                        lambda p: Implies(p >= 0 and p < len(out), out[p] == top[k]),
                    ),
                ),
            )
            and Forall(
                int,
                lambda k: Implies(
                    k >= 0 and k < j and comp[k] is not None,
                    Exists(
                        int,
                        lambda p: Implies(p >= 0 and p < len(out), out[p] == comp[k]),
                    ),
                ),
            )
            and Forall(
                int,
                lambda p: Implies(
                    p >= 0 and p < len(out),
                    Exists(
                        int,
                        lambda k: Implies(k >= 0 and k < len(top), top[k] == out[p]),
                    )
                    or Exists(
                        int,
                        lambda k: Implies(
                            k >= 0 and k < j and comp[k] is not None,
                            comp[k] == out[p],
                        ),
                    ),
                ),
            )
        )
        c = comp[j]
        if c is not None and not Exists(
            int, lambda p: Implies(p >= 0 and p < len(out), out[p] == c)
        ):
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
    Requires(list_pred(top_keys) and list_pred(comp_keys))
    Ensures(
        ModelKeys,
        lambda v: (
            list_pred(v)
            and list_pred(top_keys)
            and list_pred(comp_keys)
            and no_dup_keys(v)
            and len(v) <= len(top_keys) + len(comp_keys)
            and Forall(
                int,
                lambda k: Implies(
                    k >= 0 and k < len(top_keys),
                    Exists(
                        int,
                        lambda p: Implies(
                            p >= 0 and p < len(v), (v[p][0] == top_keys[k][0] and v[p][1] == top_keys[k][1])
                        ),
                    ),
                ),
            )
            and Forall(
                int,
                lambda k: Implies(
                    k >= 0 and k < len(comp_keys) and comp_keys[k][1],
                    Exists(
                        int,
                        lambda p: Implies(
                            p >= 0 and p < len(v), (v[p][0] == comp_keys[k][0] and v[p][1] == comp_keys[k][1])
                        ),
                    ),
                ),
            )
            and Forall(
                int,
                lambda p: Implies(
                    p >= 0 and p < len(v),
                    Exists(
                        int,
                        lambda k: Implies(
                            k >= 0 and k < len(top_keys), (top_keys[k][0] == v[p][0] and top_keys[k][1] == v[p][1])
                        ),
                    )
                    or Exists(
                        int,
                        lambda k: Implies(
                            k >= 0 and k < len(comp_keys), (comp_keys[k][0] == v[p][0] and comp_keys[k][1] == v[p][1])
                        ),
                    ),
                ),
            )
        ),
    )
    out = []  # type: list[tuple[str, bool]]
    i = 0
    while i < len(top_keys):
        Invariant(
            list_pred(out)
            and list_pred(top_keys)
            and no_dup_keys(out)
            and i >= 0
            and i <= len(top_keys)
            and len(out) <= i
            and Forall(
                int,
                lambda k: Implies(
                    k >= 0 and k < i,
                    Exists(
                        int,
                        lambda p: Implies(
                            p >= 0 and p < len(out), (out[p][0] == top_keys[k][0] and out[p][1] == top_keys[k][1])
                        ),
                    ),
                ),
            )
            and Forall(
                int,
                lambda p: Implies(
                    p >= 0 and p < len(out),
                    Exists(
                        int,
                        lambda k: Implies(
                            k >= 0 and k < i, (top_keys[k][0] == out[p][0] and top_keys[k][1] == out[p][1])
                        ),
                    ),
                ),
            )
        )
        if not Exists(
            int,
            lambda p: Implies(
                p >= 0 and p < len(out), out[p][0] == top_keys[i][0] and out[p][1] == top_keys[i][1]
            ),
        ):
            out.append(top_keys[i])
        i = i + 1
    j = 0
    while j < len(comp_keys):
        Invariant(
            list_pred(out)
            and list_pred(top_keys)
            and list_pred(comp_keys)
            and no_dup_keys(out)
            and j >= 0
            and j <= len(comp_keys)
            and len(out) <= len(top_keys) + j
            and Forall(
                int,
                lambda k: Implies(
                    k >= 0 and k < len(top_keys),
                    Exists(
                        int,
                        lambda p: Implies(
                            p >= 0 and p < len(out), (out[p][0] == top_keys[k][0] and out[p][1] == top_keys[k][1])
                        ),
                    ),
                ),
            )
            and Forall(
                int,
                lambda k: Implies(
                    k >= 0 and k < j and comp_keys[k][1],
                    Exists(
                        int,
                        lambda p: Implies(
                            p >= 0 and p < len(out), (out[p][0] == comp_keys[k][0] and out[p][1] == comp_keys[k][1])
                        ),
                    ),
                ),
            )
            and Forall(
                int,
                lambda p: Implies(
                    p >= 0 and p < len(out),
                    Exists(
                        int,
                        lambda k: Implies(
                            k >= 0 and k < len(top_keys), (top_keys[k][0] == out[p][0] and top_keys[k][1] == out[p][1])
                        ),
                    )
                    or Exists(
                        int,
                        lambda k: Implies(
                            k >= 0 and k < j, (comp_keys[k][0] == out[p][0] and comp_keys[k][1] == out[p][1])
                        ),
                    ),
                ),
            )
        )
        c = comp_keys[j]
        if c[1] and not Exists(
            int,
            lambda p: Implies(
                p >= 0 and p < len(out), out[p][0] == c[0] and out[p][1] == c[1]
            ),
        ):
            out.append(c)
        j = j + 1
    return out


def dedupe_event_names(names: list[str]) -> StrList:
    """First-occurrence dedupe of event names (rule 4, N-3)."""
    Requires(list_pred(names))
    Ensures(
        StrList,
        lambda v: (
            list_pred(v)
            and list_pred(names)
            and no_dup(v)
            and len(v) <= len(names)
            and Forall(
                int,
                lambda k: Implies(
                    k >= 0 and k < len(names),
                    Exists(
                        int,
                        lambda p: Implies(p >= 0 and p < len(v), v[p] == names[k]),
                    ),
                ),
            )
            and Forall(
                int,
                lambda p: Implies(
                    p >= 0 and p < len(v),
                    Exists(
                        int,
                        lambda k: Implies(
                            k >= 0 and k < len(names), names[k] == v[p]
                        ),
                    ),
                ),
            )
        ),
    )
    out = []  # type: list[str]
    i = 0
    while i < len(names):
        Invariant(
            list_pred(out)
            and list_pred(names)
            and no_dup(out)
            and i >= 0
            and i <= len(names)
            and len(out) <= i
            and Forall(
                int,
                lambda k: Implies(
                    k >= 0 and k < i,
                    Exists(
                        int,
                        lambda p: Implies(p >= 0 and p < len(out), out[p] == names[k]),
                    ),
                ),
            )
            and Forall(
                int,
                lambda p: Implies(
                    p >= 0 and p < len(out),
                    Exists(
                        int,
                        lambda k: Implies(k >= 0 and k < i, names[k] == out[p]),
                    ),
                ),
            )
        )
        if not Exists(
            int, lambda p: Implies(p >= 0 and p < len(out), out[p] == names[i])
        ):
            out.append(names[i])
        i = i + 1
    return out
