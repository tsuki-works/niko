from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from jarvis.jobs.github_queries import list_dependabot_prs, list_open_prs


@pytest.mark.asyncio
async def test_list_open_prs_calls_correct_endpoint_and_returns_payload():
    client = AsyncMock()
    client.get = AsyncMock(return_value=[{"number": 1}, {"number": 2}])
    out = await list_open_prs(client, "tsuki-works/niko")
    assert out == [{"number": 1}, {"number": 2}]
    client.get.assert_awaited()
    args = client.get.call_args
    assert args.args[0] == "/repos/tsuki-works/niko/pulls"
    assert args.kwargs["params"]["state"] == "open"


@pytest.mark.asyncio
async def test_list_dependabot_prs_filters_by_login():
    client = AsyncMock()
    client.get = AsyncMock(
        return_value=[
            {"number": 1, "user": {"login": "alice"}},
            {"number": 2, "user": {"login": "dependabot[bot]"}},
            {"number": 3, "user": {"login": "dependabot[bot]"}},
        ]
    )
    out = await list_dependabot_prs(client, "tsuki-works/niko")
    assert [p["number"] for p in out] == [2, 3]
