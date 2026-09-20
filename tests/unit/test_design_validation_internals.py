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
Direct unit tests for the src.design_validation decision engine.

src.design_validation is in the mutmut scope (it is not listed in
`do_not_mutate`), so this module is its direct kill oracle — the wire-schema
tests (`tests/unit/test_design.py`, `tests/schemas/test_schemas.py`) only
exercise it transitively through one layer of Pydantic plumbing and cannot pin
per-path locators, index arithmetic, or ordering.

Case design (each documented case names the mutation class it kills):

- rule predicates are exercised in isolation per DIV id: each family asserts
  the exact ``(rule_id, path)`` tuple, so a flipped membership test, a
  source/target swap, or a dropped check flips a verdict;
- locator index arithmetic uses multi-element inputs (relationships[1],
  consumed_by[1], api_contracts[1]) so an off-by-one or a first-element-only
  mutant cannot survive;
- the duplicate-id family pins the "first declared at" message, killing
  ``first_index`` overwrite mutants of the repeat-reporting branch;
- ordering cases use index 10 vs 2 (lexicographic path order differs from
  insertion order) and all four rule families at once (rule-first grouping
  differs from path-first grouping), killing a dropped or re-keyed sort;
- the renderers are pinned byte-for-byte (separator and count-literal mutants).
"""

from src.design_validation import (
    DIV_DUPLICATE_COMPONENT_ID,
    DIV_UNRESOLVED_API_CONTRACT_REFERENCE,
    DIV_UNRESOLVED_EVENT_REFERENCE,
    DIV_UNRESOLVED_RELATIONSHIP_ENDPOINT,
    DesignIntegrityVerdict,
    IntegrityViolation,
    evaluate_design_integrity,
    format_integrity_error,
    render_integrity_violation,
)
from src.schemas.components import Component, Relationship
from src.schemas.contracts import ApiContract, EventContract


def _component(component_id: str) -> Component:
    return Component(
        id=component_id,
        name=f"Component {component_id}",
        type="service",
        description="test component",
        responsibilities=["serve"],
    )


def _relationship(source: str, target: str) -> Relationship:
    return Relationship(source=source, target=target, type="sync", description="calls")


def _api_contract(component_id: str) -> ApiContract:
    return ApiContract(component_id=component_id, base_path="/api/v1/x")


def _event(name: str, published_by: str, consumed_by: list[str]) -> EventContract:
    return EventContract(
        event_name=name,
        payload_schema={"type": "object"},
        published_by=published_by,
        consumed_by=consumed_by,
    )


def _paths(verdict: DesignIntegrityVerdict) -> list[tuple[str, str]]:
    return [(violation.rule_id, violation.path) for violation in verdict.violations]


class TestCleanDesign:
    def test_closed_reference_graph_yields_no_violations(self) -> None:
        """Kills inverted-predicate mutants: a fully resolvable design must be clean."""
        verdict = evaluate_design_integrity(
            components=[_component("ingest"), _component("worker")],
            relationships=[_relationship("ingest", "worker")],
            api_contracts=[_api_contract("worker")],
            event_contracts=[_event("job.done", "worker", ["ingest"])],
        )
        assert verdict.violations == ()

    def test_contract_lists_default_to_empty(self) -> None:
        """Lean wire schema path: omitted contract lists must default to clean."""
        verdict = evaluate_design_integrity(
            components=[_component("ingest")],
            relationships=[],
        )
        assert verdict.violations == ()


class TestDuplicateComponentIdRule:
    def test_repeat_id_reports_occurrence_and_first_declaration(self) -> None:
        """Kills detection removal and first_index overwrite mutants."""
        verdict = evaluate_design_integrity(
            components=[_component("ingest"), _component("worker"), _component("ingest")],
            relationships=[],
        )
        assert _paths(verdict) == [(DIV_DUPLICATE_COMPONENT_ID, "components[2].id")]
        assert verdict.violations[0].message == (
            "duplicate component id 'ingest'; first declared at components[0].id"
        )

    def test_triple_id_reports_every_repeat_against_the_first(self) -> None:
        """Kills ``first_index`` assignment mutants: the second repeat must still
        name index 0 as the original declaration, not the previous repeat."""
        verdict = evaluate_design_integrity(
            components=[_component("api"), _component("api"), _component("api")],
            relationships=[],
        )
        assert _paths(verdict) == [
            (DIV_DUPLICATE_COMPONENT_ID, "components[1].id"),
            (DIV_DUPLICATE_COMPONENT_ID, "components[2].id"),
        ]
        assert verdict.violations[1].message == (
            "duplicate component id 'api'; first declared at components[0].id"
        )

    def test_unique_ids_produce_no_violation(self) -> None:
        verdict = evaluate_design_integrity(
            components=[_component("a"), _component("b"), _component("c")],
            relationships=[],
        )
        assert verdict.violations == ()


class TestRelationshipEndpointRule:
    def test_unresolved_source_reported_with_its_own_locator(self) -> None:
        """Kills a target-only check (source and target must be checked apart)."""
        verdict = evaluate_design_integrity(
            components=[_component("ingest")],
            relationships=[_relationship("ghost", "ingest")],
        )
        assert _paths(verdict) == [
            (DIV_UNRESOLVED_RELATIONSHIP_ENDPOINT, "relationships[0].source")
        ]
        assert "ghost" in verdict.violations[0].message

    def test_unresolved_target_reported_with_its_own_locator(self) -> None:
        """Kills a source-only check and source/target label swaps."""
        verdict = evaluate_design_integrity(
            components=[_component("ingest")],
            relationships=[_relationship("ingest", "ghost")],
        )
        assert _paths(verdict) == [
            (DIV_UNRESOLVED_RELATIONSHIP_ENDPOINT, "relationships[0].target")
        ]
        assert "ghost" in verdict.violations[0].message

    def test_second_relationship_reports_its_own_index(self) -> None:
        """Kills first-element-only scans (the locator must follow the item)."""
        verdict = evaluate_design_integrity(
            components=[_component("ingest")],
            relationships=[
                _relationship("ingest", "ingest"),
                _relationship("ingest", "ghost"),
            ],
        )
        assert _paths(verdict) == [
            (DIV_UNRESOLVED_RELATIONSHIP_ENDPOINT, "relationships[1].target")
        ]

    def test_both_endpoints_unresolved_report_two_violations(self) -> None:
        verdict = evaluate_design_integrity(
            components=[_component("ingest")],
            relationships=[_relationship("ghost", "phantom")],
        )
        assert _paths(verdict) == [
            (DIV_UNRESOLVED_RELATIONSHIP_ENDPOINT, "relationships[0].source"),
            (DIV_UNRESOLVED_RELATIONSHIP_ENDPOINT, "relationships[0].target"),
        ]

    def test_no_components_means_every_endpoint_is_dangling(self) -> None:
        verdict = evaluate_design_integrity(
            components=[],
            relationships=[_relationship("ingest", "worker")],
        )
        assert _paths(verdict) == [
            (DIV_UNRESOLVED_RELATIONSHIP_ENDPOINT, "relationships[0].source"),
            (DIV_UNRESOLVED_RELATIONSHIP_ENDPOINT, "relationships[0].target"),
        ]


class TestEventReferenceRule:
    def test_unresolved_producer_reported(self) -> None:
        verdict = evaluate_design_integrity(
            components=[_component("ingest")],
            relationships=[],
            event_contracts=[_event("job.done", "ghost", ["ingest"])],
        )
        assert _paths(verdict) == [
            (DIV_UNRESOLVED_EVENT_REFERENCE, "event_contracts[0].published_by")
        ]
        assert verdict.violations[0].message == (
            "event 'job.done' has unresolved producer 'ghost'"
        )

    def test_missing_consumer_reported(self) -> None:
        """Kills the dropped ``not event.consumed_by`` check."""
        verdict = evaluate_design_integrity(
            components=[_component("worker")],
            relationships=[],
            event_contracts=[_event("job.done", "worker", [])],
        )
        assert _paths(verdict) == [
            (DIV_UNRESOLVED_EVENT_REFERENCE, "event_contracts[0].consumed_by")
        ]
        assert verdict.violations[0].message == "event 'job.done' has no consumer"

    def test_unresolved_consumer_reports_its_list_index(self) -> None:
        """Kills first-consumer-only scans and consumer-index arithmetic mutants."""
        verdict = evaluate_design_integrity(
            components=[_component("ingest")],
            relationships=[],
            event_contracts=[_event("job.done", "ingest", ["ingest", "ghost"])],
        )
        assert _paths(verdict) == [
            (DIV_UNRESOLVED_EVENT_REFERENCE, "event_contracts[0].consumed_by[1]")
        ]
        assert verdict.violations[0].message == (
            "event 'job.done' has unresolved consumer 'ghost'"
        )

    def test_all_event_defects_reported_together(self) -> None:
        verdict = evaluate_design_integrity(
            components=[_component("ingest")],
            relationships=[],
            event_contracts=[
                _event("job.done", "ghost", []),
                _event("job.failed", "ingest", ["phantom"]),
            ],
        )
        assert _paths(verdict) == [
            (DIV_UNRESOLVED_EVENT_REFERENCE, "event_contracts[0].consumed_by"),
            (DIV_UNRESOLVED_EVENT_REFERENCE, "event_contracts[0].published_by"),
            (DIV_UNRESOLVED_EVENT_REFERENCE, "event_contracts[1].consumed_by[0]"),
        ]

    def test_producer_may_consume_its_own_event(self) -> None:
        """Boundary: a self-consuming event is resolvable, not a violation."""
        verdict = evaluate_design_integrity(
            components=[_component("worker")],
            relationships=[],
            event_contracts=[_event("job.done", "worker", ["worker"])],
        )
        assert verdict.violations == ()


class TestApiContractReferenceRule:
    def test_unresolved_contract_component_reported(self) -> None:
        verdict = evaluate_design_integrity(
            components=[_component("ingest")],
            relationships=[],
            api_contracts=[_api_contract("ghost")],
        )
        assert _paths(verdict) == [
            (DIV_UNRESOLVED_API_CONTRACT_REFERENCE, "api_contracts[0].component_id")
        ]
        assert verdict.violations[0].message == (
            "api contract for unresolved component 'ghost'"
        )

    def test_second_contract_reports_its_own_index(self) -> None:
        verdict = evaluate_design_integrity(
            components=[_component("ingest")],
            relationships=[],
            api_contracts=[_api_contract("ingest"), _api_contract("ghost")],
        )
        assert _paths(verdict) == [
            (DIV_UNRESOLVED_API_CONTRACT_REFERENCE, "api_contracts[1].component_id")
        ]

    def test_resolved_contract_produces_no_violation(self) -> None:
        verdict = evaluate_design_integrity(
            components=[_component("ingest")],
            relationships=[],
            api_contracts=[_api_contract("ingest")],
        )
        assert verdict.violations == ()


class TestViolationOrdering:
    def test_paths_sort_lexicographically_not_by_insertion_index(self) -> None:
        """Kills a dropped or replaced sort: index 10 sorts before index 2 as a
        path string, so a stable-in-insertion-order result fails this pin."""
        relationships = [_relationship("a", "b") for _ in range(12)]
        relationships[2] = _relationship("a", "ghost-two")
        relationships[10] = _relationship("a", "ghost-ten")
        verdict = evaluate_design_integrity(
            components=[_component("a"), _component("b")],
            relationships=relationships,
        )
        assert _paths(verdict) == [
            (DIV_UNRESOLVED_RELATIONSHIP_ENDPOINT, "relationships[10].target"),
            (DIV_UNRESOLVED_RELATIONSHIP_ENDPOINT, "relationships[2].target"),
        ]

    def test_rules_group_before_paths(self) -> None:
        """Kills a re-keyed sort: path-first order would put the api_contracts
        entry before the components entry; the contract is rule-first."""
        verdict = evaluate_design_integrity(
            components=[_component("a"), _component("a")],
            relationships=[_relationship("a", "ghost")],
            api_contracts=[_api_contract("phantom")],
            event_contracts=[_event("job.done", "a", [])],
        )
        assert _paths(verdict) == [
            (DIV_DUPLICATE_COMPONENT_ID, "components[1].id"),
            (DIV_UNRESOLVED_RELATIONSHIP_ENDPOINT, "relationships[0].target"),
            (DIV_UNRESOLVED_EVENT_REFERENCE, "event_contracts[0].consumed_by"),
            (DIV_UNRESOLVED_API_CONTRACT_REFERENCE, "api_contracts[0].component_id"),
        ]


class TestRenderers:
    def test_violation_render_joins_rule_path_and_message(self) -> None:
        violation = IntegrityViolation(
            rule_id="DIV-3",
            path="relationships[3].target",
            message="unresolved component id 'ghost'",
        )
        assert render_integrity_violation(violation) == (
            "DIV-3: relationships[3].target: unresolved component id 'ghost'"
        )

    def test_error_header_counts_violations_and_lists_each_line(self) -> None:
        verdict = DesignIntegrityVerdict(
            violations=(
                IntegrityViolation(
                    rule_id="DIV-3",
                    path="relationships[0].source",
                    message="unresolved component id 'ghost'",
                ),
                IntegrityViolation(
                    rule_id="DIV-4",
                    path="event_contracts[0].consumed_by",
                    message="event 'job.done' has no consumer",
                ),
            )
        )
        assert format_integrity_error(verdict) == (
            "Design cross-reference integrity failed: 2 violation(s)\n"
            "DIV-3: relationships[0].source: unresolved component id 'ghost'\n"
            "DIV-4: event_contracts[0].consumed_by: event 'job.done' has no consumer"
        )

    def test_empty_verdict_renders_header_only(self) -> None:
        """Kills trailing-newline and phantom-line mutants."""
        assert format_integrity_error(DesignIntegrityVerdict(violations=())) == (
            "Design cross-reference integrity failed: 0 violation(s)"
        )
