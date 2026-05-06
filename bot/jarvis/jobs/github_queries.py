"""Read-only GitHub queries shared by ≥2 kind handlers.

Kept separate from bot/jarvis/tools/github.py — those are agent-callable
ToolDescriptors, these are async helpers callable directly from kinds.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


async def list_open_prs(client: Any, repo: str, *, max_pages: int = 2) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        chunk = await client.get(
            f"/repos/{repo}/pulls",
            params={"state": "open", "per_page": 100, "page": page},
        )
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < 100:
            break
    return out


async def list_dependabot_prs(client: Any, repo: str) -> list[dict[str, Any]]:
    prs = await list_open_prs(client, repo)
    return [p for p in prs if (p.get("user") or {}).get("login") == "dependabot[bot]"]


async def find_branch_with_issue_ref(
    client: Any, repo: str, issue_number: int, *, since: datetime
) -> dict[str, Any] | None:
    """Find the most recent commit whose message references #<issue_number>.

    Uses the GitHub search-commits API. Returns None if no matching commit
    is newer than `since`. The first hit is enough — we just need
    'has anyone touched this issue lately?' for staleness detection.
    """
    q = f"repo:{repo} #{issue_number}"
    raw = await client.get("/search/commits", params={"q": q, "per_page": 5})
    items = (raw or {}).get("items") or []
    since_iso = since.isoformat().replace("+00:00", "Z")
    for item in items:
        committed = ((item.get("commit") or {}).get("committer") or {}).get("date")
        if committed and committed >= since_iso:
            return item
    return None
