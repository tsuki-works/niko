from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from jarvis.jobs.github_queries import (
    list_check_runs_for_ref,
    list_dependabot_prs,
    list_open_prs,
    list_pr_reviews,
)


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
async def test_list_pr_reviews_uses_pulls_review_endpoint():
    client = AsyncMock()
    client.get = AsyncMock(return_value=[{"state": "APPROVED"}])
    out = await list_pr_reviews(client, "tsuki-works/niko", 191)
    assert out[0]["state"] == "APPROVED"
    client.get.assert_awaited_once_with("/repos/tsuki-works/niko/pulls/191/reviews")


@pytest.mark.asyncio
async def test_list_check_runs_for_ref_returns_check_runs_array():
    client = AsyncMock()
    client.get = AsyncMock(return_value={"total_count": 2, "check_runs": [{"name": "ci"}]})
    out = await list_check_runs_for_ref(client, "tsuki-works/niko", "abcd")
    assert out == [{"name": "ci"}]


@pytest.mark.asyncio
async def test_list_dependabot_prs_filters_by_login():
    client = AsyncMock()
    client.get = AsyncMock(return_value=[
        {"number": 1, "user": {"login": "alice"}},
        {"number": 2, "user": {"login": "dependabot[bot]"}},
        {"number": 3, "user": {"login": "dependabot[bot]"}},
    ])
    out = await list_dependabot_prs(client, "tsuki-works/niko")
    assert [p["number"] for p in out] == [2, 3]
