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
- **`/pr-driven-dev`** — enforces feature-branch + PR workflow; never commit directly to `master`. Includes a rescue flow if edits start on `master` by accident.
- **`/shared-creds`** — fetches shared third-party credentials (Twilio, Deepgram, Anthropic, ElevenLabs, Square, etc.) from the private Discord `#shared-creds` channel via the Discord MCP. Encodes the don't-commit / don't-memory-save rules.
- **`/onboard-restaurant`** — admin-assisted onboarding from a restaurant website URL: scrapes name/phone/address/hours/menu, asks for any gaps (image-only menus, missing hours, etc.), writes `restaurants/<rid>.json`, and dry-runs/then-confirms `scripts/provision_restaurant.py`. The Sprint 2.1 path; pre-dates the Sprint 4.2 self-serve wizard.

## Discord integration

The team coordinates in the **Tsuki Works** Discord server. Two integration paths are live:

- **GitHub → Discord webhooks (passive):**
  - `#code-review` — PR opened/reviewed/merged, PR review comments, issue comments.
  - `#ci-alerts` — pushes, check runs, workflow runs, status events.
  Configured on the repo via `gh api repos/tsuki-works/niko/hooks`. Don't duplicate — before adding a webhook, `gh api repos/tsuki-works/niko/hooks` to see what's already there.
- **MCP (active, Claude-initiated):** `.mcp.json` at the repo root configures the `discord` MCP server (`@quadslab.io/discord-mcp`). File is gitignored; `.mcp.json.example` is the committed template. Use the Discord MCP tools to post to specific channels when the user asks for team updates, decisions-log entries, etc.

Useful channel IDs: `#code-review` = `1495194166886400021`, `#ci-alerts` = `1495194041246285857`, `#okrs-roadmap` = `1495192531766345919`, `#decisions-log` = `1495192153947766885`, `#blockers` = `1495192657545396354`, `#general` (COMPANY) = `1495192027913130074`, `#shared-creds` = `1495461045622280382` (use `/shared-creds` skill to fetch — never commit or memory-save credentials).

## Decisions & non-obvious context

- **Legal/LLC is intentionally deferred** until the product is near market-readiness (Phase 3 Beta or Phase 4 Production). Do not flag it as missing from Phase 0 exit criteria — this is a deliberate choice. The item lives under a "Deferred to Phase 3 / 4" section in issue #2.
- **Default branch is `master`** (not `main`).
- **Repo is public** — flipped from private to unlock branch-protection features on the free tier until the org moves to a paid/enterprise plan.
- **`master` is protected by a repository ruleset** (`gh api repos/tsuki-works/niko/rulesets`): PR required (1 approval, conversation resolution, stale-review dismissal), linear history enforced, force-push and deletion blocked, Copilot code review + code-quality checks on push. Repo admins can bypass — don't rely on bypass as the default path; land changes via PR.
- **Company branding** lives in an `assets/` folder (logos by Daniel).

## Conventions

- Commit messages: short imperative, followed by a blank line and a paragraph of context if needed. Keep Claude's co-author trailer when pair-programming with the assistant.
- Secrets (`.env`, `.mcp.json`) are gitignored — don't commit them.
