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


from jarvis.tools.github import build_get_pr_tool


async def test_get_pr_returns_compact_record():
    raw = {
        "title": "Add Twilio recording",
        "state": "open",
        "user": {"login": "meet"},
        "body": "Closes #42. Adds recording webhook.",
        "changed_files": 5,
        "html_url": "https://github.com/o/r/pull/123",
    }
    gh = AsyncMock()
    gh.get = AsyncMock(return_value=raw)
    desc = build_get_pr_tool(github_client=gh, repo="tsuki-works/niko")
    out = await desc.fn(number=123)
    assert out == {
        "title": "Add Twilio recording",
        "state": "open",
        "author": "meet",
        "body": "Closes #42. Adds recording webhook.",
        "files_changed": 5,
        "url": "https://github.com/o/r/pull/123",
    }
    gh.get.assert_awaited_once_with("/repos/tsuki-works/niko/pulls/123")


async def test_get_pr_handles_null_body():
    raw = {
        "title": "T",
        "state": "closed",
        "user": {"login": "u"},
        "body": None,
        "changed_files": 0,
        "html_url": "u",
    }
    gh = AsyncMock()
    gh.get = AsyncMock(return_value=raw)
    desc = build_get_pr_tool(github_client=gh, repo="o/r")
    out = await desc.fn(number=1)
    assert out["body"] == ""


async def test_get_pr_descriptor_metadata():
    gh = AsyncMock()
    desc = build_get_pr_tool(github_client=gh, repo="o/r")
    assert desc.name == "get_pr"
    assert "pull request" in desc.description.lower() or "pr" in desc.description.lower()
    assert desc.input_schema["properties"]["number"]["type"] == "integer"
    assert desc.input_schema.get("required") == ["number"]


from jarvis.tools.github import build_get_issue_tool


async def test_get_issue_returns_compact_record():
    raw = {
        "title": "Fix the thing",
        "state": "open",
        "body": "Steps to reproduce: ...",
        "labels": [
            {"name": "bug"},
            {"name": "phase-2"},
        ],
        "assignees": [
            {"login": "meet"},
            {"login": "sandeep"},
        ],
        "html_url": "https://github.com/o/r/issues/45",
    }
    gh = AsyncMock()
    gh.get = AsyncMock(return_value=raw)
    desc = build_get_issue_tool(github_client=gh, repo="o/r")
    out = await desc.fn(number=45)
    assert out == {
        "title": "Fix the thing",
        "state": "open",
        "body": "Steps to reproduce: ...",
        "labels": ["bug", "phase-2"],
        "assignees": ["meet", "sandeep"],
        "url": "https://github.com/o/r/issues/45",
    }
    gh.get.assert_awaited_once_with("/repos/o/r/issues/45")


async def test_get_issue_handles_empty_labels_assignees():
    raw = {
        "title": "T",
        "state": "closed",
        "body": "",
        "labels": [],
        "assignees": [],
        "html_url": "u",
    }
    gh = AsyncMock()
    gh.get = AsyncMock(return_value=raw)
    desc = build_get_issue_tool(github_client=gh, repo="o/r")
    out = await desc.fn(number=1)
    assert out["labels"] == []
    assert out["assignees"] == []


async def test_get_issue_descriptor_metadata():
    gh = AsyncMock()
    desc = build_get_issue_tool(github_client=gh, repo="o/r")
    assert desc.name == "get_issue"
    assert "issue" in desc.description.lower()
    assert desc.input_schema["properties"]["number"]["type"] == "integer"
    assert desc.input_schema.get("required") == ["number"]


from jarvis.tools.github import build_open_issue_tool


async def test_open_issue_creates_issue_with_basic_fields():
    raw = {"number": 200, "html_url": "https://github.com/o/r/issues/200"}
    gh = AsyncMock()
    gh.post = AsyncMock(return_value=raw)
    desc = build_open_issue_tool(
        github_client=gh,
        repo="o/r",
        allowed_labels=["bug", "feature"],
    )
    out = await desc.fn(title="Bug: x", body="Steps: ...", labels=["bug"])
    assert out == {"number": 200, "url": "https://github.com/o/r/issues/200"}
    gh.post.assert_awaited_once()
    path, kwargs = gh.post.await_args.args[0], gh.post.await_args.kwargs
    assert path == "/repos/o/r/issues"
    payload = kwargs["json"]
    assert payload["title"] == "Bug: x"
    assert payload["body"] == "Steps: ..."
    assert payload["labels"] == ["bug"]


async def test_open_issue_drops_labels_not_in_allowlist():
    raw = {"number": 201, "html_url": "u"}
    gh = AsyncMock()
    gh.post = AsyncMock(return_value=raw)
    desc = build_open_issue_tool(
        github_client=gh,
        repo="o/r",
        allowed_labels=["bug", "feature"],
    )
    out = await desc.fn(
        title="t", body="b", labels=["bug", "production-incident", "paid"]
    )
    payload = gh.post.await_args.kwargs["json"]
    assert payload["labels"] == ["bug"]
    assert out["dropped_labels"] == ["production-incident", "paid"]


async def test_open_issue_omits_labels_field_when_none_accepted():
    raw = {"number": 202, "html_url": "u"}
    gh = AsyncMock()
    gh.post = AsyncMock(return_value=raw)
    desc = build_open_issue_tool(
        github_client=gh,
        repo="o/r",
        allowed_labels=["bug"],
    )
    out = await desc.fn(title="t", body="b", labels=["foo", "bar"])
    payload = gh.post.await_args.kwargs["json"]
    assert "labels" not in payload  # don't send empty list
    assert out["dropped_labels"] == ["foo", "bar"]


async def test_open_issue_handles_no_labels_kwarg():
    raw = {"number": 203, "html_url": "u"}
    gh = AsyncMock()
    gh.post = AsyncMock(return_value=raw)
    desc = build_open_issue_tool(
        github_client=gh,
        repo="o/r",
        allowed_labels=["bug"],
    )
    out = await desc.fn(title="t", body="b")
    payload = gh.post.await_args.kwargs["json"]
    assert "labels" not in payload
    assert "dropped_labels" not in out


async def test_open_issue_descriptor_metadata():
    gh = AsyncMock()
    desc = build_open_issue_tool(
        github_client=gh, repo="o/r", allowed_labels=["bug"]
    )
    assert desc.name == "open_issue"
    assert "open" in desc.description.lower() or "create" in desc.description.lower()
    props = desc.input_schema["properties"]
    assert props["title"]["type"] == "string"
    assert props["body"]["type"] == "string"
    assert props["labels"]["type"] == "array"
    assert props["labels"]["items"]["type"] == "string"
    # title and body required; labels optional.
    assert set(desc.input_schema.get("required", [])) == {"title", "body"}
