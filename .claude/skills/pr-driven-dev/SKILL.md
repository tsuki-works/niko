---
name: pr-driven-dev
description: Enforce pull-request-driven development on the niko repo — every change lands via a feature branch and PR, never directly to master. Use when starting a new task, when finishing work and ready to merge, or whenever the user mentions opening a PR, creating a feature branch, or wrapping up a task.
---

# PR-Driven Development

Every change to this repo lands through a feature branch and pull request. Direct commits to `master` are forbidden unless the user explicitly overrides.

## Detect the phase

On entry, check state:

```bash
git branch --show-current
git status --porcelain
```

- On `master` with no uncommitted changes → **Start flow** (user is about to pick up work).
- On `master` with uncommitted changes → **Rescue flow** (stash/move to a feature branch before committing).
- On a feature branch → either continue work or **Finish flow** if user signals they're done.

If unclear, ask the user which mode.

## Start flow — new task

1. Confirm the task. Prefer a GitHub issue number. If the user named an issue (e.g. "Phase 0" or #2), resolve it:
   ```bash
   gh issue view <N> --repo tsuki-works/niko --json number,title,state
   ```
   If no issue exists for the work, ask if one should be created first (issues are cheap; they also link PRs back to the roadmap).

2. Pick a branch name in the form `<type>/<issue>-<slug>`:
   - `type`: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`
   - `issue`: the GitHub issue number (omit if truly no issue applies)
   - `slug`: 2-5 lowercase words, hyphen-separated, describing the change

   Examples: `feat/4-multi-tenant-architecture`, `docs/2-update-phase0-exit-criteria`, `chore/ci-github-actions`.

3. Create and switch:
   ```bash
   git checkout master
   git pull --rebase
   git checkout -b <branch-name>
   ```

4. Optional — flip the project board item to **In progress** so `/current-sprint` surfaces it. This uses the issue's ProjectV2 item ID. If the user doesn't ask for it, skip.

5. Announce: "Working on branch `<name>` for issue #<N>." Then do the work.

## Rescue flow — uncommitted changes on master

If the user started editing on `master` by accident:

```bash
git stash -u
git checkout -b <branch-name>
git stash pop
```

Then continue on the feature branch. Do not commit the rescued changes directly to master.

## Finish flow — ready to merge

Trigger when the user says "done", "wrap up", "open a PR", "ship it", or similar.

1. **Sanity check** the branch:
   ```bash
   git status
   git log master..HEAD --oneline
   git diff master...HEAD --stat
   ```
   Make sure there are commits, no untracked staged-worthy files, and the diff is what the user expects.

2. **Run tests only if the project has them.** Detect:
   ```bash
   test -f package.json && jq -e '.scripts.test' package.json >/dev/null 2>&1 && echo "npm"
   test -f pyproject.toml -o -f pytest.ini && echo "pytest"
   test -f Cargo.toml && echo "cargo"
   ```
   If a test command is detected, run it. If tests fail, stop and surface failures.
   If no test suite is configured (true for this repo until Phase 1), skip the gate silently.

3. **Present exactly 4 options** (verbatim):

   ```
   Implementation complete. What would you like to do?

   1. Push and open a Pull Request (recommended — our default)
   2. Merge back to master locally (bypass PR)
   3. Keep the branch as-is (handle later)
   4. Discard this work

   Which option?
   ```

   Default strongly toward option 1. If the user picks option 2, warn: "This bypasses PR review — are you sure? (yes/no)".

4. **Option 1 — Push + PR:**
   ```bash
   git push -u origin <branch-name>
   gh pr create --repo tsuki-works/niko --base master --head <branch-name> \
     --title "<short imperative title>" \
     --body-file <tmp-body-file>
   ```

   PR body template:
   ```markdown
   ## Summary
   <2-3 bullets of what changed and why>

   ## Linked issue
   Closes #<N>    <!-- or "Relates to #<N>" if it doesn't fully resolve -->

   ## Test plan
   - [ ] <manual verification step>
   - [ ] <...>

   ## Notes
   <anything reviewer should know: tradeoffs, follow-ups, out-of-scope items>
   ```

   Output the PR URL when done. Don't auto-merge.

5. **Option 2 — Merge locally (discouraged):**
   ```bash
   git checkout master
   git pull --rebase
   git merge --no-ff <branch-name>
   git push
   git branch -d <branch-name>
   git push origin --delete <branch-name>
   ```

6. **Option 3 — Keep:** just report the branch name and stop.

7. **Option 4 — Discard:** require the user to type `discard` to confirm, then:
   ```bash
   git checkout master
   git branch -D <branch-name>
   # only delete remote if it was pushed
   git push origin --delete <branch-name> 2>/dev/null || true
   ```

## Hard rules

- **Never** commit directly to `master` unless the user explicitly says "commit to master" or "skip the PR".
- **Never** force-push to `master`. Force-push to feature branches is fine when rebasing.
- **Never** merge a PR without the user's say-so, even if checks pass.
- **Never** delete work (option 4) without typed `discard` confirmation.

## Common mistakes

- **Branch name without issue number** when an issue exists — reviewers lose the link. Always include `<issue>` when there is one.
- **Committing unrelated changes** — if the user's task is "fix X" but the diff also touches Y, ask before including Y; usually split into a second branch.
- **Opening a PR with an empty test plan** — if you genuinely can't test (no UI, no code yet), write "No runtime to test; docs-only change" so the reviewer knows it was considered.
- **Running tests when the repo has none** — wastes time and produces scary-looking errors. Detect first.

## Integration

- Pairs with `/current-sprint` — once a board item's Status is "In progress", that skill surfaces it. Optionally flip the status when starting work.
- Relies on `gh` CLI with `repo` and `project` scopes (already configured on this machine).
