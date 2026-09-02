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

All embeddings are L2-normalised on the way out so that a FAISS
``IndexFlatIP`` inner product equals cosine similarity — the same contract
the former custom DomainVectorIndex enforced in its own ``_embed`` helper.
"""
from typing import Any

import numpy as np
from llama_index.core.bridge.pydantic import PrivateAttr
from llama_index.embeddings.litellm import LiteLLMEmbedding


def _normalize(vecs: list[list[float]]) -> list[list[float]]:
    """L2-normalise embedding vectors row-wise (zero vectors pass through)."""
    arr = np.asarray(vecs, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (arr / norms).tolist()


class InstructionAwareEmbedding(LiteLLMEmbedding):
    """LiteLLMEmbedding with asymmetric query/text instruction prefixes.

    Wraps _get_query_embedding and _get_text_embedding to prepend
    configurable instruction strings before delegating to the parent.

    Uses PrivateAttr (LlamaIndex's documented extension point) so that
    _query_instruction and _text_instruction are stored as proper private
    attributes without triggering ``object.__setattr__`` workarounds.

    Every embedding-producing path normalises its output to unit length
    (see module docstring): single query/text, plural batch, and async
    variants. Batch chunking is delegated to the upstream
    ``BaseEmbedding.get_text_embedding_batch`` implementation, which
    flushes every ``embed_batch_size`` texts through the overridden
    ``_get_text_embeddings`` (instruction prefix + normalisation applied
    per chunk) and additionally provides the embeddings cache, rate
    limiting, and dispatcher/callback events.
    """

    _query_instruction: str = PrivateAttr("")
    _text_instruction: str = PrivateAttr("")

    def __init__(
        self,
        query_instruction: str | None = None,
        text_instruction: str | None = None,
        embed_batch_size: int = 16,
        **kwargs: Any,
    ) -> None:
        kwargs.pop("embed_batch_size", None)
        super().__init__(embed_batch_size=max(1, int(embed_batch_size)), **kwargs)
        self._query_instruction = query_instruction or ""
        self._text_instruction = text_instruction or ""

    def _format_query(self, query: str) -> str:
        return f"{self._query_instruction}{query}" if self._query_instruction else query

    def _format_text(self, text: str) -> str:
        return f"{self._text_instruction}{text}" if self._text_instruction else text

    def _get_query_embedding(self, query: str) -> list[float]:
        return _normalize([super()._get_query_embedding(self._format_query(query))])[0]

    def _get_text_embedding(self, text: str) -> list[float]:
        return _normalize([super()._get_text_embedding(self._format_text(text))])[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return _normalize(super()._get_text_embeddings([self._format_text(t) for t in texts]))

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return _normalize([await super()._aget_query_embedding(self._format_query(query))])[0]

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return _normalize([await super()._aget_text_embedding(self._format_text(text))])[0]


TEI_RERANKER_MODEL = "Alibaba-NLP/gte-reranker-modernbert-base"


def build_embedder(
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
