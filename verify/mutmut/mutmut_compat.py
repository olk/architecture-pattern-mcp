# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
mutmut compatibility shim for this repo's import package literally named
``src`` (root-relative layout, hatch ``packages = ["src"]``).

Upstream limitation (mutmut 3.7.0): mutmut assumes ``src/`` is a src-LAYOUT
container whose contents are imported WITHOUT the prefix —

1. ``record_trampoline_hit`` asserts recorded module names never start with
   ``src.``;
2. ``get_mutant_name`` unconditionally strips the ``src.`` prefix from
   path-derived mutant keys.

Here the package itself is ``src.*`` (every test does ``from src.x import
...``), so legitimate trampoline hits assert away and the recorded keys can
never match the stripped keys. This shim patches both functions in-process:

- trampoline recording: assert relaxed, keys keep the ``src.`` prefix —
  so the per-mutant activation check (``MUTANT_UNDER_TEST`` module vs
  ``decorated_func.__module__``) sees the SAME prefixed name and mutants
  actually activate instead of silently no-oping;
- mutant naming: prefix kept, matching the recorded keys.

Loaded from two places (idempotent):
- the mutmut main process, via the Makefile bootstrap (generation time);
- every mutmut pytest run, via ``-p verify.mutmut.mutmut_compat`` in
  ``[tool.mutmut] pytest_add_cli_args``.

Regular pytest runs never import it. Pinned-version discipline
(testing-strategies §7.4): the shim fails loudly when the guarded upstream
source changes — update it together with a mutmut bump.

Tmp isolation (2026-09, plan ``.opencode/plans/plan-mutmut-pytest-tmp-race.md``):
the gate's parallel pytest children used to share pytest's default tmp root
(``/tmp/pytest-of-<user>/``), where roughly one ``pytest-current`` symlink swap
per session races other children's ``cleanup_dead_symlinks`` teardown — a child
dies with FileNotFoundError and ``scripts/mutmut_baseline.py`` records the
nonzero exit as "killed" (silent kill-ratio inflation; the ratchet never fails
on improvements). With an explicit ``--basetemp`` pytest creates no symlink and
no shared-root cleanup at all, so ``pytest_configure`` pins every mutmut pytest
run to ``$MUTMUT_PYTEST_TMP/p<pid>`` (exported by the Makefile recipe; cleaned
by the recipe's EXIT trap). Without the env var it falls back to a
self-cleaning process-unique mkdtemp. An explicit user ``--basetemp`` is never
overridden. Regular pytest runs are unaffected: this plugin is only wired
through ``[tool.mutmut] pytest_add_cli_args``.
"""

import inspect
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

_TRAMPOLINE_GUARD = (
    'assert not name.startswith("src."), '
    '"Failed trampoline hit. Module name starts with `src.`, which is invalid"\n'
)
_NAMING_GUARD = 'module_name = strip_prefix(module_name, prefix="src.")\n'


def _patch_record_trampoline_hit(mm: Any) -> None:
    original = inspect.getsource(mm.record_trampoline_hit)
    if _TRAMPOLINE_GUARD not in original:
        raise RuntimeError(
            "verify.mutmut.mutmut_compat: the upstream trampoline assert changed — "
            "update this shim together with the mutmut bump (TCB discipline)"
        )
    namespace: dict[str, Any] = dict(mm.__dict__)
    exec(compile(original.replace(_TRAMPOLINE_GUARD, ""), "<mutmut_compat>", "exec"), namespace)
    mm.record_trampoline_hit = namespace["record_trampoline_hit"]


def _patch_get_mutant_name(mm: Any) -> None:
    original = inspect.getsource(mm.get_mutant_name)
    if _NAMING_GUARD not in original:
        raise RuntimeError(
            "verify.mutmut.mutmut_compat: the upstream mutant-naming prefix-strip "
            "changed — update this shim together with the mutmut bump"
        )
    namespace: dict[str, Any] = dict(mm.__dict__)
    exec(compile(original.replace(_NAMING_GUARD, ""), "<mutmut_compat>", "exec"), namespace)
    mm.get_mutant_name = namespace["get_mutant_name"]


def apply() -> None:
    """Apply both patches (idempotent; safe in every process)."""
    try:
        # mutmut is an ephemeral dev tool (`uv run --with 'mutmut==3.7.*'`), absent
        # from the project env — the ImportError guard below is the contract.
        import mutmut.__main__ as mm  # type: ignore[import-not-found]
        from mutmut.mutation import trampoline  # type: ignore[import-not-found]
    except ImportError:
        return

    if not getattr(mm, "_mutmut_compat_src_prefix_kept", False):
        _patch_get_mutant_name(mm)
        _patch_record_trampoline_hit(mm)
        mm._mutmut_compat_src_prefix_kept = True

    # trampoline.py binds record_trampoline_hit by name at import time —
    # rebind the live reference used on every call.
    trampoline.record_trampoline_hit = mm.record_trampoline_hit


# --- per-PID pytest tmp isolation (mechanism B, plan mutmut-pytest-tmp-race) ---
# Module-level holder instead of `global` (ruff PLW0603 is not ignored here).
_FALLBACK: dict[str, Path | None] = {"root": None}


def _fallback_basetemp_root() -> str:
    """Process-unique fallback root, used when MUTMUT_PYTEST_TMP is unset.

    mkdtemp is atomic and PID-suffixed, so concurrent children can never share
    a root; pytest_unconfigure removes the process's own root (best effort).
    """
    if _FALLBACK["root"] is None:
        _FALLBACK["root"] = Path(tempfile.mkdtemp(prefix=f"mutmut-pytest-{os.getpid()}-"))
    return str(_FALLBACK["root"])


def _isolate_basetemp(config: Any) -> None:
    """Pin this pytest process to its own per-PID basetemp (race-free teardown).

    With an explicit --basetemp, pytest 9.x wipes it at session start, creates
    no pytest-current symlink, and registers no shared-root cleanup — the
    crashed teardown path (cleanup_numbered_dir -> cleanup_dead_symlinks on
    the shared default root) is never reached. Absolute path is mandatory:
    mutmut runs pytest from mutants/ and a relative basetemp would resolve
    against that CWD.
    """
    if getattr(config.option, "basetemp", None):
        return  # never override an explicit user --basetemp
    try:
        env_root = os.environ.get("MUTMUT_PYTEST_TMP")
        if env_root:
            root = Path(env_root)
            root.mkdir(parents=True, exist_ok=True)
        else:
            root = Path(_fallback_basetemp_root())
        # str: --basetemp is an argparse string option; keep the natural type.
        config.option.basetemp = str((root / f"p{os.getpid()}").absolute())
    except OSError as exc:
        print(
            "verify.mutmut.mutmut_compat: per-PID basetemp isolation failed "
            f"({exc}); pytest falls back to the shared default tmp root",
            file=sys.stderr,
        )


def pytest_configure(config: Any) -> None:
    apply()
    _isolate_basetemp(config)


def pytest_unconfigure(config: Any) -> None:
    if _FALLBACK["root"] is not None:
        shutil.rmtree(_FALLBACK["root"], ignore_errors=True)
        _FALLBACK["root"] = None


# Register the gate's Hypothesis profile at plugin import time: the
# hypothesis-pytest plugin resolves ``--hypothesis-profile`` during ITS
# pytest_configure, which runs before this plugin's hook, so a hook-time
# registration is too late. The profile suppresses differing_executors —
# the gate re-runs the same Hypothesis tests under many executors
# (clean-test + one pytest per mutant) against one per-run database.
# Normal pytest runs never load this plugin (it is only wired through
# [tool.mutmut] pytest_add_cli_args).
try:
    from hypothesis import HealthCheck, settings

    settings.register_profile(
        "mutmut",
        suppress_health_check=[HealthCheck.differing_executors],
    )
except ImportError:
    pass
