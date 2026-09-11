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
Direct unit tests for the src.design_normalization key-level decisions.

``denormalize_contracts`` is pinned by tests/unit/test_normalization.py and the
L2 oracle (N-1..N-4). This module tests the four decision primitives directly —
``promote_api_contract_ids``, ``promote_shared_model_keys``,
``dedupe_event_names``, ``_select_first`` — because the public function only
reaches them transitively: index-step mutants (``i = i + 1`` -> ``i = i + 2``)
and membership-flip mutants survive wrapper-level tests whenever the sample
shapes happen to coincide.

Case design (each case names the mutation class it kills):

- two-element inputs distinguish ``+1`` from ``+2`` steps (a step past the
  second element silently drops it);
- None entries in ``comp`` pin the ``is not None`` conjunct (``or``-flips
  leak None into the result);
- duplicate keys pin the ``not in out`` membership and the ``seen`` add.
"""

from src.design_normalization import (
    _select_first,
    dedupe_event_names,
    promote_api_contract_ids,
    promote_shared_model_keys,
)


def _k(obj: dict[str, str]) -> str:
    """Key extractor for _select_first call sites (keeps T/K inference concrete)."""
    return obj["k"]


class TestPromoteApiContractIds:
    def test_empty_inputs(self) -> None:
        assert promote_api_contract_ids([], []) == []

    def test_top_level_order_preserved(self) -> None:
        assert promote_api_contract_ids(["a", "b", "c"], []) == ["a", "b", "c"]

    def test_two_top_level_entries_catch_index_step_mutants(self) -> None:
        """Kills ``i = i + 1`` -> ``i = i + 2``: the +2 step drops element 'b'."""
        assert promote_api_contract_ids(["a", "b"], []) == ["a", "b"]

    def test_top_level_dedupe(self) -> None:
        """Kills ``not in out`` -> ``in out`` membership flip."""
        assert promote_api_contract_ids(["a", "a", "b"], []) == ["a", "b"]

    def test_component_ids_appended_after_top_level(self) -> None:
        assert promote_api_contract_ids(["a"], ["b", "c"]) == ["a", "b", "c"]

    def test_component_collision_with_top_level_wins_nothing(self) -> None:
        """Rule 1/2: top-level id wins; component duplicate is dropped."""
        assert promote_api_contract_ids(["a"], ["a", "b"]) == ["a", "b"]

    def test_none_component_entries_are_skipped(self) -> None:
        """Kills ``c is not None and ...`` -> ``or`` (None would leak into out)."""
        assert promote_api_contract_ids([], [None, "c", None]) == ["c"]

    def test_all_none_components(self) -> None:
        assert promote_api_contract_ids(["a"], [None, None]) == ["a"]

    def test_component_level_dedupe(self) -> None:
        assert promote_api_contract_ids([], ["c", "c"]) == ["c"]


class TestPromoteSharedModelKeys:
    def test_empty_inputs(self) -> None:
        assert promote_shared_model_keys([], []) == []

    def test_top_level_keys_all_count(self) -> None:
        """Both flags kept — (name, is_shared) is the dedupe key, name alone is not."""
        keys = [("User", False), ("User", True)]
        assert promote_shared_model_keys(keys, []) == keys

    def test_top_level_dedupe_by_full_tuple(self) -> None:
        assert promote_shared_model_keys(
            [("User", True), ("User", True)], []
        ) == [("User", True)]

    def test_local_component_keys_are_not_promoted(self) -> None:
        """Kills ``c[1] and ...`` -> ``c[0]`` (name truthiness would promote)."""
        assert promote_shared_model_keys(
            [], [("OrderItem", False), ("Audit", False)]
        ) == []

    def test_shared_component_keys_are_promoted(self) -> None:
        assert promote_shared_model_keys([], [("User", True)]) == [("User", True)]

    def test_component_collision_with_top_level_is_dropped(self) -> None:
        assert promote_shared_model_keys(
            [("User", True)], [("User", True), ("Order", True)]
        ) == [("User", True), ("Order", True)]

    def test_component_level_dedupe(self) -> None:
        assert promote_shared_model_keys(
            [], [("User", True), ("User", True)]
        ) == [("User", True)]

    def test_mixed_flags_in_components(self) -> None:
        """Local entries between shared ones do not break the shared chain."""
        assert promote_shared_model_keys(
            [],
            [("A", True), ("B", False), ("C", True), ("A", True)],
        ) == [("A", True), ("C", True)]


class TestDedupeEventNames:
    def test_empty(self) -> None:
        assert dedupe_event_names([]) == []

    def test_no_duplicates_order_preserved(self) -> None:
        assert dedupe_event_names(["user.created", "order.completed"]) == [
            "user.created",
            "order.completed",
        ]

    def test_duplicates_removed_first_occurrence_wins(self) -> None:
        assert dedupe_event_names(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]

    def test_two_element_list_catches_index_step_mutants(self) -> None:
        """Kills ``i = i + 1`` -> ``i = i + 2``: the +2 step silently drops 'b'."""
        assert dedupe_event_names(["a", "b"]) == ["a", "b"]

    def test_all_duplicates(self) -> None:
        assert dedupe_event_names(["x", "x", "x"]) == ["x"]


class TestSelectFirst:
    def test_empty_everything(self) -> None:
        assert _select_first([], [], set(), lambda o: o) == []

    def test_primary_scanned_before_secondary(self) -> None:
        """First occurrence wins: the primary object for a wanted key is kept."""
        result = _select_first(
            [{"k": "a", "src": "top"}],
            [{"k": "a", "src": "comp"}],
            {"a"},
            _k,
        )
        assert result == [{"k": "a", "src": "top"}]

    def test_unwanted_keys_are_skipped(self) -> None:
        """Kills ``k in wanted and k not in seen`` -> ``or`` (b would leak in)."""
        result = _select_first(
            [{"k": "a"}, {"k": "b"}],
            [],
            {"a"},
            _k,
        )
        assert result == [{"k": "a"}]

    def test_seen_guard_keeps_only_first_per_key(self) -> None:
        """Kills ``seen.add(k)`` deletion (both duplicates would be emitted)."""
        result = _select_first(
            [{"k": "a", "n": "1"}, {"k": "a", "n": "2"}],
            [],
            {"a"},
            _k,
        )
        assert result == [{"k": "a", "n": "1"}]

    def test_secondary_only_keys_are_promoted(self) -> None:
        result = _select_first(
            [{"k": "a"}],
            [{"k": "b"}],
            {"a", "b"},
            _k,
        )
        assert [o["k"] for o in result] == ["a", "b"]

    def test_empty_wanted_selects_nothing(self) -> None:
        result = _select_first(
            [{"k": "a"}],
            [{"k": "b"}],
            set(),
            _k,
        )
        assert result == []

    def test_order_follows_scan_order_not_wanted_order(self) -> None:
        """N-3/N-4: emitted order is scan order, wanted is a set (unordered)."""
        result = _select_first(
            [{"k": "c"}, {"k": "a"}],
            [],
            {"a", "c"},
            _k,
        )
        assert [o["k"] for o in result] == ["c", "a"]
