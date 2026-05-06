"""ci_red_pr_nudge — pings author when an open PR has at least one failing check-run."""

from __future__ import annotations

from jarvis.jobs import KindContext, KindResult, PlannedPost
from jarvis.jobs.github_queries import list_check_runs_for_ref, list_open_prs
from jarvis.jobs.kinds import register_kind
from jarvis.jobs.team import mention

_FAIL_CONCLUSIONS = {"failure", "timed_out", "cancelled", "action_required"}


async def handle(ctx: KindContext) -> KindResult:
    repo = getattr(ctx.settings, "github_repo", "tsuki-works/niko")
    prs = await list_open_prs(ctx.github_client, repo)
    posts: list[PlannedPost] = []
    for pr in prs:
        sha = (pr.get("head") or {}).get("sha")
        number = pr["number"]
        if not sha:
            continue
        runs = await list_check_runs_for_ref(ctx.github_client, repo, sha)
        failing = [r for r in runs if (r.get("conclusion") or "") in _FAIL_CONCLUSIONS]
        if not failing:
            continue
        first = failing[0]
        check_name = first.get("name") or "unknown"
        check_url = first.get("html_url") or ""
        author = (pr.get("user") or {}).get("login")
        posts.append(PlannedPost(
            content=f"❌ PR #{number} — `{check_name}` failed. {mention(author)} {check_url or pr.get('html_url') or ''}",
            dedup_key=f"PR-{number}_red_{sha}_{check_name}",
        ))
    return KindResult(posts=posts, summary=f"{len(posts)} red PR(s)")


register_kind("ci_red_pr_nudge", handle)
