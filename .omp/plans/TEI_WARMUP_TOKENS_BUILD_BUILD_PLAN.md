# Build TEI v1.9.4 from source with PR #884 (`--warmup-tokens`) in both TEI sidecar images

## Context

TEI sidecar startup is dominated by the synthetic warmup pass, not weight loading. Measured 2026-10-09 from `pattern-tei-embed` logs: backend load ~10 s, warmup `08:46:08 → 08:48:19` ≈ 131 s (Qwen3-Embedding-0.6B fp32 ONNX, `MAX_BATCH_TOKENS=8192`); `pattern-tei-rerank` warmup `08:46:00 → 08:47:18` ≈ 78 s (gte-reranker-modernbert-base, 16384). Stock image `ghcr.io/huggingface/text-embeddings-inference:cpu-1.9` has no warmup control (verified: `--help | grep warmup` → empty).

PR huggingface/text-embeddings-inference#884 adds `--warmup-tokens` / `WARMUP_TOKENS` (`0` = skip warmup entirely). PR state: **open, unmerged**, head SHA `5806bdc99f11ad490cd7e38c1f4dd757034c0adb`, +138/−10 across `backends/src/lib.rs`, `router/src/lib.rs`, `router/src/main.rs`, README, docs. Its three code hunks were diff-checked this session against the **v1.9.4 tag** sources — pre-image context matches at every hunk (`Backend::warmup(max_input_length, max_batch_tokens, max_batch_requests, padded_model)` at `backends/src/lib.rs:302`, call site `router/src/lib.rs:299-311`, `prometheus_port` arg block `router/src/main.rs:~195`), so the commit cherry-picks/appplies onto v1.9.4 cleanly or near-cleanly.

`MAX_BATCH_TOKENS` must stay at 8192 (embed) / 16384 (rerank) — measured retrieval-quality drop when lowered; user constraint. The image-level default becomes `WARMUP_TOKENS=0`.

End state: both TEI images (`docker/Dockerfile.tei-embed`, `docker/Dockerfile.tei-rerank`) build the v1.9.4 router with PR #884 from source, overwrite the stock binary in the unchanged `cpu-1.9` runtime base, expose `WARMUP_TOKENS=0` as an image ENV tunable, warmup drops from 131 s/78 s to ~0 s (container Ready ≈ backend-load time only), and embedding/rerank outputs are bit-for-bit-parity with the current images (same fp32 models, numerics untouched by the PR).

## Approach

### Step 1 — Add router builder stage + binary overwrite + `WARMUP_TOKENS` to `docker/Dockerfile.tei-embed`

Insert a new first stage **before** the existing `FROM python:3.10-slim AS model-downloader` (stage order is free; model stages stay untouched):

```dockerfile
# Stage 0: Build the TEI router from source (v1.9.4 + unmerged PR #884).
#
# PR #884 (huggingface/text-embeddings-inference#884, head 5806bdc) adds
# --warmup-tokens / WARMUP_TOKENS so the synthetic startup warmup pass can
# be skipped (0) or shrunk (N) without lowering MAX_BATCH_TOKENS. The PR is
# OPEN/UNMERGED as of 2026-10-09; both ARGs must be bumped together when
# rebasing onto a newer tag or when the PR merges (then drop the cherry-pick).
# Feature set matches the PR author's validated x86 ONNX build:
#   cargo build -p text-embeddings-router --no-default-features --features ort,http
# (TEI README's recommended x86 ONNX path is `cargo install --path router -F ort`.)
FROM rust:1.92-bookworm AS router-builder
# rust:1.92 matches upstream rust-toolchain.toml channel 1.92.0; bookworm
# matches the cpu-1.9 runtime base (Debian 12) so glibc ABI lines up.
ARG TEI_SOURCE_VERSION=v1.9.4
ARG TEI_PR884_SHA=5806bdc99f11ad490cd7e38c1f4dd757034c0adb
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch ${TEI_SOURCE_VERSION} \
        https://github.com/huggingface/text-embeddings-inference.git /usr/src/tei \
    && cd /usr/src/tei \
    && git fetch --depth 1 origin pull/884/head \
    && git cherry-pick ${TEI_PR884_SHA}
```

(Clone is detached at the v1.9.4 tag; fetching `pull/884/head` brings in the PR commit; `git cherry-pick` applies exactly that commit on top. On conflicts, see Contingency C1.)

```dockerfile
RUN cd /usr/src/tei \
    && cargo build --release -p text-embeddings-router \
        --no-default-features --features ort,http
# Binary lands at /usr/src/tei/target/release/text-embeddings-router
```

Runtime stage changes (same file, stage `FROM ghcr.io/huggingface/text-embeddings-inference:cpu-1.9`):

1. After `COPY --from=model-downloader /data /data`, add:
   ```dockerfile
   # Overwrite the stock router with the v1.9.4+PR#884 build (same feature
   # family: ORT backend, HTTP router). The cpu-1.9 base provides the shared
   # libs (glibc, onnxruntime dylib) the binary was linked against.
   COPY --from=router-builder /usr/src/tei/target/release/text-embeddings-router \
        /usr/local/bin/text-embeddings-router
   ```
2. Extend the `ENV` tunables block (currently lines 160-166): add `WARMUP_TOKENS=0` to the list. Do NOT touch `MAX_BATCH_TOKENS=8192`.
3. Extend the header "Runtime tunables" comment contract (lines 47-88) with one entry mirroring the existing style:
   ```
   #   WARMUP_TOKENS          (default in upstream TEI: unset = warm
   #                          min(max_input_length, max_batch_tokens) on CPU;
   #                          we set 0 to skip the synthetic warmup pass —
   #                          the 131s measured startup cost — via PR #884.
   #                          Positive N warms with N tokens instead; values
   #                          > MAX_BATCH_TOKENS are rejected at startup.)
   ```
4. Also note in the header that the runtime binary is a self-built v1.9.4+PR#884 router, not the stock cpu-1.9 binary.

### Step 2 — Same builder stage + overwrite + ENV in `docker/Dockerfile.tei-rerank`

Identical `router-builder` stage (verbatim Step 1 block). Runtime stage (`FROM ghcr.io/huggingface/text-embeddings-inference:cpu-1.9`, line 95): add the same `COPY --from=router-builder …` after `COPY --from=model-downloader /data /data` (line 97), add `WARMUP_TOKENS=0` to the ENV block (lines 103-109, keep `MAX_BATCH_TOKENS=16384`), extend the header tunables contract (lines 18-55) with the same `WARMUP_TOKENS` entry.

Known repo trap: the `edit` tool historically reformats Dockerfile continuation-line indentation (4-space → 2-space) producing whole-file noise (observed on the root Dockerfile). After every Dockerfile edit, run `git diff --numstat docker/Dockerfile.tei-embed docker/Dockerfile.tei-rerank` and re-do any edit that touched lines outside the intended hunks.

### Step 3 — Wire `WARMUP_TOKENS` through the dev compose

`docker/docker-compose.yml` only (grep confirmed `TEI_MAX_BATCH_TOKENS` passthroughs exist nowhere else — systemd and hub compose files carry no TEI env passthroughs; they inherit the image-level ENV default automatically):

- Embed sidecar env block (after line 115 `- MAX_BATCH_TOKENS=${TEI_MAX_BATCH_TOKENS:-8192}`):
  `- WARMUP_TOKENS=${TEI_WARMUP_TOKENS:-0}`
- Rerank sidecar env block (after line 142 `- MAX_BATCH_TOKENS=${TEI_RERANK_MAX_BATCH_TOKENS:-16384}`):
  `- WARMUP_TOKENS=${TEI_RERANK_WARMUP_TOKENS:-0}`

### Step 4 — Build embed image under a test tag (keeps the baseline image intact for parity)

From repo root (build context is `.`, per `make docker-build-tei`):

```bash
docker build -f docker/Dockerfile.tei-embed -t pattern-tei-embed:warmup-test .
```

First build ≈ 15-25 min (Rust + ort feature compile); the model-downloader stage is cache-hit from the existing build.

### Step 5 — Verify embed image (flag, linkage, timing, parity)

Sequential only — never run two TEI containers concurrently for measurements (CPU reranker contention invalidates paired reads; measured 2026-09).

1. Flag present:
   `docker run --rm pattern-tei-embed:warmup-test --help 2>&1 | grep -A3 warmup-tokens`
   → must show `--warmup-tokens <WARMUP_TOKENS>` and `[env: WARMUP_TOKENS=]`.
2. Linkage clean:
   `docker run --rm --entrypoint sh pattern-tei-embed:warmup-test -c 'ldd /usr/local/bin/text-embeddings-router | grep "not found"'` → empty output (exit 1 from grep).
3. Startup timing:
   ```bash
   docker run -d --name tei-warmup-test-embed -p 18081:8080 pattern-tei-embed:warmup-test
   time curl -sf --retry 30 --retry-delay 1 --retry-connrefused http://127.0.0.1:18081/health
   docker logs tei-warmup-test-embed 2>&1 | grep -E 'Starting model backend|Warming up|warmup skipped|Ready'
   ```
   Pass: log contains `Explicit warmup skipped via --warmup-tokens=0`, `Ready` follows `Starting model backend` within ~20 s (baseline: 131 s warmup + 10 s load). Keep this container for step 4.
4. Output parity vs baseline (`pattern-tei-embed:latest` is still the pre-change image — do not retag before this passes):
   ```bash
   docker run -d --name tei-baseline-embed -p 18080:8080 pattern-tei-embed:latest
   curl -sf --retry 30 --retry-delay 1 --retry-connrefused http://127.0.0.1:18080/health
   uv run python - <<'EOF'
   import httpx, math
   probes = [
     "layered architecture for an e-commerce checkout system",
     "event-driven microservices with sagas for distributed transactions",
     "pipe and filter data processing pipeline",
     "rule based engine for insurance claim validation",
     "reactive system with backpressure for iot telemetry ingestion",
   ]
   def embed(port):
       r = httpx.post(f"http://127.0.0.1:{port}/v1/embeddings",
                      json={"model": "m", "input": probes}, timeout=120)
       r.raise_for_status()
       return [d["embedding"] for d in r.json()["data"]]
   a, b = embed(18080), embed(18081)
   for i, (x, y) in enumerate(zip(a, b)):
       dot = sum(p*q for p, q in zip(x, y))
       nx = math.sqrt(sum(p*p for p in x)); ny = math.sqrt(sum(q*q for q in y))
       cos = dot/(nx*ny)
       print(i, f"{cos:.6f}", "OK" if cos >= 0.98 else "FAIL")
   EOF
   ```
   Pass: every cosine ≥ 0.98 (same fp32 weights and numerics — expect ≈ 1.0; 0.98 is the repo's established parity gate). Then `docker rm -f tei-warmup-test-embed tei-baseline-embed`.

### Step 6 — Build + verify rerank image

```bash
docker build -f docker/Dockerfile.tei-rerank -t pattern-tei-rerank:warmup-test .
docker run -d --name tei-warmup-test-rerank -p 18083:8080 pattern-tei-rerank:warmup-test
time curl -sf --retry 30 --retry-delay 1 --retry-connrefused http://127.0.0.1:18083/health
docker logs tei-warmup-test-rerank 2>&1 | grep -E 'Starting model backend|warmup skipped|Ready'
docker run -d --name tei-baseline-rerank -p 18082:8080 pattern-tei-rerank:latest
curl -sf --retry 30 --retry-delay 1 --retry-connrefused http://127.0.0.1:18082/health
uv run python - <<'EOF'
import httpx
q = "architecture pattern for fault isolation between microservices"
texts = ["bulkhead pattern isolates failures per dependency pool",
         "mvc separates model view controller",
         "saga coordinates distributed transactions with compensations",
         "pipe and filter transforms data streams"]
def rr(port):
    r = httpx.post(f"http://127.0.0.1:{port}/rerank", json={"query": q, "texts": texts}, timeout=120)
    r.raise_for_status(); return r.json()
a, b = rr(18082), rr(18083)
print(a); print(b)
assert [e["index"] for e in a] == [e["index"] for e in b], "ordering changed"
assert all(abs(x["score"]-y["score"]) < 1e-3 for x, y in zip(a, b)), "score drift"
print("PARITY OK")
EOF
docker rm -f tei-warmup-test-rerank tei-baseline-rerank
```

Pass: skip warning in logs, Ready ≤ ~15 s (baseline 78 s), identical ordering, score drift < 1e-3.

### Step 7 — Cutover tags, compose validation, gates

1. Retag after both parity checks pass: `docker tag pattern-tei-embed:warmup-test pattern-tei-embed:latest && docker tag pattern-tei-rerank:warmup-test pattern-tei-rerank:latest` (dev/systemd compose reference `latest`).
2. `docker compose -f docker/docker-compose.yml config -q` — validates the env additions.
3. No `src/` Python change → `make check-lint make check-static-typing make test-unit` unaffected, but run `make check-all` once as the repo's task gate.

Publishing the new TEI images to Docker Hub/GHCR (`make docker-publish-tei`) and bumping `TEI_VERSION` pins in `docker/docker-compose.hub.yml` / INSTALL.md are explicitly deferred to a follow-up release task — Hub tags still ship the old binary until then.

## Critical files & anchors

| File | Anchor | Why |
|---|---|---|
| `docker/Dockerfile.tei-embed` | new stage before `FROM python:3.10-slim AS model-downloader` (line 118); runtime ENV block lines 160-166; header tunables lines 47-88 | Builder stage + binary overwrite + `WARMUP_TOKENS=0` default |
| `docker/Dockerfile.tei-rerank` | runtime stage line 95; ENV block lines 103-109; header lines 18-55 | Same three edits |
| `docker/docker-compose.yml` | embed env after line 115, rerank env after line 142 | `TEI_WARMUP_TOKENS` / `TEI_RERANK_WARMUP_TOKENS` passthroughs |
| upstream `backends/src/lib.rs` (v1.9.4) | `Backend::warmup` at :302 | Cherry-pick target; context verified matching this session |
| `Makefile` | `docker-build-tei` :243-249 | Unchanged — builds both Dockerfiles from repo root; listed so implementer does not "fix" it |

## Verification

End-to-end proof (all in Step 5/6, summarized):

- New behavior: `docker run --rm pattern-tei-embed:warmup-test --help` shows `--warmup-tokens`; container log shows `Explicit warmup skipped via --warmup-tokens=0`; `/health` reachable ≤ 20 s after start vs 131 s baseline (embed) and ≤ 15 s vs 78 s (rerank).
- No regression: embedding cosines ≥ 0.98 on 5 diverse probes old-vs-new; rerank identical ordering, |Δscore| < 1e-3; `make check-all` green; `docker compose -f docker/docker-compose.yml config -q` clean.
- `git diff --numstat` on both Dockerfiles shows only intended hunks (no whole-file reformat).

## Assumptions & contingencies

**Assumptions** (user-set, do not revisit):

- `WARMUP_TOKENS=0` (full skip) is the image default, per explicit request — not `--warmup-tokens 64`. Overridable per deployment via compose (`TEI_WARMUP_TOKENS`).
- `MAX_BATCH_TOKENS` stays 8192 / 16384 — measured quality drop when lowered; this whole plan exists to decouple warmup from that limit.
- PR #884 stays a cherry-pick until upstream merges (watch v1.10.0 milestone); both `ARG`s are bumped together on rebase.

**Contingencies**:

- **C1 — cherry-pick conflicts** (PR is based on `main`, may have drifted at docs hunks): only the three code files matter. Fallback inside the builder stage: replace the cherry-pick with
  `git fetch --depth 1 origin pull/884/head && git diff HEAD FETCH_HEAD -- backends/src/lib.rs router/src/lib.rs router/src/main.rs | git apply --3way` — docs/README conflicts are skipped entirely.
- **C2 — cargo build failure** (missing build tool, e.g. `cmake`): add it to the builder apt line: `git ca-certificates cmake`. Do not add MKL/candle features — the ORT-only build is the validated minimal path and matches the runtime image's ORT backend.
- **C3 — `ldd` shows missing libs or container fails to start** (binary/dylib ABI mismatch with the cpu-1.9 base): locate the onnxruntime dylib the builder linked against (`find /usr/src/tei/target -name 'libonnxruntime*'` and check `~/.cargo` cache), `COPY --from=router-builder` it into `/usr/local/lib/` and set `ENV LD_LIBRARY_PATH=/usr/local/lib` (or `ORT_DYLIB_PATH` to the copied file) in the runtime stage. If still failing, last resort: switch the builder to upstream's full recipe (`--features ort,candle,mkl,static-linking` per upstream `Dockerfile`) which produces a self-contained binary — heavier build, same runtime stage.
- **C4 — parity fails on embed (cosine < 0.98)**: do NOT retag; diff `/info` output old vs new (backend, dtype, pooling) and `docker logs` backend selection lines. Since weights and features are identical this signals the ORT dylib differs — resolve via C3 first. Reranker score drift > 1e-3 with identical ordering: acceptable only if user confirms; default is to treat as failure and apply C3.
- **C5 — timing still slow**: if `Ready` > 30 s with the skip warning present, the residual is ORT session load, not warmup — that is the separate int8-variant discussion, out of scope here; report the measured split instead of iterating.
