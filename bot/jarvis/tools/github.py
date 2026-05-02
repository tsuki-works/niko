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
