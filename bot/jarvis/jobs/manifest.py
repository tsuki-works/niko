"""v1 manifest — synthesis-and-signal jobs for a 4-person team.

The original v1 included three PR-nag kinds (pr_review_nudge,
approved_pr_not_merged, ci_red_pr_nudge); they were removed before they
ever fired — judged too noisy for a small team where everyone already
sees PR state in #ci-alerts and the GitHub UI. If reintroduced later,
their kinds + tests live in git history and can be cherry-picked back.
"""

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
