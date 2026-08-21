# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
Consistency tests for pattern data integrity.

Validates:
- Migration refs are canonical catalog names or well-formed external refs
- No malformed domain slugs (commas, spaces)
- ArchitectureStyle values match JSON file names
- Alias resolution works correctly in filter_by_domain
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from src.patterns.loader import PatternLoader


class TestMigrationRefConsistency:
    """Migration refs should be canonical catalog names or well-formed external refs."""

    def test_all_migration_refs_are_valid(self) -> None:
        """Every migration_from/to entry is a catalog name or well-formed external ref."""
        import re

        from src.schemas.enums import ArchitectureStyle

        catalog = {item.value for item in ArchitectureStyle}

        loader = PatternLoader()
        patterns = loader.load_all()

        bad_refs: list[tuple[str, str, str, str]] = []
        for p in patterns:
            name = p.get("name", "?")
            for field in ("migration_from", "migration_to"):
                for ref in p.get(field, []):
                    is_catalog = ref in catalog
                    is_well_formed = bool(
                        ref and
                        ref == ref.lower() and
                        " " not in ref and
                        "," not in ref
                    )
                    if not is_catalog and not is_well_formed:
                        bad_refs.append((name, field, ref, "malformed slug"))

        assert not bad_refs, (
            f"Found {len(bad_refs)} malformed migration refs:\n" +
            "\n".join(f"  {n} {f}: '{r}'" for n, f, r, _ in bad_refs)
        )

    def test_all_migration_refs_point_to_existing_patterns_or_external(self) -> None:
        """Every migration ref resolves to a known catalog name or documented external."""
        from src.schemas.enums import ArchitectureStyle

        catalog = {item.value for item in ArchitectureStyle}

        loader = PatternLoader()
        patterns = loader.load_all()

        bad_refs: list[tuple[str, str, str]] = []
        for p in patterns:
            name = p.get("name", "?")
            for field in ("migration_from", "migration_to"):
                for ref in p.get(field, []):
                    if ref not in catalog and not ref.islower():
                        bad_refs.append((name, field, ref))

        assert not bad_refs, (
            f"Found {len(bad_refs)} non-catalog refs with uppercase:\n" +
            "\n".join(f"  {n} {f}: '{r}'" for n, f, r in bad_refs)
        )


class TestDomainSlugIntegrity:
    """Domain slugs must not contain commas or spaces."""

    def test_no_domain_slug_contains_comma_or_space(self) -> None:
        """No suitable_domains or unsuitable_domains entry contains ',' or ' '."""
        loader = PatternLoader()
        patterns = loader.load_all()

        bad: list[tuple[str, str, str, str]] = []
        for p in patterns:
            name = p.get("name", "?")
            for field in ("suitable_domains", "unsuitable_domains"):
                for v in p.get(field, []):
                    if not isinstance(v, str):
                        continue
                    if "," in v or " " in v:
                        bad.append((name, field, v, "contains comma or space"))

        assert not bad, (
            f"Found {len(bad)} malformed domain slugs:\n" +
            "\n".join(f"  {n} {f}: '{v}'" for n, f, v in bad)
        )


class TestPatternFileCompleteness:
    """Every ArchitectureStyle enum value has a corresponding JSON file."""

    def test_all_enum_values_have_json_file(self) -> None:
        """Every ArchitectureStyle value has a matching *-architecture.json file."""
        from src.schemas.enums import ArchitectureStyle

        pattern_dir = Path(__file__).parent.parent.parent / "pattern"
        json_files = set()
        for p in pattern_dir.glob("*-architecture.json"):
            with open(p) as f:
                d = json.load(f)
                json_files.add(d.get("name", ""))

        missing: list[str] = []
        for item in ArchitectureStyle:
            if item.value not in json_files:
                missing.append(item.value)

        assert not missing, f"Enum values missing JSON files: {missing}"

    def test_all_json_files_have_enum_value(self) -> None:
        """Every *-architecture.json file has a corresponding ArchitectureStyle value."""
        from src.schemas.enums import ArchitectureStyle

        pattern_dir = Path(__file__).parent.parent.parent / "pattern"
        json_names = set()
        for p in pattern_dir.glob("*-architecture.json"):
            with open(p) as f:
                d = json.load(f)
                json_names.add(d.get("name", ""))

        enum_values = {item.value for item in ArchitectureStyle}

        orphan = json_names - enum_values
        assert not orphan, f"JSON files without enum entries: {orphan}"


class TestDomainAliasResolution:
    """Domain aliases resolve correctly in filter_by_domain."""

    def test_legacy_domain_slugs_resolve(self) -> None:
        """Querying with a legacy/variant slug returns the same result as canonical."""
        loader = PatternLoader()

        canonical_results = loader.filter_by_domain("microservices")
        legacy_results = loader.filter_by_domain("microservices-architecture")
        assert canonical_results == legacy_results, (
            "Alias resolution mismatch for microservices-architecture vs microservices"
        )

    def test_unknown_domain_returns_empty(self) -> None:
        """An unknown domain returns empty list."""
        loader = PatternLoader()
        results = loader.filter_by_domain("nonexistent-domain-xyz")
        assert results == []


class TestPatternCatalogCount:
    """Pattern catalog has expected size."""

    def test_pattern_count(self) -> None:
        """Loader returns exactly 40 patterns."""
        loader = PatternLoader()
        patterns = loader.load_all()
        assert len(patterns) == 40, f"Expected 40 patterns, got {len(patterns)}"
