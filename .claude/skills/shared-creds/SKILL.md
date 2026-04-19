---
name: shared-creds
description: Fetch shared third-party credentials (Twilio, Deepgram, Anthropic, ElevenLabs, Square, GCP service keys, etc.) from the team's private Discord channel `#shared-creds`. Use when the user asks for a credential, API key, account login, or "the shared X account info" — and when setting up a teammate's local env, configuring a third-party SDK, or wiring a new service that needs an existing team account.
---

# Shared Credentials

Tsuki Works keeps shared third-party credentials in a private Discord channel rather than a password manager during Phase 0–2. This skill explains how to retrieve them on demand via the Discord MCP.

## Where creds live

- **Server:** Tsuki Works
- **Channel:** `#shared-creds` (under category 🏢 COMPANY)
- **Channel ID:** `1495461045622280382`

The channel is private — only founders + the Discord MCP bot have read access. If you can't read it, see "Permission troubleshooting" below.

## How to fetch

Use the Discord MCP `mcp__discord__get_messages` tool. The channel name is fuzzy-matched, so any of these work:

```
channel: "shared-creds"
channel: "1495461045622280382"
```

Default `limit` is 10. Bump it (max 100) if the credential you need was posted earlier.

### Typical patterns

- **"Get me the Twilio creds"** → `get_messages(channel: "shared-creds", limit: 50)`, then scan the returned messages for one mentioning Twilio. Surface only the lines containing the relevant key/secret.
- **"What's the Anthropic API key?"** → same, filter by service name.
- **"Set up my local env for the dashboard"** → fetch all creds, write the relevant ones to `.env` (which is gitignored), confirm what was written without echoing the values back.

If the channel has more than 100 messages and the credential isn't in the latest 100, ask the user which service it's for and they'll repost it pinned.

## Hard rules

- **Never commit credentials to git.** The repo `.gitignore` already excludes `.env` and `.mcp.json` — verify any file you write a cred to is gitignored before saving.
- **Never save credentials to memory** (`MEMORY.md` or any `memory/*.md` file). Memory persists across sessions and across users; credentials must stay in Discord (the canonical store) and on the user's local disk only.
- **Never paste credentials into PR descriptions, commit messages, GitHub issues, GitHub Actions logs, or other public/shared surfaces.** Use repo Variables for non-secret config and repo Secrets (`gh secret set`) for sensitive values destined for CI.
- **Redact when summarizing.** If you fetched creds and need to report what you did, say "wrote Anthropic API key to `.env`" — do not echo the key value in chat unless the user explicitly asks "show me the key."
- **Don't fetch unprompted.** Only call `get_messages` on this channel when the user actually needs a credential. Routine work doesn't need to scan it.

## Adding a new credential

When a new third-party service is set up, post the credential to `#shared-creds` in this format so future fetches are easy to parse:

```
**<Service Name>** — <account email or username>
KEY_NAME=<value>
SECONDARY_KEY=<value>
notes: <expiry, who owns the account, anything non-obvious>
```

Use `mcp__discord__send_message` to post on the user's behalf when they ask, e.g. "post the new Deepgram key to shared-creds." Confirm the content with the user before sending.

## Permission troubleshooting

If `get_messages` returns `"Channel not found"` even though `mcp__discord__list_channels` shows `#shared-creds`, the bot lacks read permission on that specific channel. Tell the user to:

1. Right-click `#shared-creds` in Discord → **Edit Channel** → **Permissions**
2. Add the **bot user directly** (not just a role the bot might be in) with **View Channel** + **Read Message History**
3. Save, then retry the fetch

If the bot needs to *post* (for "add a new credential" flows), it also needs **Send Messages** on the channel.

## Why Discord and not a password manager

Phase 0–2 trade-off: a real password manager (1Password, Bitwarden) costs $5–10/seat/month and adds a setup tax for every founder. Discord is already the team comms hub, the bot integration is one-shot, and the founders rotate through credentials infrequently enough that this works for early-stage. Migrate to a real secrets manager when the team grows past 4 or when SOC 2 prep starts in Phase 4.
