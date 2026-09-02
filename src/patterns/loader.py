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
PatternLoader - Load, filter, and score architecture patterns.

FR-183: PatternLoader class for loading, filtering, scoring architecture patterns
FR-186: load_all method loads all pattern JSON files from pattern/
FR-189: filter_by_domain method filters patterns by domain suitability
FR-193: score_by_quality method scores patterns by alignment with quality priorities


Implementation Constraints:
- IC-31: Domain normalization (lowercase + replace spaces with hyphens)
- IC-32: Score formula: sum(quality_value * weight * 10), max 100
- IC-33: Default weights 0.2 per attribute (5 attributes total)

Error Handling:
- E-5: Pattern validation failed against Pattern schema (http_status: 400, severity: warn)
"""

import json
import logging
import re
from pathlib import Path

from llama_index.core.readers.base import BaseReader
from llama_index.core.schema import Document

# Quality attribute names (6 keys — must be present in every pattern's
# quality_attributes dict; the scoring stage iterates over exactly this set).
QUALITY_ATTRIBUTES = [
    "performance",
    "scalability",
    "reliability",
    "maintainability",
    "security",
    "simplicity",
]

# Domain alias map: legacy/variant slug -> canonical slug.
# Applied during filter_by_domain (query side) and load_all (data side) to ensure
# both old and new slugs resolve correctly. Canonical values live in ArchitectureDomain.
DOMAIN_ALIASES: dict[str, str] = {
    "cloud-native-applications": "cloud-native",
    "enterprise-applications": "enterprise",
    "enterprise-scale": "enterprise",
    "event-driven-architectures": "event-driven",
    "event-driven-systems": "event-driven",
    "financial-systems": "financial",
    "government-systems": "government",
    "high-traffic-systems": "high-traffic",
    "low-latency-requirements": "low-latency",
    "low-traffic-applications": "low-traffic",
    "messaging-systems": "messaging",
    "microservices-architecture": "microservices",
    "microservices-architectures": "microservices",
    "microservices-ready": "microservices",
    "microservices-scale": "microservices",
    "rule-based-systems": "rule-based-system",
    "simple-crud-applications": "simple-crud",
}


def _normalize_domain_slug(slug: str) -> str:
    """Normalize a domain slug: apply aliases, then lowercase + spaces-to-hyphens."""
    result = slug.lower()
    result = re.sub(r"\s+", "-", result)
    result = re.sub(r"-+", "-", result).strip("-")
    return DOMAIN_ALIASES.get(result, result)


def _validate_pattern(pattern_data: dict) -> bool:
    """
    Validate pattern against required schema.

    E-5: Pattern validation failed against Pattern schema
         (http_status: 400, severity: warn, logging_context: pattern_file)

    Required fields:
    - name: str
    - context: str (also required by Pydantic Pattern.model_validate)
    - category: str (required by Pydantic Pattern.model_validate)
    - suitable_domains: List[str]
    - quality_attributes: Dict[str, float] with all 6 keys present

    Returns:
        True if valid, False otherwise
    """
    required_fields = [
        "name",
        "context",
        "category",
        "suitable_domains",
        "quality_attributes",
    ]

    for field in required_fields:
        if field not in pattern_data:
            return False

    quality_attrs = pattern_data.get("quality_attributes", {})
    for attr in QUALITY_ATTRIBUTES:
        if attr not in quality_attrs:
            return False

    return True


class PatternJSONReader(BaseReader):
    """LlamaIndex BaseReader for ``*-architecture.json`` pattern files.

    Parses one pattern file per ``load_data`` call, validates it against
    the required schema (E-5 warning on failure), and returns a single
    Document whose text is the canonical JSON dump and whose metadata
    carries the source file path.  PatternLoader consumes the Document's
    text so its in-memory cache keeps the plain-dict shape the rest of
    the system expects.
    """

    def load_data(
        self, file: Path, extra_info: dict | None = None
    ) -> list[Document]:
        path = Path(file)
        extra = {"pattern_file": str(path)}
        try:
            with open(path, encoding="utf-8") as f:
                pattern_data = json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from {path}: {e}", extra=extra)
            return []
        except Exception as e:
            logger.warning(f"Error loading pattern {path}: {e}", extra=extra)
            return []

        if not _validate_pattern(pattern_data):
            # E-5: Pattern validation failed against Pattern schema
            logger.warning(f"Pattern validation failed: {path}", extra=extra)
            return []

        return [
            Document(
                text=json.dumps(pattern_data, ensure_ascii=False),
                metadata=extra,
            )
        ]

logger = logging.getLogger(__name__)


class PatternLoader:
    """
    PatternLoader class for loading, filtering, and scoring architecture patterns.

    FR-183: The system SHALL provide a PatternLoader class that loads, filters, 
    and scores architecture patterns (depends on IC-32, IC-33)

    This class implements lazy loading with in-memory cache per ADR-2:
    "PatternLoader with lazy-loading JSON cache for pattern management"

    Attributes:
        _patterns_dir: Path to pattern/ directory
        _patterns_cache: In-memory cache of loaded patterns
        _loaded: Flag indicating if patterns have been loaded
    """

    def __init__(self, patterns_dir: str | Path | None = None) -> None:
        """
        Initialize PatternLoader.

        AC-183: Verify PatternLoader class exists, accepts optional patterns_dir parameter

        Args:
            patterns_dir: Optional path to patterns directory.
                         Defaults to pattern/ relative to project root (not docs/pattern/).
        """
        if patterns_dir is None:
            _resolved: str | Path = Path(__file__).parent.parent.parent / "pattern"
        else:
            _resolved = patterns_dir
        self._patterns_dir = Path(_resolved)
        self._patterns_cache: list[dict] = []
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        """True once load_all() has populated the in-memory cache."""
        return self._loaded

    def load_all(self) -> list[dict]:
        """
        Load all pattern JSON files from pattern/.

        FR-186: The system SHALL provide a load_all method that loads all pattern JSON files
        AC-186: Verify load_all method exists, loads all JSON files
        SCEN-12: PatternLoader loads all *-architecture.json files

        Uses lazy loading - loads on first call, caches result for subsequent calls.
        Logs warning (E-5) for validation failures.

        Error Handling:
            E-5 (ERR_005): Pattern validation failed against Pattern schema
                          (http_status: 400, severity: warn)

        Returns:
            List of pattern dictionaries loaded from *-architecture.json files
        """
        # Lazy loading - return cached if already loaded
        if self._loaded:
            return self._patterns_cache

        patterns: list[dict] = []

        # Find all *-architecture.json files in patterns directory
        # SCEN-12: PatternLoader loads all *-architecture.json files
        # sorted() for deterministic load order across filesystems.
        if not self._patterns_dir.exists():
            logger.warning(
                f"Patterns directory does not exist: {self._patterns_dir}"
            )
            self._patterns_cache = patterns
            self._loaded = True
            return patterns

        reader = PatternJSONReader()
        for pattern_file in sorted(self._patterns_dir.glob("*-architecture.json")):
            for doc in reader.load_data(pattern_file):
                patterns.append(json.loads(doc.text))

        self._patterns_cache = patterns
        self._loaded = True
        logger.info(
            f"{len(self._patterns_cache)} architecture pattern(s) loaded",
            extra={"pattern_count": len(self._patterns_cache), "pattern_dir": str(self._patterns_dir)}
        )
        return self._patterns_cache

    def filter_by_domain(self, domain: str) -> list[dict]:
        """
        Filter patterns by domain suitability.

        FR-189: The system SHALL provide a filter_by_domain method that filters patterns
                by domain suitability
        AC-189: Verify filter_by_domain method exists, accepts domain string parameter
        SCEN-13: filter_by_domain normalizes domain

        IC-31: Domain normalization SHALL convert to lowercase and replace spaces with hyphens

        Domain normalization is performed as the FIRST step per ADR-6 implementation guidance:
        "Implement domain normalization as first step in filter_by_domain"

        A pattern is included if:
        - The normalized domain appears in its suitable_domains (or suitable_domains is empty), AND
        - The normalized domain does NOT appear in its unsuitable_domains

        Args:
            domain: Domain string to filter by

        Returns:
            Filtered list of patterns matching the domain criteria
        """
        normalized_domain = _normalize_domain_slug(domain)

        if not self._loaded:
            self.load_all()

        filtered = []
        for pattern in self._patterns_cache:
            suitable_domains = [_normalize_domain_slug(d) for d in pattern.get("suitable_domains", [])]
            unsuitable_domains = [_normalize_domain_slug(d) for d in pattern.get("unsuitable_domains", [])]

            if normalized_domain in unsuitable_domains:
                continue
            if suitable_domains and normalized_domain not in suitable_domains:
                continue

            filtered.append(pattern)

        return filtered

    def get_by_name(self, name: str) -> dict | None:
        """
        Look up a single pattern by its 'name' field.

        Used for fallback resolution when no patterns match a query.

        Args:
            name: The pattern name to look up.

        Returns:
            The pattern dict if found, otherwise None.
        """
        if not self._loaded:
            self.load_all()
        for pattern in self._patterns_cache:
            if pattern.get("name") == name:
                return pattern
        return None
