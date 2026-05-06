"""digest_via_agent — deterministic data brief + constrained LLM polish.

Used by morning_sprint_brief and end_of_week_recap. The Anthropic call
explicitly passes tools=[] so the model can NEVER call tools — it only
polishes the data we hand it.
"""

from __future__ import annotations

import logging

from jarvis.jobs import KindContext, KindResult, PlannedPost
from jarvis.jobs.github_queries import list_open_prs
from jarvis.jobs.kinds import register_kind

logger = logging.getLogger(__name__)

_MAX_TOKENS = 600
_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPTS: dict[str, str] = {
    "morning_sprint_brief": (
        "You polish a daily standup brief for a 4-person engineering team's Discord. "
        "Stay tight (≤200 words). Use plain Markdown headings + bullets. "
        "NEVER invent facts, PR numbers, or names. NEVER call tools — you don't have any. "
        "If the data is empty, say so honestly."
    ),
    "end_of_week_recap": (
        "You polish a Friday afternoon recap for a 4-person engineering team's Discord. "
        "Lead with what shipped this week, then carry-over items. ≤250 words. "
        "Plain Markdown bullets. NEVER invent facts. NEVER call tools."
    ),
}

_GRAPHQL = """
query($id: ID!) {
  node(id: $id) {
    ... on ProjectV2 {
      items(first: 100) {
        nodes {
          content {
            ... on Issue { title url number }
            ... on PullRequest { title url number }
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


async def _gather_sources(ctx: KindContext) -> dict:
    sources = ctx.job.params.get("sources", [])
    repo = getattr(ctx.settings, "github_repo", "tsuki-works/niko")
    project_id = getattr(ctx.settings, "github_project_id", None)
    out: dict = {}

    if "sprint" in sources and project_id:
        data = await ctx.github_client.graphql(_GRAPHQL, variables={"id": project_id})
        nodes = (((data or {}).get("node") or {}).get("items") or {}).get("nodes") or []
        items = []
        for n in nodes:
            content = n.get("content") or {}
            status = None
            for fv in (n.get("fieldValues") or {}).get("nodes") or []:
                if (fv.get("field") or {}).get("name") == "Status":
                    status = fv.get("name")
            items.append(
                {
                    "number": content.get("number"),
                    "title": content.get("title"),
                    "status": status,
                }
            )
        out["sprint"] = {"items": items}

    if "recent_commits" in sources:
        commits = await ctx.github_client.get(
            f"/repos/{repo}/commits", params={"sha": "master", "per_page": 20}
        )
        out["recent_commits"] = [
            {
                "sha": (c.get("sha") or "")[:8],
                "title": (c.get("commit", {}).get("message") or "").split("\n", 1)[0],
                "author": c.get("commit", {}).get("author", {}).get("name"),
            }
            for c in (commits or [])
        ]

    if "open_prs" in sources:
        out["open_prs"] = await list_open_prs(ctx.github_client, repo)

    if "merged_prs" in sources:
        prs = await ctx.github_client.get(
            f"/repos/{repo}/pulls",
            params={"state": "closed", "per_page": 30, "sort": "updated", "direction": "desc"},
        )
        out["merged_prs"] = [p for p in (prs or []) if p.get("merged_at")]

    return out


def _build_data_brief(data: dict) -> str:
    parts: list[str] = []
    sprint = data.get("sprint")
    if sprint and sprint.get("items"):
        parts.append("**Sprint**")
        for it in sprint["items"]:
            parts.append(
                f" • #{it.get('number')} [{it.get('status') or '?'}] {it.get('title') or ''}"
            )
    commits = data.get("recent_commits")
    if commits:
        parts.append("\n**Recent commits**")
        for c in commits[:10]:
            parts.append(f" • `{c.get('sha')}` {c.get('title')} ({c.get('author')})")
    prs = data.get("open_prs")
    if prs:
        parts.append("\n**Open PRs**")
        for p in prs[:10]:
            author = (p.get("user") or {}).get("login") or "?"
            parts.append(f" • PR #{p.get('number')} {p.get('title')} ({author})")
    merged = data.get("merged_prs")
    if merged:
        parts.append("\n**Merged this period**")
        for p in merged[:10]:
            parts.append(f" • PR #{p.get('number')} {p.get('title')}")
    return "\n".join(parts) if parts else "(no data — check back later)"


async def handle(ctx: KindContext) -> KindResult:
    data = await _gather_sources(ctx)
    brief = _build_data_brief(data)
    polish_key = ctx.job.params.get("polish_prompt", "morning_sprint_brief")
    system_prompt = _SYSTEM_PROMPTS.get(polish_key, _SYSTEM_PROMPTS["morning_sprint_brief"])

    try:
        msg = await ctx.anthropic_client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system_prompt,
            tools=[],
            messages=[
                {"role": "user", "content": f"{brief}\n\nWrite a short Discord-friendly summary."}
            ],
        )
        polished = "".join(getattr(b, "text", "") for b in (msg.content or []))
        if not polished.strip():
            polished = brief
    except Exception:  # noqa: BLE001
        logger.exception("digest polish failed; using deterministic brief")
        polished = brief

    return KindResult(posts=[PlannedPost(content=polished)], summary=polish_key)


register_kind("digest_via_agent", handle)
