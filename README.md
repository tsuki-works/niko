# niko

AI voice agent for restaurants. Built by [Tsuki Works](https://github.com/tsuki-works).

> **Status:** Phase 0 — product scoping and team bootstrap. No application code yet; this repo currently holds product documentation and project scaffolding. Code arrives in Phase 1 (POC).

## What it is

A voice-AI platform that answers restaurant phones, takes orders and reservations in natural conversation, and drops those orders into the restaurant's POS. Target market: the 70%+ of restaurants still running on phone orders without a modern automation layer. See [`docs/PRODUCT-PROPOSAL.md`](docs/PRODUCT-PROPOSAL.md) for the full pitch.

## Docs

| File | Purpose |
|------|---------|
| [`docs/PRODUCT-PROPOSAL.md`](docs/PRODUCT-PROPOSAL.md) | Master proposal — market, product, team, financials |
| [`docs/01-product-requirements-document.md`](docs/01-product-requirements-document.md) | PRD — what we're building |
| [`docs/02-product-roadmap.md`](docs/02-product-roadmap.md) | Phase 0–5 roadmap, ~6 months to production |
| [`docs/03-technical-architecture.md`](docs/03-technical-architecture.md) | System design, tech stack options |
| [`docs/04-sprint-tracking-and-backlog.md`](docs/04-sprint-tracking-and-backlog.md) | Sprint cadence and backlog discipline |
| [`docs/05-team-roles-and-responsibilities.md`](docs/05-team-roles-and-responsibilities.md) | Who owns what |

## Roadmap tracking

Phase and sprint work is tracked on the [niko GitHub Project](https://github.com/orgs/tsuki-works/projects/2). Each phase/sprint from the roadmap is a GitHub issue with a checklist of deliverables, tagged with a custom **Phase** field (Phase 0 → Phase 5).

Group the board by **Phase** to see the roadmap at a glance.

## How we work

- **Default branch:** `master`.
- **PR-driven development:** every change lands through a feature branch and pull request. No direct commits to `master`. The `pr-driven-dev` Claude skill (see below) enforces this when using Claude Code.
- **Branch naming:** `<type>/<issue>-<slug>` — e.g. `feat/4-multi-tenant-architecture`, `docs/add-readme`. Omit `<issue>` only if no issue applies.
- **Commits:** short imperative title, blank line, paragraph of context if needed.

## Claude Code integration

This repo is set up to be worked on with [Claude Code](https://claude.com/claude-code). A few project-local conveniences:

- **[`CLAUDE.md`](CLAUDE.md)** — project guide loaded automatically by Claude Code: conventions, decisions, and non-obvious context.
- **`/current-sprint`** — skill that surfaces the active sprint from the project board (in-progress items, or the earliest incomplete Phase).
- **`/pr-driven-dev`** — skill that enforces the feature-branch + PR workflow described above, with a four-option finish flow (open PR / merge locally / keep / discard).

Skills live under [`.claude/skills/`](.claude/skills/).

### MCP setup (Discord)

The Claude skills talk to Discord through an MCP server. The runtime config lives in `.mcp.json`, which is gitignored because it holds a bot token. A committed `.mcp.json.example` shows the shape.

To set up locally:

1. Copy the example: `cp .mcp.json.example .mcp.json`
2. Ask an admin for the Tsuki Works Discord bot token, or generate your own at https://discord.com/developers/applications.
3. Paste it into the `DISCORD_TOKEN` field. Leave `DISCORD_GUILD_ID` as-is.
4. Restart Claude Code — the `discord` MCP server will start automatically.

Never commit a filled-in `.mcp.json`.

## Discord integration

GitHub activity auto-posts to the Tsuki Works Discord server:

| Event | Channel |
|-------|---------|
| PR opened / reviewed / merged, issue comments | `#code-review` |
| Pushes, CI check runs, workflow results | `#ci-alerts` |

Wired via GitHub → Discord channel webhooks (Discord's native GitHub integration — `/github` suffix on the webhook URL). Adjust event types in repo settings → Webhooks if the volume is wrong.

## Team

Four-person founding team at Tsuki Works. Role breakdown in [`docs/05-team-roles-and-responsibilities.md`](docs/05-team-roles-and-responsibilities.md).

Branding assets (logos, icon variants) are in [`assets/tsuki-works/`](assets/tsuki-works/).

## License

Private repository — all rights reserved to Tsuki Works for now. License decision deferred until closer to market.
