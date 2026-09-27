"""Harness configuration: server config load, scenario corpus load, run provenance.

Adapted from design-pattern-mcp-local ``tests/benchmark/harness/config.py``
(commit 25cbfba) and retargeted to this repository:

- ``CONFIG_PATH`` (not ``DESIGN_PATTERN_CONFIG_PATH``) selects the config file.
  Default is the repository ``config/config.json`` — never the legacy
  ``~/.config/architecture-pattern-mcp/config.json``, whose retrieval schema
  ``ServerConfig`` rejects.
- ``ConfigManager`` is bypassed on purpose: its class-level ``_config`` cache
  leaks state between arms in one process. The harness expands env
  placeholders itself (``src.config_expansion.expand_env_in_obj``) and
  validates directly.
- Scenario "family" is the ``PatternCategory`` of the primary label, so the
  train/holdout split is category-disjoint (whole categories move together).
- The catalog is ``PatternLoader`` over ``pattern/``: ``get_by_name`` /
  ``load_all`` replace A's ``catalog.records`` / ``catalog.enums``.

Secrets never enter a manifest: :func:`mask_secrets` strips every value behind
a key/token/secret/password/credential-shaped name, and
:func:`masked_env_snapshot` records only the environment this deployment reads
(``GENERATOR_*/EMBEDDER_*/RERANKER_*/RETRIEVAL_*/REASONING_*/VALIDATION_*/TASKS_*``
plus ``PATTERN_DIRECTORY`` and the provider API-key extras).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from jsonschema import Draft7Validator

from src.config import ServerConfig
from src.config_expansion import expand_env_in_obj
from src.patterns.loader import PatternLoader
from src.schemas.analysis import QUALITY_ATTRIBUTE_KEYS

#: Harness contract version — bump on any change to record/summary/manifest shapes.
HARNESS_VERSION = "0.1.0"

#: Repository root (``tests/benchmark/harness/config.py`` → three parents up).
REPO_ROOT = Path(__file__).resolve().parents[3]

BENCHMARK_DIR = REPO_ROOT / "tests" / "benchmark"
SCENARIOS_DIR = BENCHMARK_DIR / "scenarios"
DEFAULT_SCENARIOS = SCENARIOS_DIR / "seed.json"
SCENARIO_SCHEMA = SCENARIOS_DIR / "scenario.schema.json"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "benchmark-runs"

MODES: tuple[str, ...] = ("offline", "live", "e2e")
SPLITS: tuple[str, ...] = ("train", "holdout")

_SECRET_KEY_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)
_ENV_PREFIXES: tuple[str, ...] = (
    "GENERATOR_",
    "EMBEDDER_",
    "RERANKER_",
    "RETRIEVAL_",
    "REASONING_",
    "VALIDATION_",
    "TASKS_",
)
_ENV_EXTRA_KEYS: tuple[str, ...] = (
    "PATTERN_DIRECTORY",
    "CONFIG_PATH",
    "MINIMAXAI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)


def utc_now_iso() -> str:
    """Current UTC timestamp in ISO-8601 (seconds resolution)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


#: Third-party loggers that pin their own level at import (``bm25s`` calls
#: ``logging.getLogger("bm25s").setLevel(logging.DEBUG)`` in its ``__init__``) and are
#: imported *after* the harness configures logging, so a logger-level pin alone cannot hold
#: the configured level: the handler level below is the gate the import cannot reopen. The
#: logger pin is kept for records emitted before a handler sees them.
_NOISY_THIRD_PARTY_LOGGERS: tuple[str, ...] = ("bm25s",)

#: ``extra`` keys surfaced in the rendered line. The pipeline puts its diagnostics there
#: (e.g. ``ArchitectureDesign construction failed validation`` carries ``errors``); the
#: default format drops them, which leaves a self-healing live-arm retry undiagnosable.
_SURFACED_LOG_EXTRA_KEYS: tuple[str, ...] = ("phase", "attempt", "error", "errors")

#: Character budget per surfaced ``extra`` value (pydantic error dicts are verbose).
_SURFACED_VALUE_CHARS = 600


def _render_log_extra(value: object) -> str:
    """Compact one-line rendering of an ``extra`` value (truncated, never raises)."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= _SURFACED_VALUE_CHARS else text[: _SURFACED_VALUE_CHARS - 3] + "..."


class _DiagnosticsFilter(logging.Filter):
    """Append selected ``extra`` diagnostics to rendered warning-and-worse lines.

    Info lines carry ``phase`` routinely (the pipeline tags every phase log), so the filter
    only touches records at WARNING or above — the level at which the harness's default
    output stops saying anything unless the reason is in the message.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.WARNING:
            return True
        surfaced = [
            f"{key}={_render_log_extra(getattr(record, key))}"
            for key in _SURFACED_LOG_EXTRA_KEYS
            if hasattr(record, key)
        ]
        if surfaced:
            record.msg = f"{record.getMessage()} ({', '.join(surfaced)})"
            record.args = ()
        return True


def configure_logging(level: str) -> int:
    """Apply the harness log level to the root logger, its handlers and third-party noise.

    The level is enforced on the handlers as well: ``bm25s`` is imported lazily and re-pins
    its own logger to DEBUG at import time, which a logger-level pin applied here cannot
    prevent. A handler level is checked after the logger level, so it always holds.
    """
    resolved = getattr(logging, str(level).upper(), logging.WARNING)
    logging.basicConfig(
        level=resolved,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    diagnostics = _DiagnosticsFilter()
    for handler in logging.root.handlers:
        handler.setLevel(resolved)
        handler.addFilter(diagnostics)
    for name in _NOISY_THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(resolved)
    return resolved


def file_sha256(path: Path) -> str:
    """SHA-256 of a file's bytes (scenario-corpus and artifact pinning)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` as deterministic pretty JSON (UTF-8, trailing newline), creating dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object from ``path``."""
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def mask_secrets(value: Any) -> Any:
    """Recursively replace values behind secret-shaped keys with ``"***set***"``/``"***empty***"``.

    Any value type behind a secret-shaped key is masked (not only strings), so a
    non-string credential cannot slip into a manifest unmasked.
    """
    if isinstance(value, dict):
        return {
            key: (
                f"***{'set' if item else 'empty'}***"
                if _SECRET_KEY_RE.search(str(key)) and not isinstance(item, (dict, list))
                else mask_secrets(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_secrets(item) for item in value]
    return value


def masked_env_snapshot() -> dict[str, str]:
    """The deployment-relevant environment, secrets masked (drift attribution between arms)."""
    snapshot: dict[str, str] = {}
    for key in sorted(os.environ):
        if key.startswith(_ENV_PREFIXES) or key in _ENV_EXTRA_KEYS:
            value = os.environ[key]
            snapshot[key] = f"***{'set' if value else 'empty'}***" if _SECRET_KEY_RE.search(key) else value
    return snapshot


def _git(*args: str) -> str:
    """Run a read-only git command in the repository root; empty string when git fails."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


def git_snapshot() -> dict[str, Any]:
    """HEAD, dirty flag and a hash over the working-tree diff (replay provenance)."""
    status = _git("status", "--porcelain")
    diff = _git("diff", "HEAD")
    combined = (status + diff).encode("utf-8")
    return {
        "head": _git("rev-parse", "HEAD").strip() or None,
        "dirty": bool(status.strip()),
        "status_lines": status.splitlines()[:50],
        "worktree_sha256": hashlib.sha256(combined).hexdigest(),
    }


# --------------------------------------------------------------------------------------
# Server configuration
# --------------------------------------------------------------------------------------


def resolve_config_path() -> Path:
    """``CONFIG_PATH`` > repository ``config/config.json`` (never the legacy home default)."""
    configured = os.environ.get("CONFIG_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return REPO_ROOT / "config" / "config.json"


def load_server_config(mode: str) -> ServerConfig:
    """Load the effective ``ServerConfig`` for ``mode`` (env placeholders expanded).

    Only ``offline`` changes anything: it pins ``retrieval.min_fusion_score``
    to 0.0 so degenerate stub recall can never trip the relevance floor (the
    shipped default is already 0.0; the override exists for explicitness). Live
    and e2e run the shipped configuration unmodified. ``ConfigManager`` is
    deliberately bypassed — its class-level cache would leak configuration
    between arms sharing a process.
    """
    if mode not in MODES:
        raise ValueError(f"unknown benchmark mode {mode!r}; expected one of {MODES}")
    raw = expand_env_in_obj(json.loads(resolve_config_path().read_text(encoding="utf-8")))
    if mode == "offline":
        raw = dict(raw)
        raw["retrieval"] = {**raw.get("retrieval", {}), "min_fusion_score": 0.0}
    return ServerConfig.model_validate(raw)


def resolve_pattern_directory(config: ServerConfig) -> Path:
    """Catalog ``pattern`` directory, resolved against the repository root.

    The shipped config default (``~/.config/architecture-pattern-mcp/pattern``)
    predates the in-repo catalogue; benchmark runs always want the repository's
    ``pattern/`` directory, so that exact default is redirected instead of
    failing on a machine without an installed catalogue.
    """
    pattern_dir = Path(config.pattern_directory).expanduser()
    legacy_default = Path("~/.config/architecture-pattern-mcp/pattern").expanduser()
    if pattern_dir == legacy_default or not pattern_dir.exists():
        pattern_dir = REPO_ROOT / "pattern"
    return pattern_dir


def load_repo_catalog(config: ServerConfig) -> PatternLoader:
    """Load the repository catalog through the production loader."""
    return PatternLoader(resolve_pattern_directory(config))


# --------------------------------------------------------------------------------------
# Scenario corpus
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """One benchmark scenario: the request, its expert label and its split membership."""

    scenario_id: str
    family: str
    category: str
    domain: str
    split: str
    description: str
    weights: dict[str, float] | None
    style: str | None
    expected_primary: str
    acceptable_primary: tuple[str, ...]
    notes: str | None = None
    source_path: Path | None = None

    @property
    def primary(self) -> str:
        """The single expected (expert-chosen) primary pattern."""
        return self.expected_primary

    @property
    def acceptable(self) -> tuple[str, ...]:
        """Every acceptable label id (all share the primary's ``PatternCategory``)."""
        return self.acceptable_primary

    def record_identity(self) -> dict[str, Any]:
        """The label/identity block echoed into every run record (replay without the corpus)."""
        return {
            "scenario_id": self.scenario_id,
            "family": self.family,
            "category": self.category,
            "domain": self.domain,
            "split": self.split,
            "weights": self.weights,
            "style": self.style,
            "expected": {
                "primary": self.primary,
                "acceptable_primary": list(self.acceptable_primary),
            },
            "description": self.description,
            "notes": self.notes,
        }


@runtime_checkable
class _SchemaValidator(Protocol):
    """Structural view of a ``jsonschema`` validator (library ships no stubs)."""

    def iter_errors(self, instance: object) -> Iterator[Any]: ...


def _scenario_schema_validator() -> object:
    """Draft-07 validator over ``scenarios/scenario.schema.json``.

    ``jsonschema`` ships no type stubs, so the validator instance is typed as
    ``object`` and narrowed to the structural ``iter_errors`` protocol below
    (mypy-strict without plugins).
    """
    validator: _SchemaValidator = Draft7Validator(read_json(SCENARIO_SCHEMA))
    return validator


def load_scenarios(path: Path, catalog: PatternLoader | None = None) -> list[Scenario]:
    """Validate and load a scenario corpus; fails loudly on any label the catalog cannot resolve.

    Checks (plan §4/§5.7): schema conformance, unique ids, split coverage,
    catalog-resolvable pattern labels, ``primary ∈ acceptable_primary``, at
    least two acceptable primaries (near-miss discrimination) — and, when the
    catalog is supplied, that every label's ``PatternCategory`` equals the
    scenario ``category`` (the family definition in this repository) and that
    ``domain`` is one of the primary label's ``suitable_domains`` (live
    retrieval is keyed on that string; see :func:`_assert_labels_resolvable`).
    """
    payload = read_json(path)
    entries = payload.get("scenarios")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{path}: 'scenarios' must be a non-empty list")
    validator = _scenario_schema_validator()
    scenarios: list[Scenario] = []
    seen_ids: set[str] = set()
    assert isinstance(validator, _SchemaValidator)
    for index, entry in enumerate(entries):
        errors = sorted(validator.iter_errors(entry), key=lambda error: list(error.absolute_path))
        if errors:
            details = "; ".join(f"{'/'.join(str(part) for part in error.absolute_path)}: {error.message}" for error in errors)
            raise ValueError(f"{path}: scenario #{index} violates scenario.schema.json: {details}")
        scenario = _scenario_from_entry(entry, path)
        if scenario.scenario_id in seen_ids:
            raise ValueError(f"{path}: duplicate scenario_id {scenario.scenario_id!r}")
        seen_ids.add(scenario.scenario_id)
        scenarios.append(scenario)
    if catalog is not None:
        for scenario in scenarios:
            _assert_labels_resolvable(scenario, catalog)
        _assert_family_disjoint(scenarios)
    return scenarios


def _scenario_from_entry(entry: dict[str, Any], path: Path) -> Scenario:
    """Build a :class:`Scenario` from one schema-validated JSON object."""
    expected = entry["expected"]
    weights = entry.get("weights")
    return Scenario(
        scenario_id=entry["scenario_id"],
        family=entry["family"],
        category=entry["category"],
        domain=entry["domain"],
        split=entry["split"],
        description=entry["description"],
        weights=dict(weights) if weights is not None else None,
        style=entry.get("style"),
        expected_primary=expected["primary"],
        acceptable_primary=tuple(expected["acceptable_primary"]),
        notes=entry.get("notes"),
        source_path=path,
    )


def _assert_family_disjoint(scenarios: Sequence[Scenario]) -> None:
    """The train/holdout split must be category-disjoint (a family is a category here)."""
    split_of: dict[str, str] = {}
    conflicts: list[str] = []
    for scenario in scenarios:
        known = split_of.setdefault(scenario.family, scenario.split)
        if known != scenario.split:
            conflicts.append(f"{scenario.family!r} appears in both {known} and {scenario.split}")
    if conflicts:
        raise ValueError("scenario split is not family-disjoint: " + "; ".join(sorted(set(conflicts))))


def _assert_labels_resolvable(scenario: Scenario, catalog: PatternLoader) -> None:
    """Fail loudly when a label id has no ``pattern/<name>-architecture.json`` record."""
    unknown = [name for name in scenario.acceptable if catalog.get_by_name(name) is None]
    if unknown:
        raise ValueError(
            f"{scenario.source_path}: scenario {scenario.scenario_id!r} labels unresolvable in the catalog: {unknown}"
        )
    primary_record = catalog.get_by_name(scenario.primary)
    if primary_record is None:  # pragma: no cover - guarded by the unknown check above
        raise ValueError(f"{scenario.source_path}: scenario {scenario.scenario_id!r} primary unresolvable")
    if primary_record.get("category") != scenario.category:
        raise ValueError(
            f"{scenario.source_path}: scenario {scenario.scenario_id!r} category {scenario.category!r} is not the "
            f"PatternCategory of its primary {scenario.primary!r} ({primary_record.get('category')!r})"
        )
    suitable_domains = [str(domain) for domain in primary_record.get("suitable_domains", [])]
    if scenario.domain not in suitable_domains:
        raise ValueError(
            f"{scenario.source_path}: scenario {scenario.scenario_id!r} domain {scenario.domain!r} is not a "
            f"catalogue suitable_domain of its primary {scenario.primary!r} ({suitable_domains}). Live retrieval "
            "is keyed on the domain string, so the corpus must name a catalogue domain of the labelled pattern "
            "(and should share it with an acceptable sibling); see scenarios/seed.json _meta.domain_convention."
        )
    for name in scenario.acceptable:
        record = catalog.get_by_name(name)
        if record is not None and record.get("category") != scenario.category:
            raise ValueError(
                f"{scenario.source_path}: scenario {scenario.scenario_id!r} label {name!r} has category "
                f"{record.get('category')!r}, outside scenario category {scenario.category!r}"
            )
    if scenario.primary not in scenario.acceptable_primary:
        raise ValueError(
            f"{scenario.source_path}: scenario {scenario.scenario_id!r} primary {scenario.primary!r} "
            "is not listed in acceptable_primary"
        )
    if len(set(scenario.acceptable_primary)) < 2:
        raise ValueError(
            f"{scenario.source_path}: scenario {scenario.scenario_id!r} needs at least two distinct "
            "acceptable_primary ids (near-miss discrimination)"
        )
    if scenario.weights is not None:
        unknown_weights = sorted(set(scenario.weights) - set(QUALITY_ATTRIBUTE_KEYS))
        if unknown_weights:
            raise ValueError(
                f"{scenario.source_path}: scenario {scenario.scenario_id!r} has unknown weight keys {unknown_weights}"
            )


def select_scenarios(
    scenarios: list[Scenario], *, split: str, limit: int | None
) -> list[Scenario]:
    """Filter by ``split`` (``train``/``holdout``/``all``) preserving corpus order, then cut."""
    if split not in (*SPLITS, "all"):
        raise ValueError(f"unknown split {split!r}; expected one of {(*SPLITS, 'all')}")
    selected = [scenario for scenario in scenarios if split in ("all", scenario.split)]
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        selected = selected[:limit]
    return selected


@dataclass
class RunPaths:
    """Resolved run-directory layout (``data/benchmark-runs/<run-id>/``)."""

    root: Path
    manifest: Path
    summary: Path
    report: Path
    scenarios_dir: Path
    extra: dict[str, Path] = field(default_factory=dict)

    @classmethod
    def for_run(cls, out_dir: Path) -> RunPaths:
        """Build the layout for a run directory created at ``out_dir``."""
        return cls(
            root=out_dir,
            manifest=out_dir / "manifest.json",
            summary=out_dir / "summary.json",
            report=out_dir / "report.md",
            scenarios_dir=out_dir / "scenarios",
        )


def default_run_id(mode: str, *, now: datetime | None = None) -> str:
    """Timestamped run id: ``<mode>-<UTC yyyymmdd-HHMMSS>``."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return f"{mode}-{stamp}"
