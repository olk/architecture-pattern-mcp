#!/usr/bin/env bash
# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT
#
# Run one .fizz spec through the FizzBee checker in an isolated temp copy of
# the spec directory (compiled .json ASTs and out/ graphs are written there
# and discarded), then apply the gate verdict for the given mode.
#
# Isolation rationale (docs/make_rules.md #verify-fizz): the compiled .json
# artifacts and out/ run dirs are shared mutable state when fizz runs against
# verify/fizz/ directly — concurrent gate runs can clobber each other's
# compilation and an aborted run can leave stale artifacts. A private temp
# copy makes every run hermetic.
#
# Usage: fizz-check.sh <spec-path> <exhaustive|simulation> [extra fizz args...]
# The checker binary is taken from FIZZ_BIN (default: fizz).
set -u

SPEC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/verify/fizz"
FIZZ_BIN="${FIZZ_BIN:-fizz}"
spec_path="${1:?usage: fizz-check.sh <spec-path> <exhaustive|simulation> [extra fizz args...]}"
mode="${2:?usage: fizz-check.sh <spec-path> <exhaustive|simulation> [extra fizz args...]}"
shift 2
name="$(basename "$spec_path")"

tmpdir="$(mktemp -d "${SPEC_DIR}/.fizz-run-XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT
cp "${SPEC_DIR}"/*.fizz "${SPEC_DIR}"/fizz.yaml "$tmpdir"/

# fizz v0.5.3 exits 0 even on invariant failure (only panics exit non-zero),
# so the verdict must also check the output lines, not just the exit status.
out="$("$FIZZ_BIN" "$@" "$tmpdir/$name" 2>&1)"
st=$?
printf '%s\n' "$out"

if [ "$mode" = exhaustive ]; then
    if [ "$st" -ne 0 ] || ! printf '%s\n' "$out" | grep -q '^PASSED: Model checker completed successfully'; then
        echo "verify-fizz: FAILED: $spec_path (exit $st)" >&2
        exit 1
    fi
else
    if [ "$st" -ne 0 ] || printf '%s\n' "$out" | grep -q '^FAILED'; then
        echo "verify-fizz-simulation: FAILED: $spec_path (exit $st)" >&2
        exit 1
    fi
fi
