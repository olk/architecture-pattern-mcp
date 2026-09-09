# Stub for the unicodedata stdlib module — Nagini verification subset only
# (nagini plan §3.5). Phase-0 needs exactly one function: category, declared
# PURE and UNINTERPRETED. All totality/index/termination proofs of
# src/text_validation_core.py are independent of what category returns; the
# Unicode semantics remain covered by the Hypothesis oracles and unit tests.
# Oracle assumption: category(ch) returns a two-letter category string for
# any one-character str — spot-checked by tests/verification stub conformance.
def category(c: str) -> str: ...
def is_normalized(form: str, unistr: str, /) -> bool: ...
