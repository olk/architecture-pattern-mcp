#!/usr/bin/env bash
# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT
#
# Verify every pattern/*.json against docs/pattern-schema.json using ajv-cli.
#
# Usage: scripts/verify-patterns.sh
# Requires: ajv (npm install -g ajv-cli)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v ajv >/dev/null 2>&1; then
    echo "ERROR: ajv not found — install with: npm install -g ajv-cli" >&2
    exit 2
fi

if [ ! -f docs/pattern-schema.json ]; then
    echo "ERROR: schema not found: docs/pattern-schema.json" >&2
    exit 2
fi

# Quoted glob: ajv expands it (ajv-cli requires double-quoted globs).
ajv validate -s docs/pattern-schema.json -d "pattern/*.json" --all-errors
