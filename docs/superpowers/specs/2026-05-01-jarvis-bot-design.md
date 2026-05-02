# Jarvis 2.0 — Custom Discord Bot

**Status:** Draft, pending implementation plan
**Author:** Meet (with Claude)
**Date:** 2026-05-01
**Replaces:** `@quadslab.io/discord-mcp` (the off-the-shelf MCP currently wired in `.mcp.json`)

## 1. Goal

Replace the off-the-shelf Discord MCP ("Jarvis") with a team-owned bot that:

1. Is **bidirectional** — team members can talk to it in Discord channels, not just Claude Code talking out.
2. Is **agentic** — uses Claude tool-use to answer questions about the niko project (sprint state, recent commits, PRs, docs).
3. Continues to support **outbound posting from Claude Code sessions** (the current MCP's only job) without disrupting that flow.

The bot should feel like a teammate, not a chatbot wrapper. The bar is: "@-mention it asking what shipped this week, and it gives you a useful, accurate answer with links."

## 2. Non-goals

- **Not** a generalized Claude Code remote-execution surface in v1. The "have the bot dispatch a Claude Code session that opens a PR" path is deferred — see §10.
- **Not** a public-facing bot. Guild-restricted to the Tsuki Works server (`1495086675523797032`). No DMs from non-team users.
- **Not** a replacement for human moderation, on-call, or paging.

## 3. Stack

| Concern | Pick | Reasoning |
|---|---|---|
| Language | Python 3.12 | Matches `app/` backend. Shared idioms, shared deps, easy review for the team. |
| Discord library | `discord.py` 2.x | Mature, supports application commands + gateway + threads. The standard. |
| LLM | Anthropic Claude Sonnet 4.6 | Right speed/quality for chat. (Haiku 4.5 is reserved for the telephony hot path; mixing models inside one tool-use loop isn't supported.) Cost-tier downshift to Haiku for select non-conversational commands is a v1.1 optimization, not v1. |
| LLM SDK | `anthropic` Python SDK (already in backend) | Reuse existing patterns and the existing API key. |
| Persistence | Firestore | Same project, free tier, fits ephemeral per-thread state. No new database. |
| Deployment | GCE `e2-micro` (free tier, `us-west1`) | Discord gateway needs a persistent websocket; Cloud Run with min-instances=1 costs ~$10–15/mo idle and is the wrong abstraction. e2-micro is free forever and a single systemd unit is simpler than a Cloud Run revision dance. |
| Secrets | GCP Secret Manager | Same approach as the backend. No `.env` on the VM. |
| Observability | Cloud Logging + a Cloud Monitoring uptime check on the bot's `/healthz` | Consistent with existing infra. |

## 4. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Discord Guild (Tsuki Works)                                │
│                                                             │
│   #general, #blockers, #okrs-roadmap, …                     │
│        │  ▲                                                 │
│   @ /  │  │ replies, slash-command responses                │
│        ▼  │                                                 │
└────────┼──┼─────────────────────────────────────────────────┘
         │  │
         │  │ Discord Gateway (websocket, persistent)
         │  │
   ┌─────▼──┴─────┐
   │   bot/       │     GCE e2-micro VM (us-west1)
   │              │     systemd service: jarvis.service
   │  ┌────────┐  │
   │  │ events │  │  ←  on_message, on_app_command, on_ready
   │  └───┬────┘  │
   │      │       │
   │  ┌───▼────┐  │
   │  │ router │  │  →  conversational? slash? ignore?
   │  └───┬────┘  │
   │      │       │
   │  ┌───▼────┐  │       ┌──────────────────────────┐
   │  │ agent  │  │ ────► │ Anthropic API            │
   │  │ loop   │  │       │ (Sonnet 4.6 + tool-use)  │
   │  └───┬────┘  │       └──────────────────────────┘
   │      │       │
   │  ┌───▼────┐  │       ┌──────────────────────────┐
   │  │ tools  │  │ ────► │ GitHub API, Firestore,   │
   │  └────────┘  │       │ docs/ grep, project board│
   │              │       └──────────────────────────┘
   │  ┌────────┐  │
   │  │ http   │  │  ←  POST /post (auth: shared secret)
   │  │  api   │  │     used by the niko-discord-mcp shim
   │  └────────┘  │
   │  ┌────────┐  │
   │  │/healthz│  │  ←  uptime check
   │  └────────┘  │
   └──────────────┘
```

### 4.1 Modules (`bot/`)

```
bot/
├── pyproject.toml
├── Dockerfile                # for local dev / future portability
├── README.md
├── jarvis/
│   ├── __init__.py
│   ├── main.py               # entrypoint: starts gateway client + HTTP server
│   ├── config.py             # env/Secret-Manager loading, typed settings
│   ├── client.py             # the discord.py Bot subclass
│   ├── events.py             # on_message, on_ready, on_app_command_error
│   ├── router.py             # decides: ignore / chat / slash
│   ├── agent.py              # the Claude tool-use loop
│   ├── system_prompt.py      # builds the system prompt (team, sprint, repo)
│   ├── memory.py             # per-thread conversation buffer (Firestore)
│   ├── ratelimit.py          # per-user token + message budget
│   ├── tools/
│   │   ├── __init__.py       # tool registry
│   │   ├── sprint.py         # get_current_sprint
│   │   ├── github.py         # get_recent_commits, get_pr, get_issue, open_issue
│   │   ├── docs.py           # search_repo_docs
│   │   └── chat.py           # get_recent_messages
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── sprint.py         # /sprint
│   │   ├── ask.py            # /ask
│   │   ├── blockers.py       # /blockers
│   │   ├── issue.py          # /issue
│   │   └── digest.py         # /digest
│   └── http/
│       ├── __init__.py
│       └── app.py            # FastAPI app with /post and /healthz
└── tests/
    ├── test_router.py
    ├── test_agent.py
    ├── test_tools/
    └── test_http.py
```

Each module has one purpose. `agent.py` does not know about Discord; `client.py` does not know about Anthropic. The router is the only place those layers meet. This is a deliberate boundary so the agent can be unit-tested without a Discord stub and without hitting the live Anthropic API.

### 4.2 Conversational flow (@-mention)

1. `on_message` fires. Router checks: was the bot mentioned, or are we already in a thread the bot owns?
2. If mention in a top-level channel → bot creates a thread off the triggering message and replies in the thread. Channels stay clean.
3. Router loads thread memory (last N turns) from Firestore.
4. Agent runs the Claude tool-use loop with Sonnet 4.6:
   - System prompt = team roster + current-sprint snapshot + CLAUDE.md essentials + tool descriptions.
   - User turn = the new message + thread context.
   - LLM may emit `tool_use`; the loop runs the tool and feeds `tool_result` back. Max 6 tool steps per turn.
5. Final text streams back to Discord by editing the placeholder reply message every ~250ms (Discord rate-limit-friendly chunk size).
6. Memory is persisted, the turn is logged.

### 4.3 Slash commands (§5 lists them)

Registered as **guild commands** (instant propagation, guild-scoped). On `on_ready`, the bot syncs commands. Each command has its own handler in `commands/`.

### 4.4 Outbound from Claude Code (HTTP API)

`POST /post` accepts `{channel, content, replyTo?}` and posts via the bot's gateway connection. Auth: shared secret in `Authorization: Bearer <token>`. Used by a tiny custom MCP shim (§7) that replaces the QuadsLab MCP.

## 5. Slash commands

| Command | Behavior | Notes |
|---|---|---|
| `/sprint` | Posts current sprint summary (the `current-sprint` skill logic, server-side). | Public response in-channel. |
| `/blockers` | Summarizes the last 7 days of `#blockers` messages and tags blockers without owners. | Calls `get_recent_messages` + LLM. |
| `/ask <question>` | One-shot Q&A. No thread, ephemeral if invoker prefers. | Cheaper than @-mention; no memory. |
| `/issue <title>` | Opens a GitHub issue in `tsuki-works/niko`, pre-filled body, links it back. | Uses GitHub App token (see §8). Asks for body in a follow-up modal. |
| `/digest` | Generates a "what shipped, what's open, what's next" post. | Used for daily/weekly standups. Can be invoked by humans or by a scheduled cron task in v1.1. |

Out of scope for v1: `/agent`, `/deploy`, `/release`. These are §10 territory.

## 6. Tools (Claude tool-use)

The agent loop has access to:

| Tool | Args | Returns |
|---|---|---|
| `get_current_sprint()` | — | Same shape as `/current-sprint` skill output. |
| `get_recent_commits(n: int = 10, branch: str = "master")` | n, branch | List of `{sha, title, author, date, url}`. |
| `get_pr(number: int)` | number | `{title, state, author, body, files_changed, url}`. |
| `get_issue(number: int)` | number | `{title, state, body, labels, assignees, url}`. |
| `open_issue(title, body, labels?)` | … | `{number, url}`. Labels validated against an allowlist. |
| `search_repo_docs(query: str)` | query | List of `{path, snippet}` from `docs/`. Uses ripgrep over a fresh git clone refreshed hourly. |
| `get_recent_messages(channel: str, n: int = 50)` | … | Thread-safe read via the bot's own gateway connection. Channel allowlist (no DMs, no other servers). |

All tools have JSON schemas; the agent cannot call anything outside this set. New tools require a code change + PR review.

## 7. Replacing the QuadsLab MCP

Two-phase, no dark period:

**Phase 1 — Ship the bot alongside.** New bot runs on GCE; existing `@quadslab.io/discord-mcp` keeps working in Claude Code sessions. Both bots may be active simultaneously (different bot accounts, or the same one — see §11). Risk: low.

**Phase 2 — Custom MCP shim.** Add a tiny `tools/niko-discord-mcp/` (~50 LOC TypeScript or Python, runnable via `npx`-equivalent or `uvx`) that wraps `POST /post` and exposes the same tool surface Claude Code expects (`send_message`, `list_channels`, etc.). Update `.mcp.json.example` to point at the new shim. Update each teammate's local `.mcp.json` once. Retire the QuadsLab MCP from the example and from CLAUDE.md.

After Phase 2: one bot identity, one codebase, full control.

## 8. Auth & secrets

| Secret | Storage | Used by |
|---|---|---|
| Discord bot token | Secret Manager: `jarvis-discord-token` | gateway client |
| Anthropic API key | Reuse existing `anthropic-api-key` secret | agent loop |
| GitHub App private key + installation ID | Secret Manager: `jarvis-github-app` | GitHub tools (`get_pr`, `open_issue`, …) |
| `POST /post` shared secret | Secret Manager: `jarvis-post-secret` | the custom MCP shim |

GitHub access is via a **GitHub App** installed on `tsuki-works/niko` (not a PAT). Permissions: `issues:write`, `pull_requests:read`, `contents:read`. Rotate yearly.

The bot itself runs as a GCE service account with `secretmanager.secretAccessor` on those four secrets only.

## 9. Guardrails

- **Guild restriction.** Bot ignores messages from any guild other than `1495086675523797032`. DMs ignored except from a hardcoded admin allowlist (Meet, for runtime debugging).
- **Per-user rate limit.** Default: 20 LLM-backed interactions per user per hour. Counted across every command that calls Anthropic (chat, `/ask`, `/blockers`, `/digest`). Pure-data commands (`/sprint`, `/issue`) are unlimited.
- **Per-response token cap.** `max_tokens=1024` for chat, `max_tokens=2048` for `/digest`. Hard ceiling.
- **Tool-step cap.** Max 6 tool calls per agent turn. Prevents runaway loops.
- **Cost cap.** Bot exposes `/metrics` (Prometheus-style: tokens-in, tokens-out, cost-USD, per command). A daily Cloud Monitoring alert pages Meet if spend > $5/day. Hard kill-switch via a `bot.disabled` flag in Firestore — flipping it makes the bot reply with a maintenance message and skip all LLM calls.
- **Prompt-injection hygiene.** System prompt tells the model: it cannot post outside this guild, cannot @-everyone, cannot delete messages, cannot DM users. The actual permissions on the bot account match this — defense in depth.
- **No secrets in chat.** System prompt forbids ever reading or echoing files matching `.env`, `*.key`, `*-token*`, `secrets/*`. The `search_repo_docs` tool excludes those paths at the file-system level too.

## 10. Deferred: full remote Claude Code execution

Out of v1 scope. The realistic future path:

- A `/agent <task description>` slash command opens an ephemeral GitHub Actions workflow run that boots Claude Code in CI mode against a fresh branch, with the bot's GitHub App token. Output (PR link, logs) is posted back to the originating thread.
- Requires: tighter sandboxing of what the CI Claude can touch, a clear cost ceiling per run, and a human-approval gate before merge (which the existing branch protection already enforces).
- Track as a separate issue once v1 is stable. Tentative target: alongside Phase 4 (Production).

This is consciously deferred because the gap between "bot with tool-use" and "bot that writes and merges code" is large in surface area (auth, sandboxing, cost, abuse) and small in incremental value if the team is already opening PRs from Claude Code locally.

## 11. Open question — bot identity during the migration

Two options for Phase 1 (when both bots are active):

- **(a) Reuse the existing bot account.** Same token; the new bot uses the gateway, the QuadsLab MCP uses the REST API. They don't conflict on the wire, but only one process can hold the gateway connection at a time. Practically: Claude Code's MCP only does REST calls (no gateway), so no collision. **Recommended.**
- **(b) Register a new bot ("Jarvis 2") in Discord, run side-by-side, retire the old account in Phase 2.** Cleaner separation but two bot icons in the member list briefly.

Picking (a) unless the user prefers otherwise. This decision can be deferred to the implementation plan — not load-bearing for the design.

## 12. Rollout

| PR | Scope | Verifies |
|---|---|---|
| #1 | `bot/` scaffold: pyproject, Dockerfile, `main.py` boots and connects to the gateway, `/healthz` responds. | Bot appears online in Discord; `gh pr` CI green. |
| #2 | Conversational @-mention path with stub agent (no tools yet). Per-thread memory in Firestore. | @-mention in a test channel returns an LLM response in a thread. |
| #3 | Tool-use loop + tools (`sprint`, `github`, `docs`, `chat`). | "@bot what shipped this week?" returns a real, sourced answer. |
| #4 | Slash commands: `/sprint`, `/ask`, `/blockers`, `/issue`, `/digest`. | Each command works in a test channel. |
| #5 | GCE deploy: Terraform for VM + service account + Secret Manager bindings; systemd unit; uptime check. | Bot survives reboot; uptime check green for 24h. |
| #6 | Custom MCP shim + `.mcp.json.example` swap; CLAUDE.md update; retire QuadsLab MCP from docs. | Posting from Claude Code via the new shim works end-to-end. |

Each PR is independently reviewable and revertable. PR #5 is the only one that touches infra; everything before it can be tested locally with a dev bot token.

## 13. Testing

- **Unit tests** (`pytest`) on every module. Agent loop is tested against a recorded Anthropic response fixture (no live API in CI).
- **Tool tests** mock GitHub and Firestore; one integration test per tool against a live sandbox repo runs **only on `main` post-merge**, not on PRs.
- **No live Discord integration test.** Discord's API is rate-limited and flaky in CI; a smoke test on the dev bot in a `#bot-test` channel is a manual gate before each PR merge to `master`.
- **Local dev**: `bot/scripts/dev.py` runs the bot against a separate dev bot account in a private dev guild. Documented in `bot/README.md`.

## 14. Success criteria

- **Day 1 of v1.0:** the team can @-mention Jarvis in `#general` and ask "what shipped this week" and get a correct, link-rich reply within 10 seconds.
- **Week 1:** all five slash commands used at least once by a non-Meet teammate without help.
- **Month 1:** zero rate-limit incidents from Anthropic. Daily LLM cost under $1 at current team size.
- **Reliability:** bot uptime ≥ 99% over 30 days (excludes planned restarts). One `/healthz` failure paging Meet.

## 15. Decisions log entry (to be posted on merge of PR #6)

> **Decision:** Replaced the off-the-shelf `@quadslab.io/discord-mcp` with `bot/` (Jarvis 2.0), a team-owned Python bot running on GCE e2-micro. Custom MCP shim now mediates Claude-Code → Discord. Bidirectional in-channel use is unlocked; agentic tool-use surfaces sprint state, GitHub data, and docs.
>
> **Rationale:** Off-the-shelf MCP was outbound-only and not extensible. Owning the bot gives us slash commands, agentic Q&A, and a path toward `/agent` in a later phase.

---

**End of design.**
