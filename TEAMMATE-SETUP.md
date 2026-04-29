# Teammate Setup — Claude Code + Agent Teams

Get from `git clone` to "I can dispatch a `niko-developer` agent to land an issue" in ~10 minutes.

> Backstory: we use Claude Code with a custom set of project-scoped subagents (`niko-developer`, `niko-tester`, `niko-reviewer`, `niko-pm`) and the `superpowers` plugin's brainstorm → spec → plan → dispatch workflow. Sprint 2.2 was shipped end-to-end this way (#104, #106, #108, #110, #112). This doc is the on-ramp.

---

## 1. Prerequisites

- **Claude Code ≥ 2.1.32.** Older versions don't support agent teams. Check: `claude --version`.
- **Python 3.12** (backend dev). `python --version`.
- **Node 20+** + **pnpm** (dashboard dev). `node --version && pnpm --version`.
- **`gh` CLI** authenticated against the `tsuki-works` org. `gh auth status`.

If anything's missing, fix it before continuing.

---

## 2. Clone + first run

```bash
git clone git@github.com:tsuki-works/niko.git
cd niko
```

What you get for free from the clone:

| Path | What it does |
|---|---|
| `.claude/agents/*.md` | The 4 niko-* subagent definitions. Auto-loaded by Claude Code in this repo. |
| `.claude/skills/*` | Project-scoped skills: `/current-sprint`, `/pr-driven-dev`, `/shared-creds`, `/onboard-restaurant`. |
| `.claude/settings.json` | Has `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` enabled. |
| `.mcp.json.example` | Template for the Discord MCP. Copy to `.mcp.json` (next step). |
| `CLAUDE.md` | The repo's instruction file; Claude Code reads it on every session. |

---

## 3. Install plugins

The `superpowers` plugin is the engine — it provides the `brainstorming`, `writing-plans`, `subagent-driven-development`, `executing-plans`, and `requesting-code-review` skills. Without it, the workflow doesn't exist.

In Claude Code:

```
/plugin install superpowers
```

**Optional plugins we use selectively:**

```
/plugin install frontend-design       # for net-new UI work
/plugin install feature-dev           # alt feature-dev workflow
/plugin install pr-review-toolkit     # alt PR review tools
```

Verify with:

```
/plugin list
```

---

## 4. Configure the Discord MCP

We use Discord for credential sharing + project comms. The MCP gives Claude Code authenticated access to read `#shared-creds` and post updates.

```bash
cp .mcp.json.example .mcp.json
```

Open `.mcp.json` and fill in `DISCORD_TOKEN`:

1. Open Discord → **Tsuki Works** server → `#shared-creds` channel
2. Find the message titled **"Discord MCP bot"** — copy the `DISCORD_TOKEN=...` value
3. Paste into `.mcp.json` (already templated to the right shape)

Restart Claude Code so it picks up the MCP server. Verify:

```
/mcp
```

You should see `discord` listed as connected. If reconnect fails, check `node`/`npx` are on `PATH` and that the token is valid.

**`.mcp.json` is gitignored** — don't commit it.

---

## 5. Set up `.env`

The backend reads API keys from `.env` at the repo root.

```bash
touch .env  # if it doesn't exist
```

Fetch each key from `#shared-creds`:

```dotenv
ANTHROPIC_API_KEY=sk-ant-api03-...        # required for any LLM work
DEEPGRAM_API_KEY=...                      # required for STT
TWILIO_ACCOUNT_SID=AC...                  # required for telephony
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1...
ELEVENLABS_API_KEY=sk_...                 # legacy; we now use Deepgram TTS
SQUARE_ACCESS_TOKEN=...                   # only needed for Sprint 2.3+
```

`.env` is gitignored. Once the Discord MCP is up, you can ask Claude to fetch a specific key for you (it'll use the `/shared-creds` skill).

---

## 6. Verify the setup with a quick smoke

In Claude Code, open the niko repo and try these one at a time:

```
/current-sprint
```

Should print the active sprint items from the project board.

```
"List the niko-* subagents and what each does"
```

Should reference `niko-developer`, `niko-tester`, `niko-reviewer`, `niko-pm` — pulled from `.claude/agents/`.

```
"Brainstorm a tiny test feature, then dispatch niko-developer to add a hello-world test"
```

Should walk through brainstorm → present design → ask for approval → spec → plan → dispatch a single test commit. Cancel before it commits if you don't actually want the test.

If any of these fail, see Troubleshooting (§8).

---

## 7. Day-to-day usage

The basic shape:

```
"Brainstorm + ship issue #N — use the agent team to land it"
```

What happens:
1. **Brainstorm.** Claude asks a few sharp design questions (one at a time), proposes 2-3 approaches, recommends one. You agree or redirect.
2. **Spec.** Writes `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`, commits it on a new feature branch.
3. **Plan.** Writes `docs/superpowers/plans/YYYY-MM-DD-<topic>.md` with bite-sized TDD tasks (tests, commands, exact code).
4. **Dispatch.** For each plan task, spawns a fresh `niko-developer` (or `niko-tester`) subagent with the full task text + context. Subagent implements, runs tests, commits.
5. **Review.** After each task or at the end, dispatches `niko-reviewer` for spec compliance + code quality.
6. **Push + PR.** Pushes the branch, opens a PR via `gh`, returns the URL.

You stay in the loop on:
- Design decisions during brainstorm
- Spec approval
- Anything the implementer surfaces as `DONE_WITH_CONCERNS` or `BLOCKED`
- Final merge (admin-merge with `--squash --admin --delete-branch` matches the `master` linear-history rule)

You're NOT in the loop on:
- Per-task code review (the agent loop handles that)
- Test-running noise

**Tips that landed well in practice:**
- "Use frontend-design plugin" if it's a UI-heavy feature.
- Decompose big features into sub-projects in brainstorm; ship each as its own PR. (Sprint 2.2's feature B was decomposed into B1+B2+B3 — three smaller, reviewable PRs instead of one massive one.)
- If you're confident in the design, say "use my recommendation" — Claude will skip per-section approval and present a complete spec.
- "drive autonomously" tells Claude to skip per-PR approval gates and run brainstorm → ship → merge → next sub-project end-to-end. Use sparingly, but works well for clear plans.

---

## 8. Troubleshooting

**`/mcp` says Discord is disconnected.** Try `/mcp` again to reconnect. If that fails, restart Claude Code entirely (`/exit` and re-launch). If still failing, the bot token may have been rotated — re-fetch from `#shared-creds`.

**Subagent says `ANTHROPIC_API_KEY not set`.** Subagent shells inherit env from your `.env` file via `pydantic-settings`. Verify with `python -c "from app.config import settings; print(bool(settings.anthropic_api_key))"`. If False, your `.env` is missing the key or has it under the wrong name.

**Subagent reports `BLOCKED` on something.** Read the report — it's specific. Usually means the task description was missing context. Provide the missing piece and re-dispatch.

**Pre-existing `firebase_admin` import errors when running `pytest tests/`.** Known dev-env gap: `firebase_admin` isn't installed in the local venv. Affects `test_auth_dependency`, `test_orders_route`, `test_telephony`, `test_voice` collection. CI runs these fine. Fix locally with `pip install firebase-admin` if you need to run them.

**Browser refuses dashboard audio (B2 alert cue).** Browsers block audio without a user gesture. Click anywhere on the dashboard once after page load — the audio "primer" then unlocks the AudioContext for the session.

**You committed to `master` by accident.** The `pr-driven-dev` skill has a rescue flow:
```bash
git stash
git checkout -b <branch-name>
git stash pop
```
Then push the branch normally and open a PR.

---

## 9. Where to get help

- **Workflow questions**: post in `#infra` Discord channel.
- **Project status / sprint**: `/current-sprint` skill, or check the `tsuki-works/niko` GitHub Project board.
- **Codebase conventions**: `CLAUDE.md` (root) + `dashboard/CLAUDE.md` (dashboard-specific).
- **Agent team docs**: https://code.claude.com/docs/en/agent-teams
- **Superpowers plugin**: skill content lives at `~/.claude/plugins/cache/claude-plugins-official/superpowers/` once installed; each skill has its own `SKILL.md`.

If you want a live walkthrough of your first agent dispatch, ping in `#infra` — happy to pair on it.
