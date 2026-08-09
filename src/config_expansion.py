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
Environment variable expansion for configuration files.

Supports {env:VAR} and {env:VAR:-default} placeholder syntax.
"""

import re
from typing import Any

_ENV_PATTERN = re.compile(r"\{env:([A-Z_][A-Z0-9_]*)(?::-([^}]*))?\}")


def expand_env(value: str, environ: dict[str, str] | None = None) -> str:
    """
    Expand {env:VAR} and {env:VAR:-default} placeholders in a string.

    {env:VAR}          → value of VAR from environ, or "" if unset
    {env:VAR:-default} → value of VAR, or "default" if unset

    Args:
        value: String containing {env:...} placeholders.
        environ: Dict to read env vars from. Defaults to os.environ.

    Returns:
        String with all placeholders expanded.
    """
    env = environ if environ is not None else __import__("os").environ

    def repl(m: re.Match) -> str:
        var = m.group(1)
        default = m.group(2)
        return env.get(var, default if default is not None else "")

    return _ENV_PATTERN.sub(repl, value)


def expand_env_in_obj(obj: Any, environ: dict[str, str] | None = None) -> Any:
    """
    Recursively expand {env:...} placeholders in a dict/list/string structure.

    Args:
        obj: Object to expand. Strings are expanded in-place. Dicts and lists
             are traversed recursively.
        environ: Dict to read env vars from. Defaults to os.environ.

    Returns:
        Copy of obj with all string values expanded.
    """
    if isinstance(obj, str):
        return expand_env(obj, environ)
    if isinstance(obj, dict):
        return {k: expand_env_in_obj(v, environ) for k, v in obj.items()}
    if isinstance(obj, list):
        return [expand_env_in_obj(v, environ) for v in obj]
    return obj
