"""Tests for jarvis.github_client.AsyncGitHubClient.

Mocks httpx at the AsyncClient level — no live GitHub.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from jarvis.github_client import AsyncGitHubClient


def _make_response(status: int, json_body: dict) -> httpx.Response:
    request = httpx.Request("GET", "https://api.github.com/")
    return httpx.Response(status, json=json_body, request=request)


def _make_async_client(response: httpx.Response):
    """Return a MagicMock standing in for httpx.AsyncClient with .request()."""
    client = MagicMock()
    client.request = AsyncMock(return_value=response)
    return client


async def test_get_returns_parsed_json():
    response = _make_response(200, {"login": "tsuki-works"})
    httpx_client = _make_async_client(response)
    gh = AsyncGitHubClient(token="ghp_x", httpx_client=httpx_client)
    out = await gh.get("/orgs/tsuki-works")
    assert out == {"login": "tsuki-works"}
    httpx_client.request.assert_awaited_once()
    call_kwargs = httpx_client.request.await_args.kwargs
    assert call_kwargs["method"] == "GET"
    assert call_kwargs["url"] == "https://api.github.com/orgs/tsuki-works"
    assert call_kwargs["headers"]["Authorization"] == "Bearer ghp_x"
    assert call_kwargs["headers"]["Accept"] == "application/vnd.github+json"


async def test_get_with_params():
    response = _make_response(200, [{"sha": "abc"}])
    httpx_client = _make_async_client(response)
    gh = AsyncGitHubClient(token="t", httpx_client=httpx_client)
    out = await gh.get("/repos/x/y/commits", params={"per_page": 5})
    assert out == [{"sha": "abc"}]
    assert httpx_client.request.await_args.kwargs["params"] == {"per_page": 5}


async def test_graphql_posts_query_and_variables():
    response = _make_response(200, {"data": {"node": {"items": []}}})
    httpx_client = _make_async_client(response)
    gh = AsyncGitHubClient(token="t", httpx_client=httpx_client)
    out = await gh.graphql("query { x }", variables={"id": "PVT_x"})
    assert out == {"node": {"items": []}}
    kwargs = httpx_client.request.await_args.kwargs
    assert kwargs["method"] == "POST"
    assert kwargs["url"] == "https://api.github.com/graphql"
    assert kwargs["json"] == {"query": "query { x }", "variables": {"id": "PVT_x"}}


async def test_graphql_raises_on_top_level_errors():
    response = _make_response(200, {"errors": [{"message": "Could not resolve"}], "data": None})
    httpx_client = _make_async_client(response)
    gh = AsyncGitHubClient(token="t", httpx_client=httpx_client)
    with pytest.raises(RuntimeError, match="Could not resolve"):
        await gh.graphql("query { x }", variables={})


async def test_non_2xx_raises_with_status_and_body():
    response = _make_response(404, {"message": "Not Found"})
    httpx_client = _make_async_client(response)
    gh = AsyncGitHubClient(token="t", httpx_client=httpx_client)
    with pytest.raises(RuntimeError, match="404"):
        await gh.get("/repos/x/y/pulls/9999")


async def test_close_closes_underlying_client():
    httpx_client = _make_async_client(_make_response(200, {}))
    httpx_client.aclose = AsyncMock()
    gh = AsyncGitHubClient(token="t", httpx_client=httpx_client)
    await gh.close()
    httpx_client.aclose.assert_awaited_once()
