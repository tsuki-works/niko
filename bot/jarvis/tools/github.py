"""GitHub-backed tools for Jarvis.

PR 3a ships `get_recent_commits`. PR 3b will add `get_pr`,
`get_issue`, `open_issue` in the same module.
"""

from __future__ import annotations

from typing import Any

from jarvis.tools import ToolDescriptor

_MAX_COMMITS = 50


def _clamp_n(n: int) -> int:
    if n < 1:
        return 1
    if n > _MAX_COMMITS:
        return _MAX_COMMITS
    return n


def build_get_recent_commits_tool(
    *, github_client: Any, repo: str
) -> ToolDescriptor:
    async def get_recent_commits(
        n: int = 10, branch: str = "master"
    ) -> list[dict[str, Any]]:
        clamped = _clamp_n(n)
        raw = await github_client.get(
            f"/repos/{repo}/commits",
            params={"sha": branch, "per_page": clamped},
        )
        return [
            {
                "sha": (c.get("sha") or "")[:8],
                "title": (c.get("commit", {}).get("message") or "").split(
                    "\n", 1
                )[0],
                "author": c.get("commit", {})
                .get("author", {})
                .get("name"),
                "date": c.get("commit", {})
                .get("author", {})
                .get("date"),
                "url": c.get("html_url"),
            }
            for c in (raw or [])
        ]

    return ToolDescriptor(
        name="get_recent_commits",
        description=(
            "List the most recent commits on a branch of "
            "tsuki-works/niko. Defaults to master / last 10. Use this "
            "when the user asks 'what shipped this week?', 'what's "
            "in master?', 'recent changes?'. Each commit returns its "
            "short SHA, subject line, author, date, and GitHub URL."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "description": "Number of commits (1–50, default 10).",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch name (default 'master').",
                },
            },
            "required": [],
        },
        fn=get_recent_commits,
    )


def build_get_pr_tool(
    *, github_client: Any, repo: str
) -> ToolDescriptor:
    async def get_pr(number: int) -> dict[str, Any]:
        raw = await github_client.get(f"/repos/{repo}/pulls/{number}")
        return {
            "title": raw.get("title"),
            "state": raw.get("state"),
            "author": (raw.get("user") or {}).get("login"),
            "body": raw.get("body") or "",
            "files_changed": raw.get("changed_files"),
            "url": raw.get("html_url"),
        }

    return ToolDescriptor(
        name="get_pr",
        description=(
            "Fetch a single pull request from tsuki-works/niko by number. "
            "Returns title, state (open/closed/merged), author, body, "
            "files_changed count, and GitHub URL. Use this when the user "
            "asks 'what does PR #123 do?', 'is #123 ready?', or to read "
            "a PR's description before commenting."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "number": {
                    "type": "integer",
                    "description": "Pull request number (e.g., 191).",
                },
            },
            "required": ["number"],
        },
        fn=get_pr,
    )


def build_get_issue_tool(
    *, github_client: Any, repo: str
) -> ToolDescriptor:
    async def get_issue(number: int) -> dict[str, Any]:
        raw = await github_client.get(f"/repos/{repo}/issues/{number}")
        return {
            "title": raw.get("title"),
            "state": raw.get("state"),
            "body": raw.get("body") or "",
            "labels": [
                (l or {}).get("name") for l in (raw.get("labels") or [])
            ],
            "assignees": [
                (a or {}).get("login") for a in (raw.get("assignees") or [])
            ],
            "url": raw.get("html_url"),
        }

    return ToolDescriptor(
        name="get_issue",
        description=(
            "Fetch a single issue from tsuki-works/niko by number. "
            "Returns title, state, body, labels, assignees, and "
            "GitHub URL. Use this when the user asks 'what's #42 "
            "about?', 'who's working on #42?', or to read an issue "
            "before referencing it. Note that GitHub treats PRs as a "
            "subtype of issues — for PRs prefer get_pr for richer fields."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "number": {
                    "type": "integer",
                    "description": "Issue number (e.g., 42).",
                },
            },
            "required": ["number"],
        },
        fn=get_issue,
    )
