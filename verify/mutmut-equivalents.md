# mutmut Equivalents Ledger — Governed Survivors

> Companion to `verify/mutmut-scope.md` and `verify/mutmut-baseline.json`.
> Doctrine (testing-strategies §3.4): survivors are hints, never verdicts —
> this ledger is where a hint becomes a *decision*. A survivor may only stop
> failing the gate through the deliberate ratchet refresh
> (`make regen-mutmut-baseline`), never by ignoring the gate.

## Rules

1. Every survivor triage ends in exactly one of two states:
   - **killed**: write the missing test (preferred — do it in the same PR
     that regenerates the baseline);
   - **equivalent**: record the mutant key cluster here with a reason, then
     refresh the baseline.
2. An equivalence claim must state the *observable behaviour* that is
   unchanged, not just "the test can't see it". "The test can't see it" is a
   test gap, not an equivalence.
3. Rows are per survivor-key cluster (mutmut keys share the mutated token),
   never per individual mutant index — indices shift on every source edit.

## Known survivor clusters (from the 2026-09-11 baseline, triage pending)

The baseline seed recorded 157 survivors / 570 mutants (kill ratio 0.725).
The clusters below are ranked triage candidates — most are expected to be
test gaps (kill them), not equivalents.

| Function | Survivors | First-glance classification | Disposition |
|---|---|---|---|
| `src/validation.py::validate_with_retries` | 44/59 | **suspected test gap** — the E5 oracle drives `max_retries=2` only; loop-bound and branch-order mutants likely survive. Kill by parametrizing the retry budget and asserting exact call counts. | pending |
| `src/tools/jobs.py::_init` | 19/51 | likely gap — schema DDL string mutants are invisible to behaviour tests. Candidates for `# pragma: no mutate` once pragma semantics are verified on 3.7, or a `PRAGMA table_info` shape assertion. | pending |
| `src/text_validation.py::__init__` (StripWindow/TextVerdict) | 11/11 | **closed by R1**: `test_text_validation_internals.py::TestStripWindowInit`/`TestTextVerdictInit` now kill the constant mutants — these rows should drop out at the next full run. | expect gone at next regen |
| `src/tools/jobs.py::create_job` | 11/21 | gap — debug-log f-string mutants + `uuid4()`/timestamp interleave. Log mutants become observational if a caplog test is added; otherwise they are the ledger's first legitimate equivalents. | pending |
| `src/text_validation.py::_pattern_name_validator` / `_domain_validator` / `_freetext_validator` | 7+4+4 | partially closed by R1 direct tests; residual mutants are the `field=` literal in wrapper calls — killable by asserting the field name in error messages per validator. | pending |
| `src/validation.py::format_validation_errors` | 6/21 | gap — message-shape mutants (`[:80]` truncation, join separator) survive; kill by pinning the exact rendered string. | pending |
| `src/text_validation.py::_category_code` | 4/14 | **closed by R1**: `TestCategoryCode` pins every branch. | expect gone at next regen |
| `src/text_validation.py::evaluate_printable_text` | 4/40 | residual window-field mutants — R1's field assertions should cover most; recheck at next regen. | pending |
| `src/tools/jobs.py::_conn` | 4/5 | the `RuntimeError` guard text + condition — guard-presence is tested via a not-initialised store? if not, that is the gap. | pending |

## Entry format (for future rows)

```
| <module>::<function> | <mutant-key token cluster> | <observable behaviour unchanged> | killed-by <test id> / equivalent <reason> | <date> |
```
