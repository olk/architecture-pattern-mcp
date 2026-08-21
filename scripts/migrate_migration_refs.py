#!/usr/bin/env python3
"""
Migrate pattern JSON files: normalize migration refs, fix typos.

Run from repo root:
    python scripts/migrate_migration_refs.py [--dry-run]

Philosophy:
- The stranger-fig-pattern typo gets fixed to strangler-fig.
- Known variant spellings get mapped to canonical ArchitectureStyle names.
- Complex prose refs that don't fit either category stay as external concepts
  (they're descriptive, not catalog references — e.g. "IPC (Inter-Process
  Communication) for flexible message passing").
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PATTERNS_DIR = Path(__file__).parent.parent / "pattern"

CATALOG_NAMES: set[str] = {
    "actor-based", "aiml-centric", "api-gateway", "backend-for-frontend",
    "blackboard", "blockchain-based", "broker",
    "command-query-responsibility-segregation", "data-mesh", "edge-computing",
    "enterprise-service-bus", "event-driven", "event-sourcing",
    "half-sync-half-async", "hexagonal", "hybrid-cloud", "kappa-architecture",
    "lambda-architecture", "layered-monolith", "microkernel-plugin",
    "microservices", "model-view-controller", "modular-monolith", "monolithic",
    "multi-cloud", "pipe-and-filter", "presentation-abstraction-control",
    "reactive-architecture", "reflection-architecture", "rule-based-system",
    "saga", "serverless", "service-mesh", "service-oriented-architecture",
    "space-based", "task-control-architecture",
    # Phase 4 additions:
    "strangler-fig", "clean-architecture", "client-server", "master-slave",
}

# Explicit known mappings: malformed/variant → canonical name
CANONICAL_NAME_MAP: dict[str, str] = {
    # Strangler fig typo
    "stranger-fig-pattern": "strangler-fig",
    # Monolith variants
    "monolith": "monolithic",
    # Layered variants
    "layered-architecture": "layered-monolith",
    # Event-driven variants
    "event-driven-architecture": "event-driven",
    "event-driven-architectures": "event-driven",
    "event-driven-systems": "event-driven",
    "event-driven microservices": "event-driven",
    "Event-driven microservices": "event-driven",
    # CQRS variants
    "cqrs": "command-query-responsibility-segregation",
    "CQRS": "command-query-responsibility-segregation",
    # Microservices variants
    "microservices-architecture": "microservices",
    "microservices-architectures": "microservices",
    # Actor variants
    "actor-model": "actor-based",
    "actor-model-architecture": "actor-based",
    # Event sourcing variants
    "Event Sourcing": "event-sourcing",
    "event_streaming": "event-sourcing",
    "event_store_clustering": "event-sourcing",
    # Service mesh
    "service-mesh-architecture": "service-mesh",
    # Hybrid/multi-cloud
    "hybrid-multi-cloud": "multi-cloud",
    # Lambda
    "Lambda Architecture": "lambda-architecture",
    # Saga
    "saga_pattern": "saga",
    # GraphQL
    "graphql-federation": "graphql-federation",
}


def _strip_parenthetical(s: str) -> str:
    """Strip (explanation) suffix from a string, handling nested parens."""
    # Simple heuristic: if string ends with ")..." or has " (... )" at end,
    # strip the parenthetical. Avoids stripping mid-string parens.
    # Only strip when the entire string is "Something (Explanation)" pattern.
    s = s.strip()
    if s.endswith(")") and "(" in s:
        # Find the matching opening paren
        depth = 0
        for i in range(len(s) - 1, -1, -1):
            if s[i] == ")":
                depth += 1
            elif s[i] == "(":
                depth -= 1
                if depth == 0:
                    # This is the outermost opening paren
                    before = s[:i].strip()
                    if before:
                        return before
                    break
    return s


def normalize_ref(ref: str) -> str:
    """Normalize a migration ref."""
    original = ref.strip()

    # 1. Fix the stranger-fig typo directly
    if original == "stranger-fig-pattern":
        return "strangler-fig"

    # 2. Try explicit canonical map first (handles mixed-case keys like "CQRS")
    if original in CANONICAL_NAME_MAP:
        return CANONICAL_NAME_MAP[original]

    # 3. Strip parenthetical suffix and retry canonical map
    stripped = _strip_parenthetical(original)
    if stripped in CANONICAL_NAME_MAP:
        return CANONICAL_NAME_MAP[stripped]

    # 4. Normalize: lowercase, spaces to hyphens
    result = re.sub(r"\s+", "-", stripped.lower())
    result = re.sub(r"-+", "-", result).strip("-")

    # 5. Check catalog or canonical map
    if result in CATALOG_NAMES:
        return result
    if result in CANONICAL_NAME_MAP:
        return CANONICAL_NAME_MAP[result]

    return result


def migrate_file(path: Path, dry_run: bool = False) -> tuple[list[str], list[str]]:
    """Migrate one pattern JSON. Returns (changes, external_refs)."""
    changes = []
    external = []

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    for field in ("migration_from", "migration_to"):
        if field not in data or not isinstance(data[field], list):
            continue
        new_list = []
        for ref in data[field]:
            if not isinstance(ref, str):
                new_list.append(ref)
                continue
            normalized = normalize_ref(ref)
            new_list.append(normalized)
            if normalized != ref:
                changes.append(f"  {path.name} {field}: '{ref}' -> '{normalized}'")
            if normalized not in CATALOG_NAMES:
                external.append(f"  {path.name} {field}: '{ref}' -> '{normalized}' [external]")
        data[field] = new_list

    if not dry_run and changes:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    return changes, external


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dry_run = args.dry_run
    action = "Would apply" if dry_run else "Applying"

    files = sorted(PATTERNS_DIR.glob("*-architecture.json"))
    print(f"Found {len(files)} pattern files in {PATTERNS_DIR}\n")

    all_changes = []
    all_external = []

    for path in files:
        changes, external = migrate_file(path, dry_run=dry_run)
        for c in changes:
            print(c)
            all_changes.append(c)
        for e in external:
            all_external.append(e)

    print()
    print(f"{action} {len(all_changes)} migration ref changes.")
    print(f"{len(all_external)} refs became external (expected — non-pattern concepts).")


if __name__ == "__main__":
    main()
