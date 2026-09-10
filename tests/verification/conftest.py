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
Executable oracles — tests/verification/.

Home of the verification program's executable layers (testing-strategies.md):
L1 secret canary, L2 Hypothesis property oracles, L3 gardens, L4/L6 trace
replay, L5 conformance, L9 corpus harness. Collected by
``make test-oracles``.
"""

import os

import pytest

from src.tools.jobs import JobsStore


@pytest.fixture(autouse=True)
async def jobs_store(tmp_path, monkeypatch):
    """Isolate JobsStore to a per-test tmp_path SQLite database.

    Mirrors tests/unit/conftest.py::jobs_store so oracles over the real store
    never bleed state between tests.
    """
    db = tmp_path / "jobs.db"
    monkeypatch.setenv("ARCHITECTURE_PATTERN_JOBS_DB", str(db))
    await JobsStore.reset_for_test()
    yield await JobsStore.get_instance()
    await JobsStore.reset_for_test()
    monkeypatch.delenv("ARCHITECTURE_PATTERN_JOBS_DB", raising=False)


@pytest.fixture
def jobs_db_path() -> str:
    """Absolute path of the current test's jobs DB file (E4 persistence checks)."""
    return os.environ["ARCHITECTURE_PATTERN_JOBS_DB"]
