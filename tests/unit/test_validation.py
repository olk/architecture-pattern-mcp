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
Unit tests for src/validation self-healing async retry mechanism.

Tests:
- validate_with_retries succeeds on first attempt
- validate_with_retries catches ValidationError and calls repair on failure
- validate_with_retries catches LLMError and calls repair on failure
- Exhausted retries raises the last error
- CancelledError propagates
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel, ValidationError

from src.agent import LLMError
from src.validation import format_validation_errors, validate_with_retries


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


class TestValidateWithRetries:
    """validate_with_retries self-healing async retry loop."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self):
        """First successful call returns immediately without calling repair."""
        initial_called = False
        repair_called = False

        async def initial_caller() -> SimpleSchema:
            nonlocal initial_called
            initial_called = True
            return SimpleSchema(name="success", score=8.0)

        async def repair_caller(sp: str, up: str) -> SimpleSchema:
            nonlocal repair_called
            repair_called = True
            return SimpleSchema(name="repaired", score=7.0)

        result = await validate_with_retries(
            initial_caller,
            repair_caller,
            SimpleSchema,
            max_retries=3,
        )
        assert result.name == "success"
        assert initial_called
        assert not repair_called

    @pytest.mark.asyncio
    async def test_retries_and_repairs_on_validation_error(self):
        """ValidationError triggers repair attempt; repair succeeds."""
        initial_called = False
        repair_called = False

        async def initial_caller() -> SimpleSchema:
            nonlocal initial_called
            initial_called = True
            raise ValidationError.from_exception_data(
                "SimpleSchema",
                [{"type": "missing", "loc": ("name",), "msg": "Field required", "input": {}}],
            )

        async def repair_caller(sp: str, up: str) -> SimpleSchema:
            nonlocal repair_called
            repair_called = True
            return SimpleSchema(name="repaired", score=7.0)

        result = await validate_with_retries(
            initial_caller,
            repair_caller,
            SimpleSchema,
            max_retries=3,
            system_prompt="system prompt",
            user_prompt="original user prompt",
        )
        assert initial_called
        assert repair_called
        assert result.name == "repaired"

    @pytest.mark.asyncio
    async def test_retries_on_llm_error(self):
        """LLMError triggers repair attempt; repair succeeds."""
        initial_called = False
        repair_called = False

        async def initial_caller() -> SimpleSchema:
            nonlocal initial_called
            initial_called = True
            raise LLMError(provider="openai", error="ERR_009", provider_message="timeout")

        async def repair_caller(sp: str, up: str) -> SimpleSchema:
            nonlocal repair_called
            repair_called = True
            return SimpleSchema(name="repaired", score=7.0)

        result = await validate_with_retries(
            initial_caller,
            repair_caller,
            SimpleSchema,
            max_retries=3,
        )
        assert initial_called
        assert repair_called
        assert result.name == "repaired"

    @pytest.mark.asyncio
    async def test_raises_last_error_after_exhausted_retries(self):
        """After max_retries exhausted, raises the last ValidationError."""
        initial_called = False
        repair_attempt = 0

        async def initial_caller() -> SimpleSchema:
            nonlocal initial_called
            initial_called = True
            raise ValidationError.from_exception_data(
                "SimpleSchema",
                [{"type": "missing", "loc": ("name",), "msg": "Field required", "input": {}}],
            )

        async def repair_always_fails(sp: str, up: str) -> SimpleSchema:
            nonlocal repair_attempt
            repair_attempt += 1
            raise ValidationError.from_exception_data(
                "SimpleSchema",
                [{"type": "missing", "loc": ("name",), "msg": "Field required", "input": {}}],
            )

        with pytest.raises(ValidationError):
            await validate_with_retries(
                initial_caller,
                repair_always_fails,
                SimpleSchema,
                max_retries=2,
            )
        assert initial_called
        assert repair_attempt == 2  # 2 repair attempts

    @pytest.mark.asyncio
    async def test_raises_last_llm_error_after_exhausted_retries(self):
        """After max_retries exhausted on LLMError, raises the LLMError."""
        repair_attempt = 0

        async def initial_caller() -> SimpleSchema:
            raise LLMError(provider="openai", error="ERR_009", provider_message="timeout")

        async def repair_always_fails(sp: str, up: str) -> SimpleSchema:
            nonlocal repair_attempt
            repair_attempt += 1
            raise LLMError(provider="openai", error="ERR_009", provider_message="repair failed")

        with pytest.raises(LLMError) as exc_info:
            await validate_with_retries(
                initial_caller,
                repair_always_fails,
                SimpleSchema,
                max_retries=2,
            )
        assert exc_info.value.provider_message == "timeout"
        assert repair_attempt == 2

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates(self):
        """asyncio.CancelledError propagates without being caught."""

        async def initial_cancelled() -> SimpleSchema:
            raise asyncio.CancelledError

        async def repair_caller(sp: str, up: str) -> SimpleSchema:
            return SimpleSchema(name="repaired", score=7.0)

        with pytest.raises(asyncio.CancelledError):
            await validate_with_retries(
                initial_cancelled,
                repair_caller,
                SimpleSchema,
                max_retries=2,
            )

    @pytest.mark.asyncio
    async def test_repair_receives_original_system_and_user_prompt(self):
        """repair_caller receives original system_prompt and error-appended user_prompt."""
        recorded_repairs: list[tuple[str, str]] = []

        async def initial_caller() -> SimpleSchema:
            raise ValidationError.from_exception_data(
                "SimpleSchema",
                [{"type": "missing", "loc": ("name",), "msg": "Field required", "input": {}}],
            )

        async def repair_caller(sp: str, up: str) -> SimpleSchema:
            recorded_repairs.append((sp, up))
            return SimpleSchema(name="fixed", score=8.0)

        await validate_with_retries(
            initial_caller,
            repair_caller,
            SimpleSchema,
            max_retries=1,
            system_prompt="the system prompt",
            user_prompt="the user prompt",
        )

        assert len(recorded_repairs) == 1
        sp, up = recorded_repairs[0]
        assert sp == "the system prompt"
        assert "the user prompt" in up
        assert "name" in up
        assert "Field required" in up

    @pytest.mark.asyncio
    async def test_max_retries_default_is_3(self):
        """Default max_retries in validate_with_retries is 3."""
        import inspect
        sig = inspect.signature(validate_with_retries)
        assert sig.parameters["max_retries"].default == 3
