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
Pure transformations on ArchitectureDesign for spec §4.11 denormalization.

Pydantic adapter: the pure precedence/dedup logic lives in
src/design_normalization_core.py (plain-data protocols, Nagini target);
this module passes the Pydantic design through the core and applies the
result with a single model_copy (deep=True).

See docs/implementation-guide.md §4.14 for the full rule table.
"""

from src.design_normalization_core import denormalize_core
from src.schemas import ArchitectureDesign


def denormalize_contracts(design: ArchitectureDesign) -> ArchitectureDesign:
    """Flatten component.api_contract and component.data_models (is_shared=True)
    into top-level lists. event_contracts deduped by event_name.

    Precedence rules:
      1. Existing top-level entries are preserved (LLM's explicit choice wins).
      2. component.api_contract promoted if its component_id not yet present.
      3. component.data_models entries with is_shared=True promoted if their
         (name, is_shared) tuple is not already present at top level.
      4. event_contracts deduped by event_name; order preserved.

    Idempotent. Uses model_copy(update=..., deep=True). Caller must treat
    the returned design as immutable — list fields are references to trusted
    input.
    """
    promoted = denormalize_core(design)
    return design.model_copy(
        update={
            "api_contracts": promoted["api_contracts"],
            "shared_data_models": promoted["shared_data_models"],
            "event_contracts": promoted["event_contracts"],
        },
        deep=True,
    )
