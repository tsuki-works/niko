# niko — Claude Code Guide

AI voice agent for restaurants. Built by **Tsuki Works** (4-person team).

## Repo state

This repo currently holds product documentation and project scaffolding — no application code yet. Code will arrive in Phase 1 (POC).

Key locations:
- `docs/` — product requirements, roadmap, architecture, sprint plan, team roles, and the master proposal. Read these before answering product/architecture questions.
- `.claude/skills/` — project-scoped Claude Code skills (see below).

## Project management

- **GitHub Project:** `tsuki-works/niko` #2 — https://github.com/orgs/tsuki-works/projects/2
- Each phase/sprint from `docs/02-product-roadmap.md` is tracked as a GitHub Issue with a checklist of deliverables.
- The project has a custom **Phase** single-select field (Phase 0 → Phase 5) in addition to the default Status field.
- When work starts on an item, flip its Status to **In progress** on the board — the `current-sprint` skill keys off that.

## Available skills

- **`/current-sprint`** — surfaces the active sprint from the project board. Prefers items with Status = "In progress"; falls back to the earliest incomplete Phase.

## Decisions & non-obvious context

- **Legal/LLC is intentionally deferred** until the product is near market-readiness (Phase 3 Beta or Phase 4 Production). Do not flag it as missing from Phase 0 exit criteria — this is a deliberate choice. The item lives under a "Deferred to Phase 3 / 4" section in issue #2.
- **Default branch is `master`** (not `main`).
- Branch protection on `master` is **not** enabled — GitHub requires a paid plan for this on private repos, and the org is on free. Treat `master` pushes with care.
- **Company branding** lives in an `assets/` folder (logos by Daniel).

## Conventions

- Commit messages: short imperative, followed by a blank line and a paragraph of context if needed. Keep Claude's co-author trailer when pair-programming with the assistant.
- Secrets (`.env`, `.mcp.json`) are gitignored — don't commit them.
