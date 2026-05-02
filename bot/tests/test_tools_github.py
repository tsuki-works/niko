"""Tests for jarvis.tools.github — GitHub-API-backed tools."""

from __future__ import annotations

from unittest.mock import AsyncMock

from jarvis.tools.github import build_get_recent_commits_tool


def _gh_with_response(data):
    gh = AsyncMock()
    gh.get = AsyncMock(return_value=data)
    return gh


async def test_get_recent_commits_returns_compact_records():
    raw = [
        {
            "sha": "abc123def456",
            "html_url": "https://github.com/o/r/commit/abc",
            "commit": {
                "message": "feat: did a thing\n\nbody we drop",
                "author": {"name": "Meet", "date": "2026-04-30T18:22:00Z"},
            },
        },
        {
            "sha": "789xyz",
            "html_url": "https://github.com/o/r/commit/789",
            "commit": {
                "message": "fix: another thing",
                "author": {"name": "Sandeep", "date": "2026-04-29T10:00:00Z"},
            },
        },
    ]
    gh = _gh_with_response(raw)
    desc = build_get_recent_commits_tool(
        github_client=gh, repo="tsuki-works/niko"
    )
    out = await desc.fn(n=2, branch="master")
    assert len(out) == 2
    assert out[0]["sha"] == "abc123de"  # short sha
    assert out[0]["title"] == "feat: did a thing"  # subject only
    assert out[0]["author"] == "Meet"
    assert out[0]["date"] == "2026-04-30T18:22:00Z"
    assert out[0]["url"] == "https://github.com/o/r/commit/abc"
    gh.get.assert_awaited_once()
    call_kwargs = gh.get.await_args.kwargs
    assert call_kwargs["params"]["sha"] == "master"
    assert call_kwargs["params"]["per_page"] == 2


async def test_get_recent_commits_defaults_to_master_and_10():
    gh = _gh_with_response([])
    desc = build_get_recent_commits_tool(
        github_client=gh, repo="tsuki-works/niko"
    )
    await desc.fn()
    params = gh.get.await_args.kwargs["params"]
    assert params["sha"] == "master"
    assert params["per_page"] == 10


async def test_get_recent_commits_clamps_n():
    gh = _gh_with_response([])
    desc = build_get_recent_commits_tool(
        github_client=gh, repo="tsuki-works/niko"
    )
    # Anthropic models occasionally pass big numbers; we cap to 50.
    await desc.fn(n=10000)
    assert gh.get.await_args.kwargs["params"]["per_page"] == 50
    # And clamps low values to 1.
    await desc.fn(n=0)
    assert gh.get.await_args.kwargs["params"]["per_page"] == 1


async def test_get_recent_commits_descriptor_metadata():
    gh = _gh_with_response([])
    desc = build_get_recent_commits_tool(
        github_client=gh, repo="tsuki-works/niko"
    )
    assert desc.name == "get_recent_commits"
    assert "commit" in desc.description.lower()
    assert "n" in desc.input_schema["properties"]
    assert "branch" in desc.input_schema["properties"]
    # Both args optional.
    assert desc.input_schema.get("required", []) == []
