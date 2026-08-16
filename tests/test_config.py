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
# Validates: FR-8, FR-14, FR-15, FR-271, FR-272, AC-8, AC-14, AC-15, AC-271, AC-272
# UT-1: Configuration loading tests

Test file for src/config.py configuration loading.

Tests:
- SCEN-1: load_config loads valid config.json
- SCEN-2: load_config raises FileNotFoundError for missing file
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.config import (
    ERROR_CONFIG_NOT_FOUND,
    ERROR_INVALID_CONFIG,
    ConfigManager,
    RetrievalConfig,
    ServerConfig,
)


class TestServerConfig:
    """Test suite for ServerConfig Pydantic model."""

    def test_valid_config_with_custom_values(self) -> None:
        """
        AC-8: JSON configuration loading
        # Validates: FR-8, FR-271
        """
        config = ServerConfig(
            generator={"provider": "anthropic", "config": {"model": "claude-3", "temperature": 0.5}},
            embedder={"provider": "tei", "config": {"base_url": "http://localhost:8080"}},
        )
        assert config.generator.provider == "anthropic"
        assert config.generator.config.model == "claude-3"
        assert config.generator.config.temperature == 0.5
        assert config.embedder.provider == "tei"


class TestLoadConfig:
    """Test suite for load_config function and ConfigManager."""

    @pytest.fixture
    def valid_config_file(self, tmp_path: Path) -> Path:
        """
        Create a valid JSON configuration file.

        SCEN-1: load_config loads valid config.json
        # Validates: FR-8, FR-14, AC-8
        """
        config_path = tmp_path / "config.json"
        config_data = {
            "generator": {
                "provider": "openai",
                "config": {
                    "model": "gpt-4",
                    "temperature": 0.7
                }
            },
            "embedder": {
                "provider": "tei",
                "config": {
                    "base_url": "http://localhost:8080",
                    "embed_batch_size": 16,
                    "query_instruction": "Instruct: test\nQuery: ",
                    "text_instruction": "",
                    "max_embedder_tokens": 3000,
                }
            }
        }
        config_path.write_text(json.dumps(config_data))
        return config_path

    @pytest.fixture
    def clear_config_cache(self):
        """Clear ConfigManager cache before and after tests."""
        ConfigManager.clear_cache()
        yield
        ConfigManager.clear_cache()

    def test_load_config_valid_json(
        self, valid_config_file: Path, clear_config_cache: None
    ) -> None:
        """
        SCEN-1: load_config loads valid config.json

        # Validates: FR-8, FR-14, AC-8
        """
        config = ConfigManager.load_config(str(valid_config_file))

        assert config["generator"]["provider"] == "openai"
        assert config["generator"]["config"]["model"] == "gpt-4"
        assert config["generator"]["config"]["temperature"] == 0.7
        assert config["embedder"]["provider"] == "tei"

    def test_load_config_raises_filenotfound_for_missing_file(
        self, clear_config_cache: None
    ) -> None:
        """
        SCEN-2: load_config raises FileNotFoundError for missing file

        # Validates: FR-15, AC-15, IC-9
        """
        with pytest.raises(FileNotFoundError) as exc_info:
            ConfigManager.load_config("/nonexistent/path/config.json")

        assert "Configuration file not found" in str(exc_info.value)

    def test_load_config_with_config_path_parameter(
        self, valid_config_file: Path, clear_config_cache: None
    ) -> None:
        """
        AC-14: load_config function exists and accepts optional config_path parameter

        # Validates: FR-14, AC-14, IC-7
        """
        config = ConfigManager.load_config(config_path=str(valid_config_file))

        assert config["generator"]["provider"] == "openai"

    def test_load_config_default_path(
        self, tmp_path: Path, clear_config_cache: None
    ) -> None:
        """
        AC-271: Default CONFIG_PATH

        # Validates: FR-271, AC-271, IC-43
        """
        default_dir = tmp_path / ".config" / "architecture-pattern-mcp"
        default_dir.mkdir(parents=True, exist_ok=True)
        default_config = default_dir / "config.json"
        default_config.write_text(json.dumps({
            "generator": {
                "provider": "anthropic",
                "config": {
                    "model": "claude-3",
                    "temperature": 0.5
                }
            },
            "embedder": {
                "provider": "tei",
                "config": {
                    "base_url": "http://localhost:8080",
                    "embed_batch_size": 16,
                    "query_instruction": "Instruct: test\nQuery: ",
                    "text_instruction": "",
                    "max_embedder_tokens": 3000,
                }
            }
        }))

        with patch("os.path.expanduser", return_value=str(default_config)):
            config = ConfigManager.load_config()

        assert config["generator"]["provider"] == "anthropic"

    def test_load_config_env_var_override(
        self, tmp_path: Path, clear_config_cache: None
    ) -> None:
        """
        AC-272: CONFIG_PATH env var accepted

        # Validates: FR-272, AC-272, IC-44
        """
        custom_dir = tmp_path / "custom" / "config"
        custom_dir.mkdir(parents=True, exist_ok=True)
        custom_config = custom_dir / "config.json"
        custom_config.write_text(json.dumps({
            "generator": {
                "provider": "vertexai",
                "config": {
                    "model": "gemini-pro",
                    "temperature": 0.9
                }
            },
            "embedder": {
                "provider": "tei",
                "config": {
                    "base_url": "http://localhost:8080",
                    "embed_batch_size": 16,
                    "query_instruction": "Instruct: test\nQuery: ",
                    "text_instruction": "",
                    "max_embedder_tokens": 3000,
                }
            }
        }))

        with patch.dict(os.environ, {"CONFIG_PATH": str(custom_config)}):
            config = ConfigManager.load_config()

        assert config["generator"]["provider"] == "vertexai"
        assert config["generator"]["config"]["model"] == "gemini-pro"

    def test_load_config_invalid_json(
        self, tmp_path: Path, clear_config_cache: None
    ) -> None:
        """
        E-13: INVALID_CONFIG - Config structure invalid

        # Validates: E-13
        """
        invalid_config = tmp_path / "invalid.json"
        invalid_config.write_text("not valid json {")

        with pytest.raises(ValueError):
            ConfigManager.load_config(str(invalid_config))

    def test_load_config_caching(
        self, valid_config_file: Path, clear_config_cache: None
    ) -> None:
        """
        Test that load_config caches configuration.

        # Validates: FR-14 (caching behavior)
        """
        config1 = ConfigManager.load_config(str(valid_config_file))

        valid_config_file.write_text(json.dumps({
            "generator": {
                "provider": "modified",
                "config": {
                    "model": "modified-model",
                    "temperature": 1.0
                }
            },
            "embedder": {
                "provider": "tei",
                "config": {
                    "base_url": "http://localhost:8080",
                    "embed_batch_size": 32,
                    "query_instruction": "Instruct: modified\nQuery: ",
                    "text_instruction": "",
                    "max_embedder_tokens": 3000,
                }
            }
        }))

        config2 = ConfigManager.load_config(str(valid_config_file))

        assert config1 == config2
        assert config2["generator"]["provider"] == "openai"


class TestConfigManager:
    """Test suite for ConfigManager class methods."""

    def test_clear_cache(self) -> None:
        """
        Test that clear_cache properly resets cached configuration.

        # Validates: ConfigManager.clear_cache
        """
        assert ConfigManager._config is None

        ConfigManager.clear_cache()
        assert ConfigManager._config is None

    def test_default_config_path_constant(self) -> None:
        """
        AC-271: Default CONFIG_PATH

        # Validates: FR-271, IC-43
        """
        assert ConfigManager.DEFAULT_CONFIG_PATH == "~/.config/architecture-pattern-mcp/config.json"


class TestErrorHandling:
    """Test suite for error handling and logging."""

    def test_error_codes_defined(self) -> None:
        """
        Test that error codes are properly defined.

        # Validates: E-10, E-13
        """
        assert ERROR_CONFIG_NOT_FOUND == "ERR_010"
        assert ERROR_INVALID_CONFIG == "INVALID_CONFIG"


class TestRetrievalConfig:
    """Test suite for RetrievalConfig Pydantic model."""

    def test_retrieval_config_default_values(self) -> None:
        """
        Test that RetrievalConfig accepts valid default values.

        bm25_top_k / dense_top_k default to 0, meaning
        "full corpus" (lossless stage-1 recall). top_k_patterns (the
        post-scoring selection cap) defaults to 5.
        """
        config = RetrievalConfig()
        assert config.bm25_top_k == 0
        assert config.dense_top_k == 0
        assert config.top_k_patterns == 5
        assert config.max_tries == 2
        assert config.min_quality_score == 50.0
        assert config.style_score_threshold == 50.0
        assert config.pattern_context_limits == {
            "benefits": 3,
            "tradeoffs": 3,
            "best_practices": 3,
            "component_types": 5,
            "technology_stack": 5,
            "anti_patterns": 3,
            "suitable_domains": 5,
        }

    def test_retrieval_config_custom_values(self) -> None:
        """
        Test that RetrievalConfig accepts valid custom values.
        """
        config = RetrievalConfig(
            bm25_top_k=50,
            dense_top_k=75,
            top_k_patterns=10,
        )
        assert config.bm25_top_k == 50
        assert config.dense_top_k == 75
        assert config.top_k_patterns == 10

    def test_retrieval_config_boundary_min_values(self) -> None:
        """
        Test that RetrievalConfig accepts boundary minimum values.
        """
        config = RetrievalConfig(
            bm25_top_k=1,
            dense_top_k=1,
            top_k_patterns=1,
        )
        assert config.bm25_top_k == 1
        assert config.dense_top_k == 1
        assert config.top_k_patterns == 1

    def test_retrieval_config_boundary_max_values(self) -> None:
        """
        Test that RetrievalConfig accepts boundary maximum values.
        """
        config = RetrievalConfig(
            bm25_top_k=1000,
            dense_top_k=1000,
            top_k_patterns=100,
        )
        assert config.bm25_top_k == 1000
        assert config.dense_top_k == 1000
        assert config.top_k_patterns == 100

    def test_retrieval_config_bm25_top_k_zero_means_full_corpus(self) -> None:
        """Test that bm25_top_k=0 is accepted (means "full corpus")."""
        config = RetrievalConfig(bm25_top_k=0)
        assert config.bm25_top_k == 0

    def test_retrieval_config_bm25_top_k_too_low(self) -> None:
        """Test that bm25_top_k < 0 raises ValidationError."""
        with pytest.raises(ValidationError):
            RetrievalConfig(bm25_top_k=-1)

    def test_retrieval_config_bm25_top_k_too_high(self) -> None:
        """Test that bm25_top_k > 1000 raises ValidationError."""
        with pytest.raises(ValidationError):
            RetrievalConfig(bm25_top_k=1001)

    def test_retrieval_config_dense_top_k_zero_means_full_corpus(self) -> None:
        """Test that dense_top_k=0 is accepted (means "full corpus")."""
        config = RetrievalConfig(dense_top_k=0)
        assert config.dense_top_k == 0

    def test_retrieval_config_dense_top_k_too_low(self) -> None:
        """Test that dense_top_k < 0 raises ValidationError."""
        with pytest.raises(ValidationError):
            RetrievalConfig(dense_top_k=-1)

    def test_retrieval_config_dense_top_k_too_high(self) -> None:
        """Test that dense_top_k > 1000 raises ValidationError."""
        with pytest.raises(ValidationError):
            RetrievalConfig(dense_top_k=1001)

    def test_retrieval_config_dense_top_k_zero_means_full_corpus(self) -> None:
        """Test that dense_top_k=0 is accepted (means "full corpus")."""
        config = RetrievalConfig(dense_top_k=0)
        assert config.dense_top_k == 0

    def test_retrieval_config_dense_top_k_too_low(self) -> None:
        """Test that dense_top_k < 0 raises ValidationError."""
        with pytest.raises(ValidationError):
            RetrievalConfig(dense_top_k=-1)

    def test_retrieval_config_dense_top_k_too_high(self) -> None:
        """Test that dense_top_k > 1000 raises ValidationError."""
        with pytest.raises(ValidationError):
            RetrievalConfig(dense_top_k=1001)

    def test_retrieval_config_top_k_patterns_too_low(self) -> None:
        """Test that top_k_patterns < 1 raises ValidationError."""
        with pytest.raises(ValidationError):
            RetrievalConfig(top_k_patterns=0)

    def test_retrieval_config_top_k_patterns_too_high(self) -> None:
        """Test that top_k_patterns > 100 raises ValidationError."""
        with pytest.raises(ValidationError):
            RetrievalConfig(top_k_patterns=101)

    @pytest.mark.parametrize("mode", [
        "simple",
        "reciprocal_rerank",
    ])
    def test_all_two_modes_accepted(self, mode: str) -> None:
        """Test that all two fusion modes are accepted."""
        config = RetrievalConfig(mode=mode)
        assert config.mode == mode

    def test_unknown_mode_rejected(self) -> None:
        """Test that an unknown mode string raises ValidationError."""
        with pytest.raises(ValidationError):
            RetrievalConfig(mode="bogus")


class TestExtraForbid:
    """Test suite for extra: forbid policy on ServerConfig."""

    def test_server_config_rejects_unknown_field(self) -> None:
        """
        Test that ServerConfig raises ValidationError for unknown keys.
        Extra keys are forbidden.
        """
        with pytest.raises(ValidationError):
            ServerConfig(
                generator={"provider": "openai", "config": {"model": "gpt-4"}},
                embedder={"provider": "tei", "config": {"base_url": "http://localhost:8080"}},
                unknown_field={"invalid": "value"},
            )

    def test_server_config_rejects_top_level_unknown_field(self) -> None:
        """
        Test that ServerConfig raises ValidationError for an unknown top-level key.
        Extra keys are forbidden at the ServerConfig level.
        """
        with pytest.raises(ValidationError):
            ServerConfig(
                generator={"provider": "openai", "config": {"model": "gpt-4"}},
                embedder={"provider": "tei", "config": {"base_url": "http://localhost:8080"}},
                retrieval={"bm25_top_k": 30, "dense_top_k": 40, "top_k_patterns": 8},
                invalid_top_level_key=True,
            )

    def test_server_config_accepts_retrieval_block(self) -> None:
        """
        Test that ServerConfig accepts a valid retrieval block.
        """
        config = ServerConfig(
            generator={"provider": "openai", "config": {"model": "gpt-4"}},
            embedder={"provider": "tei", "config": {"base_url": "http://localhost:8080"}},
            retrieval={"bm25_top_k": 30, "dense_top_k": 40, "top_k_patterns": 8},
        )
        assert config.retrieval is not None
        assert config.retrieval.bm25_top_k == 30
        assert config.retrieval.dense_top_k == 40
        assert config.retrieval.top_k_patterns == 8
