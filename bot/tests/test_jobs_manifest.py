from __future__ import annotations

# Importing kinds populates the registry; importing manifest then validates.
import jarvis.jobs.kinds.approved_pr_not_merged  # noqa: F401
import jarvis.jobs.kinds.ci_red_pr_nudge  # noqa: F401
import jarvis.jobs.kinds.dependabot_pair_check  # noqa: F401
import jarvis.jobs.kinds.digest_via_agent  # noqa: F401
import jarvis.jobs.kinds.pr_review_nudge  # noqa: F401
import jarvis.jobs.kinds.stuck_in_progress  # noqa: F401
from jarvis.jobs.manifest import JOBS
from jarvis.jobs.scheduler import validate_manifest


def test_v1_manifest_has_seven_jobs():
    assert len(JOBS) == 7
    names = {j.name for j in JOBS}
    assert names == {
        "morning_sprint_brief", "pr_review_nudge", "approved_pr_not_merged",
        "ci_red_pr_nudge", "dependabot_pair_check", "stuck_in_progress",
        "end_of_week_recap",
    }


def test_v1_manifest_validates():
    validate_manifest(JOBS)
