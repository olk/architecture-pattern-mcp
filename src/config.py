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
# FR-14: The system SHALL provide a load_config function that accepts an optional config_path parameter and loads configuration from JSON file
# FR-271: By default, the system SHALL look for config.json at ~/.config/architecture-pattern-mcp/config.json
# FR-272: The system SHALL support a CONFIG_PATH environment variable
# IC-7: load_config function SHALL accept optional config_path parameter
# IC-43: By default, the system SHALL look for config.json at ~/.config/architecture-pattern-mcp/config.json
# IC-44: The system SHALL support a CONFIG_PATH environment variable

Configuration loading from JSON file with environment variable expansion.

# FR-8: The server SHALL use a JSON configuration file (config.json) for all settings.
# Environment variables are embedded in config.json using {env:VAR:-default} syntax.
# IC-6: Configuration SHALL use JSON format with {env:...} env-var expansion

# FR-15: The system SHALL verify the configuration file exists before attempting to read it
# and raise FileNotFoundError if the file does not exist
# IC-9: FileNotFoundError SHALL be raised if configuration file does not exist
# E-10: ERR_010 - Configuration file not found (HTTP 404, severity: critical)
"""

import json
import logging
import os
from typing import Any, ClassVar, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from src.config_expansion import expand_env_in_obj
from src.reasoning.config import ReasoningConfig

# Error codes for logging
ERROR_CONFIG_NOT_FOUND = "ERR_010"
ERROR_INVALID_CONFIG = "INVALID_CONFIG"

logger = logging.getLogger(__name__)


class GeneratorInnerConfig(BaseModel):
    """Generator per-provider configuration."""

    model: str
    base_url: str = ""
    api_key: str | None = None
    temperature: float = 0.1
    top_p: float = 1.0
    top_k: int = 20
    stream: bool = Field(
        default=False,
        description="Enable streaming responses for improved time-to-first-byte",
    )


class GeneratorConfig(BaseModel):
    """Generator provider configuration."""

    provider: str
    config: GeneratorInnerConfig


class EmbedderInnerConfig(BaseModel):
    """Embedder per-provider configuration."""

    base_url: str = ""
    api_key: str | None = None
    embed_batch_size: int = 16
    query_instruction: str = ""
    text_instruction: str = ""


class EmbedderConfig(BaseModel):
    """Embedder provider configuration."""

    provider: str
    config: EmbedderInnerConfig


class RerankerInnerConfig(BaseModel):
    """Reranker per-provider configuration (TEI-backed)."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = ""
    timeout: float = Field(30.0, gt=0)
    max_batch_size: int = Field(
        48,
        ge=1,
        le=1024,
        description=(
            "Max number of texts sent to TEI /rerank in a single HTTP request. "
            "Must be ≤ min(sidecar MAX_CLIENT_BATCH_SIZE, MAX_CONCURRENT_REQUESTS). "
            "HybridPatternRetriever chunks the fused slug pool into requests of this size. "
            "Default 48 matches the TEI reranker sidecar's MAX_CLIENT_BATCH_SIZE."
        ),
    )


class RerankerConfig(BaseModel):
    """Reranker provider configuration — connection and post-fusion slug-cut settings.

    Contains the TEI-backed cross-encoder connection settings (base_url, timeout)
    and the reranking stage parameters (rerank_top_n, rerank_selection).
    """

    model_config = ConfigDict(extra="forbid")

    config: RerankerInnerConfig = Field(
        default_factory=lambda: RerankerInnerConfig(base_url="http://pattern-tei-rerank:8080")
    )
    rerank_top_n: int = Field(
        10, ge=1, le=100,
        description=(
            "Max candidates kept AFTER cross-encoder reranking. Bounds the slug "
            "pool fed to pattern resolution and matched_domains reporting. "
            "Reranker scoring itself remains lossless."
        ),
    )
    rerank_selection: Literal["rerank", "rank_fusion"] = Field(
        "rerank",
        description=(
            "Slug-cut strategy after cross-encoder scoring. "
            '"rerank" (default): keep top rerank_top_n by cross-encoder order only '
            "(llama-index convention). Reported fusion_score is the original RRF score. "
            '"rank_fusion": Vespa-style blend — keep top rerank_top_n by '
            "RR(rrf_rank) + RR(ce_rank), k=60.  "
            "Protects consensus-backed slugs from CE outliers on short domain-slug inputs. "
            "Reported fusion_score is the blended selection score "
            "(the min_fusion_score gate applies to that blended value in this mode). "
            "Has no effect when the candidate pool is < rerank_top_n."
        ),
    )


FusionMode = Literal["reciprocal_rerank", "relative_score", "dist_based_score"]


PATTERN_CONTEXT_LIMITS: dict[str, int] = {
    "benefits": 3,
    "tradeoffs": 3,
    "best_practices": 3,
    "component_types": 5,
    "technology_stack": 5,
    "anti_patterns": 3,
    "suitable_domains": 5,
}


class RetrievalConfig(BaseModel):
    """Retrieval tuning configuration for hybrid BM25 + dense fusion.

    Stage-1 (recall) caps: bm25_top_k / dense_top_k accept 0,
    which means "full corpus" (lossless recall). Any value >=1 caps each leg to
    that many candidates. Selection of the final pattern set happens AFTER
    requirements-aware scoring in the analyze phase (see top_k_patterns and
    style_score_threshold).

    .. note::
        Three fields (analysis_blend_weight, fusion_blend_weight,
        weight_smoothing_alpha) had their defaults changed in PR-A. Operators
        who need pre-PR behaviour can pin::

            analysis_blend_weight=1.0
            fusion_blend_weight=0.0
            weight_smoothing_alpha=1.0
    """

    model_config = ConfigDict(extra="forbid")

    bm25_top_k: int = Field(0, ge=0, le=1000)
    dense_top_k: int = Field(0, ge=0, le=1000)
    top_k_patterns: int = Field(5, ge=1, le=100)
    mode: FusionMode = Field(
        "reciprocal_rerank",
        description=(
            "Stage-1 fusion strategy, applied by the upstream QueryFusionRetriever: "
            '"reciprocal_rerank" (Reciprocal Rank Fusion, k=60, default), '
            '"relative_score" (min-max normalized per-leg scores), '
            '"dist_based_score" (relative score with a 3-sigma range). '
            'The former "simple" rank-union mode was removed.'
        ),
    )
    min_fusion_score: float = Field(
        0.0, ge=0.0, le=1.0,
        description=(
            "RRF scores encode rank consensus, not calibrated relevance — "
            "0.0 disables this gate (recommended). Relevance gating happens "
            "downstream via style_score_threshold (0-100 scale)."
        )
    )
    min_quality_score: float = Field(
        50.0, ge=0.0, le=100.0,
        description=(
            "Early-stop threshold for the design loop on the 0-100 quality "
            "scale. Below this, the loop runs to max_tries. Above this, "
            "stops after the first attempt that meets it. 100.0 disables "
            "the early stop."
        ),
    )
    max_tries: int = Field(2, ge=1, le=10)
    use_lean_wire_schema: bool = Field(
        default=False,
        description=(
            "If True, generate() uses a lean response schema (ArchitectureDesignResponseWire) "
            "that omits patterns and top-level contract lists. Saves ~15KB schema + 1-3K output "
            "tokens per call. Default False for backward compatibility with existing tests."
        ),
    )
    style_score_threshold: float = Field(
        50.0, ge=0.0, le=100.0,
        description="Minimum deterministic analysis_score (0-100) required for "
                    "the top-scoring pattern's name to be used as "
                    "recommended_style; below this, falls back to "
                    "layered-monolith.",
    )
    analysis_blend_weight: float = Field(
        default=0.7, ge=0.0, le=1.0,
        description=(
            "Weight on analysis_score in the blended selection score (0.0-1.0). "
            "Default 0.7. BREAKING default change from prior implicit value 1.0. "
            "Set to 1.0 (with fusion_blend_weight=0.0) to restore pre-change behaviour."
        ),
    )
    fusion_blend_weight: float = Field(
        default=0.3, ge=0.0, le=1.0,
        description=(
            "Weight on min-max-normalized fusion_score in the blended selection "
            "score (0.0-1.0). Default 0.3. BREAKING default change from prior "
            "implicit value 0.0. Set to 0.0 to restore pre-change behaviour."
        ),
    )
    weight_smoothing_alpha: float = Field(
        default=0.7, ge=0.0, le=1.0,
        description=(
            "Convex smoothing for RequirementWeights: w' = alpha*w + (1-alpha)*(1/n). "
            "Default 0.7. BREAKING default change from prior implicit value 1.0 "
            "(no smoothing). Set to 1.0 to restore raw LLM weights."
        ),
    )
    verbose_timing: bool = Field(
        default=False,
        description=(
            "When True, _timed_phase logs at INFO instead of DEBUG, enabling "
            "phase-duration observability without changing the global logging level. "
            "Off by default to preserve hot-path performance."
        ),
    )
    pattern_context_limits: dict[str, int] = Field(default_factory=lambda: PATTERN_CONTEXT_LIMITS.copy())

    @model_validator(mode="after")
    def _check_score_blend_weights(self) -> "RetrievalConfig":
        s = self.analysis_blend_weight + self.fusion_blend_weight
        if abs(s - 1.0) > 1e-3:
            raise ValueError(
                f"analysis_blend_weight + fusion_blend_weight must sum to 1.0, got {s}"
            )
        return self


class ValidationConfig(BaseModel):
    """
    Validation settings for self-healing retry loop.

    max_retries: Maximum number of self-healing retry attempts on validation failure.
                  Each retry sends a corrected prompt with validation error details.
    retry_on_fail: If False, disable self-healing retries (raise on first validation failure).
    """

    max_retries: int = Field(3, ge=0, le=10)
    retry_on_fail: bool = True


class TasksConfig(BaseModel):
    """Heartbeat configuration for long-running tools.

    Implements Fix 2 of the long-running-tool timeout fix: a parallel coroutine
    emits progress notifications at regular intervals during a tool's execution,
    keeping client idle timers alive.

    FR-XXX: Heartbeat settings SHALL be configurable via config.json.
    """

    heartbeat_enabled: bool = Field(
        default=True,
        description="Emit progress notifications from a parallel coroutine during long tool calls. "
                    "Keeps client HTTP/stdio idle timers alive; works for every client.",
    )
    heartbeat_interval_seconds: int = Field(
        default=30,
        ge=5,
        le=600,
        description="Heartbeat emit interval in seconds. Must be shorter than the "
                    "client's idle timeout (5 minutes for HTTP transport).",
    )


class ServerConfig(BaseModel):
    """
    # E-13: INVALID_CONFIG - Config structure invalid (HTTP 400, severity: warn)

    Pydantic model for validating configuration structure.

    # FR-8: JSON configuration file for all settings
    # IC-6: Configuration SHALL use JSON format with {env:...} env-var expansion
    """

    generator: GeneratorConfig

    embedder: EmbedderConfig

    # Reranker: TEI-backed cross-encoder connection and post-fusion slug-cut settings.
    reranker: RerankerConfig = Field(
        default_factory=lambda: RerankerConfig(
            config=RerankerInnerConfig(base_url="http://pattern-tei-rerank:8080")
        )
    )

    # Retrieval tuning: hybrid BM25 + dense fusion parameters.
    retrieval: RetrievalConfig | None = None

    # Pattern directory: PatternLoader reads *-architecture.json files from here.
    # Default: ~/.config/architecture-pattern-mcp/pattern
    pattern_directory: str = "~/.config/architecture-pattern-mcp/pattern"

    # CPARA-16: Logging level (DEBUG|INFO|WARNING|ERROR|CRITICAL)
    logging_level: str = "INFO"

    # CPARA-17: Logging format (json|text)
    logging_format: str = "json"

    # Log level applied to the LiteLLM SDK and its transport loggers (litellm,
    # LiteLLM, httpcore, httpx, openai, aiosqlite, asyncio) so DEBUG-level root
    # operation does not flood the log with prompt bodies and HTTP frames.
    litellm_log_level: str = "WARNING"

    # Validation: self-healing retry loop settings for LLM structured generation
    validation: ValidationConfig = Field(default_factory=lambda: ValidationConfig())

    # Server-side reasoning MCP integration (shannonthinking / code-reasoning).
    # Enabled by default: Docker images embed both packages at build time;
    # outside Docker the client auto-falls back to npx.
    reasoning: ReasoningConfig = Field(default_factory=lambda: ReasoningConfig())

    @field_validator("litellm_log_level")
    @classmethod
    def _validate_litellm_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_up = v.upper().strip()
        if v_up not in valid:
            raise ValueError(
                f"litellm_log_level must be one of {sorted(valid)}, got {v!r}"
            )
        return v_up

    @model_validator(mode="after")
    def _check_reranker_configured(self) -> "ServerConfig":
        if (
            self.reranker is None
            or self.reranker.config is None
            or not self.reranker.config.base_url.strip()
        ):
            raise ValueError(
                "Reranking is mandatory; `reranker.config.base_url` "
                "must be a non-empty URL. Set RERANKER_BASE_URL and ensure the "
                "deployed config.json contains the `reranker` block "
                "(an outdated config file copied from an older image may omit it)."
            )
        return self

    # Heartbeat settings for long-running tools
    tasks: TasksConfig = Field(default_factory=lambda: TasksConfig())

    # Transport mode: "stdio" for local, "streamable-http" for HTTP
    transport: str = "streamable-http"

    # Server bind host for SSE transport
    host: str = "0.0.0.0"

    # Server bind port for SSE transport
    port: int = 8050

    model_config = {"extra": "forbid"}


class ConfigManager:
    """
    Configuration Manager for loading JSON config with env-var expansion.

    # FR-14: load_config function accepts optional config_path parameter

    # IC-7: load_config function SHALL accept optional config_path parameter
    """

    # FR-271/IC-43: Default config path is ~/.config/architecture-pattern-mcp/config.json
    DEFAULT_CONFIG_PATH: str = "~/.config/architecture-pattern-mcp/config.json"

    # Class variable for caching loaded configuration
    _config: ClassVar[dict[str, Any] | None] = None

    @classmethod
    def load_config(cls, config_path: str | None = None) -> dict[str, Any]:
        """
        Load configuration from JSON file with {env:VAR:-default} expansion.

        # FR-14: The system SHALL provide a load_config function that accepts
        an optional config_path parameter and loads configuration from JSON file
        # FR-271: By default, the system SHALL look for config.json at ~/.config/architecture-pattern-mcp/config.json
        # FR-272: The system SHALL support a CONFIG_PATH environment variable

        # IC-7: load_config function SHALL accept optional config_path parameter
        # IC-43: By default, the system SHALL look for config.json at ~/.config/architecture-pattern-mcp/config.json
        # IC-44: The system SHALL support a CONFIG_PATH environment variable

        Configuration path resolution order:
        1. CONFIG_PATH environment variable (highest priority)
        2. config_path parameter (if provided)
        3. DEFAULT_CONFIG_PATH (~/.config/architecture-pattern-mcp/config.json)

        Environment variable expansion:
        - {env:VAR}           → value of VAR from environ, or "" if unset
        - {env:VAR:-default}  → value of VAR, or "default" if unset

        # FR-15: The system SHALL verify the configuration file exists before attempting to read it
        # and raise FileNotFoundError if the file does not exist
        # IC-9: FileNotFoundError SHALL be raised if configuration file does not exist
        # E-10: ERR_010 - Configuration file not found (HTTP 404, severity: critical)

        Args:
            config_path: Optional path to configuration file. If not provided,
                        uses CONFIG_PATH env var or default path.

        Returns:
            dict: Parsed, expanded, and validated configuration dictionary.

        Raises:
            FileNotFoundError: If configuration file does not exist at path.
            ValidationError: If configuration structure is invalid.
        """
        if cls._config is not None:
            return cls._config

        load_dotenv()

        if os.environ.get("CONFIG_PATH"):
            resolved_path = os.environ["CONFIG_PATH"]
            logger.debug(f"Using CONFIG_PATH env var: {resolved_path}")
        elif config_path:
            resolved_path = config_path
            logger.debug(f"Using config_path parameter: {resolved_path}")
        else:
            resolved_path = cls.DEFAULT_CONFIG_PATH
            logger.debug(f"Using default config path: {resolved_path}")

        expanded_path = os.path.expanduser(resolved_path)
        abs_path = os.path.abspath(expanded_path)

        if not os.path.exists(expanded_path):
            logger.error(
                "Configuration file not found",
                extra={
                    "config_path": abs_path,
                    "error_code": ERROR_CONFIG_NOT_FOUND
                }
            )
            raise FileNotFoundError(
                f"Configuration file not found at path: {abs_path}"
            )

        try:
            with open(expanded_path, encoding="utf-8") as f:
                raw_config = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(
                "Invalid JSON in configuration file",
                extra={
                    "config_path": abs_path,
                    "error_code": ERROR_INVALID_CONFIG,
                    "json_error": str(e)
                }
            )
            raise ValueError(f"Invalid JSON configuration: {e}")

        expanded_config = expand_env_in_obj(raw_config)

        try:
            validated_config = ServerConfig.model_validate(expanded_config)
        except ValidationError as e:
            logger.error(
                "Configuration structure invalid",
                extra={
                    "config_path": abs_path,
                    "error_code": ERROR_INVALID_CONFIG,
                    "validation_error": str(e)
                }
            )
            raise

        cls._config = validated_config.model_dump()

        logger.info(
            "Configuration loaded successfully",
            extra={"config_path": abs_path}
        )

        return cls._config
