"""approved_pr_not_merged — pings author when a green-checked, approved PR sits open."""

from __future__ import annotations

from datetime import datetime, timedelta

from jarvis.jobs import KindContext, KindResult, PlannedPost
from jarvis.jobs.github_queries import (
    list_check_runs_for_ref,
    list_open_prs,
    list_pr_reviews,
)
from jarvis.jobs.kinds import register_kind
from jarvis.jobs.team import mention


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def handle(ctx: KindContext) -> KindResult:
    repo = getattr(ctx.settings, "github_repo", "tsuki-works/niko")
    min_hours = int(ctx.job.params.get("min_age_after_approval_hours", 2))
    threshold = ctx.now - timedelta(hours=min_hours)

    prs = await list_open_prs(ctx.github_client, repo)
    posts: list[PlannedPost] = []
    for pr in prs:
        number = pr["number"]
        sha = (pr.get("head") or {}).get("sha")
        if not sha:
            continue

        reviews = await list_pr_reviews(ctx.github_client, repo, number)
        approvals = [r for r in reviews if r.get("state") == "APPROVED" and r.get("submitted_at")]
        if not approvals:
            continue
        latest_approval = max(_parse(r["submitted_at"]) for r in approvals)
        if latest_approval > threshold:
            continue

        check_runs = await list_check_runs_for_ref(ctx.github_client, repo, sha)
        completed = [c for c in check_runs if c.get("status") == "completed"]
        if not completed:
            continue
        if any(c.get("conclusion") not in ("success", "neutral", "skipped") for c in completed):
            continue

        author = (pr.get("user") or {}).get("login")
        age = max(1, int((ctx.now - latest_approval).total_seconds() // 3600))
        posts.append(PlannedPost(
            content=f"✅ PR #{number} approved {age}h ago and green — {mention(author)} ready to merge? {pr.get('html_url') or ''}",
            dedup_key=f"PR-{number}_approved_{latest_approval.date().isoformat()}",
        ))

    return KindResult(posts=posts, summary=f"{len(posts)} mergeable PR(s)")


register_kind("approved_pr_not_merged", handle)
