"""stuck_in_progress — flags Project items in 'In progress' with no recent commits."""

from __future__ import annotations

from datetime import timedelta

from jarvis.jobs import KindContext, KindResult, PlannedPost
from jarvis.jobs.github_queries import find_branch_with_issue_ref
from jarvis.jobs.kinds import register_kind
from jarvis.jobs.team import mention

_QUERY = """
query($id: ID!) {
  node(id: $id) {
    ... on ProjectV2 {
      items(first: 100) {
        nodes {
          id
          content {
            ... on Issue { title url number assignees(first: 5) { nodes { login } } }
            ... on PullRequest { title url number assignees(first: 5) { nodes { login } } }
          }
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2SingleSelectField { name } }
              }
            }
          }
        }
      }
    }
  }
}
"""


def _flatten_status(item: dict) -> str | None:
    for fv in (item.get("fieldValues") or {}).get("nodes") or []:
        if (fv.get("field") or {}).get("name") == "Status":
            return fv.get("name")
    return None


async def handle(ctx: KindContext) -> KindResult:
    project_id = getattr(ctx.settings, "github_project_id", None)
    repo = getattr(ctx.settings, "github_repo", "tsuki-works/niko")
    stale_days = int(ctx.job.params.get("stale_days", 3))
    if not project_id:
        return KindResult(posts=[], summary="no project_id configured")

    data = await ctx.github_client.graphql(_QUERY, variables={"id": project_id})
    nodes = (((data or {}).get("node") or {}).get("items") or {}).get("nodes") or []

    since = ctx.now - timedelta(days=stale_days)
    posts: list[PlannedPost] = []
    today = ctx.now.date().isoformat()

    for item in nodes:
        if _flatten_status(item) != "In progress":
            continue
        content = item.get("content") or {}
        number = content.get("number")
        if number is None:
            continue
        recent = await find_branch_with_issue_ref(ctx.github_client, repo, number, since=since)
        if recent:
            continue
        assignees = (content.get("assignees") or {}).get("nodes") or []
        first_login = assignees[0]["login"] if assignees else None
        title = content.get("title") or ""
        url = content.get("url") or ""
        posts.append(
            PlannedPost(
                content=f"⏳ {mention(first_login)} Issue #{number} has been 'In progress' for {stale_days}d+ with no recent commits — anything blocking? {title} {url}",
                dedup_key=f"item-{item.get('id')}_{today}",
            )
        )

    return KindResult(posts=posts, summary=f"{len(posts)} stuck item(s)")


register_kind("stuck_in_progress", handle)
