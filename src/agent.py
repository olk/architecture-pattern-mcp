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
# FR-174: The system SHALL provide a SoftwareArchitectAgent class that encapsulates LLM interactions via LlamaIndex LiteLLM
# FR-175: The system SHALL provide a generate_structured method that accepts system_prompt, user_prompt, and response_schema and returns a validated Pydantic model
# E-9: ERR_009 - LLM provider returned error (HTTP 502, severity: error)

LLM interaction wrapper via LlamaIndex LiteLLM with generate_structured method.

# ADR-8: LlamaIndex LiteLLM for Multi-Provider LLM Access
# Strategy Pattern (DP-2): LlamaIndex abstracts multiple providers enabling provider switching
"""

import logging
from typing import Any, cast

from llama_index.core.base.llms.types import ChatMessage, MessageRole
from llama_index.llms.litellm import LiteLLM
from pydantic import BaseModel, ValidationError

from src.config import ServerConfig

ERROR_LLM_PROVIDER = "ERR_009"

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """
    # E-9: ERR_009 - LLM provider returned error (HTTP 502, severity: error)

    Custom exception for LLM provider errors mapped from LlamaIndex/LiteLLM exceptions.

    # logging_context: provider, error, provider_message
    """

    def __init__(self, provider: str, error: str, provider_message: str):
        """
        Initialize LLMError with logging context.

        Args:
            provider: The LLM provider name (e.g., "openai", "anthropic").
            error: The error code (e.g., "ERR_009").
            provider_message: The error message from the provider.
        """
        self.provider = provider
        self.error = error
        self.provider_message = provider_message
        super().__init__(f"LLM provider {provider} error: {error} - {provider_message}")


class SoftwareArchitectAgent:
    """
    # FR-174: The system SHALL provide a SoftwareArchitectAgent class that encapsulates LLM interactions via LlamaIndex LiteLLM

    LLM interaction wrapper using LlamaIndex LiteLLM for multi-provider support.

    # ADR-8: LlamaIndex LiteLLM for Multi-Provider LLM Access
    # Strategy Pattern (DP-2): LlamaIndex abstracts multiple providers (OpenAI, Anthropic, Azure, etc.)

    This class provides a unified interface for LLM interactions across multiple providers,
    supporting generate_structured (Pydantic model) responses.

    # FR-175: generate_structured method implemented in SoftwareArchitectAgent
    """

    def __init__(self, config: ServerConfig):
        """
        Initialize SoftwareArchitectAgent with LLM configuration.

        # FR-174: SoftwareArchitectAgent class accepts ServerConfig parameter

        Args:
            config: ServerConfig instance containing LLM configuration.
                   Must have generator.provider, generator.config.model, generator.config.temperature, etc.
        """
        self._generator = config.generator
        _model = self._generator.config.model
        if "/" in _model:
            _model = _model.split("/", 1)[1]
        self._model_string = f"{self._generator.provider}/{_model}"
        self._validation_config = config.validation

        additional_kwargs: dict[str, Any] = {
            "top_p": self._generator.config.top_p,
            "top_k": self._generator.config.top_k,
        }
        if self._generator.config.stream:
            additional_kwargs["stream"] = True

        self._client = LiteLLM(
            model=self._model_string,
            temperature=self._generator.config.temperature,
            api_key=self._generator.config.api_key,
            api_base=self._generator.config.base_url or None,
            additional_kwargs=additional_kwargs,
        )

        logger.debug(
            "SoftwareArchitectAgent initialized",
            extra={
                "model_string": self._model_string,
                "temperature": self._generator.config.temperature,
                "top_p": self._generator.config.top_p,
                "top_k": self._generator.config.top_k,
                "has_api_key": bool(self._generator.config.api_key),
                "has_base_url": bool(self._generator.config.base_url),
            }
        )

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel],
    ) -> BaseModel:
        """
        # FR-175: The system SHALL provide a generate_structured method that accepts
        system_prompt, user_prompt, and response_schema and returns a validated Pydantic model

        # AC-175: Verify generate_structured method exists with correct signature
        # given_precondition: AppConfig with LLM configuration loaded
        # when_action: System calls generate_structured method
        # then_outcome: Returns instance of response_schema type

        Generate a structured response using LlamaIndex LiteLLM with Pydantic validation.

        Self-healing retry loop: on ValidationError, extracts error details and
        retries with a corrected prompt (up to validation.max_retries times).

        Args:
            system_prompt: The system prompt to guide the LLM behavior.
            user_prompt: The user prompt/content for the LLM.
            response_schema: A Pydantic BaseModel subclass for response validation.

        Returns:
            An instance of response_schema validated by Pydantic.

        # E-9: ERR_009 - LLM provider returned error
        """
        if self._validation_config.retry_on_fail and self._validation_config.max_retries > 0:
            async def initial_caller() -> BaseModel:
                return await self._generate_structured_once(
                    system_prompt, user_prompt, response_schema
                )

            async def repair_caller(sp: str, up: str) -> BaseModel:
                return await self._generate_structured_once(sp, up, response_schema)

            from src.validation import validate_with_retries

            return await validate_with_retries(
                initial_caller,
                repair_caller,
                response_schema,
                max_retries=self._validation_config.max_retries,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

        return await self._generate_structured_once(
            system_prompt, user_prompt, response_schema
        )

    async def _generate_structured_once(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel],
    ) -> BaseModel:
        """Single-shot structured generation without retry."""
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=system_prompt),
            ChatMessage(role=MessageRole.USER, content=user_prompt),
        ]

        try:
            structured_llm = self._client.as_structured_llm(response_schema)
            response = await structured_llm.achat(messages)

            logger.debug(
                "generate_structured returned validated model",
                extra={
                    "schema_type": response_schema.__name__,
                    "model_string": self._model_string,
                }
            )

            return cast(BaseModel, response.raw)

        except ValidationError:
            raise
        except Exception as e:
            raise LLMError(
                provider=self._generator.provider,
                error=ERROR_LLM_PROVIDER,
                provider_message=str(e)
            ) from e
