# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""
L2 oracles for the TEI reranker boundary
(src/patterns/safe_tei_rerank.py; ledger rows TEI-1 / RET-1, garden
mutants FG-23 / FG-24).

  TEI-1  a result body exists ONLY for the OK verdict — HTTP errors and
         non-list bodies never produce one (pure error signals).
  RET-1  a rerank error propagates as RuntimeError — never a partial or
         un-reranked outcome.

Transport is stubbed with httpx.MockTransport; the production module's
``httpx.Client`` constructor is patched, so the real request-building and
response-handling code runs end to end. Decorrelated from L1
(test_retriever.py exercises chosen HTTP-error cases; this oracle generates
the status/body matrix).

Direction of the implication: the .fizz model (tei_fallback.fizz) checks
the verdict discipline exhaustively up to bounds; this oracle samples the
payload space of the real transport code.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any
from unittest import mock

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.patterns.safe_tei_rerank import _safe_tei_rerank_call

_ERROR_STATUSES = [400, 401, 403, 404, 422, 429, 500, 502, 503, 504]

_error_bodies = st.one_of(
    st.dictionaries(st.text(max_size=12), st.text(max_size=40), max_size=3),
    st.none(),
    st.integers(min_value=0, max_value=999),
)

_tei_result_row = st.fixed_dictionaries(
    {"index": st.integers(min_value=0, max_value=64), "score": st.floats(allow_nan=False)}
)


def _patch_transport(status_code: int, body: Any) -> AbstractContextManager[object]:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)

    fake_client = httpx.Client(transport=httpx.MockTransport(_handler))
    return mock.patch(
        "src.patterns.safe_tei_rerank.httpx.Client", return_value=fake_client
    )


class TestTEI1NoResultOnError:
    @given(
        status=st.sampled_from(_ERROR_STATUSES),
        body=_error_bodies,
    )
    @settings(max_examples=30)
    def test_http_error_never_returns_a_body(self, status: int, body: Any) -> None:
        with _patch_transport(status, body):
            with pytest.raises(RuntimeError, match="TEI reranker"):
                _safe_tei_rerank_call(
                    base_url="http://tei:80",
                    timeout=1.0,
                    auth_token=None,
                    query="q",
                    texts=["t1", "t2"],
                )

    @given(body=st.one_of(_error_bodies, st.text(min_size=1, max_size=80)))
    @settings(max_examples=30)
    def test_non_list_body_never_returns_a_body(self, body: Any) -> None:
        with _patch_transport(200, body):
            with pytest.raises(RuntimeError, match="TEI reranker") as exc_info:
                _safe_tei_rerank_call(
                    base_url="http://tei:80",
                    timeout=1.0,
                    auth_token=None,
                    query="q",
                    texts=["t1"],
                )
        message = str(exc_info.value)
        assert "non-list" in message or "malformed JSON" in message


class TestTEI1HappyPathUnchanged:
    """The OK verdict passes the parsed list body through unchanged."""

    @given(rows=st.lists(_tei_result_row, min_size=1, max_size=8))
    @settings(max_examples=20)
    def test_ok_list_body_passes_through(self, rows: list[dict[str, Any]]) -> None:
        with _patch_transport(200, rows):
            result = _safe_tei_rerank_call(
                base_url="http://tei:80",
                timeout=1.0,
                auth_token=None,
                query="q",
                texts=["t1"],
            )
        assert result == rows


class TestRET1ErrorPropagates:
    @given(status=st.sampled_from([500, 502, 503, 504]))
    @settings(max_examples=10)
    def test_sidecar_outage_raises_never_partial(self, status: int) -> None:
        with _patch_transport(status, {"error": "sidecar down"}):
            with pytest.raises(RuntimeError):
                _safe_tei_rerank_call(
                    base_url="http://tei:80",
                    timeout=1.0,
                    auth_token=None,
                    query="q",
                    texts=["a", "b", "c"],
                )

    @given(
        status=st.sampled_from(_ERROR_STATUSES),
        body=_error_bodies,
    )
    @settings(max_examples=15)
    def test_error_message_carries_status_not_traceback(
        self, status: int, body: Any
    ) -> None:
        with _patch_transport(status, body):
            with pytest.raises(RuntimeError) as exc_info:
                _safe_tei_rerank_call(
                    base_url="http://tei:80",
                    timeout=1.0,
                    auth_token=None,
                    query="q",
                    texts=["t"],
                )
        message = str(exc_info.value)
        assert f"HTTP {status}" in message
        assert "Traceback" not in message
