# Shared Third-Party Accounts

Phase 0 exit requires shared accounts for every service in the niko stack. Each service has a designated **owner** — the teammate who creates the account, administers it, and posts credentials to `#shared-creds`.

**Assignment principle:** the service-account owner matches the domain owner per `05-team-roles-and-responsibilities.md`. Whoever administers the service in production creates the account.

## Status

| Service | Purpose | Owner | Status | Notes |
|---|---|---|---|---|
| GCP | Cloud Run hosting + Firestore | Meet | ✅ Done | Live; Cloud Run auto-deploys from `master` via `.github/workflows/deploy.yml` |
| Twilio | Voice telephony | Meet | ✅ Done | Trial account, $15 credit. Toronto (647) number — swap to US before pilot. Upgrade to paid before Phase 1 demo day to drop trial watermark. Creds in `#shared-creds` |
| Deepgram | STT (Nova-2 streaming) | Meet | ⬜ Todo | $200 free credit on signup |
| Anthropic | Claude Haiku 4.5 LLM | Meet | ✅ Done | Pay-as-you-go on Console; Claude for Startups is VC-gated (revisit post-raise). Key posted to `#shared-creds` |
| ElevenLabs | TTS streaming | Meet | ⬜ Todo | Free tier: 10k chars/month |
| Square Developer | POS sandbox + production API | Meet | ⬜ Todo | Sandbox access is free |

> **Owner note:** Meet is doing all Phase 0 signups in one pass to avoid parallel-coordination overhead. Domain owners (per `05-team-roles`) take over admin once the account is live and the service is used in code — e.g., Kailash inherits Twilio/Deepgram/Square admin when the telephony + STT + POS work lands; Sandeep inherits ElevenLabs admin with the TTS pipeline.

## How to complete a signup

1. **Use the shared Gmail** (`tsukiworksca@gmail.com`) as the account email when the service allows it. If the service requires a personal email, use your own and note it in the table.
   - Shared Gmail creds are in `#shared-creds` — fetch via the `/shared-creds` skill.
2. **Credit card:** leave blank for free-tier / trial signups. For services that require one up front, pause and discuss — per `05-team-roles §4 Business Decisions`, any monthly spend > $100 requires unanimous agreement.
3. **Post credentials** to `#shared-creds` in the template format:

    ```
    **<Service Name>** — <account email or username>
    KEY_NAME=<value>
    SECONDARY_KEY=<value>
    notes: <trial expiry, free-tier limits, anything non-obvious>
    ```

4. **Flip your row** in the table above to ✅ Done and open a PR.
5. **Never commit the credential value** — `.claude/skills/shared-creds/SKILL.md` has the canonical rules (no git, no `MEMORY.md`, no PR descriptions, no CI logs).

## Re-assignment

If the designated owner is blocked (waitlist, KYC friction, personal-email requirement, etc.), reassign in the table via PR — don't silently hand off. The signup owner is also the account admin going forward, so the hand-off must be explicit.

## When this is done

Phase 0 exit criterion *"Create shared accounts for all third-party services"* (issue #2) closes when all five remaining rows are ✅ Done and credentials are posted to `#shared-creds`.
