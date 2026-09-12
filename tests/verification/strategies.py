# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
Shared Hypothesis strategies for L2 oracles (testing-strategies.md §3.3).

Valid-by-construction generation only — no ``.filter()`` rejection loops
(rejection above ~20% degrades shrinking). Import as::

    from tests.verification.strategies import any_text, clean_text

``st.text()`` already includes control/format characters (Cc/Cf) — that is
the *any* alphabet. ``clean_text`` excludes every C-class category so the
text_validation disallowed-character scan cannot fire (used by the
strip-window / length / printable properties where DISALLOWED is noise).
"""

from __future__ import annotations

from typing import Literal

from hypothesis import strategies as st

# Unicode general-category codes accepted by st.characters (hypothesis stubs
# type the parameter as a Collection of this Literal union).
CategoryCode = Literal[
    "L", "Lu", "Ll", "Lt", "Lm", "Lo", "M", "Mn", "Mc", "Me",
    "N", "Nd", "Nl", "No", "P", "Pc", "Pd", "Ps", "Pe", "Pi", "Pf", "Po",
    "S", "Sm", "Sc", "Sk", "So", "Z", "Zs", "Zl", "Zp",
    "C", "Cc", "Cf", "Cs", "Co", "Cn",
]

# C-class categories that map to CAT_CONTROL in src/text_validation.py
# (Cc control, Cf format, Cs surrogates, Co private use, Cn unassigned).
_C_CLASSES: tuple[CategoryCode, ...] = ("Cc", "Cf", "Cs", "Co", "Cn")
_LETTER_DIGIT: tuple[CategoryCode, ...] = ("L", "N")

# Known adversarial code points with C-class (control/format) categories —
# every one of these must trip the DISALLOWED scan regardless of
# allow_line_breaks. Verified categories: BOM/ZWSP/ZWNJ/ZWJ/LRM/RLM/word
# joiner/RLO are all Cf. (Note: U+2028/U+2029 are Zl/Zp and U+FE00 is Mn —
# those are ALLOWED characters that merely strip away; pinned separately in
# the oracle's known-corners class.)
_ADVERSARIAL_CHARS: tuple[str, ...] = (
    "\ufeff",  # BOM (Cf)
    "\u200b",  # ZWSP (Cf)
    "\u200c",  # ZWNJ (Cf)
    "\u200d",  # ZWJ (Cf)
    "\u2060",  # word joiner (Cf)
    "\u200e",  # LRM (Cf)
    "\u200f",  # RLM (Cf)
    "\u202e",  # RLO override (Cf)
)


def any_text(max_size: int = 300) -> st.SearchStrategy[str]:
    """Arbitrary text including control/format characters (totality domain)."""
    return st.text(max_size=max_size)


def clean_text(max_size: int = 300) -> st.SearchStrategy[str]:
    """Text whose characters are never in a C-class category.

    Guarantees the text_validation DISALLOWED scan cannot fire, so
    window/length/printable properties can be asserted unconditionally.
    """
    return st.text(
        alphabet=st.characters(exclude_categories=_C_CLASSES),
        max_size=max_size,
    )


def clean_visible_text(max_size: int = 300) -> st.SearchStrategy[str]:
    """Clean text guaranteed to contain at least one letter/digit.

    Generates directly (no rejection sampling): a drawn core character from
    the letter/digit pool plus optional clean filler on either side.
    """
    core = st.text(
        alphabet=st.characters(categories=_LETTER_DIGIT),
        min_size=1,
        max_size=10,
    )
    filler = st.text(
        alphabet=st.characters(exclude_categories=_C_CLASSES),
        max_size=max_size,
    )
    return st.builds(
        lambda pre, c, post: pre + c + post,
        filler,
        core,
        filler,
    )


def disallowed_somewhere(max_size: int = 100) -> st.SearchStrategy[str]:
    """Clean text with one guaranteed disallowed character inserted.

    The disallowed character is drawn from the format/Cc pool but never
    from the allowed-whitespace set (\\t, \\n, \\r), so the DISALLOWED
    verdict must fire regardless of ``allow_line_breaks``.
    """
    bad = st.sampled_from(_ADVERSARIAL_CHARS)
    filler = st.text(
        alphabet=st.characters(exclude_categories=_C_CLASSES),
        max_size=max_size,
    )
    return st.builds(
        lambda pre, b, post: pre + b + post,
        filler,
        bad,
        filler,
    )
