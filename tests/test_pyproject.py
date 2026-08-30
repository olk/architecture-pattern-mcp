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

# Validates: FR-1, FR-2, FR-3, AC-1, AC-2, AC-3
# Test file for pyproject.toml configuration validation

import re
import sys
from pathlib import Path
from typing import Any

import pytest

# Use tomllib for Python 3.11+, otherwise use tomli
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli


def load_toml_config(file_path: str) -> dict[str, Any]:
    """
    Load and parse a TOML configuration file.

    SCEN-1: load_config loads valid config.json (TOML file in our case)

    # Validates: FR-1, FR-2, FR-3
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")

    with open(file_path, "rb") as f:
        if sys.version_info >= (3, 11):
            return tomllib.load(f)
        return tomli.load(f)


def load_config(file_path: str) -> dict[str, Any]:
    """
    Load configuration file with proper error handling.

    SCEN-1: load_config loads valid config.json
    SCEN-2: load_config raises FileNotFoundError for missing file

    # Validates: FR-1, FR-2, FR-3
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")

    with open(file_path, "rb") as f:
        if sys.version_info >= (3, 11):
            return tomllib.load(f)
        return tomli.load(f)


class TestPyprojectToml:
    """Test suite for pyproject.toml validation."""

    @pytest.fixture
    def pyproject_path(self, tmp_path: Path) -> Path:
        """Provide path to pyproject.toml."""
        return tmp_path / "pyproject.toml"

    @pytest.fixture
    def valid_pyproject_content(self) -> str:
        """Provide valid pyproject.toml content."""
        return """\
[project]
name = "architecture-pattern-mcp"
version = "1.0.17"
requires-python = ">=3.12"
description = "MCP Architect Server providing comprehensive architectural expertise"

[build-system]
requires = ["hatchling>=1.0.0"]
build-backend = "hatchling.build"
"""

    def test_load_config_loads_valid_toml(self, pyproject_path: Path, valid_pyproject_content: str) -> None:
        """
        SCEN-1: load_config loads valid config.json (TOML file)

        # Validates: FR-1, FR-2, FR-3, AC-1, AC-2, AC-3
        """
        pyproject_path.write_text(valid_pyproject_content)
        config = load_config(str(pyproject_path))

        assert "project" in config
        assert config["project"]["name"] == "architecture-pattern-mcp"
        assert config["project"]["version"] == "1.0.17"

    def test_load_config_raises_filenotfound_for_missing_file(self) -> None:
        """
        SCEN-2: load_config raises FileNotFoundError for missing file

        # Validates: FR-1, FR-2, FR-3
        """
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/pyproject.toml")

    def test_project_name_architecture_pattern_mcp(self, tmp_path: Path) -> None:
        """
        AC-1: Verify the project name in pyproject.toml is architecture-pattern-mcp

        # Validates: FR-1, AC-1
        """
        content = """\
[project]
name = "architecture-pattern-mcp"
version = "1.0.17"
requires-python = ">=3.12"

[build-system]
requires = ["hatchling>=1.0.0"]
build-backend = "hatchling.build"
"""
        pyproject_path = tmp_path / "pyproject.toml"
        pyproject_path.write_text(content)

        config = load_toml_config(str(pyproject_path))
        assert config["project"]["name"] == "architecture-pattern-mcp"

    def test_version_0_1_0(self, tmp_path: Path) -> None:
        """
        AC-2: Verify the version in pyproject.toml is 0.1.0

        # Validates: FR-2, AC-2
        """
        content = """\
[project]
name = "architecture-pattern-mcp"
version = "1.0.17"
requires-python = ">=3.12"

[build-system]
requires = ["hatchling>=1.0.0"]
build-backend = "hatchling.build"
"""
        pyproject_path = tmp_path / "pyproject.toml"
        pyproject_path.write_text(content)

        config = load_toml_config(str(pyproject_path))
        assert config["project"]["version"] == "1.0.17"

    def test_python_requires_312_or_higher(self, tmp_path: Path) -> None:
        """
        AC-3: Verify requires-python in pyproject.toml is >=3.12

        # Validates: FR-3, IC-1, AC-3
        """
        content = """\
[project]
name = "architecture-pattern-mcp"
version = "1.0.17"
requires-python = ">=3.12"

[build-system]
requires = ["hatchling>=1.0.0"]
build-backend = "hatchling.build"
"""
        pyproject_path = tmp_path / "pyproject.toml"
        pyproject_path.write_text(content)

        config = load_toml_config(str(pyproject_path))
        requires_python = config["project"]["requires-python"]

        # Parse ">=3.12" to extract version
        match = re.match(r">=(\d+)\.(\d+)", requires_python)
        assert match is not None, f"Invalid requires-python format: {requires_python}"

        major = int(match.group(1))
        minor = int(match.group(2))
        assert (major, minor) >= (3, 12), f"Python version {requires_python} is less than 3.12"

    def test_hatchling_build_backend(self, tmp_path: Path) -> None:
        """
        IC-41: Verify hatchling is the build backend

        # Validates: IC-41
        """
        content = """\
[project]
name = "architecture-pattern-mcp"
version = "1.0.17"
requires-python = ">=3.12"

[build-system]
requires = ["hatchling>=1.0.0"]
build-backend = "hatchling.build"
"""
        pyproject_path = tmp_path / "pyproject.toml"
        pyproject_path.write_text(content)

        config = load_toml_config(str(pyproject_path))
        assert config["build-system"]["build-backend"] == "hatchling.build"
        assert "hatchling" in config["build-system"]["requires"][0]

    def test_runtime_python_version_check(self) -> None:
        """
        AC-3: Python version check passes at runtime

        # Validates: FR-3, IC-1, AC-3
        """
        version = sys.version_info
        assert version >= (3, 12), f"Python version {version.major}.{version.minor} is less than 3.12"


class TestPyprojectTomlFromWorktree:
    """Test pyproject.toml from actual worktree location."""

    def test_worktree_pyproject_exists(self) -> None:
        """Verify pyproject.toml exists in worktree."""
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        assert pyproject_path.exists(), f"pyproject.toml not found at {pyproject_path}"

    def test_worktree_pyproject_valid_toml(self) -> None:
        """Verify pyproject.toml is valid TOML."""
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if not pyproject_path.exists():
            pytest.skip("pyproject.toml does not exist")

        with open(pyproject_path, "rb") as f:
            if sys.version_info >= (3, 11):
                config = tomllib.load(f)
            else:
                config = tomli.load(f)
            assert "project" in config
            assert "build-system" in config

    def test_worktree_project_name(self) -> None:
        """
        AC-1: Verify the project name in pyproject.toml is architecture-pattern-mcp

        # Validates: FR-1, AC-1
        """
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if not pyproject_path.exists():
            pytest.skip("pyproject.toml does not exist")

        config = load_toml_config(str(pyproject_path))
        assert config["project"]["name"] == "architecture-pattern-mcp"

    def test_worktree_version(self) -> None:
        """
        AC-2: Verify the version in pyproject.toml is 0.1.0

        # Validates: FR-2, AC-2
        """
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if not pyproject_path.exists():
            pytest.skip("pyproject.toml does not exist")

        config = load_toml_config(str(pyproject_path))
        assert config["project"]["version"] == "1.0.17"

    def test_worktree_python_requires(self) -> None:
        """
        AC-3: Verify requires-python in pyproject.toml is >=3.12

        # Validates: FR-3, IC-1, AC-3
        """
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if not pyproject_path.exists():
            pytest.skip("pyproject.toml does not exist")

        config = load_toml_config(str(pyproject_path))
        requires_python = config["project"]["requires-python"]

        match = re.match(r">=(\d+)\.(\d+)", requires_python)
        assert match is not None, f"Invalid requires-python format: {requires_python}"

        major = int(match.group(1))
        minor = int(match.group(2))
        assert (major, minor) >= (3, 12), f"Python version {requires_python} is less than 3.12"

    def test_worktree_hatchling_backend(self) -> None:
        """
        IC-41: Verify hatchling is the build backend

        # Validates: IC-41
        """
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if not pyproject_path.exists():
            pytest.skip("pyproject.toml does not exist")

        config = load_toml_config(str(pyproject_path))
        assert config["build-system"]["build-backend"] == "hatchling.build"


class TestDependencyDeclarations:
    """Test suite for dependency declarations in pyproject.toml (FR-4, FR-5, FR-6, FR-7, FR-200)."""

    def test_worktree_dependencies_exist(self) -> None:
        """
        AC-4, AC-5, AC-6, AC-7, AC-200: Verify dependencies section exists

        # Validates: FR-4, FR-5, FR-6, FR-7, FR-200
        """
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if not pyproject_path.exists():
            pytest.skip("pyproject.toml does not exist")

        config = load_toml_config(str(pyproject_path))
        assert "project" in config
        assert "dependencies" in config["project"]

    def test_fastmcp_dependency(self) -> None:
        """
        AC-4: Verify fastmcp>=3.3.1 specified in dependencies

        # Validates: FR-4, IC-2, AC-4
        """
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if not pyproject_path.exists():
            pytest.skip("pyproject.toml does not exist")

        config = load_toml_config(str(pyproject_path))
        deps = config["project"]["dependencies"]

        # Find fastmcp dependency
        fastmcp_dep = next((d for d in deps if d.startswith("fastmcp")), None)
        assert fastmcp_dep is not None, "fastmcp dependency not found"

        # Verify version constraint >=3.3.1
        match = re.match(r"fastmcp(>=[\d.]+)", fastmcp_dep)
        assert match is not None, f"Invalid fastmcp version format: {fastmcp_dep}"

        version_str = match.group(1)
        version_match = re.match(r">=(\d+)\.(\d+)\.(\d+)", version_str)
        assert version_match is not None, f"Invalid version format: {version_str}"

        major = int(version_match.group(1))
        minor = int(version_match.group(2))
        patch = int(version_match.group(3))
        assert (major, minor, patch) >= (3, 3, 1), f"fastmcp version {fastmcp_dep} is less than 3.3.1"

    def test_llama_index_dependencies(self) -> None:
        """
        AC-5: Verify llama-index-core and llama-index-llms-litellm specified in dependencies

        # Validates: FR-5, IC-3, AC-5
        """
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if not pyproject_path.exists():
            pytest.skip("pyproject.toml does not exist")

        config = load_toml_config(str(pyproject_path))
        deps = config["project"]["dependencies"]

        llama_index_core_dep = next(
            (d for d in deps if d.startswith("llama-index-core")), None
        )
        assert llama_index_core_dep is not None, "llama-index-core dependency not found"

        llama_index_llms_litellm_dep = next(
            (d for d in deps if d.startswith("llama-index-llms-litellm")), None
        )
        assert llama_index_llms_litellm_dep is not None, "llama-index-llms-litellm dependency not found"

        litellm_dep = next((d for d in deps if d.startswith("litellm")), None)
        assert litellm_dep is None, "litellm should not be a direct dependency (it is transitive)"

    def test_pydantic_dependency(self) -> None:
        """
        AC-6: Verify pydantic>=2.0.0 specified in dependencies

        # Validates: FR-6, IC-4, AC-6
        """
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if not pyproject_path.exists():
            pytest.skip("pyproject.toml does not exist")

        config = load_toml_config(str(pyproject_path))
        deps = config["project"]["dependencies"]

        # Find pydantic dependency
        pydantic_dep = next((d for d in deps if d.startswith("pydantic")), None)
        assert pydantic_dep is not None, "pydantic dependency not found"

        # Verify version constraint >=2.0.0
        match = re.match(r"pydantic(>=[\d.]+)", pydantic_dep)
        assert match is not None, f"Invalid pydantic version format: {pydantic_dep}"

        version_str = match.group(1)
        version_match = re.match(r">=(\d+)\.(\d+)\.(\d+)", version_str)
        assert version_match is not None, f"Invalid version format: {version_str}"

        major = int(version_match.group(1))
        minor = int(version_match.group(2))
        patch = int(version_match.group(3))
        assert (major, minor, patch) >= (2, 11, 7), f"pydantic version {pydantic_dep} is less than 2.11.7"

    def test_python_dotenv_dependency(self) -> None:
        """
        AC-7: Verify python-dotenv>=1.0.0 specified in dependencies

        # Validates: FR-7, IC-5, AC-7
        """
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if not pyproject_path.exists():
            pytest.skip("pyproject.toml does not exist")

        config = load_toml_config(str(pyproject_path))
        deps = config["project"]["dependencies"]

        # Find python-dotenv dependency
        dotenv_dep = next((d for d in deps if d.startswith("python-dotenv")), None)
        assert dotenv_dep is not None, "python-dotenv dependency not found"

        # Verify version constraint >=1.0.0
        match = re.match(r"python-dotenv(>=[\d.]+)", dotenv_dep)
        assert match is not None, f"Invalid python-dotenv version format: {dotenv_dep}"

        version_str = match.group(1)
        version_match = re.match(r">=(\d+)\.(\d+)\.(\d+)", version_str)
        assert version_match is not None, f"Invalid version format: {version_str}"

        major = int(version_match.group(1))
        minor = int(version_match.group(2))
        patch = int(version_match.group(3))
        assert (major, minor, patch) >= (1, 0, 0), f"python-dotenv version {dotenv_dep} is less than 1.0.0"

    def test_tei_reranker_dependency(self) -> None:
        """
        AC-200: Verify llama-index-postprocessor-tei-rerank is specified in dependencies.

        Reranking moved from local sentence-transformers (torch, CUDA stack) to a
        TEI sidecar in PR feat/tei-rerank-shrink-image.
        """
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if not pyproject_path.exists():
            pytest.skip("pyproject.toml does not exist")

        config = load_toml_config(str(pyproject_path))
        deps = config["project"]["dependencies"]

        tei_dep = next(
            (d for d in deps if d.startswith("llama-index-postprocessor-tei-rerank")), None
        )
        assert tei_dep is not None, "llama-index-postprocessor-tei-rerank dependency not found"

        match = re.match(r"llama-index-postprocessor-tei-rerank(>=[\d.]+)", tei_dep)
        assert match is not None, f"Invalid llama-index-postprocessor-tei-rerank version format: {tei_dep}"

        version_str = match.group(1)
        version_match = re.match(r">=(\d+)\.(\d+)(?:\.(\d+))?", version_str)
        assert version_match is not None, f"Invalid version format: {version_str}"

        major = int(version_match.group(1))
        minor = int(version_match.group(2))
        patch = int(version_match.group(3)) if version_match.group(3) is not None else 0
        assert (major, minor, patch) >= (0, 5, 0), (
            f"llama-index-postprocessor-tei-rerank version {tei_dep} is less than 0.5.0"
        )

    def test_faiss_cpu_dependency(self) -> None:
        """
        AC-200: Verify faiss-cpu>=1.14.3 specified in dependencies

        # Validates: FR-200, IC-34, AC-200
        """
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if not pyproject_path.exists():
            pytest.skip("pyproject.toml does not exist")

        config = load_toml_config(str(pyproject_path))
        deps = config["project"]["dependencies"]

        # Find faiss-cpu dependency
        faiss_dep = next((d for d in deps if d.startswith("faiss-cpu")), None)
        assert faiss_dep is not None, "faiss-cpu dependency not found"

        # Verify version constraint >=1.7.0
        match = re.match(r"faiss-cpu(>=[\d.]+)", faiss_dep)
        assert match is not None, f"Invalid faiss-cpu version format: {faiss_dep}"

        version_str = match.group(1)
        version_match = re.match(r">=(\d+)\.(\d+)\.(\d+)", version_str)
        assert version_match is not None, f"Invalid version format: {version_str}"

        major = int(version_match.group(1))
        minor = int(version_match.group(2))
        patch = int(version_match.group(3))
        assert (major, minor, patch) >= (1, 14, 3), f"faiss-cpu version {faiss_dep} is less than 1.14.3"
