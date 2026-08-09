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
Self-healing validation with Pydantic lax mode and retry loop.

When LLM-structured output fails Pydantic validation, this module formats
the error into a correction prompt and retries generation with feedback.

The retry loop:
    1. Attempt structured generation via LiteLLM.as_structured_llm
    2. On ValidationError, extract error details → correction prompt
    3. Retry with corrected user prompt (up to max_retries)
    4. Return best-effort result or raise

Used by: SoftwareArchitectAgent.generate_structured
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ValidationError

from src.agent import LLMError

logger = logging.getLogger(__name__)


@dataclass
class RetryContext:
    """Bundles prompt context for self-healing repair calls."""
    system_prompt: str
    user_prompt: str


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


def attempt_repair(
    repair_caller: Callable[[str, str], BaseModel],
    context: RetryContext,
    validation_errors: str,
    response_schema: type[BaseModel],
) -> BaseModel | None:
    """
    Attempt to repair failed structured generation by calling the LLM
    with a corrected prompt containing validation error details.

    This is the "self-healing" step: we tell the LLM what went wrong
    and ask it to produce a correctly-structured response.

    Args:
        repair_caller: Callable that takes (system_prompt, user_prompt) and
                       returns a single-shot structured generation result.
                       Must NOT retry — only one attempt.
        context: RetryContext with original system_prompt and user_prompt
                (forwarded so the LLM has context during repair).
        validation_errors: Formatted validation error string
        response_schema: Target Pydantic model class

    Returns:
        Validated Pydantic model, or None if repair attempt also failed
    """
    repair_user_prompt = (
        f"{context.user_prompt}\n\n"
        f"IMPORTANT: Your previous response failed validation.\n"
        f"{validation_errors}\n\n"
        f"Please produce a new response that conforms exactly to the schema "
        f"for {response_schema.__name__}. Double-check every field before responding."
    )

    try:
        repaired = repair_caller(
            system_prompt=context.system_prompt,
            user_prompt=repair_user_prompt,
        )
        logger.debug(
            "Self-healing repair succeeded",
            extra={"schema": response_schema.__name__},
        )
        return repaired
    except (ValidationError, LLMError):
        logger.debug("Self-healing repair also failed validation")
        return None
    except Exception as e:
        logger.warning(f"Self-healing repair call failed: {e}")
        return None


def validate_with_retries(
    initial_caller: Callable[[], BaseModel],
    repair_caller: Callable[[str, str], BaseModel],
    response_schema: type[BaseModel],
    max_retries: int = 3,
    context: RetryContext | None = None,
) -> BaseModel:
    """
    Generate a structured response with self-healing retry on validation failure.

    Calls initial_caller to attempt structured generation. On ValidationError or
    LLMError (provider error), repairs with a corrected prompt and retries up
    to max_retries times.

    Args:
        initial_caller: Zero-arg callable that returns the first structured generation attempt.
                        Raises ValidationError or LLMError on failure.
        repair_caller: Callable(system_prompt, user_prompt) for repair attempts.
                        Must NOT retry — only one attempt per call.
        response_schema: Pydantic model class used for validation (passed explicitly).
        max_retries: Maximum self-healing retry attempts (default 3)
        context: RetryContext bundling system_prompt and user_prompt for repair
                 calls (so the LLM has full context when self-healing).

    Returns:
        Validated Pydantic model instance

    Raises:
        ValidationError: If all attempts (including repairs) fail validation
        LLMError: If all attempts fail with provider errors after retries exhausted
    """
    if context is None:
        context = RetryContext(system_prompt="", user_prompt="")
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return initial_caller()
        except ValidationError as exc:
            last_error = exc
            if attempt < max_retries:
                errors_str = format_validation_errors(exc)
                logger.debug(
                    f"Validation attempt {attempt + 1} failed, attempting repair",
                    extra={"errors": errors_str[:200]},
                )
                repaired = attempt_repair(
                    repair_caller=repair_caller,
                    context=context,
                    validation_errors=errors_str,
                    response_schema=response_schema,
                )
                if repaired is not None:
                    return repaired
        except LLMError as exc:
            last_error = exc
            if attempt < max_retries:
                errors_str = f"LLM provider error: {exc.provider_message}"
                logger.debug(
                    f"LLM attempt {attempt + 1} failed, attempting repair",
                    extra={"error": errors_str},
                )
                repaired = attempt_repair(
                    repair_caller=repair_caller,
                    context=context,
                    validation_errors=errors_str,
                    response_schema=response_schema,
                )
                if repaired is not None:
                    return repaired

    if last_error is not None:
        raise last_error
    raise RuntimeError(
        f"validate_with_retries: all {max_retries + 1} attempts failed without known error"
    )
