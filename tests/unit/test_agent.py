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
# Validates: FR-174, FR-175, AC-174, AC-175
# Scenario: Unit tests for SoftwareArchitectAgent class

Test suite for SoftwareArchitectAgent class with LlamaIndex LiteLLM integration.

# FR-174: The system SHALL provide a SoftwareArchitectAgent class that encapsulates LLM interactions via LlamaIndex LiteLLM
# FR-175: The system SHALL provide a generate_structured method that accepts system_prompt, user_prompt, and response_schema and returns a validated Pydantic model

# AC-174: Verify SoftwareArchitectAgent class exists, accepts AppConfig parameter
# AC-175: Verify generate_structured method exists with correct signature
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from src.agent import (
    ERROR_LLM_PROVIDER,
    LLMError,
    SoftwareArchitectAgent,
)
from src.config import ServerConfig


class ResponseSchema(BaseModel):
    """Test schema for generate_structured method validation."""
    name: str
    description: str
    score: float


class TestSoftwareArchitectAgentInit:
    """
    # AC-174: Verify SoftwareArchitectAgent class exists, accepts AppConfig parameter
    # given_precondition: AppConfig with LLM configuration loaded
    # when_action: System creates SoftwareArchitectAgent instance
    # then_outcome: SoftwareArchitectAgent class exists
    """

    def test_agent_initialization_with_valid_config(self):
        """
        # FR-174: SoftwareArchitectAgent class accepts AppConfig parameter
        # Scenario: Create agent with valid ServerConfig
        """
        config = ServerConfig(
            generator={"provider": "openai", "config": {"model": "gpt-4", "temperature": 0.7}},
            embedder={"provider": "tei", "config": {"model": "Qwen/Qwen3-Embedding-0.6B", "base_url": "http://localhost:8080"}}
        )

        agent = SoftwareArchitectAgent(config)

        assert agent is not None
        assert agent._model_string == "openai/gpt-4"
        assert agent._generator.config.temperature == 0.7

    def test_agent_initialization_model_string_format(self):
        """
        # ADR-8: LlamaIndex LiteLLM for Multi-Provider LLM Access
        # Model string format: '{provider}/{model}'
        # Scenario: Verify model string is correctly formatted
        """
        config = ServerConfig(
            generator={"provider": "anthropic", "config": {"model": "claude-3-opus", "temperature": 0.5}}, embedder={"provider": "tei", "config": {"model": "Qwen/Qwen3-Embedding-0.6B", "base_url": "http://localhost:8080"}}
        )

        agent = SoftwareArchitectAgent(config)

        assert agent._model_string == "anthropic/claude-3-opus"

    def test_agent_initialization_with_custom_settings(self):
        """
        # CPARA-2 through CPARA-8: Configuration parameters
        # Scenario: Create agent with custom LLM settings
        """
        config = ServerConfig(
            generator={
                "provider": "openai",
                "config": {
                    "model": "gpt-4",
                    "temperature": 0.9,
                    "top_p": 0.9,
                    "top_k": 10,
                    "api_key": "sk-test",
                    "base_url": "https://api.openai.com/v1",
                }
            },
            embedder={"provider": "tei", "config": {"model": "Qwen/Qwen3-Embedding-0.6B", "base_url": "http://localhost:8080"}}
        )

        agent = SoftwareArchitectAgent(config)

        assert agent._generator.config.top_p == 0.9
        assert agent._generator.config.top_k == 10
        assert agent._generator.config.api_key == "sk-test"
        assert agent._generator.config.base_url == "https://api.openai.com/v1"


class TestGenerateStructured:
    """
    # AC-175: Verify generate_structured method exists with correct signature
    # given_precondition: AppConfig with LLM configuration loaded
    # when_action: System calls generate_structured method
    # then_outcome: Returns instance of response_schema type
    """

    @pytest.mark.asyncio
    async def test_generate_structured_returns_valid_model(self):
        """
        # FR-175: generate_structured method returns validated Pydantic model
        # Scenario: LLM returns valid JSON matching schema
        """
        config = ServerConfig(
            generator={"provider": "openai", "config": {"model": "gpt-4", "temperature": 0.7}},
            embedder={"provider": "tei", "config": {"model": "Qwen/Qwen3-Embedding-0.6B", "base_url": "http://localhost:8080"}}
        )
        agent = SoftwareArchitectAgent(config)

        mock_response = MagicMock()
        mock_response.raw = ResponseSchema(name="test", description="test desc", score=0.95)

        mock_structured_llm = AsyncMock()
        mock_structured_llm.achat = AsyncMock(return_value=mock_response)

        original_client = agent._client
        agent._client = MagicMock()
        agent._client.as_structured_llm.return_value = mock_structured_llm

        try:
            result = await agent.generate_structured(
                system_prompt="You are a helpful assistant.",
                user_prompt="Generate a test response.",
                response_schema=ResponseSchema
            )

            assert isinstance(result, ResponseSchema)
            assert result.name == "test"
            assert result.description == "test desc"
            assert result.score == 0.95
        finally:
            agent._client = original_client

    @pytest.mark.asyncio
    async def test_generate_structured_message_format(self):
        """
        # ADR-8: LlamaIndex LiteLLM for Multi-Provider LLM Access
        # Messages format: [ChatMessage(role=SYSTEM, ...), ChatMessage(role=USER, ...)]
        # Scenario: Verify messages are correctly formatted
        """
        config = ServerConfig(
            generator={"provider": "openai", "config": {"model": "gpt-4", "temperature": 0.7}},
            embedder={"provider": "tei", "config": {"model": "Qwen/Qwen3-Embedding-0.6B", "base_url": "http://localhost:8080"}}
        )
        agent = SoftwareArchitectAgent(config)

        mock_response = MagicMock()
        mock_response.raw = ResponseSchema(name="t", description="d", score=1.0)

        achat_calls = []

        async def mock_achat(messages):
            achat_calls.append(messages)
            return mock_response

        mock_structured_llm = AsyncMock()
        mock_structured_llm.achat = mock_achat

        original_client = agent._client
        agent._client = MagicMock()
        agent._client.as_structured_llm.return_value = mock_structured_llm

        try:
            await agent.generate_structured(
                system_prompt="System prompt",
                user_prompt="User prompt",
                response_schema=ResponseSchema
            )

            assert len(achat_calls) == 1
            messages = achat_calls[0]
            assert len(messages) == 2
            assert messages[0].role.value == "system"
            assert messages[0].content == "System prompt"
            assert messages[1].role.value == "user"
            assert messages[1].content == "User prompt"
        finally:
            agent._client = original_client


class TestErrorMapping:
    """
    # E-9: ERR_009 - LLM provider returned error
    # Verifies that connector exceptions are mapped to LLMError
    """

    @pytest.mark.asyncio
    async def test_generate_structured_raises_llm_error_on_exception(self):
        """
        # E-9: ERR_009 - LLM provider returned error
        # Scenario: Connector raises an exception
        """
        config = ServerConfig(
            generator={"provider": "openai", "config": {"model": "gpt-4", "temperature": 0.7}},
            embedder={"provider": "tei", "config": {"model": "Qwen/Qwen3-Embedding-0.6B", "base_url": "http://localhost:8080"}}
        )
        agent = SoftwareArchitectAgent(config)

        mock_llm = AsyncMock()
        mock_llm.achat.side_effect = Exception("API error: connection refused")

        original_client = agent._client
        agent._client = MagicMock()
        agent._client.as_structured_llm.return_value = mock_llm

        try:
            with pytest.raises(LLMError) as exc_info:
                await agent.generate_structured(
                    system_prompt="System",
                    user_prompt="User",
                    response_schema=ResponseSchema
                )

            assert exc_info.value.error == ERROR_LLM_PROVIDER
            assert exc_info.value.provider == "openai"
            assert "API error: connection refused" in exc_info.value.provider_message
        finally:
            agent._client = original_client

    @pytest.mark.asyncio
    async def test_generate_structured_lets_validation_error_propagate(self):
        """
        ValidationError must propagate uncaught so validate_with_retries can
        catch it and trigger self-healing retry.

        Before Fix: _generate_structured_once wrapped ALL exceptions as LLMError,
        breaking the retry loop (which only catches ValidationError).
        """
        config = ServerConfig(
            generator={"provider": "openai", "config": {"model": "gpt-4", "temperature": 0.7}},
            embedder={"provider": "tei", "config": {"model": "Qwen/Qwen3-Embedding-0.6B", "base_url": "http://localhost:8080"}}
        )
        agent = SoftwareArchitectAgent(config)

        mock_llm = AsyncMock()
        mock_exc = ValidationError.from_exception_data(
            "ResponseSchema",
            [{"type": "missing", "loc": ("name",), "msg": "Field required", "input": {}}],
        )
        mock_llm.achat.side_effect = mock_exc

        original_client = agent._client
        agent._client = MagicMock()
        agent._client.as_structured_llm.return_value = mock_llm

        try:
            with pytest.raises(ValidationError):
                await agent.generate_structured(
                    system_prompt="System",
                    user_prompt="User",
                    response_schema=ResponseSchema
                )
        finally:
            agent._client = original_client


class TestLLMError:
    """
    # E-9: ERR_009 - LLM provider returned error (HTTP 502, severity: error)
    # logging_context: provider, error, provider_message
    """

    def test_llm_error_attributes(self):
        """
        # E-9: LLMError has provider, error, provider_message attributes
        # Scenario: Create and verify LLMError attributes
        """
        error = LLMError(
            provider="openai",
            error="ERR_009",
            provider_message="API key invalid"
        )

        assert error.provider == "openai"
        assert error.error == "ERR_009"
        assert error.provider_message == "API key invalid"
        assert "openai" in str(error)
        assert "ERR_009" in str(error)


class TestConstants:
    """
    # Constants defined in task context
    """

    def test_error_llm_provider_code(self):
        """
        # ERROR_LLM_PROVIDER = "ERR_009"
        """
        assert ERROR_LLM_PROVIDER == "ERR_009"
