# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
Deterministic regression pin: per-PID basetemp isolation for the mutmut gate
(plan .opencode/plans/plan-mutmut-pytest-tmp-race.md, file 3).

The gate's parallel pytest children used to share pytest's default tmp root
(/tmp/pytest-of-<user>/), where ~one-symlink-swap-per-session on
``pytest-current`` races other children's ``cleanup_dead_symlinks`` teardown:
the child dies with FileNotFoundError and scripts/mutmut_baseline.py records
the nonzero exit as "killed" (silent kill-ratio inflation; RC1). The fix pins
every mutmut pytest run to ``$MUTMUT_PYTEST_TMP/p<pid>`` via
verify/mutmut/mutmut_compat.py's pytest_configure (mechanism B). These tests
pin that hook's contract — they are NOT a race test (environmental races get
no flaky unit tests; the mutation gate itself is the race oracle):

- with MUTMUT_PYTEST_TMP set, the hook yields a per-PID ABSOLUTE basetemp
  under that root and pre-creates the root (Makefile contract);
- an explicit user --basetemp is never overridden;
- without the env var, the hook falls back to a self-cleaning
  process-unique mkdtemp root (removed by pytest_unconfigure).
"""

import os
from pathlib import Path

import pytest

from verify.mutmut import mutmut_compat


class _FakeOption:
    """Just the attribute the hook is allowed to touch: option.basetemp."""

    def __init__(self, basetemp: str | None) -> None:
        self.basetemp = basetemp


class _FakeConfig:
    def __init__(self, basetemp: str | None = None) -> None:
        self.option = _FakeOption(basetemp)


@pytest.fixture
def isolation_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Env contract set to a NOT-yet-existing root: the hook must create it."""
    root = tmp_path / "pytest-tmp"
    monkeypatch.setenv("MUTMUT_PYTEST_TMP", str(root))
    return root


def test_env_root_pins_per_pid_absolute_basetemp(isolation_root: Path) -> None:
    config = _FakeConfig()
    mutmut_compat.pytest_configure(config)

    basetemp = config.option.basetemp
    assert isinstance(basetemp, str)
    expected = (isolation_root / f"p{os.getpid()}").absolute()
    assert Path(basetemp) == expected
    assert isolation_root.is_dir()  # hook pre-creates the Makefile-exported root


def test_explicit_user_basetemp_is_never_overridden(isolation_root: Path) -> None:
    chosen = isolation_root.parent / "user-choice"
    config = _FakeConfig(basetemp=str(chosen))

    mutmut_compat.pytest_configure(config)

    assert config.option.basetemp == str(chosen)


def test_missing_env_falls_back_to_selfcleaning_pid_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MUTMUT_PYTEST_TMP", raising=False)
    config = _FakeConfig()

    mutmut_compat.pytest_configure(config)
    basetemp = config.option.basetemp
    assert isinstance(basetemp, str)
    assert f"p{os.getpid()}" in Path(basetemp).parts
    fallback_root = Path(basetemp).parent
    assert fallback_root.is_dir()  # parent root exists; pytest creates the leaf

    mutmut_compat.pytest_unconfigure(config)
    assert not fallback_root.exists()  # fallback root removed with the session
