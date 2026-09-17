# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
Lockstep tests for the official MCP Registry listing (server.json).

server.json is the OCI listing consumed by registry.modelcontextprotocol.io;
`mcp-publisher publish` rejects a version whose artifact is not published, and
registry versions are immutable once published. These tests pin the invariants
that a release must satisfy so a version bump cannot leave the listing
advertising a stale or non-existent artifact:

- server.json version == pyproject.toml version == Dockerfile image version label
- server.json name == Dockerfile io.modelcontextprotocol.server.name label
  (the registry compares the label on the published image config blob with the
  server name; any drift fails the ownership check)
- the OCI identifier pins the released tag (docker.io/<repo>:<version>)

The launch side of the same contract — the image must keep the ENTRYPOINT/CMD
split so appended packageArguments reach the server — is proven per release with
`docker run --rm <image> --health` (prints OK only when args reach the CLI).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_JSON = REPO_ROOT / "server.json"
PYPROJECT = REPO_ROOT / "pyproject.toml"
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"


def _server_json() -> dict[str, Any]:
    return json.loads(SERVER_JSON.read_text(encoding="utf-8"))


def _pyproject_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match, "pyproject.toml declares no [project] version"
    return match.group(1)


def _dockerfile_label(label: str) -> str:
    text = DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(rf'^\s*{re.escape(label)}="([^"]*)"', text, re.MULTILINE)
    assert match, f"docker/Dockerfile declares no LABEL {label}"
    return match.group(1)


class TestRegistryListingLockstep:
    """server.json must match the release it advertises."""

    def test_version_matches_pyproject_and_image_label(self) -> None:
        version = _pyproject_version()
        assert _server_json()["version"] == version
        assert _dockerfile_label("org.opencontainers.image.version") == version

    def test_server_name_matches_image_label(self) -> None:
        assert _server_json()["name"] == _dockerfile_label(
            "io.modelcontextprotocol.server.name"
        )

    def test_oci_package_pins_released_tag_over_stdio(self) -> None:
        oci_packages = [
            p for p in _server_json()["packages"] if p["registryType"] == "oci"
        ]
        assert len(oci_packages) == 1, "the Hub image is the canonical distribution"
        package = oci_packages[0]
        assert package["identifier"] == (
            f"docker.io/olkowa/architecture-pattern-mcp:{_pyproject_version()}"
        )
        assert package["transport"] == {"type": "stdio"}
