# bot/ — Jarvis 2.0

Team-owned Discord bot for the Tsuki Works niko project. Replaces the
off-the-shelf `@quadslab.io/discord-mcp` over six PRs (see
`docs/superpowers/specs/2026-05-01-jarvis-bot-design.md`).

This PR (PR 1) lands only the scaffold: the bot connects to the Discord
gateway, comes online in the guild, and serves `GET /healthz`. No
conversational behavior, no slash commands, no LLM calls. Those land
in PRs 2–6.

## Local dev

1. Install the dev deps (one-time):

   ```bash
   .venv/Scripts/python -m pip install -r bot/requirements-dev.txt
   ```

### Privileged intent

The bot enables the `message_content` intent (used for @-mentions in PR 2
onwards). This is a [privileged Discord intent](https://discord.com/developers/docs/topics/gateway#privileged-intents)
and must be toggled on in the bot's settings page in the
[Discord Developer Portal](https://discord.com/developers/applications)
under **Bot → Privileged Gateway Intents**, otherwise the gateway will
connect but `on_message` will receive empty `content` strings. PR 1 doesn't
depend on this (no `on_message` handler yet), but enable it now so PR 2
doesn't get a "why are messages empty" debugging detour.

2. Copy `.env.example` to `.env` (already gitignored) and fill in:

   - `DISCORD_BOT_TOKEN` — from the Discord developer portal. Use a
     **dev** bot account, not the production Jarvis token. Ask Meet for
     access, or create your own test bot in your own dev guild.
   - `DISCORD_GUILD_ID` — `1495086675523797032` for the Tsuki Works
     guild, or your dev guild ID.
   - `JARVIS_HTTP_PORT` — defaults to 8080.
   - `JARVIS_LOG_LEVEL` — `DEBUG` while iterating, `INFO` otherwise.

3. Run:

   ```bash
   PYTHONPATH=bot .venv/Scripts/python -m jarvis.main
   ```

   The bot should appear online in your guild within a few seconds.
   `curl http://localhost:8080/healthz` should return:

   ```json
   {"status": "ok", "commit_sha": "", "started_at": "2026-05-01T00:00:00+00:00"}
   ```

## Tests

From the repo root:

```bash
.venv/Scripts/python -m pytest bot/tests -v
```

The root `pytest.ini` includes `bot/tests` in `testpaths`, so a bare
`pytest` from the repo root runs both backend and bot tests.

The `live_discord` marker is reserved for tests that touch the live
gateway; PR 1 has none.
