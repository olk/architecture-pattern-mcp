#!/usr/bin/env bash
# FizzBee Docker wrapper (fizzbee plan §3.2) — command-compatible with the
# native `fizz` binary for machines without Homebrew. Set FIZZ=scripts/fizz-docker.sh
# for the Make targets. The repo root is mounted read-only at /work.
set -euo pipefail

IMAGE="ghcr.io/fizzbee-io/fizzbee:latest"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Map a spec path into the container: verify/fizz/x.fizz -> /work/verify/fizz/x.fizz
ARGS=()
for arg in "$@"; do
  case "$arg" in
    /*) ARGS+=("$arg") ;;
    *) ARGS+=("/work/$arg") ;;
  esac
done

exec docker run --rm -v "${ROOT}:/work:ro" -w /work "${IMAGE}" "${ARGS[@]}"
