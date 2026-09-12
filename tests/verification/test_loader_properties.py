# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
L2 oracles for the pattern-loader decision surfaces
(src/patterns/loader.py — mutmut-scoped round 2; previously L1-only).

  LD-1  domain-slug normalization is idempotent over arbitrary text.
  LD-2  normalized slugs satisfy the canonical form: lowercase, no
        whitespace, no leading/trailing/duplicated hyphens.
  LD-3  the alias map is closed: every value is a normalization fixed
        point, and every key normalizes to its value.
  LD-4  filter equivalence over the REAL catalogue: a case/whitespace
        mutation of a catalogue domain yields the identical result set
        (the entire point of query-side normalization).
  LD-5  unknown domains resolve to the empty list.
  LD-6  catalogue shape: every loaded pattern carries a name and the six
        quality-attribute keys (T5 family, real-data pin).

Vacuity (P2): LD-1/LD-2 kill regex-branch mutants in ``_normalize_domain_slug``;
LD-4 kills dropped-normalization mutants in ``filter_by_domain`` (the
query would silently miss mutated domains).
"""

from __future__ import annotations

import functools
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from src.patterns.loader import DOMAIN_ALIASES, PatternLoader, _normalize_domain_slug
from src.schemas.analysis import QUALITY_ATTRIBUTE_KEYS


class TestLD1NormalizationIdempotence:
    @given(slug=st.text(max_size=80))
    @settings(max_examples=50, deadline=None)
    def test_double_normalization_is_identity(self, slug: str) -> None:
        once = _normalize_domain_slug(slug)
        assert _normalize_domain_slug(once) == once


class TestLD2CanonicalForm:
    @given(slug=st.text(max_size=80))
    @settings(max_examples=50, deadline=None)
    def test_output_is_canonical(self, slug: str) -> None:
        normalized = _normalize_domain_slug(slug)
        assert normalized == normalized.lower()
        assert not any(ch.isspace() for ch in normalized)
        assert not normalized.startswith("-")
        assert not normalized.endswith("-")
        assert "--" not in normalized


class TestLD3AliasClosure:
    def test_alias_values_are_fixed_points(self) -> None:
        for key, canonical in DOMAIN_ALIASES.items():
            assert _normalize_domain_slug(canonical) == canonical, (
                f"alias value {canonical!r} is not a normalization fixed point"
            )
            assert _normalize_domain_slug(key) == canonical, (
                f"alias key {key!r} does not resolve to {canonical!r}"
            )


@st.composite
def _mutated_catalogue_domain(draw: st.DrawFn, domains: list[str]) -> str:
    """Case/whitespace corruption of a real catalogue domain."""
    slug = draw(st.sampled_from(domains))
    separator = draw(st.sampled_from([" ", "  ", "\t", " - "]))
    case_bits = draw(st.lists(st.booleans(), min_size=len(slug), max_size=len(slug) + 4))
    raw = separator.join(slug.split("-"))
    bits = (case_bits * 4)[: len(raw)]
    return "".join(
        c.upper() if b else c.lower()
        for c, b in zip(raw, bits, strict=len(raw) == len(bits))
    )


@functools.lru_cache(maxsize=1)
def _catalogue_domains() -> tuple[str, ...]:
    loader = _loaded_loader()
    domains: set[str] = set()
    for pattern in loader.load_all():
        for domain in pattern.get("suitable_domains", []):
            domains.add(_normalize_domain_slug(str(domain)))
    return tuple(sorted(domains))


@functools.lru_cache(maxsize=1)
def _loaded_loader() -> PatternLoader:
    loader = PatternLoader("pattern")
    loader.load_all()
    return loader


def _pick_original(corrupted: str) -> str:
    return _normalize_domain_slug(corrupted)


class TestLD4FilterEquivalenceOverRealCatalogue:
    @given(
        corrupted=_mutated_catalogue_domain(list(_catalogue_domains())),
    )
    @settings(max_examples=25, deadline=None)
    def test_mutated_domain_yields_identical_result_set(
        self, corrupted: str
    ) -> None:
        loader = _loaded_loader()
        original = _pick_original(corrupted)
        assert original in _catalogue_domains(), (
            "corrupted slug must normalize back into the catalogue pool"
        )
        assert loader.filter_by_domain(original) == loader.filter_by_domain(corrupted), (
            f"normalization broke equivalence: {corrupted!r} vs {original!r}"
        )


class TestLD5UnknownDomainEmpty:
    @given(
        unknown=st.from_regex(r"zzz-[a-z]{3,10}", fullmatch=True).filter(
            lambda s: s not in DOMAIN_ALIASES
        )
    )
    @settings(max_examples=15, deadline=None)
    def test_unknown_domain_resolves_empty(self, unknown: str) -> None:
        loader = _loaded_loader()
        assert loader.filter_by_domain(unknown) == []


class TestLD6CatalogueShape:
    def test_every_catalogue_pattern_has_required_keys(self) -> None:
        loader = _loaded_loader()
        patterns: list[dict[str, Any]] = loader.load_all()
        assert patterns, "catalogue must not be empty"
        for pattern in patterns:
            assert isinstance(pattern.get("name"), str) and pattern["name"]
            qa = pattern.get("quality_attributes", {})
            missing = set(QUALITY_ATTRIBUTE_KEYS) - set(qa)
            assert not missing, f"{pattern['name']}: missing QA keys {missing}"
