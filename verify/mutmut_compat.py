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
- every mutmut pytest run, via ``-p verify.mutmut_compat`` in
  ``[tool.mutmut] pytest_add_cli_args``.

Regular pytest runs never import it. Pinned-version discipline
(testing-strategies §7.4): the shim fails loudly when the guarded upstream
source changes — update it together with a mutmut bump.
"""

import inspect
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
            "verify.mutmut_compat: the upstream trampoline assert changed — "
            "update this shim together with the mutmut bump (TCB discipline)"
        )
    namespace: dict[str, Any] = dict(mm.__dict__)
    exec(compile(original.replace(_TRAMPOLINE_GUARD, ""), "<mutmut_compat>", "exec"), namespace)
    mm.record_trampoline_hit = namespace["record_trampoline_hit"]


def _patch_get_mutant_name(mm: Any) -> None:
    original = inspect.getsource(mm.get_mutant_name)
    if _NAMING_GUARD not in original:
        raise RuntimeError(
            "verify.mutmut_compat: the upstream mutant-naming prefix-strip "
            "changed — update this shim together with the mutmut bump"
        )
    namespace: dict[str, Any] = dict(mm.__dict__)
    exec(compile(original.replace(_NAMING_GUARD, ""), "<mutmut_compat>", "exec"), namespace)
    mm.get_mutant_name = namespace["get_mutant_name"]


def apply() -> None:
    """Apply both patches (idempotent; safe in every process)."""
    try:
        import mutmut.__main__ as mm
        from mutmut.mutation import trampoline
    except ImportError:
        return

    if not getattr(mm, "_mutmut_compat_src_prefix_kept", False):
        _patch_get_mutant_name(mm)
        _patch_record_trampoline_hit(mm)
        mm._mutmut_compat_src_prefix_kept = True

    # trampoline.py binds record_trampoline_hit by name at import time —
    # rebind the live reference used on every call.
    trampoline.record_trampoline_hit = mm.record_trampoline_hit


def pytest_configure(config: Any) -> None:
    apply()
