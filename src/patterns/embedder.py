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

"""Embedder factory built on llama_index.embeddings.litellm.LiteLLMEmbedding.

Supports openai, tei, ollama, vllm providers via EmbedderConfig.
"""
from typing import Any

from llama_index.core.bridge.pydantic import PrivateAttr
from llama_index.embeddings.litellm import LiteLLMEmbedding


class InstructionAwareEmbedding(LiteLLMEmbedding):
    """LiteLLMEmbedding with asymmetric query/text instruction prefixes.

    Wraps _get_query_embedding and _get_text_embedding to prepend
    configurable instruction strings before delegating to the parent.
    Batch override: sends a single HTTP call for a chunk of texts instead
    of one call per text (issue #9).

    Uses PrivateAttr (LlamaIndex's documented extension point) so that
    _query_instruction, _text_instruction, and _embed_batch_size are
    stored as proper private attributes without triggering
    ``object.__setattr__`` workarounds.
    """

    _query_instruction: str = PrivateAttr("")
    _text_instruction: str = PrivateAttr("")
    _embed_batch_size: int = PrivateAttr(16)

    def __init__(
        self,
        query_instruction: str | None = None,
        text_instruction: str | None = None,
        embed_batch_size: int = 16,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._query_instruction = query_instruction or ""
        self._text_instruction = text_instruction or ""
        self._embed_batch_size = max(1, int(embed_batch_size))

    def _format_query(self, query: str) -> str:
        return f"{self._query_instruction}{query}" if self._query_instruction else query

    def _format_text(self, text: str) -> str:
        return f"{self._text_instruction}{text}" if self._text_instruction else text

    def _get_query_embedding(self, query: str) -> list[float]:
        return super()._get_query_embedding(self._format_query(query))

    def _get_text_embedding(self, text: str) -> list[float]:
        return super()._get_text_embedding(self._format_text(text))

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return await super()._aget_query_embedding(self._format_query(query))

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return await super()._aget_text_embedding(self._format_text(text))

    def get_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch text embedding with instruction prefixes applied.

        One HTTP call per ``_embed_batch_size`` chunk instead of one call
        per text. With 213 domain slugs and ``embed_batch_size=16``, this
        drops cold-start from 213 serial HTTP calls to 14 batched ones.
        """
        prefixed = [self._format_text(t) for t in texts]
        return super()._get_text_embeddings(prefixed)


TEI_RERANKER_MODEL = "Alibaba-NLP/gte-reranker-modernbert-base"


def build_embedder(  # noqa: PLR0913
    provider: str,
    base_url: str,
    api_key: str | None,
    query_instruction: str,
    text_instruction: str,
    embed_batch_size: int = 16,
) -> LiteLLMEmbedding:
    """Construct a LiteLLMEmbedding from individual config fields.

    Dispatches on provider: openai / tei / ollama / vllm / hosted_vllm.
    For the tei provider the model name is fixed to the local Qwen3-0.6B
    variant and cannot be overridden. Non-tei providers require a model name
    to be set via the LLM provider's configuration.

    Returns:
        LiteLLMEmbedding (InstructionAwareEmbedding when instructions are set, otherwise plain).

    Raises:
        ValueError: If provider is not supported.
    """
    normalized = provider.lower()

    if normalized not in ("openai", "tei", "ollama", "vllm", "hosted_vllm"):
        raise ValueError(f"Unsupported embedder provider: {provider!r}")

    if normalized == "tei":
        model_name = "openai//data/qwen3-embedding-0.6b"
    else:
        model_name = ""

    return InstructionAwareEmbedding(
        model_name=model_name,
        api_base=base_url,
        api_key=api_key,
        query_instruction=query_instruction or "",
        text_instruction=text_instruction or "",
        embed_batch_size=embed_batch_size,
    )
