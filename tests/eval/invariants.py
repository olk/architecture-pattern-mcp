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
L9 structural invariants over LLM output (testing-strategies.md §3.9a).

The mechanizable T1.5 slice between "machinery fails on no input" (T1) and
"the design is good" (T2, unmechanizable): a generated design either is
well-formed and internally consistent or it is not — no semantic judgment
required. These invariants are REGRESSION oracles for the product: a prompt
edit, model swap, or pipeline change that silently drops section
completeness or breaks reference closure fails the corpus.

The boundary sentence (part of the layer's claim template): this layer
certifies WELL-FORMEDNESS and INTERNAL CONSISTENCY — never whether the
design is good. It is the cheap mechanical precursor to the FizzBee
design_meta experiment, not a substitute for T2 rubrics or human review.
"""

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PATTERN_DIR = REPO_ROOT / "pattern"

# Score ranges as declared by the schemas (src/schemas/evaluation.py,
# src/schemas/architecture.py). Keep in sync with the Field constraints.
SCORE_RANGE = (0.0, 100.0)


def catalogue_pattern_names() -> set[str]:
    """Pattern names the design may cite (from the pattern directory)."""
    names: set[str] = set()
    for path in PATTERN_DIR.glob("*-architecture.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "name" in data:
            names.add(str(data["name"]))
    return names


def check_invariants(design: dict[str, Any], pattern_names: set[str] | None = None) -> list[str]:
    """Run every structural invariant; returns the list of violations.

    A non-empty list means the LLM output drifted: the triggering change
    (prompt/model/pipeline) blocks until triaged (prompt bug vs corpus
    staleness). An empty list on a KNOWN-BAD design would mean the invariants
    are vacuous — the offline vacuity test guards that.
    """
    violations: list[str] = []
    names = catalogue_pattern_names() if pattern_names is None else pattern_names

    overview: dict[str, Any] = design.get("overview") or {}
    components: list[dict[str, Any]] = list(design.get("components") or [])
    relationships: list[dict[str, Any]] = list(design.get("relationships") or [])
    api_contracts: list[dict[str, Any]] = list(design.get("api_contracts") or [])
    events: list[dict[str, Any]] = list(design.get("event_contracts") or [])
    quality: dict[str, str] = design.get("quality_attributes") or {}

    component_ids = [str(c.get("id")) for c in components]

    # INV-1: section completeness — required sections present and non-empty.
    if not overview:
        violations.append("INV-1: overview section missing/empty")
    if not components:
        violations.append("INV-1: components section missing/empty")
    if not quality:
        violations.append("INV-1: quality_attributes section missing/empty")

    # INV-2: component ids unique and well-formed (dangling references would
    # otherwise be ambiguous).
    if len(component_ids) != len(set(component_ids)):
        violations.append("INV-2: duplicate component ids")

    # INV-3: every relationship endpoint resolves to a declared component.
    id_set = set(component_ids)
    for rel in relationships:
        for endpoint in ("source", "target"):
            node = str(rel.get(endpoint))
            if node not in id_set:
                violations.append(f"INV-3: relationship {endpoint}={node!r} unresolved")

    # INV-4: every event contract names a producer AND at least one consumer,
    # both declared components.
    for event in events:
        producer = str(event.get("published_by"))
        if producer not in id_set:
            violations.append(f"INV-4: event {event.get('event_name')!r} producer unresolved")
        consumers: list[Any] = list(event.get("consumed_by") or [])
        if not consumers:
            violations.append(f"INV-4: event {event.get('event_name')!r} has no consumer")
        for consumer in consumers:
            if str(consumer) not in id_set:
                violations.append(
                    f"INV-4: event {event.get('event_name')!r} consumer unresolved"
                )

    # INV-5: api_contract component references resolve; endpoints defined.
    contract_ids = {str(ac.get("component_id")) for ac in api_contracts}
    for contract_id in contract_ids:
        if contract_id not in id_set:
            violations.append(f"INV-5: api_contract for unresolved component {contract_id!r}")
    for component in components:
        contract = component.get("api_contract")
        if contract is not None:
            for endpoint in contract.get("endpoints") or []:
                if not endpoint.get("path"):
                    violations.append(
                        f"INV-5: endpoint of component {component.get('id')!r} has no path"
                    )

    # INV-6: cited pattern names exist in the catalogue (no hallucinated
    # patterns — the in-repo cousin of package slopsquatting).
    cited = overview.get("style")
    if cited is not None and str(cited) not in names and str(cited) != "":
        violations.append(f"INV-6: cited style/pattern {str(cited)!r} not in catalogue")

    # INV-7: score fields fall within their declared ranges.
    for label, score in (
        ("overview.score", overview.get("score")),
        ("final_quality_score", design.get("final_quality_score")),
    ):
        if score is not None and not (SCORE_RANGE[0] <= float(score) <= SCORE_RANGE[1]):
            violations.append(f"INV-7: {label}={score!r} outside {SCORE_RANGE}")

    return violations
