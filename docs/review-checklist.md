# Review Checklist — critical paths of the verification program

> L10 (human review + canaries, testing-strategies.md §3.10). Humans remain
> the oracle for T2 (is the design good?) and for the judgment calls the
> mechanical layers cannot make. This checklist names the paths where review
> is REQUIRED, and the questions the reviewer answers explicitly.

## Required-review paths (PR cannot merge without a human pass)

| Path | Why it is critical | Reviewer must confirm |
|---|---|---|
| `src/tools/jobs.py` transition setters / guards | J-1/J-2 live here; every later proof (twin, `.fizz`, DST) claims what this file does | Guard sets unchanged or deliberately changed WITH the matching twin + `.fizz` + oracle + ledger updates in the same PR (AGENTS.md rule) |
| `src/pipeline.py` control flow (stage order, attempt bound, cancellation checkpoints) | P-1/FP-2..FP-4 claims | `.fizz` model updated in the same PR; `make verify-fizz` re-run |
| `verify/**` (twins, stubs, contracts shim) | Unproven oracle assumptions — reviewed like source (nagini plan §3.1 principle 4) | Stub assumptions flagged; twin contracts crash-free at call time; no ghost machinery in `src/` |
| `specs/fizz/**` property-claim changes | Model assertions are claims about the implementation | Ledger row updated; assertion kills ≥ 1 spec-garden mutant or carries `# spec-explains:`; bounds still justified |
| `tests/verification/gardens/` | The vacuity authority | New mutants have working kills; weakened mutants documented |
| Secret canary surfaces (`tests/verification/test_secret_canary.py`) | Tier-E information-flow assurance | Capture surfaces still cover payloads/logs/persisted state; negative controls intact |

## Vacuity triage (every review of oracle-bearing changes)

1. Could this test/assertion pass on a broken implementation? (If yes:
   reject or plant a garden mutant that proves the opposite.)
2. Does each new `Requires`/`Ensures`/`.fizz` assertion kill at least one
   garden mutant (AGENTS.md rule)? Non-trivial contracts only.
3. Weakened bounds or guards? Diff `fizz.yaml`, frontmatter, and `MAX_*`
   constants — bound relaxation needs a ledger reason.

## Bound / fairness justification (model changes)

- Every model bound is a named `MAX_*` constant with the
  model-bound-vs-protocol-limit comment (fizzbee plan §3.1 principle 4).
- No liveness claim without a `# liveness-assumption:` comment and ledger
  entry — an unfounded `fair` silently weakens the claim (§3.7).
- A spec that doubled its state count without doubling its properties is a
  defect (S2′ prune rule).

## Canary discipline (post-merge)

- Nightly TCB canaries (`.github/workflows/verification.yml`): gardens,
  oracle suites, ledger, inventory, perf smoke. A mutant that stops being
  killed after a dependency bump blocks the bump until triaged (§6.3/§6.4).
- `continue-on-error` jobs are ADVISORY: findings are leads that must be
  triaged, never silent green.
- Performance smoke (RUN_PERF): proofs guarantee functional correctness, not
  performance — budget breaches on verified cores block the refactor (AxDafny
  lesson, nagini plan §5.5).

## T2 boundary reminder

Mechanical layers never judge design quality. Architecture designs are judged
by evaluation rubrics and human review — that boundary is the core claim of
`formal_verification.md`, and L9's invariants stop exactly at it.
