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
SafeTEIReranker - proper subclass of LlamaIndex's TextEmbeddingInference
that overrides _call_api to raise RuntimeError (instead of AssertionError)
when the TEI sidecar returns an error or non-list body.

This avoids the monkey-patch:
    lambda q, t: _safe_tei_rerank_call(...)

Used by: HybridPatternRetriever when reranker_config is provided.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

import httpx
from llama_index.postprocessor.tei_rerank import TextEmbeddingInference

if TYPE_CHECKING:
    pass


def _safe_tei_rerank_call(
    base_url: str,
    timeout: float,
    auth_token: str | Callable[[str], str] | None,
    query: str,
    texts: list[str],
) -> list[dict[str, Any]]:
    """Call TEI /rerank with HTTP status validation and informative error messages.

    Mirrors llama_index.postprocessor.tei_rerank.TextEmbeddingInference._call_api
    but raises RuntimeError (instead of an AssertionError) when TEI returns an
    error or a non-list response body.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if auth_token is not None:
        if callable(auth_token):
            headers["Authorization"] = auth_token(base_url)
        else:
            headers["Authorization"] = auth_token

    payload = {"query": query, "texts": texts}
    with httpx.Client() as client:
        resp = client.post(
            f"{base_url}/rerank",
            headers=headers,
            json=payload,
            timeout=timeout,
        )

    if resp.status_code >= 400:
        raise RuntimeError(
            f"TEI reranker {base_url}/rerank returned HTTP {resp.status_code}: {resp.text[:500]}"
        )

    body = resp.json()
    if not isinstance(body, list):
        raise RuntimeError(  # noqa: TRY004
            f"TEI reranker {base_url}/rerank returned non-list response "
            f"(HTTP {resp.status_code}): {str(body)[:500]}"
        )

    return body


class SafeTEIReranker(TextEmbeddingInference):
    """TEI reranker with informative RuntimeError on sidecar failures.

    Subclass-and-override is the documented extension point for the
    TextEmbeddingInference reranker (LlamaIndex docs).
    """

    def __init__(
        self,
        base_url: str,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        timeout: float = 60.0,
        top_n: int = 5,
        *,
        auth_token: str | Callable[[str], str] | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            model_name=model_name,
            timeout=timeout,
            top_n=top_n,
        )
        self.auth_token = auth_token

    def _call_api(self, query: str, texts: list[str]) -> list[dict[str, Any]]:
        """Call TEI /rerank with HTTP status validation and informative error messages.

        Raises RuntimeError (not AssertionError) when the sidecar returns an
        error or a non-list body, so callers can distinguish it from
        programming errors.
        """
        return _safe_tei_rerank_call(
            base_url=self.base_url,
            timeout=self.timeout,
            auth_token=self.auth_token,
            query=query,
            texts=texts,
        )
