"""dependabot_pair_check — flags simultaneously-open paired dependency bumps."""

from __future__ import annotations

import re

from jarvis.jobs import KindContext, KindResult, PlannedPost
from jarvis.jobs.github_queries import list_dependabot_prs
from jarvis.jobs.kinds import register_kind

_TITLE_RE = re.compile(r"^Bumps?\s+(?P<pkg>[@\w./-]+)\s+from\s")


def _extract_package(title: str) -> str | None:
    if not title:
        return None
    m = _TITLE_RE.match(title)
    return m.group("pkg") if m else None


async def handle(ctx: KindContext) -> KindResult:
    repo = getattr(ctx.settings, "github_repo", "tsuki-works/niko")
    pairs: list[list[str]] = ctx.job.params.get("pairs", [])
    if not pairs:
        return KindResult(posts=[], summary="no pairs configured")

    prs = await list_dependabot_prs(ctx.github_client, repo)
    by_pkg: dict[str, dict] = {}
    for pr in prs:
        pkg = _extract_package(pr.get("title") or "")
        if pkg:
            by_pkg[pkg] = pr

    posts: list[PlannedPost] = []
    today = ctx.now.date().isoformat()
    for group in pairs:
        present = [pkg for pkg in group if pkg in by_pkg]
        if len(present) < 2:
            continue
        lines = ["📦 Paired Dependabot PRs — merge together or master may break:"]
        for pkg in present:
            pr = by_pkg[pkg]
            lines.append(f" • PR #{pr['number']} bumps `{pkg}` — {pr.get('html_url') or ''}")
        dedup = "pair_" + "_".join(sorted(present)) + "_" + today
        posts.append(PlannedPost(content="\n".join(lines), dedup_key=dedup))

    return KindResult(posts=posts, summary=f"{len(posts)} pair group(s) flagged")


register_kind("dependabot_pair_check", handle)
