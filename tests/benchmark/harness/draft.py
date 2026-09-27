"""LLM-assisted corpus drafting from the catalog (expansion is user-gated).

Produces **candidate** scenarios for a ``full.json`` corpus by asking the configured generator
for one scenario per family group, grounded in the real catalog records of that family. The
output is a draft under ``data/benchmark-runs/drafts/`` — it is *never* committed: the
workflow requires the user to review the labels before they join
``tests/benchmark/scenarios/full.json`` (expert-reviewed labels are the whole point of the
corpus).

The family unit in this repository is the pattern ``category`` (as in the seed corpus):
every catalog record of one ``PatternCategory`` forms one drafting family, and the
train/holdout split is assigned category-disjoint (categories sorted, last third → holdout),
never by the model.

Every candidate is repaired and re-validated deterministically before it is written:

- pattern names must resolve to ``pattern/<name>-architecture.json`` records (unresolvable
  names are dropped);
- ``primary`` is forced into ``acceptable_primary``; at least two distinct acceptable
  primaries within the family category are required, else the candidate is dropped;
- weights stay unset (the reviewer decides the weighting profile).

``--dry-run`` prints the prompt for the first family and writes nothing, so the tooling is
verifiable without a key or a provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.agent import SoftwareArchitectAgent
from src.patterns.loader import PatternLoader

from . import config as cfg

DEFAULT_DRAFT_OUT = cfg.DEFAULT_OUT_DIR / "drafts" / "full.draft.json"

#: Characters of catalog text per grounding record (keeps the prompt bounded).
_GROUNDING_CHARS = 420


class DraftExpected(BaseModel):
    """The label block the model must produce."""

    primary: str = Field(default="", description="Expected primary pattern name (catalog record name).")
    acceptable_primary: list[str] = Field(
        default_factory=list, description="All acceptable primary names (same category)."
    )


class DraftScenario(BaseModel):
    """One drafted scenario (before deterministic repair)."""

    scenario_id: str = Field(default="", description="Stable kebab-case id.")
    domain: str = Field(
        default="",
        description="Target architecture domain, verbatim from the primary record's suitable_domains.",
    )
    description: str = Field(default="", description="The request text; never names the pattern.")
    expected: DraftExpected = Field(default_factory=DraftExpected)
    notes: str | None = Field(default=None, description="Why these labels (for the reviewer).")


class DraftScenarioList(BaseModel):
    """The structured response of one drafting call."""

    scenarios: list[DraftScenario] = Field(default_factory=list)


@dataclass
class Family:
    """One catalog family (all records of one ``PatternCategory``)."""

    category: str
    names: list[str] = field(default_factory=list)


def family_index(catalog: PatternLoader) -> list[Family]:
    """Catalog records grouped by ``category``, in catalog load order."""
    families: dict[str, Family] = {}
    for record in catalog.load_all():
        family = families.setdefault(str(record["category"]), Family(category=str(record["category"])))
        family.names.append(str(record["name"]))
    return sorted(families.values(), key=lambda family: family.category)


SYSTEM_PROMPT = (
    "You author evaluation scenarios for an architecture-pattern selection benchmark. "
    "You write realistic engineering requests: named components, responsibilities, cross-component "
    "flows and concrete constraints. You never name, hint at or paraphrase the catalog pattern you "
    "label as the expected answer — the description must be answerable only by reasoning about the "
    "decision, not by string matching. You deliver the scenarios by calling the DraftScenarioList "
    "function: its parameters ARE the response schema. Do not print the JSON in your reply text."
)


def build_user_prompt(family: Family, grounding: list[dict[str, str]], per_family: int) -> str:
    """The user prompt for one family (also printed by ``--dry-run``)."""
    lines = [
        f"Family (catalog category): {family.category}",
        f"Write {per_family} distinct scenarios about decisions inside this family.",
        "",
        "Catalog records in this family (ground the request in the *problem*, never in the name):",
    ]
    for record in grounding:
        lines += [f"- name: {record['name']}", f"  context: {record['context']}"]
        if record.get("domains"):
            lines.append(f"  domains: {record['domains']}")
        if record.get("use_cases"):
            lines.append(f"  use cases: {record['use_cases']}")
        if record.get("avoid_when"):
            lines.append(f"  avoid when: {record['avoid_when']}")
    lines += [
        "",
        "Rules for every scenario:",
        "- description: 600-1500 characters, plain ASCII, a concrete system with named components and",
        "  constraints; mention no pattern name, no pattern alias, and no book author.",
        "- domain: one value from the primary record's `domains:` list, verbatim kebab-case; live",
        "  retrieval is keyed on this string, so never invent one. Prefer a value that is also listed",
        "  for an acceptable_primary sibling, so both labels compete for the same domain.",
        "- expected.primary: the single best catalog name from the grounding list above.",
        "- expected.acceptable_primary: primary plus at least one sibling name from the SAME family",
        "  (near misses a reviewer could also accept); at least 2 names.",
        "- scenario_id: a short kebab-case id prefixed with the family topic.",
        "- notes: one sentence explaining to a reviewer why these labels fit.",
        "",
        "Deliver every scenario through the DraftScenarioList function call — its parameters ARE",
        "the response schema (scenarios: [{scenario_id, domain, description, expected: {primary,",
        "acceptable_primary}, notes}, ...]). Do not print the JSON in your reply text.",
    ]
    return "\n".join(lines)


def _grounding_records(family: Family, catalog: PatternLoader) -> list[dict[str, str]]:
    """Compact catalog text for the family's records (bounded per record)."""
    by_name = {str(record["name"]): record for record in catalog.load_all()}
    records: list[dict[str, str]] = []
    for name in family.names:
        record = by_name[name]
        records.append(
            {
                "name": name,
                "context": str(record.get("context", ""))[:_GROUNDING_CHARS],
                "domains": ", ".join(str(domain) for domain in record.get("suitable_domains", [])[:8])[:_GROUNDING_CHARS],
                "use_cases": "; ".join(str(item) for item in record.get("use_cases", [])[:3])[:_GROUNDING_CHARS],
                "avoid_when": "; ".join(str(item) for item in record.get("avoid_when", [])[:2])[:200],
            }
        )
    return records


def assign_split(family_position: int, family_count: int) -> str:
    """Category-disjoint split: the last third of the (sorted) families becomes holdout."""
    if family_count >= 3:
        holdout_from = family_count - max(1, family_count // 3)
        return "holdout" if family_position >= holdout_from else "train"
    return "train"


def repair_scenario(
    draft: DraftScenario, *, family: Family, catalog: PatternLoader, split: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """Deterministically repair one drafted scenario; return (record, rejection reasons)."""
    reasons: list[str] = []
    by_name = {str(record["name"]): record for record in catalog.load_all()}
    primary = draft.expected.primary.strip()
    if primary not in by_name:
        return None, [f"primary {primary!r} is not a catalog record"]
    acceptable: list[str] = []
    for raw_name in [primary, *draft.expected.acceptable_primary]:
        candidate_name = raw_name.strip()
        if candidate_name in by_name and candidate_name not in acceptable:
            acceptable.append(candidate_name)
    if len(acceptable) < 2:
        return None, ["fewer than two distinct acceptable primaries"]
    description = " ".join(draft.description.split())
    if len(description) < 40:
        return None, [f"description too short ({len(description)} chars)"]
    description = description[:10_000]
    primary_domains = [str(domain) for domain in by_name[primary].get("suitable_domains", [])]
    if not primary_domains:  # pragma: no cover - every catalogue record carries domains
        return None, [f"primary {primary!r} lists no suitable_domains to pin the scenario domain"]
    domain = _kebab(draft.domain)
    if domain not in primary_domains:
        sibling_domains = {
            str(sibling_domain)
            for sibling in acceptable[1:]
            for sibling_domain in by_name[sibling].get("suitable_domains", [])
        }
        shared = sorted(set(primary_domains) & sibling_domains)
        domain = shared[0] if shared else primary_domains[0]
        reasons.append(
            f"domain {draft.domain.strip()!r} is not a suitable_domain of {primary!r}; pinned to {domain!r} "
            f"({'shared with an acceptable sibling' if shared else 'first catalogue domain'})"
        )
    scenario_id = _kebab(draft.scenario_id) or f"{_kebab(family.category)}-draft"
    record = {
        "scenario_id": scenario_id,
        "family": family.category,
        "category": family.category,
        "domain": domain,
        "split": split,
        "description": description,
        "expected": {"primary": primary, "acceptable_primary": acceptable},
        "notes": (draft.notes or "").strip()[:1000] or "LLM draft — reviewer must confirm the labels",
    }
    return record, reasons


def _kebab(text: str) -> str:
    """Lowercase kebab-case token (schema-compatible scenario/family ids)."""
    cleaned = "".join(character if character.isalnum() else "-" for character in text.strip().lower())
    parts = [part for part in cleaned.split("-") if part]
    return "-".join(parts)[:80]


def _run_structured(agent: SoftwareArchitectAgent, user_prompt: str) -> DraftScenarioList:
    """One structured drafting call against the production agent."""

    async def _call() -> DraftScenarioList:
        return await agent.generate_structured(SYSTEM_PROMPT, user_prompt, DraftScenarioList)

    return asyncio.run(_call())


def build_parser() -> argparse.ArgumentParser:
    """CLI of the drafting tool."""
    parser = argparse.ArgumentParser(
        prog="tests.benchmark.harness.draft",
        description="Draft full.json scenario candidates from catalog records (output needs user review).",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_DRAFT_OUT, help="draft corpus path")
    parser.add_argument("--per-family", type=int, default=2, help="scenarios requested per family (2-3)")
    parser.add_argument("--families", default=None, help="only families whose category contains this substring")
    parser.add_argument("--limit-families", type=int, default=None, help="stop after N families")
    parser.add_argument("--dry-run", action="store_true", help="print the first prompt and exit (no LLM call)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: draft candidate scenarios and write the review file."""
    args = build_parser().parse_args(argv)
    config = cfg.load_server_config("live")
    catalog = cfg.load_repo_catalog(config)
    families = family_index(catalog)
    if args.families:
        families = [family for family in families if args.families.lower() in family.category.lower()]
    if args.limit_families is not None:
        families = families[: args.limit_families]
    if not families:
        print("no families selected", file=sys.stderr)
        return 2
    if args.dry_run:
        family = families[0]
        print(f"# families: {len(families)} (first: {family.category})", file=sys.stderr)
        print(SYSTEM_PROMPT)
        print()
        print(build_user_prompt(family, _grounding_records(family, catalog), max(2, min(3, args.per_family))))
        return 0

    agent = SoftwareArchitectAgent(config)
    records: list[dict[str, Any]] = []
    rejected: list[str] = []
    for position, family in enumerate(families):
        split = assign_split(position, len(families))
        prompt = build_user_prompt(family, _grounding_records(family, catalog), max(2, min(3, args.per_family)))
        try:
            answer = _run_structured(agent, prompt)
        except Exception as exc:  # noqa: BLE001 - a failed family must not abort the whole draft
            rejected.append(f"{family.category}: drafting call failed ({type(exc).__name__}: {exc})")
            continue
        for draft in answer.scenarios:
            record, reasons = repair_scenario(draft, family=family, catalog=catalog, split=split)
            if record is None:
                rejected.append(f"{family.category}: {reasons[0]}")
                continue
            records.append(record)
            for reason in reasons:
                rejected.append(f"{family.category}: {reason}")

    payload = {
        "_meta": {
            "corpus": "full.draft",
            "harness_version": cfg.HARNESS_VERSION,
            "generator": config.generator.config.model,
            "families": len(families),
            "per_family": args.per_family,
            "generated_at": cfg.utc_now_iso(),
            "workflow": (
                "review the labels, then copy the reviewed scenarios into "
                "tests/benchmark/scenarios/full.json (the draft file lives under data/ and is never committed)"
            ),
            "rejections": rejected,
        },
        "scenarios": records,
    }
    cfg.write_json(args.out, payload)
    print(
        json.dumps(
            {
                "out": str(args.out),
                "drafted": len(records),
                "rejected": len(rejected),
                "families": len(families),
                "splits": {
                    split: sum(1 for record in records if record["split"] == split)
                    for split in ("train", "holdout")
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
