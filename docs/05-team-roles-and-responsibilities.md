# Team Roles & Responsibilities
## AI Voice Agent for Restaurants

**Version:** 1.0
**Date:** April 18, 2026
**Status:** Draft — Needs Team Discussion

---

## 1. Team Overview

We are a 4-person founding team: **three backend engineers** (Meet, Sandeep, Kailash) and **one frontend engineer** (Daniel). Each member has a primary ownership area but will wear multiple hats given the team's size.

The backend weight reflects where the product's difficulty lives: real-time voice pipeline, LLM orchestration, POS integrations, and infrastructure. Daniel owns the full dashboard + marketing surface solo, which keeps the frontend lane well-defined.

---

## 2. Role Assignments

### Meet — Product & Core Backend Lead
**Primary:** Product ownership + core backend API (FastAPI app, data layer, business logic)
**Secondary:** POS integrations support, business operations

| Responsibility | Details |
|---------------|---------|
| Product ownership | Maintain PRD, prioritize backlog, define requirements |
| Core backend | FastAPI app structure, data models (Firestore schemas), business logic |
| Analytics data pipeline | Order / call aggregation, metric computation for the dashboard |
| Customer discovery | Talk to restaurant owners, gather feedback |
| Sprint planning | Facilitate planning sessions, maintain GitHub Project #2 |
| Business ops | Legal (deferred to Phase 3/4), finance, company formation |

### Sandeep — Voice Pipeline Backend Lead
**Primary:** Voice orchestrator, AI/LLM pipeline, real-time audio
**Secondary:** Performance optimization, conversation quality

| Responsibility | Details |
|---------------|---------|
| Voice pipeline | Deepgram STT → Claude Haiku LLM → ElevenLabs TTS streaming |
| LLM engineering | Prompt engineering, menu context injection, conversation flows |
| Audio engineering | Latency optimization, barge-in detection, audio quality |
| Performance | Ensure < 1 second voice response latency |
| Call state management | Session state, interruption handling, timeout/silence detection |

### Kailash — Infrastructure & Integrations Backend Lead
**Primary:** DevOps, GCP infrastructure, POS integrations, telephony
**Secondary:** Security, monitoring

| Responsibility | Details |
|---------------|---------|
| Cloud infrastructure | GCP project, Cloud Run, Firestore, Artifact Registry, Workload Identity Federation |
| CI/CD | GitHub Actions → Cloud Run auto-deploy from `master`, secrets via Secret Manager |
| POS integrations | Square (MVP), then Toast, Clover API integrations |
| Telephony | Twilio setup, phone numbers, webhooks, Media Streams WebSocket |
| Monitoring | Cloud Logging + Trace, Sentry when added |
| Security | Auth, data encryption, PCI scope minimization via tokenization |

### Daniel — Frontend & Growth Lead
**Primary:** Dashboard (Next.js), marketing site, UX/UI
**Secondary:** Customer support, documentation, branding

| Responsibility | Details |
|---------------|---------|
| Dashboard | Next.js 15 (static export), served by FastAPI monolith; menu editor, call/order history, analytics UI |
| UX/UI design | Wireframes, user flows, design system, component library |
| Branding | Logos, visual identity (already shipped Tsuki Works brand to `assets/`) |
| Landing / marketing site | Public marketing pages, SEO |
| SMS/notifications UX | Copy + flows for Twilio SMS order confirmations |
| Documentation | User-facing help content, onboarding materials |
| Customer support | Handle early customer issues, build support processes |

---

## 3. Decision-Making Framework

### Technical Decisions
- **Within your domain** — Make the call, inform the team async
- **Cross-domain** — Discuss in Slack, decide within 24 hours
- **Architecture-level** — Discuss in sprint planning or dedicated sync, all 4 agree

### Product Decisions
- **Feature prioritization** — Meet proposes, team validates in sprint planning
- **Scope changes** — Requires at least 2/4 agreement
- **Pivots / major direction changes** — Unanimous

### Business Decisions
- **Spending > $100/mo** — All 4 agree
- **Legal / contracts** — All 4 agree
- **Partnerships** — All 4 agree

---

## 4. Communication Cadence

| Meeting | Frequency | Duration | Attendees |
|---------|-----------|----------|-----------|
| Sprint Planning | Biweekly (Monday) | 30 min | All |
| Sprint Review + Retro | Biweekly (Friday) | 30 min | All |
| Daily Standup | Daily (async) | — | All |
| Technical Sync | Weekly (as needed) | 15-30 min | Relevant members |
| Founder Check-in | Monthly | 30 min | All |

### Slack/Discord Channels
```
#general          — Team announcements and discussions
#standups         — Async daily standups
#engineering      — Technical discussions, code questions
#product          — Feature discussions, customer feedback
#random           — Non-work, team bonding
#alerts           — Automated alerts (CI/CD, monitoring, errors)
```

---

## 5. Code Review Policy

- Every PR requires **at least 1 approval** before merge (enforced by `master` branch ruleset)
- Reviewer should be someone from a **different domain** when possible (cross-pollination)
- Review within **24 hours** of PR creation
- Author is responsible for merging after approval

### Review Rotation
| PR Domain | Primary Reviewer | Secondary |
|-----------|-----------------|-----------|
| Frontend (dashboard, marketing site) | Daniel | Meet |
| Core backend / API | Meet | Kailash |
| Voice pipeline | Sandeep | Kailash |
| Infrastructure (Cloud Run, CI/CD, GCP) | Kailash | Sandeep |
| POS integrations | Kailash | Meet |

**Note on cross-pollination:** With 3 backend engineers and 1 frontend engineer, frontend PRs won't always get a cross-domain reviewer. Meet (who splits product + backend) is the natural cross-domain backup for Daniel's frontend PRs; where that's unavailable, Daniel self-merges after addressing automated checks.

---

## 6. On-Call (Post-MVP)

Once we have live customers, establish a simple on-call rotation:

| Week | On-Call Primary | Backup |
|------|----------------|--------|
| Week A | Meet | Sandeep |
| Week B | Sandeep | Kailash |
| Week C | Kailash | Daniel |
| Week D | Daniel | Meet |

**On-call responsibilities:**
- Respond to production alerts within 30 minutes
- Triage and fix critical issues or escalate to domain owner
- Document incidents in a post-mortem if downtime > 15 minutes

---

## 7. Availability & Commitments

> **Fill this out as a team — be honest about availability so sprints can be planned realistically.**

| Team Member | Weekly Hours Available | Full-time / Part-time | Other Commitments |
|-------------|----------------------|----------------------|-------------------|
| Meet | TBD | TBD | TBD |
| Sandeep | TBD | TBD | TBD |
| Kailash | TBD | TBD | TBD |
| Daniel | TBD | TBD | TBD |

---

## 8. Equity & Compensation

> **This section intentionally left blank.** Equity splits and compensation should be discussed separately with legal counsel. Document the agreement formally in an operating agreement or founders' agreement.

Key items to decide:
- Equity split between 4 founders
- Vesting schedule (standard: 4-year vest, 1-year cliff)
- IP assignment agreement
- Decision on salaries vs. no salary during early stage
