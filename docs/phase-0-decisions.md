# Phase-0 Decisions — architecture-pattern-mcp

> Shared decision record for the verification program (Nagini Phase-0
> Go/No-Go, FizzBee F0 gate, DST experiment — both plans §6.2/§6.3). Started
> 2026-09-09 with the Week-0 section; each later phase appends its outcomes
> here before its gate is evaluated.

## Week 0 — fix-before-proof baseline

**Reference point for the FizzBee F0 A/B flip:** the pre-fix state is commit
`b497f54` ("docs: verification program plans"); the fix lands in the next
commit. The falsifiable check was executed against that state: a standalone
reproduction of the frozen race trace (create → set_running → set_completed →
set_cancelled) moved the job `COMPLETED → CANCELLED`, confirming the J-1
violation the September 2026 review predicted. Post-fix, the same sequence
raises `JobStateError` and the job stays `COMPLETED`.

### W0-1 — Guarded transitions in `src/tools/jobs.py` (delivered)

- All four transition setters use guarded `UPDATE`s
  (`WHERE id = ? AND status [IN] (...)`) and inspect `cursor.rowcount`;
  rejection raises `JobStateError` (new, `src/errors.py`) carrying `job_id`
  and the re-read current status.
- Guard matrix: `set_running` from `pending`; `set_completed`/`set_failed`
  from `running`; `set_cancelled` from `pending, running`.
- `cancel_architecture_design` maps a guard rejection to the honest
  "already {status}; cannot cancel" response (`cancelled: False`).
- `submit_architecture_design._run_job`: terminal writes that lost a race to
  cancel are suppressed (`set_completed`, `set_failed`); a `set_running`
  rejection (cancel won before the job went running) exits the task cleanly.
  This is the sole deliberate exemption from the no-runtime-change rule
  (nagini-verification-plan.md §3.9).
- Tests: exhaustive transition matrix (4 setters × 5 statuses), terminal
  immutability, frozen race trace (`test_cancel_races_completion_frozen_trace`
  — the future FizzBee §5.1 anchor), cancel-tool honest mapping, three
  `_run_job` race outcomes. Three existing tests that encoded the old
  unconditional-overwrite behaviour were updated under the exemption.

**Acceptance outcome:** `make check-lint check-static-typing test-unit check-deadcode check-depcheck`
green (905 unit tests); pre-fix reproduction executed (see above).

**Property IDs made true of the implementation:** `J-1` (terminal states are
immutable), `J-2` (cancellation effective only from `pending`/`running`).

### W0-2 — Constructor-injectable `JobsStore` lock (E6, delivered)

- `JobsStore.__new__(cls, lock=None)` stores a per-instance `_init_lock`
  (default: the shared class lock); `get_instance(lock=...)` accepts the same
  override for its init critical section. Singleton semantics,
  `reset_for_test()` and `close()` behaviour unchanged.
- Test: two stores constructed with independent locks initialize and operate
  interleaved lifecycles on separate DB files without deadlock; default
  singleton path asserted unchanged.

**Acceptance outcome:** full unit suite green; parallel-store smoke passes.

### W0-3 — Secret canary, E4-extended

Delivered with the L1 layer commit (testing-strategies §3.2): see
`tests/verification/test_secret_canary.py` once that commit lands.

### W0-4 — This record (delivered)

## Environment provisioning notes (recorded for the Phase-0 gate)

The local environment cannot resolve the external verifier toolchains
(`nagini[mcp]`, `fizzbee`, `simloom`/`frontrun`, `mutmut`). Per the plans'
opt-in design (`RUN_VERIFY=1`, Docker routes), their artifacts are delivered
complete and tool-gated: the Make targets check for the binary/package and
fail with install guidance only when actually run. Consequences recorded per
layer in the respective commits:

- **Nagini (L5):** DISABLED — `nagini-contracts` not installable, Python 3.14+
  compatibility issues with contract library, and Nagini 1.3.1 cannot translate
  Unicode operations in text_validation_core. The `verify/twin/` directory was
  removed. The `*_core.py` splits remain contract-ready (pure, typed, mypy-strict).
- **FizzBee (L4):** specs and ledger are complete; `make verify-fizz` runs
  the exhaustive checks when the `fizz` binary (or
  `scripts/fizz-docker.sh`) is on PATH.
- **DST (L6):** the experiment ran natively and **passed**: exhaustive
  micro-step interleaving of the cancel/completion race (all 6
  order-preserving schedules) plus seeded real-asyncio races (5 seeds,
  pre-yield-shifted interleavings) prove **both members of the discriminating
  pair J-1/J-2** on the real `JobsStore` (E1 acceptance threshold exceeded),
  with a can-fail oracle asserting the guard *rejects* the historical race
  schedule. simloom/frontrun swap-in remains pending tool provisioning; the
  harness scenarios and oracles map 1:1 onto
  `@simloom.test(systematic=True, max_delays=N)` / frontrun DPOR.
