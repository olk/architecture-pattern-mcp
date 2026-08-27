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
Self-healing validation with Pydantic lax mode and async retry loop.

When LLM-structured output fails Pydantic validation, this module formats
the error into a correction prompt and retries generation with feedback.

The async retry loop:
    1. Attempt structured generation via LiteLLM.as_structured_llm
    2. On ValidationError, extract error details → correction prompt
    3. Retry with corrected user prompt (up to max_retries)
    4. Return best-effort result or raise

Used by: SoftwareArchitectAgent.generate_structured
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from src.agent import LLMError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def format_validation_errors(exc: ValidationError) -> str:
    """
    Format a Pydantic ValidationError into a human-readable correction prompt.

    Args:
        exc: Pydantic ValidationError from failed model validation

    Returns:
        Plain-text description of each field error for inclusion in retry prompt
    """
    lines = ["The following fields failed validation:"]
    for err in exc.errors():
        loc = ".".join(str(l) for l in err["loc"])
        msg = err["msg"]
        inp = repr(err["input"])[:80]
        lines.append(f"  - {loc}: {msg} (got: {inp})")
    return "\n".join(lines)


async def validate_with_retries(  # noqa: UP047
    initial_caller: Callable[[], Awaitable[T]],
    repair_caller: Callable[[str, str], Awaitable[T]],
    response_schema: type[T],
    *,
    max_retries: int = 3,
    system_prompt: str = "",
    user_prompt: str = "",
) -> T:
    """
    Generate a structured response with self-healing async retry on validation failure.

    Calls initial_caller for the first attempt. On ValidationError or LLMError,
    calls repair_caller with corrected prompts up to max_retries times.

    Args:
        initial_caller: Zero-arg async callable returning first structured generation attempt.
                        Raises ValidationError or LLMError on failure.
        repair_caller: Async callable(system_prompt, user_prompt) for repair attempts.
                       Must NOT retry — only one attempt per call.
        response_schema: Pydantic model class used for validation (for error messages).
        max_retries: Maximum self-healing retry attempts (default 3).
        system_prompt: Original system prompt (forwarded unchanged to repair_caller).
        user_prompt: Original user prompt (used as base; repair appends error context).

    Returns:
        Validated Pydantic model instance.

    Raises:
        ValidationError: If all attempts (including repairs) fail validation.
        LLMError: If all attempts fail with provider errors after retries exhausted.
    """
    original_error: Exception | None = None

    try:
        return await initial_caller()
    except ValidationError as exc:
        original_error = exc
    except LLMError as exc:
        original_error = exc

    for attempt in range(max_retries):
        if original_error is None:
            raise RuntimeError("validate_with_retries: original_error is None")

        if isinstance(original_error, ValidationError):
            errors_str = format_validation_errors(original_error)
            repair_user_prompt = (
                f"{user_prompt}\n\n"
                "IMPORTANT: Your previous response failed validation.\n"
                f"{errors_str}\n\n"
                f"Please produce a new response that conforms exactly to the schema "
                f"for {response_schema.__name__}. "
                "Double-check every field before responding."
            )
        elif isinstance(original_error, LLMError):
            errors_str = f"LLM provider error: {original_error.provider_message}"
            repair_user_prompt = (
                f"{user_prompt}\n\n"
                f"IMPORTANT: previous LLM call failed with: {original_error.provider_message}\n"
                f"Please produce a new response conforming to {response_schema.__name__}."
            )
        else:
            raise original_error from None

        logger.debug(
            "Self-healing repair attempt %d",
            attempt + 1,
            extra={"error": errors_str[:200]},
        )

        try:
            return await repair_caller(system_prompt, repair_user_prompt)
        except (ValidationError, LLMError) as exc:
            logger.warning("Self-healing repair call failed: %s", exc)
        except Exception as exc:
            logger.warning("Self-healing repair call failed: %s", exc)

    if original_error is not None:
        raise original_error from None
    raise RuntimeError(
        f"validate_with_retries: all {max_retries + 1} attempts failed without known error"
    )
