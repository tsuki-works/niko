"""v1 manifest — seven jobs covering the team's most painful workflow gaps."""

from __future__ import annotations

from jarvis.jobs import Job

JOBS: list[Job] = [
    Job(
        name="morning_sprint_brief",
        kind="digest_via_agent",
        cron="0 9 * * 1-5",
        channel="#weekly-sync",
        params={
            "sources": ["sprint", "recent_commits", "open_prs"],
            "lookback_hours": 24,
            "polish_prompt": "morning_sprint_brief",
        },
    ),
    Job(
        name="pr_review_nudge",
        kind="pr_review_nudge",
        cron="0 10-18/4 * * 1-5",
        channel="#code-review",
        params={"min_age_hours": 4, "dedup_window": "1d"},
    ),
    Job(
        name="approved_pr_not_merged",
        kind="approved_pr_not_merged",
        cron="0 10-18/3 * * 1-5",
        channel="#code-review",
        params={"min_age_after_approval_hours": 2, "dedup_window": "12h"},
    ),
    Job(
        name="ci_red_pr_nudge",
        kind="ci_red_pr_nudge",
        cron="0 10-18/2 * * 1-5",
        channel="#code-review",
        params={"dedup_window": "6h"},
    ),
    Job(
        name="dependabot_pair_check",
        kind="dependabot_pair_check",
        cron="30 9 * * 1-5",
        channel="#code-review",
        params={
            "pairs": [
                ["react", "react-dom"],
                ["@types/react", "@types/react-dom"],
                ["eslint", "@typescript-eslint/parser", "@typescript-eslint/eslint-plugin"],
            ],
        },
    ),
    Job(
        name="stuck_in_progress",
        kind="stuck_in_progress",
        cron="0 11 * * 1-5",
        channel="#blockers",
        params={"stale_days": 3, "dedup_window": "1d"},
    ),
    Job(
        name="end_of_week_recap",
        kind="digest_via_agent",
        cron="0 16 * * 5",
        channel="#milestones-updates",
        params={
            "sources": ["sprint", "recent_commits", "merged_prs"],
            "lookback_hours": 168,
            "polish_prompt": "end_of_week_recap",
        },
    ),
]
