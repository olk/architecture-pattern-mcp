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
Architecture pattern schema.

Defines the structure of a single architecture pattern (e.g. microservices, hexagonal).
"""

import logging
from typing import Any

from pydantic import BaseModel, Field, model_validator

from src.schemas.enums import ArchitectureDomain, ArchitectureStyle, PatternCategory

logger = logging.getLogger(__name__)

_WARNED_MIGRATION_REFS: set[str] = set()


class Pattern(BaseModel):
    """
    Architecture pattern definition.

    Describes a named architectural approach with its context, tradeoffs,
    quality attributes, and suitability domain mapping.

    Pattern JSON files in pattern/ are validated against this schema.
    """

    name: str = Field(
        ...,
        description="Architecture style name, e.g. 'microservices', 'hexagonal'"
    )
    context: str = Field(
        ...,
        description="When to use this pattern — problem context and forces"
    )
    category: PatternCategory = Field(
        ...,
        description="Pattern category from PatternCategory enum"
    )
    benefits: list[str] = Field(
        default_factory=list,
        description="Positive outcomes and advantages this pattern provides"
    )
    tradeoffs: list[str] = Field(
        default_factory=list,
        description="Concrete costs, risks, and disadvantages this pattern introduces"
    )
    quality_attributes: dict[str, float] = Field(
        default_factory=dict,
        description="Quality metric scores (0-10), e.g. {'scalability': 9, 'maintainability': 7}"
    )
    suitable_domains: list[ArchitectureDomain] = Field(
        default_factory=list,
        description="Problem-space domains where this pattern excels (§4.2.1)"
    )
    unsuitable_domains: list[ArchitectureDomain] = Field(
        default_factory=list,
        description="Problem-space domains where this pattern may not fit (§4.2.1)"
    )
    use_cases: list[str] = Field(
        default_factory=list,
        description="Concrete scenarios when to use this pattern"
    )
    avoid_when: list[str] = Field(
        default_factory=list,
        description="Concrete scenarios when to avoid this pattern"
    )
    component_types: list[str] = Field(
        default_factory=list,
        description="Component types typically needed"
    )
    technology_stack: list[str] = Field(
        default_factory=list,
        description="Typical technology choices"
    )
    anti_patterns: list[str] = Field(
        default_factory=list,
        description="Common mistakes with this pattern"
    )
    migration_from: list[str] = Field(
        default_factory=list,
        description="Patterns commonly migrated from"
    )
    migration_to: list[str] = Field(
        default_factory=list,
        description="Patterns commonly migrated to"
    )
    design_principles: list[str] = Field(
        default_factory=list,
        description="Core design principles (e.g. ['Single Responsibility: Each service does one thing well'])"
    )
    best_practices: list[str] = Field(
        default_factory=list,
        description="Best practices (e.g. ['Service Decomposition: Design services around business capabilities'])"
    )
    version: str | None = Field(
        default=None,
        description="Pattern catalog version, e.g. '1.0.14'"
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Reference sources (book chapters, articles, POSA patterns)"
    )

    @model_validator(mode="after")
    def _warn_on_external_migration_refs(self) -> "Pattern":
        """
        Warn (but don't fail) when migration refs look malformed.

        Warns for any ref that is:
        - not a canonical catalog name (ArchitectureStyle), AND
        - looks like a malformed slug (contains spaces, uppercase letters, or special chars)

        This catches typos and inconsistent formatting without maintaining a large allowlist.
        Well-formed hyphenated-lowercase external refs (e.g. 'big-ball-of-mud',
        'two-phase-commit') are silently allowed — they are intentional non-pattern
        descriptors.
        """
        import re

        catalog = {item.value for item in ArchitectureStyle}

        for field in ("migration_from", "migration_to"):
            values: list[str] = getattr(self, field, []) or []
            for ref in values:
                key = f"{field}:{ref}"
                if ref not in catalog and key not in _WARNED_MIGRATION_REFS:
                    # Malformed slug indicator: has spaces, uppercase, or commas
                    is_malformed = bool(
                        re.search(r"[\sA-Z,]", ref)
                    )
                    if is_malformed:
                        _WARNED_MIGRATION_REFS.add(key)
                        logger.warning(
                            f"Pattern '{self.name}' has {field} entry '{ref}' "
                            f"that is not a canonical catalog name and looks malformed "
                            f"(contains spaces, uppercase, or commas)."
                        )
        return self


class ScoredPattern(Pattern):
    """Pattern enriched with two-stage analyze scores (response boundary only).

    Used only in AnalysisResult.selected_patterns to preserve score metadata
    that the pipeline injects but the base Pattern catalogue-validator rejects.
    """

    analysis_score: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Requirements-aware score from two-stage analyze (0-100)",
    )
    fusion_score: float | None = Field(
        default=None,
        ge=0,
        description="Stage-1 hybrid fusion score (RRF, from recall)",
    )
    fusion_score_normalized: float | None = Field(
        default=None, ge=0, le=100,
        description="Stage-1 fusion score min-max-normalized to 0-100 within the recall set",
    )
    blended_score: float | None = Field(
        default=None, ge=0, le=100,
        description="Convex blend of analysis_score and fusion_score_normalized (selection key)",
    )
