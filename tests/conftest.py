# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
Global Hypothesis profile registration for the whole test tree
(testing-strategies.md §3.3, Phase-0 enabler).

Profiles:
    ci      — deterministic CI runs (derandomize, print_blob for replay).
              Default when HYPOTHESIS_PROFILE is unset.
    dev     — DirectoryBasedExampleDatabase so failing examples discovered
              locally replay on the next run without re-generation.
    nightly — 10x the CI example budget (opt-in stress budget).

The ``mutmut`` profile is registered separately inside
``verify/mutmut/mutmut_compat.py`` and selected via
``--hypothesis-profile=mutmut`` on the mutmut CLI; a CLI-selected profile
is applied by the hypothesis-pytest plugin after this module loads, so the
mutmut gate is unaffected by the default chosen here.

Per-test ``@settings(...)`` still overrides profile values — profiles only
fill unspecified keys.
"""

import os

from hypothesis import HealthCheck, settings
from hypothesis.database import DirectoryBasedExampleDatabase

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOCAL_DB = os.path.join(_REPO_ROOT, ".hypothesis")

settings.register_profile(
    "ci",
    max_examples=50,
    deadline=None,
    derandomize=True,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "dev",
    max_examples=50,
    deadline=None,
    print_blob=True,
    database=DirectoryBasedExampleDatabase(_LOCAL_DB),
)
settings.register_profile(
    "nightly",
    max_examples=500,
    deadline=None,
    print_blob=True,
    database=DirectoryBasedExampleDatabase(_LOCAL_DB + "-nightly"),
)

# Advisory peer backend (testing-strategies.md §3.3: "same properties,
# second engine — weak but useful peer, never treated as a proof"). Only
# registered when the CrossHair toolchain is importable (ships via the
# hypothesis[crosshair] dev extra); loaded on demand with
#   HYPOTHESIS_PROFILE=crosshair uv run pytest \
#     tests/verification/test_text_validation_properties.py \
#     tests/verification/test_scoring_properties.py
# SCOPE (deliberate): the pure decision functions where concolic search
# adds value. Symbolic execution on recursive-tree/regex-heavy strategies
# (config trees, loader fixtures) hits documented z3 path-explosion —
# those stay on the random profiles. Advisory only; never a CI gate.
try:
    import crosshair  # noqa: F401

    settings.register_profile(
        "crosshair",
        max_examples=5,  # symbolic examples are ~100x the cost of random ones
        deadline=None,
        print_blob=True,
        backend="crosshair",
    )
except ImportError:
    pass

settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
