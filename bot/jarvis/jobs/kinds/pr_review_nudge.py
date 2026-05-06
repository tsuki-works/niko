"""pr_review_nudge — pings #code-review for PRs waiting > N hours."""

from __future__ import annotations

from datetime import datetime, timedelta

from jarvis.jobs import KindContext, KindResult, PlannedPost
from jarvis.jobs.github_queries import list_open_prs
from jarvis.jobs.kinds import register_kind
from jarvis.jobs.team import mention


def _parse_iso8601(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def handle(ctx: KindContext) -> KindResult:
    repo = getattr(ctx.settings, "github_repo", "tsuki-works/niko")
    min_age_hours = int(ctx.job.params.get("min_age_hours", 4))
    threshold = ctx.now - timedelta(hours=min_age_hours)

    prs = await list_open_prs(ctx.github_client, repo)
    posts: list[PlannedPost] = []
    for pr in prs:
        if pr.get("draft"):
            continue
        created_str = pr.get("created_at") or pr.get("updated_at")
        if not created_str:
            continue
        created = _parse_iso8601(created_str)
        if created > threshold:
            continue

        reviewers = [r.get("login") for r in (pr.get("requested_reviewers") or []) if r]
        target = reviewers[0] if reviewers else (pr.get("user") or {}).get("login")
        age_hours = max(1, int((ctx.now - created).total_seconds() // 3600))
        number = pr.get("number")
        title = pr.get("title") or ""
        url = pr.get("html_url") or ""

        msg = f"👀 PR #{number} waiting on review ({age_hours}h) — {mention(target)} {title} {url}"
        posts.append(
            PlannedPost(
                content=msg,
                dedup_key=f"PR-{number}_{ctx.now.date().isoformat()}",
            )
        )

    return KindResult(
        posts=posts,
        summary=f"{len(posts)} PR(s) flagged",
    )


register_kind("pr_review_nudge", handle)
