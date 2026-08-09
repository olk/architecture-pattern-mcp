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
Unit tests for src/validation self-healing retry mechanism.

Tests:
- Retry loop catches ValidationError and triggers repair
- Retry loop catches LLMError (provider errors) and triggers repair
- attempt_repair handles both ValidationError and LLMError
- Exhausted retries raises the last error
- max_retries default is 3
"""

from pydantic import BaseModel, ValidationError
import pytest

from src.agent import LLMError
from src.validation import RetryContext, attempt_repair, format_validation_errors, validate_with_retries


class SimpleSchema(BaseModel):
    name: str
    score: float


class TestFormatValidationErrors:
    """Format ValidationError into human-readable correction prompt."""

    def test_includes_field_location_and_message(self):
        """Error loc and msg are included in the formatted string."""
        exc = ValidationError.from_exception_data(
            "SimpleSchema",
            [
                {
                    "type": "missing",
                    "loc": ("name",),
                    "msg": "Field required",
                    "input": {},
                }
            ],
        )
        result = format_validation_errors(exc)
        assert "name" in result
        assert "Field required" in result

    def test_handles_nested_field_paths(self):
        """Nested field paths are joined with dots."""
        exc = ValidationError.from_exception_data(
            "SimpleSchema",
            [
                {
                    "type": "enum",
                    "loc": ("category",),
                    "msg": "Input should be 'messaging'",
                    "input": "stream-processing",
                    "ctx": {"expected": "messaging"},
                }
            ],
        )
        result = format_validation_errors(exc)
        assert "category" in result
        assert "stream-processing" in result


class TestAttemptRepair:
    """attempt_repair calls repair_caller with correction prompt."""

    def test_returns_repaired_result_on_success(self):
        """repair_caller returning a valid model returns it."""
        recorded_calls: list[tuple[str, str]] = []

        def repair_caller(system_prompt: str, user_prompt: str) -> SimpleSchema:
            recorded_calls.append((system_prompt, user_prompt))
            return SimpleSchema(name="repaired", score=9.5)

        result = attempt_repair(
            repair_caller=repair_caller,
            context=RetryContext(system_prompt="system context", user_prompt="original user prompt"),
            validation_errors="name: Field required",
            response_schema=SimpleSchema,
        )
        assert result is not None
        assert result.name == "repaired"
        assert len(recorded_calls) == 1
        sp, up = recorded_calls[0]
        assert sp == "system context"
        assert "original user prompt" in up
        assert "name: Field required" in up

    def test_returns_none_on_validation_error(self):
        """ValidationError from repair_caller returns None."""

        def failing_repair(system_prompt: str, user_prompt: str) -> SimpleSchema:
            raise ValidationError.from_exception_data(
                "SimpleSchema",
                [{"type": "missing", "loc": ("name",), "msg": "Field required", "input": {}}],
            )

        result = attempt_repair(
            repair_caller=failing_repair,
            context=RetryContext(system_prompt="", user_prompt="original prompt"),
            validation_errors="name: Field required",
            response_schema=SimpleSchema,
        )
        assert result is None

    def test_returns_none_on_llm_error(self):
        """LLMError from repair_caller returns None."""

        def failing_repair(system_prompt: str, user_prompt: str) -> SimpleSchema:
            raise LLMError(provider="openai", error="ERR_009", provider_message="rate limit")

        result = attempt_repair(
            repair_caller=failing_repair,
            context=RetryContext(system_prompt="", user_prompt="original prompt"),
            validation_errors="LLM provider error: rate limit",
            response_schema=SimpleSchema,
        )
        assert result is None


class TestValidateWithRetries:
    """validate_with_retries self-healing retry loop."""

    def test_succeeds_on_first_attempt(self):
        """First successful call returns immediately."""
        attempt_count = 0

        def happy_path() -> SimpleSchema:
            nonlocal attempt_count
            attempt_count += 1
            return SimpleSchema(name="success", score=8.0)

        result = validate_with_retries(
            initial_caller=happy_path,
            repair_caller=lambda system_prompt, user_prompt: SimpleSchema(name="repaired", score=7.0),
            response_schema=SimpleSchema,
            max_retries=3,
        )
        assert result.name == "success"
        assert attempt_count == 1

    def test_retries_and_repairs_on_validation_error(self):
        """ValidationError triggers repair attempt; repair succeeds."""
        attempt_count = 0
        repair_called = False

        def failing_once() -> SimpleSchema:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count == 1:
                raise ValidationError.from_exception_data(
                    "SimpleSchema",
                    [{"type": "missing", "loc": ("name",), "msg": "Field required", "input": {}}],
                )
            return SimpleSchema(name="success", score=8.0)

        def repair(system_prompt: str, user_prompt: str) -> SimpleSchema:
            nonlocal repair_called
            repair_called = True
            return SimpleSchema(name="repaired", score=7.0)

        result = validate_with_retries(
            initial_caller=failing_once,
            repair_caller=repair,
            response_schema=SimpleSchema,
            max_retries=3,
        )
        assert attempt_count == 1
        assert repair_called
        assert result.name == "repaired"

    def test_retries_on_llm_error(self):
        """LLMError triggers repair attempt; repair succeeds."""
        attempt_count = 0
        repair_called = False

        def failing_once() -> SimpleSchema:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count == 1:
                raise LLMError(provider="openai", error="ERR_009", provider_message="timeout")
            return SimpleSchema(name="success", score=8.0)

        def repair(system_prompt: str, user_prompt: str) -> SimpleSchema:
            nonlocal repair_called
            repair_called = True
            return SimpleSchema(name="repaired", score=7.0)

        result = validate_with_retries(
            initial_caller=failing_once,
            repair_caller=repair,
            response_schema=SimpleSchema,
            max_retries=3,
        )
        assert attempt_count == 1
        assert repair_called
        assert result.name == "repaired"

    def test_raises_last_error_after_exhausted_retries(self):
        """After max_retries exhausted, raises the last ValidationError."""
        attempt_count = 0

        def always_fail() -> SimpleSchema:
            nonlocal attempt_count
            attempt_count += 1
            raise ValidationError.from_exception_data(
                "SimpleSchema",
                [{"type": "missing", "loc": ("name",), "msg": "Field required", "input": {}}],
            )

        def repair_always_fails(system_prompt: str, user_prompt: str) -> SimpleSchema:
            raise ValidationError.from_exception_data(
                "SimpleSchema",
                [{"type": "missing", "loc": ("name",), "msg": "Field required", "input": {}}],
            )

        with pytest.raises(ValidationError):
            validate_with_retries(
                initial_caller=always_fail,
                repair_caller=repair_always_fails,
                response_schema=SimpleSchema,
                max_retries=2,
            )
        assert attempt_count == 3

    def test_raises_last_llm_error_after_exhausted_retries(self):
        """After max_retries exhausted on LLMError, raises the LLMError."""
        attempt_count = 0

        def always_fail() -> SimpleSchema:
            nonlocal attempt_count
            attempt_count += 1
            raise LLMError(provider="openai", error="ERR_009", provider_message="timeout")

        def repair_always_fails(system_prompt: str, user_prompt: str) -> SimpleSchema:
            raise LLMError(provider="openai", error="ERR_009", provider_message="repair failed")

        with pytest.raises(LLMError):
            validate_with_retries(
                initial_caller=always_fail,
                repair_caller=repair_always_fails,
                response_schema=SimpleSchema,
                max_retries=2,
            )
        assert attempt_count == 3
        assert attempt_count == 3

    def test_max_retries_default_is_3(self):
        """Default max_retries in validate_with_retries is 3."""
        import inspect
        sig = inspect.signature(validate_with_retries)
        assert sig.parameters["max_retries"].default == 3

    def test_repair_receives_original_system_prompt_and_user_prompt(self):
        """attempt_repair forwards original system_prompt and user_prompt to repair_caller."""
        recorded: list[tuple[str, str]] = []

        def repair_caller(system_prompt: str, user_prompt: str) -> SimpleSchema:
            recorded.append((system_prompt, user_prompt))
            return SimpleSchema(name="fixed", score=8.0)

        attempt_repair(
            repair_caller=repair_caller,
            context=RetryContext(system_prompt="original system prompt", user_prompt="original user prompt"),
            validation_errors="source: Field required",
            response_schema=SimpleSchema,
        )

        assert len(recorded) == 1
        sp, up = recorded[0]
        assert sp == "original system prompt"
        assert "original user prompt" in up
        assert "source: Field required" in up

    def test_validate_with_retries_repair_gets_original_system_prompt(self):
        """validate_with_retries forwards original system_prompt and user_prompt to repair."""
        attempt_count = 0
        recorded_repairs: list[tuple[str, str]] = []

        def failing_once() -> SimpleSchema:
            nonlocal attempt_count
            attempt_count += 1
            raise ValidationError.from_exception_data(
                "SimpleSchema",
                [{"type": "missing", "loc": ("name",), "msg": "Field required", "input": {}}],
            )

        def repair_caller(system_prompt: str, user_prompt: str) -> SimpleSchema:
            recorded_repairs.append((system_prompt, user_prompt))
            return SimpleSchema(name="fixed", score=8.0)

        validate_with_retries(
            initial_caller=failing_once,
            repair_caller=repair_caller,
            response_schema=SimpleSchema,
            max_retries=1,
            context=RetryContext(system_prompt="the system prompt", user_prompt="the user prompt"),
        )

        assert len(recorded_repairs) == 1
        sp, up = recorded_repairs[0]
        assert sp == "the system prompt"
        assert "the user prompt" in up
