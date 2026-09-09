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
Error codes and domain-specific exceptions for the MCP architecture tool layer.

Error codes follow the scheme:
    ERR_0xx — input / pre-condition failures
    ERR_9xx — infrastructure / LLM provider failures

Adapters (src/tools/_adapters.py) raise MalformedArchitectureOverviewError
when LLM-generated or user-supplied data fails strict Pydantic validation.
Tool handlers map it to ToolError(ERR_012).

The canonical pattern-retrieval fallback (LAYERED_MONOLITH) lives in
src/patterns/retriever.py::DEFAULT_FALLBACK_PATTERN_NAME only.
"""

from __future__ import annotations

from typing import Any

ERROR_INVALID_ARCHITECTURE = "ERR_012"
ERROR_REQUIREMENTS_VALIDATION = "ERR_001"


class JobStateError(RuntimeError):
    """
    Internal transition-guard signal (Week-0 W0-1): a guarded JobsStore
    transition was rejected because the job's current status is outside the
    setter's guard set (a terminal write lost a race to a concurrent cancel
    or completion). Mapped by callers; never exposed as a tool error code.

    Attributes:
        job_id:          ID of the job whose transition was rejected.
        current_status:  Status re-read from the store at rejection time, when known.
    """

    def __init__(
        self,
        job_id: str,
        current_status: str | None = None,
    ) -> None:
        self.job_id = job_id
        self.current_status = current_status
        super().__init__(
            f"job {job_id!r} transition rejected (current status: {current_status or 'unknown'})"
        )


class MalformedArchitectureOverviewError(ValueError):
    """
    Raised by adapter helpers when an ArchitectureOverview dict
    cannot be validated against ArchitectureOverview schema.

    Attributes:
        locator:        Dot-path to the failing node (e.g. "overview")
        errors:         Pydantic ValidationError.errors() list
    """

    def __init__(
        self,
        locator: str,
        errors: list[Any],
    ) -> None:
        super().__init__(f"{ERROR_INVALID_ARCHITECTURE}: {locator} failed validation: {errors}")
        self.locator = locator
        self.errors = errors
