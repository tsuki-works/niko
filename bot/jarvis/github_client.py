"""Thin async GitHub API wrapper.

Two surfaces:
- REST  via .get() / .post() against https://api.github.com/<path>
- GraphQL via .graphql(query, variables) against https://api.github.com/graphql

Auth is a Bearer token (PAT in PR 3a; GitHub App installation token in PR 5).

Constructor takes the httpx client so tests can mock at that seam without
monkeypatching httpx.AsyncClient at module scope.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

_BASE_URL = "https://api.github.com"
_USER_AGENT = "jarvis-bot/0.1"


class AsyncGitHubClient:
    def __init__(
        self,
        *,
        token: str,
        httpx_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._token = token
        self._client = httpx_client or httpx.AsyncClient(timeout=10.0)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
        }

    async def get(
        self, path: str, params: Optional[dict[str, Any]] = None
    ) -> Any:
        url = _BASE_URL + path
        response = await self._client.request(
            method="GET",
            url=url,
            headers=self._headers(),
            params=params,
        )
        if response.status_code >= 300:
            raise RuntimeError(
                f"GitHub GET {path} -> {response.status_code}: {response.text}"
            )
        return response.json()

    async def post(self, path: str, json: dict[str, Any]) -> Any:
        url = _BASE_URL + path
        response = await self._client.request(
            method="POST",
            url=url,
            headers=self._headers(),
            json=json,
        )
        if response.status_code >= 300:
            raise RuntimeError(
                f"GitHub POST {path} -> {response.status_code}: {response.text}"
            )
        return response.json()

    async def graphql(
        self, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        url = _BASE_URL + "/graphql"
        response = await self._client.request(
            method="POST",
            url=url,
            headers=self._headers(),
            json={"query": query, "variables": variables},
        )
        if response.status_code >= 300:
            raise RuntimeError(
                f"GitHub GraphQL -> {response.status_code}: {response.text}"
            )
        body = response.json()
        if body.get("errors"):
            messages = "; ".join(
                e.get("message", "?") for e in body["errors"]
            )
            raise RuntimeError(f"GitHub GraphQL errors: {messages}")
        return body.get("data") or {}

    async def close(self) -> None:
        await self._client.aclose()
