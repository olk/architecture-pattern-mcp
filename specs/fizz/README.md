# FizzBee Spec Suite — Property-ID Ledger and Run Stats

> Owned by [`docs/fizzbee-verification-plan.md`](../docs/fizzbee-verification-plan.md)
> (§3.4: this ledger is the drift countermeasure — a PR that touches any
> artifact below must touch its row). Property IDs are shared across the
> `.fizz` models, the Nagini twins (`verify/twin/`), the Hypothesis oracles
> (`tests/verification/test_jobs_properties.py`) and the conformance tests.
> Suite bounds: `fizz.yaml` (max_actions 2000, concurrency 2).

## Ledger

| ID | Property (one line) | Form | FizzBee assertion | Nagini twin contract | Hypothesis oracle | Conformance test |
|---|---|---|---|---|---|---|
| `J-1` | Terminal states immutable | `always` | `jobs_protocol.fizz::J1_TerminalImmutable` (ghost `_left_terminal`; `GUARDED=False` flip must violate) | `verify/twin/jobs_state_twin.py` invariant | `test_jobs_properties.py` shadow agreement | `test_fizz_traces.py::test_cancel_races_completion` |
| `J-2` | Cancel effective only from `pending`/`running` | `always` | `jobs_protocol.fizz::Trans` guard (A/B flip) | twin `J-2` | shadow automaton GUARDS | `test_fizz_traces.py::test_cancel_wins_over_completion` |
| `J-3` | `created_at <= updated_at` always (ISO-8601 UTC: lexicographic = chronological) | `always` | `jobs_protocol.fizz::J3_TimestampsMonotone` (logical clocks) | twin `J-3` | shadow `J-3` assert per step | conformance |
| `J-4` | At most one `RUNNING` per job | `always` | `jobs_protocol.fizz::J4_SingleRunner` (structural tripwire under atomic Trans) | twin `J-4` | uuid uniqueness assert | conformance |
| `P-1` | Pipeline attempt loop bounded, `attempts <= 3` | `always` | `pipeline_control.fizz::P1_AttemptBound` | `verify/twin/pipeline_control_twin.py` | oracle `P-1` (planned phase F2) | planned |
| `FP-2` | No stage advance after cancellation observed | `always` | `pipeline_control.fizz::FP2_CancelStopsPipeline` | twin extension candidate | planned | planned |
| `FP-3` | Stage order ANALYZE→GENERATE→EVALUATE→REFINE never violated | `always` | `pipeline_control.fizz::FP3_StageOrder` | twin extension candidate | planned | planned |
| `FP-4` | Every run ends in exactly one terminal outcome | `always` | `pipeline_control.fizz::FP4_TotalOutcome` | twin `Exsures` coverage | planned | planned |
| `FC-1` | *FizzBee-only:* every RUNNING job of an alive client eventually leaves RUNNING | ghost stuck-timer + `fair StoreTick` (per-job response encoding, fizzbee plan §3.3 form rule) | planned F1 addition | n/a (liveness beyond twin scope) | bounded — not sampleable | n/a |
| `FC-2` | *FizzBee-only:* an acknowledged cancel ends CANCELLED or was already terminal | `always` | planned F1 addition | future twin extension | planned | planned |

## Spec garden (vacuity authority for model assertions, testing-strategies §3.4)

Every `always` assertion must kill at least one spec-garden mutant or carry a
`# spec-explains:` justification (AGENTS.md rule). The Python-side garden
lives in `tests/verification/gardens/`; the `.fizz`-side mutants below are
executed by `fizz` when the toolchain is provisioned (each row = flip one
model element, expect a violation):

| Garden ID | Mutated element | Assertion that must fire |
|---|---|---|
| FG-01 | `jobs_protocol`: drop the `GUARDED` terminal check (`GUARDED=False`) | `J1_TerminalImmutable` |
| FG-02 | `jobs_protocol`: allow cancel from `COMPLETED` only (guard set swap) | `J1`/`J2` via Cancel trace |
| FG-03 | `jobs_protocol`: `Submit` forgets to set `created[jid]` | `J3_TimestampsMonotone` (key error / stale clock) |
| FG-04 | `jobs_protocol`: `Trans` skips `updated[jid] = clock` | `J3_TimestampsMonotone` |
| FG-05 | `jobs_protocol`: make `Trans` non-atomic (yield inside) | `J4_SingleRunner` tripwire |
| FG-06 | `pipeline_control`: `FailAttempt` does not increment | `P1_AttemptBound` unreachable-terminal / liveness |
| FG-07 | `pipeline_control`: allow `Advance` after `outcome` set | `FP2_CancelStopsPipeline` |
| FG-08 | `pipeline_control`: `Advance` past stage count without witness | `FP3_StageOrder` |
| FG-09 | `pipeline_control`: `FailRun` guard `attempts >= MAX_ATTEMPTS` dropped | `FP4_TotalOutcome` (premature FAILED) |
| FG-10 | `pipeline_control`: `Finish` guard on stage count dropped | `FP3_StageOrder` |
| FG-11 | `pipeline_control`: drop `_order_violation` bookkeeping | `FP3_StageOrder` vacuous |
| FG-12 | `jobs_protocol`: `Submit` sets status `RUNNING` directly | `J1`/`J2` transition matrix |

`J4_SingleRunner` carries its justification: with atomic `Trans` it is
structural — it exists as the tripwire that fires the moment a future change
makes store actions non-atomic (`# spec-explains:`).

## Run stats (exhaustive runs; update on tool provisioning)

| Spec | Status | Unique states | Wall time | Peak RSS |
|---|---|---|---|---|
| `jobs_protocol.fizz` | pending (`fizz` not yet provisioned; target < 1 min) | — | — | — |
| `pipeline_control.fizz` | pending (budget-capped ≤ 5 min) | — | — | — |
| `jobs_protocol.fizz` A/B flip `GUARDED=False` | pending; expected: `J1` violation trace reproducing the pre-Week-0 bug | — | — | — |

The frozen counterexample replayed against the real implementation lives in
`tests/verification/test_fizz_traces.py` and runs in every
`make verify-hypothesis-oracles` pass regardless of tool availability.
