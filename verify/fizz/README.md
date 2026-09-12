# FizzBee Spec Suite — Property-ID Ledger and Run Stats

> Owned by the L4 section of [`docs/verification.md`](../docs/verification.md)
> (this ledger is the drift countermeasure — a PR that touches any artifact
> below must touch its row). Property IDs are shared across the `.fizz`
> models, the Hypothesis oracles
> (`tests/verification/test_jobs_properties.py`) and the conformance tests.
> Suite bounds: `fizz.yaml` (max_actions 2000, concurrency 2).

## Models (element→code maps live in each `.fizz` header)

| Model | Abstracts | Assertions |
|---|---|---|
| `jobs_protocol.fizz` | caller view of the job store protocol (`src/tools/jobs.py`: create/submit, set_running, guarded terminal UPDATEs) with symmetric crashing clients | J-1, J-2 (guard structure), J-3, J-4, FC-1, FC-2 |
| `jobs_runner.fizz` | the background task lifecycle + cancel tool (`src/tools/submit_architecture_design.py::_run_job`, `src/tools/cancel_architecture_design.py`): W0-1 checkpoints, terminal-write races, task-map bookkeeping | J-1 (kill authority), RUN-1, RUN-3, RUN-4, C-1 |
| `pipeline_control.fizz` | pipeline stage machine (`src/pipeline.py` stage order + design_loop attempts) vs an unreliable LLM environment | P-1, FP-2, FP-3, FP-4, FP-5, FP-6, FP-7 |
| `design_loop.fizz` | `ArchitecturePipeline.design_loop` triage decisions (`src/pipeline.py:1015`): best-score guard, early stop, cancel checkpoint, malformed-continue | DL-2, DL-3, DL-4, DL-5 |
| `reasoning_retry.fizz` | reasoning-client timeout/retry discipline (`src/reasoning/client.py`: wait_for budget deadline, silent degradation; `_run_cached`: LRU + single-flight) | E5F-1, E5F-2, E5F-3, E5F-4 |
| `tei_fallback.fizz` | TEI reranker verdict discipline (`src/patterns/safe_tei_rerank.py`) + the retrieval rerank-error path (`src/patterns/retriever.py`) | TEI-1, RET-1 |
| `retrieval_fusion.fizz` | retrieval resolution + fallback decision (`src/patterns/retriever.py` resolve/floor/tag tail) | FUS-1, FUS-2, FUS-3 |

## Ledger

| ID | Property (one line) | Form | FizzBee assertion | Static contract | Hypothesis oracle | Conformance test |
|---|---|---|---|---|---|---|
| `J-1` | Terminal states immutable | `always` | `jobs_protocol.fizz::J1_TerminalImmutable` (caller-view twin; `# spec-explains:` structural there — unique jids leave one writer per job) **and** `jobs_runner.fizz::J1_TerminalImmutable` (kill authority: the W0-1 terminal-write race; `GUARDED=False` flip must violate — validated) | n/a (no static contract) | `test_jobs_properties.py` shadow agreement | `test_fizz_traces.py::test_cancel_races_completion` |
| `J-2` | Cancel effective only from `pending`/`running` | `always` | `jobs_protocol.fizz::Trans` guard (A/B flip) | n/a (no static contract) | shadow automaton GUARDS | `test_fizz_traces.py::test_cancel_wins_over_completion` + `test_fizz_conformance.py` |
| `J-3` | `created_at <= updated_at` always (ISO-8601 UTC: lexicographic = chronological) | `always` | `jobs_protocol.fizz::J3_TimestampsMonotone` (logical clocks) | n/a (no static contract) | shadow `J-3` assert per step | `test_fizz_conformance.py` (per step) |
| `J-4` | At most one `RUNNING` per job | `always` | `jobs_protocol.fizz::J4_SingleRunner` (structural tripwire under atomic Trans) | n/a (no static contract) | uuid uniqueness assert | `test_fizz_conformance.py` (row existence + valid status) |
| `P-1` | Pipeline attempt loop bounded, `attempts <= 3` | `always` | `pipeline_control.fizz::P1_AttemptBound` (FG-32) | n/a (no static contract) | oracle `P-1` (planned phase F2) | planned |
| `FP-2` | No stage advance after cancellation observed | `always` | `pipeline_control.fizz::FP2_CancelStopsPipeline` | n/a (no static contract) | planned | planned |
| `FP-3` | Stage order ANALYZE→GENERATE→EVALUATE→REFINE never violated | `always` | `pipeline_control.fizz::FP3_StageOrder` | n/a (no static contract) | planned | planned |
| `FP-4` | Every run ends in exactly one terminal outcome | `always` | `pipeline_control.fizz::FP4_TotalOutcome` (FG-33) | n/a (no static contract) | planned | planned |
| `FP-5` | Every run eventually reaches a terminal outcome | `always eventually` | `pipeline_control.fizz::FP5_EventualOutcome` (progress witnesses: fair LlmCall/RunFinish, bounded RetryTick; FG-16/FG-17 must violate) | n/a (liveness beyond static scope) | n/a | n/a |
| `FP-6` | A run only ends FAILED after exhausting its attempts | `always` | `pipeline_control.fizz::FP6_NoPrematureFailure` (FG-09 must violate) | n/a | planned | planned |
| `FP-7` | A run only ends COMPLETED after all stages ran | `always` | `pipeline_control.fizz::FP7_NoPrematureCompletion` (FG-10 must violate) | n/a | planned | planned |
| `FC-1` | *FizzBee-only:* every RUNNING job of an alive client eventually leaves RUNNING | `always eventually` | `jobs_protocol.fizz::FC1_NoStuckRunning` (ownership witness = client's `inflight`; fair response actions are the progress witnesses; FG-13 must violate) + `exists FC1_Coverage` | n/a (liveness beyond static scope) | bounded — not sampleable | n/a |
| `FC-2` | *FizzBee-only:* an acknowledged cancel ends CANCELLED or was already terminal | `always` | `jobs_protocol.fizz::FC2_AckCancelEndsCancelled` (ack recorded only after the guarded write landed; FG-15 must violate) | n/a (no static contract) | planned | `test_fizz_conformance.py` |
| `RUN-1` | The runner's triage outcome matches the final store state (stored⇒COMPLETED, failed⇒FAILED, discard/race⇒CANCELLED) | `always` | `jobs_runner.fizz::RUN1_FateMatchesStore` (fate ghost; FG-02 must violate) | n/a (async/Db beyond static scope) | `test_jobs_properties.py` cancel-vs-complete races | `test_fizz_traces.py` cancel races |
| `RUN-3` | A finished task's `job_tasks` entry is always popped (no jid both finished and active) | `always` | `jobs_runner.fizz::RUN3_TaskMapInvariant` (idempotent finish; FG-14 must violate) | n/a | planned | planned |
| `RUN-4` | Every RUNNING job with a live task eventually leaves RUNNING | `always eventually` | `jobs_runner.fizz::RUN4_NoStuckRunning` (progress witnesses: fair EnvOk/EnvFail/RunFinish/Cancel + bounded fair StoreTick; FG-19 must violate) + `exists RUN4_Coverage` | n/a (liveness beyond static scope) | bounded — not sampleable | n/a |
| `C-1` | An acknowledged cancel (tool layer) ends CANCELLED and stays CANCELLED | `always` | `jobs_runner.fizz::C1_AckCancelEndsCancelled` (ack only after the guarded write; FG-15 must violate) | n/a (no static contract) | planned | `test_fizz_traces.py` cancel races |
| `E5F-1` | An expired call always carries its TIMEOUT verdict (wait_for deadline semantics — the hang-bug falsifier) | `always` | `reasoning_retry.fizz::E5F1_DeadlineVerdict` (FG-20 must violate) | n/a | E5 reasoning-client oracle (LLM-boundary discipline) | planned |
| `E5F-2` | Reasoning steps appended ≤ `min(pre_llm_thoughts, max_total_steps)` | `always` | `reasoning_retry.fizz::E5F2_StepLoopBound` (`# spec-explains:` Python `range()` bound — tripwire for a rewritten loop) | n/a | `test_jobs_properties.py::TestE5F2StepLoopBound` *(2026-09-12)* | planned |
| `E5F-3` | The trace LRU never exceeds `_CACHE_MAX_ENTRIES` | `always` | `reasoning_retry.fizz::E5F3_CacheBound` (FG-21 must violate) | n/a | `test_jobs_properties.py::TestE5F3CacheBound` *(2026-09-12)* | planned |
| `E5F-4` | At most one concurrent trace generation per cache key (single-flight) | `always` | `reasoning_retry.fizz::E5F4_SingleFlight` (FG-22 must violate) | n/a | `test_jobs_properties.py::TestE5F4SingleFlight` *(2026-09-12)* | planned |
| `TEI-1` | A TEI result body exists only for the OK verdict — errors are pure signals | `always` | `tei_fallback.fizz::TEI1_ResultOnlyOnOk` (FG-23 must violate) | n/a | `test_tei_rerank_properties.py::TestTEI1*` *(2026-09-12; found+fixed the empty-200-body raw-JSONDecodeError leak)* | `test_fizz_conformance.py` |
| `RET-1` | A rerank error propagates — never a partial/un-reranked outcome | `always` | `tei_fallback.fizz::RET1_NoPartialOnRerankError` (FG-24 must violate) | n/a | `test_tei_rerank_properties.py::TestRET1ErrorPropagates` *(2026-09-12)* | `test_fizz_conformance.py` |
| `FUS-1` | A REAL outcome always carries ≥ 1 resolved pattern (empty recall must fall back) | `always` | `retrieval_fusion.fizz::FUS1_RealHasPatterns` (FG-25 must violate) | n/a | `test_retrieval_fusion_properties.py::TestFusionDecisionLaws` *(2026-09-12)* | `test_fizz_conformance.py` |
| `FUS-2` | A REAL outcome always passed the `min_fusion_score` gate | `always` | `retrieval_fusion.fizz::FUS2_RealPassedFloor` (FG-26 must violate) | n/a | `test_retrieval_fusion_properties.py::TestFusionDecisionLaws` *(2026-09-12)* | `test_fizz_conformance.py` |
| `FUS-3` | Every fallback carries the `is_fallback` sentinel (never outranks a real match) | `always` | `retrieval_fusion.fizz::FUS3_FallbackTagged` (FG-27 must violate) | n/a | `test_retrieval_fusion_properties.py::TestFusionDecisionLaws` *(2026-09-12)* | `test_fizz_conformance.py` |
| `DL-2` | `best_score` never decreases (guarded update is the only writer) | `always` | `design_loop.fizz::DL2_BestScoreMonotone` (FG-28 must violate) | n/a | planned | planned |
| `DL-3` | Once cancellation is observed no further attempt starts | `always` | `design_loop.fizz::DL3_CancelFreezesAttempts` (FG-29 must violate) | n/a | planned | planned |
| `DL-4` | A malformed attempt retries, never ends the loop early | `always` | `design_loop.fizz::DL4_MalformedContinues` (FG-30 must violate) | n/a | planned | planned |
| `DL-5` | Early stop only fires at/above the quality threshold | `always` | `design_loop.fizz::DL5_EarlyStopThreshold` (FG-31 must violate) | n/a | planned | planned |
| `N-1..N-4` | normalization idempotence (N-1) and dedup/coverage/subset (N-2..N-4) | n/a | n/a — pure decision logic, no interleavings; pinned by the L2 Hypothesis oracle, not a `.fizz` model | n/a (no static contract) | `test_normalization_idempotence.py` | `tests/unit/test_normalization.py` |

## Spec garden (vacuity authority for model assertions, testing-strategies §3.4)

Every `always` assertion must kill at least one spec-garden mutant or carry
a `# spec-explains:` justification (AGENTS.md rule). The Python-side garden
lives in `tests/verification/gardens/`; the `.fizz`-side mutants below were
executed with the provisioned toolchain on 2026-09-10 (each row = flip one
model element, expect a violation; re-validated after the F1–F6 model
changes). The `jobs_protocol` rows were re-validated on 2026-09-11 after
the Complete/Fail guard tightening (FG-03 panic, FG-04 J3, FG-05 FC2,
FG-13 FC1, FG-15 structurally unreachable — see row). Since 2026-09-11 the
revalidation is mechanical: every row has an executable encoding in
`verify/fizz/garden.toml`, and `make verify-fizz-garden`
(scripts/fizz_garden.py) re-runs the full garden in hermetic temp copies —
all 30 executable rows behaved as documented on the 2026-09-11 run
(28 expect-fail killed on their documented assertion, FG-11 correctly
inert, FG-32/FG-33 added by the coverage audit, see their rows).

| Garden ID | Mutated element | Assertion that must fire |
|---|---|---|
| FG-01 | `jobs_runner`: drop the `GUARDED` terminal check (`GUARDED=False`) | `J1_TerminalImmutable` (the A/B flip; moved from jobs_protocol — unique jids left no second-write path there) |
| FG-02 | `jobs_runner`: guard swap — only `COMPLETED` writable | `RUN1_FateMatchesStore` (set_running rejected → PENDING ≠ CANCELLED fate) |
| FG-03 | `jobs_protocol`: `Submit` forgets to set `created[jid]` | `J3_TimestampsMonotone` (missing-key panic / stale clock) |
| FG-04 | `jobs_protocol`: `Submit` stamps `created[jid] = clock + 1` (future timestamp) | `J3_TimestampsMonotone` (replaces the pre-F1 "Trans skips updated" row — that flip provably cannot violate, `updated` never falls below `created`) |
| FG-05 | `jobs_protocol`: make `Trans` non-atomic (yield inside) | `FC2_AckCancelEndsCancelled` (pre guard-tightening this flip blew the model budget at concurrency 2; the tightened Complete/Fail requires shrank the graph so the non-atomic interleavings now fit and the ack bookkeeping violation fires — `Trans` atomicity is what protects the ack) |
| FG-06 | `pipeline_control`: `FailAttempt` does not increment | `FP5_EventualOutcome` (attempt exhaustion becomes unreachable — the loop can never fail out) |
| FG-07 | `pipeline_control`: `UserCancel` observes the cancel but does not terminalize the run (drops `CancelRun`) | `FP2_CancelStopsPipeline` (stage advances while cancelled and alive) |
| FG-08 | `pipeline_control`: `Advance` past stage count without witness | `FP3_StageOrder` |
| FG-09 | `pipeline_control`: `FailRun` guard `attempts >= MAX_ATTEMPTS` dropped | `FP6_NoPrematureFailure` (premature FAILED; retargeted from FP-4 — FAILED is a legal terminal value for FP-4) |
| FG-10 | `pipeline_control`: `Finish` guard on stage count dropped | `FP7_NoPrematureCompletion` (premature COMPLETED; retargeted from FP-3 — the guard is not the order witness) |
| FG-11 | `pipeline_control`: drop `_order_violation` bookkeeping | nothing fires — demonstrates the witness is the only falsifier of FP-3 (FP-3's kill is FG-08; the row stays as the vacuity-direction check) |
| FG-12 | *retired* — "Submit sets RUNNING directly" killed nothing after the budget/jid changes (cancel from RUNNING is legal, J-1 untouched); the direct-RUNNING class is covered by FG-02 in jobs_runner |
| FG-13 | `jobs_protocol`: drop the progress fairness on `Cancel`/`Complete`/`Fail` (the FC-liveness-assumption flip) | `FC1_NoStuckRunning` (without a fair response action the stutter-only schedule counts) |
| FG-14 | `jobs_runner`: drop the done-callback finish cleanup (`active`/`active_count` never cleared) | `RUN3_TaskMapInvariant` |
| FG-15 | `jobs_protocol` / `jobs_runner`: Cancel acks without the store write | *retargeted 2026-09-11* — no `.fizz` flip fires any more: with globally unique jids a client's inflight never points at a terminal job, so Cancel's guarded `Trans` always lands before the ack (validated on both specs, incl. the runner's raced-path flip, which is dead under atomic actions). FC2/C1 carry `# spec-explains:` tripwire justifications; the ack-without-landed-write bug class is killed on the REAL code by the L4 conformance vacuity plant (`test_fizz_conformance.py::_CancelNeverLandsStore`) |
| FG-16 | `pipeline_control`: drop `fair` on `RunFinish` | `FP5_EventualOutcome` (stutter-only schedules keep `outcome == None`) |
| FG-17 | `pipeline_control`: unbounded `RetryTick` (drop `MAX_TICKS`; validated at max_actions 60 — at the suite bound the tick dimension dominates the graph) | `FP5_EventualOutcome` (fair tick self-loop) |
| FG-19 | `jobs_runner`: unbounded `StoreTick` (drop `MAX_STUCK`; validated at max_actions 40 — at the suite bound the stuck dimension dominates) | `RUN4_NoStuckRunning` (fair tick self-loop) |
| FG-20 | `reasoning_retry`: `Tick` reaches zero without writing the verdict | `E5F1_DeadlineVerdict` |
| FG-21 | `reasoning_retry`: drop the LRU eviction | `E5F3_CacheBound` |
| FG-22 | `reasoning_retry`: drop the single-flight `inflight` guard | `E5F4_SingleFlight` |
| FG-23 | `tei_fallback`: `HTTP_ERROR` also produces a result | `TEI1_ResultOnlyOnOk` |
| FG-24 | `tei_fallback`: `RerankErr` produces a REAL outcome (partial result) | `RET1_NoPartialOnRerankError` |
| FG-25 | `retrieval_fusion`: `ResolveNone` produces REAL | `FUS1_RealHasPatterns` |
| FG-26 | `retrieval_fusion`: floor gate dropped | `FUS2_RealPassedFloor` |
| FG-27 | `retrieval_fusion`: fallback without the `is_fallback` tag | `FUS3_FallbackTagged` |
| FG-28 | `design_loop`: unconditional best update (drop the `>` guard) | `DL2_BestScoreMonotone` |
| FG-29 | `design_loop`: drop the loop-top cancel checkpoint | `DL3_CancelFreezesAttempts` |
| FG-30 | `design_loop`: Malformed terminates the loop | `DL4_MalformedContinues` |
| FG-31 | `design_loop`: early stop below the threshold | `DL5_EarlyStopThreshold` |
| FG-32 | `pipeline_control`: drop the `FailAttempt` bound (`attempts < MAX_ATTEMPTS`) | `P1_AttemptBound` *(added 2026-09-11 — audit finding: P-1 had no kill mutant; the AGENTS.md coverage rule was unmet)* |
| FG-33 | `pipeline_control`: `Finish` writes a non-terminal outcome | `FP4_TotalOutcome` *(added 2026-09-11 — audit finding: FP-4 had no kill mutant)* |

Every row above has a machine-executable encoding in `verify/fizz/garden.toml`
(same ID set, same expected assertion — `scripts/fizz_garden.py` enforces 1:1
agreement between this table and that file, plus the AGENTS.md assertion-
coverage rule, on every `make verify-fizz-garden` run and in the toolchain-free
`tests/verification/test_fizz_garden.py` checks). Mutations are applied to a
hermetic temp copy — the working tree is never touched.

`J4_SingleRunner` carries its justification: with atomic `Trans` it is
structural — it exists as the tripwire that fires the moment a future change
makes store actions non-atomic (`# spec-explains:`).

## Model-authoring rules learned on the toolchain (2026-09-10)

These are the dialect facts the suite now depends on (fizz v0.5.3+, current
HEAD behaviour):

- **Liveness semantics:** `always eventually P` excludes stutter-only
  schedules only when a fair action is continuously enabled in every
  P-false state; a *fair self-loop* in the P-false region is a violation.
  Every liveness assertion therefore needs (a) fair progress actions and
  (b) cycle-free non-terminal regions — unbounded fair ticks self-loop and
  must be bounded (MAX_TICKS / MAX_STUCK).
- **Simulator stutter rule:** the seeded simulator (`-x`) samples actions
  whose *in-any requires* fail as no-op picks and flags them as
  stuttering. `require` must stay outside `any`/`oneof` blocks; role
  actions address their single instance directly.
- **No parameterized actions:** role/top-level actions take no arguments —
  per-instance selection uses `any VAR in COLLECTION` (deprecated in favour
  of `oneof VAR in COLLECTION` in current HEAD; the suite uses the
  statement form).
- **No dict.pop / dict comprehensions:** eviction and counters are modelled
  with scalar witnesses instead.
- **Missing-key reads panic:** dict reads must use `.get(...)` whenever the
  key may be absent (assertions included).

## Run stats (exhaustive runs, fizz v0.5.3, 2026-09-10)

| Spec | Status | Unique states | Wall time |
|---|---|---|---|
| `jobs_protocol.fizz` | PASSED (F1: RUNNING status + StartRun; globally unique jids — per-client counters collided across symmetric clients and broke FC-2's ack bookkeeping; submit budget 1; fair Cancel/Complete/Fail; FC-1/FC-2 + exists coverage. **2026-09-11 guard tightening:** Complete/Fail now require RUNNING, mirroring `set_completed`/`set_failed` — the L4 conformance harness caught the model accepting PENDING→COMPLETED/FAILED, which the real guards reject; 487 → 307 states) | 307 | 1.1 s |
| `pipeline_control.fizz` | PASSED (F1: FP-5 liveness; fair LlmCall/RunFinish; RetryTick bounded by MAX_TICKS) | 196 | 0.3 s |
| `jobs_runner.fizz` | PASSED (F2+F3: W0-1 races with crash_on_yield off for the runner, idempotent done-callback finish, phase gate, bounded fair StoreTick) | 458 | 2.0 s |
| `design_loop.fizz` | PASSED (F6b: DL-2..DL-5) | 154 | 0.2 s |
| `reasoning_retry.fizz` | PASSED (F4: E5F-1..E5F-4) | 4 213 | 6.7 s |
| `tei_fallback.fizz` | PASSED (F5: TEI-1, RET-1) | 19 | <0.1 s |
| `retrieval_fusion.fizz` | PASSED (F6a: FUS-1..FUS-3) | 4 | <0.1 s |
| `jobs_runner.fizz` A/B flip `GUARDED=False` | validated 2026-09-10: `J1_TerminalImmutable` violation trace reproduces the pre-Week-0 bug; `make verify-fizz` gate fails (exit ≠ 0) | — | — |
| `pipeline_control.fizz` FG-16/FG-17 flips | validated 2026-09-10: both violate `FP5_EventualOutcome` | — | — |

Note: fizz v0.5.3 exits 0 even on invariant failure — the `verify-fizz`
Make targets therefore check for the `PASSED` verdict line (exhaustive) /
absence of `FAILED` (simulation) in addition to the exit code.

The frozen counterexample replayed against the real implementation lives in
`tests/verification/test_fizz_traces.py` and runs in every
`make test-oracles` pass regardless of tool availability.

## Conformance corpus (L4 model→code replay, added 2026-09-11)

`scripts/fizz_traces.py` runs a spec exhaustively (hermetic temp copy,
`--no-symmetry-reduction`), decodes the protobuf state graph
(`nodes_*.pb` / `adjacency_lists_*.pb` — `graph.dot` is skipped above 250
visited nodes upstream), and exports the canonical graph to
`tests/verification/fizz_corpus/<spec>.json`. The graph, not a flat trace
list, is the checked-in artifact: it is byte-deterministic across runs and
~10x smaller than rooted trace sets for tree-ish graphs.

`tests/verification/test_fizz_conformance.py` re-derives rooted
edge-covering walks (100% of non-stutter edges — asserted per spec) and
replays them against the real implementation — the Python-native stand-in
for FizzBee MBT adapters (upstream ships Go/Java/Rust/TypeScript only):

| Corpus | Replay style | Real code under test | Properties checked on real code |
|---|---|---|---|
| `jobs_protocol` (307 nodes) | step-by-step, guard-outcome agreement per action | `src/tools/jobs.py` `JobsStore` | J-1, J-2, J-3, J-4, FC-2 |
| `tei_fallback` (19 nodes) | outcome-equivalence, one `retrieve()` per trace with injected TEI transport | `src/patterns/safe_tei_rerank.py`, rerank block of `src/patterns/retriever.py` | TEI-1, RET-1 |
| `retrieval_fusion` (4 nodes) | outcome-equivalence, resolution tail | resolution/fallback of `src/patterns/retriever.py` | FUS-1, FUS-2, FUS-3 |

Interleavings dedup to distinct real-code execution signatures (client
symmetry, job-id renaming, independent jobs) — the corpus graph coverage
claim stays model-side; the replay claim is per distinct execution.
Vacuity: planted mutants (`_CancelNeverLandsStore` FG-15 class,
`_StaleClockStore` J-3 clock-skew class, `_ErrorSwallowingReranker` FG-23
class) must fire the harness. Regenerate corpora with
`make regen-fizz-traces` whenever a covered spec changes (same PR).
