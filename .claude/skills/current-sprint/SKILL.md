---
name: current-sprint
description: Show the current sprint for the niko project — items from GitHub Project tsuki-works/niko #2 that are actively in progress, or the earliest incomplete Phase if nothing is in progress yet. Use when the user asks about the current sprint, what to work on now, what's in flight, or the active phase.
---

# Current Sprint

Find and display the active sprint tasks from the niko GitHub Project board.

## How to run

1. Query the project items as JSON:
   ```bash
   gh project item-list 2 --owner tsuki-works --format json --limit 100
   ```
   Each item has `title`, `status` (Todo / In progress / Done), `phase` (e.g. `Phase 0: Foundation`, `Phase 2: MVP`), and `content.body` (the issue body with checklist).

2. Pick the current sprint using this priority:
   - **(a)** Items where `status == "In progress"`. If any, those are the current sprint.
   - **(b)** Otherwise, the item(s) at the **lowest phase number** whose `status != "Done"`. Parse the phase number from the prefix (`Phase 0` → 0, `Phase 1` → 1, etc.).
   - If multiple items share the same phase (e.g. four Phase 2 sprints), show them all, but flag the earliest sprint number as "next up".

3. For each selected item, parse the checklist from `content.body`:
   - Count `- [x]` (done) and `- [ ]` (open) to compute progress.
   - Show: `title`, issue URL (`content.url`), phase, status, `done/total` checklist count, and the first 3 open checklist lines verbatim.

4. End with a one-line recommendation of what to pick up next (the first open checklist item from the earliest in-progress or lowest-phase sprint).

## Output shape

```
## Current sprint — <phase label>

### <issue title> — #<number> (<status>)
<url>
Progress: <done>/<total>
Next up:
  - [ ] <first open item>
  - [ ] <second open item>
  - [ ] <third open item>

(repeat per selected issue)

→ Recommended next task: <first open checklist item from the earliest issue>
```

## Notes

- Project ID is `PVT_kwDOEIgWQM4BVBdK` (niko, #2).
- If `gh` auth lacks `read:project`, tell the user to run `gh auth refresh -h github.com -s read:project` and stop.
- Don't invent items — only surface what the API returns. If the board is empty, say so.
