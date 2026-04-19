# Team Roles & Responsibilities
## AI Voice Agent for Restaurants

**Version:** 1.0
**Date:** April 18, 2026
**Status:** Draft — Needs Team Discussion

---

## 1. Team Overview

We are a 4-person founding team: **three backend engineers** (Meet, Sandeep, Kailash) and **one frontend engineer** (Daniel). Each member has a primary ownership area but will wear multiple hats given the team's size.

The backend weight reflects where the product's difficulty lives: real-time voice pipeline, LLM orchestration, POS integrations, and infrastructure. Daniel owns the full dashboard + marketing surface solo, which keeps the frontend lane well-defined.

Some responsibilities are **shared across the whole team** rather than assigned to one person — see §3. This is deliberate: customer discovery and customer support are learning signals we want every team member exposed to, not cost centers to delegate.

---

## 2. Role Assignments

### Meet — Product, Platform & LLM Lead
**Primary:** Product ownership, core backend, cloud platform + CI/CD, LLM engineering
**Secondary:** Toast POS integration (Phase 3.2), business operations

| Responsibility | Details |
|---------------|---------|
| Product ownership | Maintain PRD, prioritize backlog, define requirements |
| Core backend | FastAPI app structure, data models (Firestore schemas), business logic |
| Cloud infrastructure | GCP project, Cloud Run, Firestore, Artifact Registry, Workload Identity Federation |
| CI/CD | GitHub Actions → Cloud Run auto-deploy from `master`, secrets via Secret Manager |
| LLM engineering | Claude Haiku 4.5 prompt engineering, menu context injection, conversation flows, structured output |
| Analytics data pipeline | Order / call aggregation, metric computation for the dashboard |
| POS — Toast | Toast API integration (Phase 3.2) |
| Sprint planning | Facilitate planning sessions, maintain GitHub Project #2 |
| Business ops | Legal (deferred to Phase 3/4), finance, company formation |

> **Load note:** Meet's lane is deliberately the heaviest — it sits at the product/tech decision intersection during Phases 0–2. Phase 0 infra + CI/CD is front-loaded work that lightens by Phase 2, freeing capacity for the Toast integration in Phase 3.

### Sandeep — Voice Output & Audio Backend Lead
**Primary:** TTS pipeline, audio engineering, performance
**Secondary:** Clover POS integration (Phase 3.2)

| Responsibility | Details |
|---------------|---------|
| TTS pipeline | ElevenLabs streaming back to Twilio |
| Audio engineering | Barge-in detection, audio quality, interruption handling |
| Performance | Ensure < 1 second end-to-end voice response latency |
| Call state management | Session state, timeout/silence detection |
| POS — Clover | Clover API integration (Phase 3.2) |

### Kailash — Telephony, STT & Security Backend Lead
**Primary:** Telephony, STT pipeline, security, monitoring, Square POS integration
**Secondary:** Cross-cutting backend support

| Responsibility | Details |
|---------------|---------|
| Telephony | Twilio setup, phone numbers, webhooks, Media Streams WebSocket plumbing |
| STT pipeline | Deepgram Nova-2 streaming from Twilio Media Streams WebSocket (inbound audio — pairs naturally with telephony ingress) |
| POS — Square | Square API integration (Phase 2.3, MVP) — sets the pattern reused by Toast/Clover |
| Security | Auth, data encryption, PCI scope minimization via tokenization |
| Monitoring | Cloud Logging + Trace, Sentry, alerting, error tracking |

> **Voice I/O split rationale:** Kailash owns inbound audio (Twilio ingress → STT) alongside the telephony lane — both are ingest-side concerns. Sandeep owns outbound audio (LLM response → TTS → Twilio) alongside audio engineering and the overall latency contract, since perceived responsiveness lives in the output path. Meet (LLM) sits between them; all three pair frequently on the < 1s end-to-end budget.

### Daniel — Frontend & Growth Lead
**Primary:** Dashboard (Next.js), marketing site, UX/UI
**Secondary:** Branding, documentation

| Responsibility | Details |
|---------------|---------|
| Dashboard | Next.js 15 (static export), served by FastAPI monolith; menu editor, call/order history, analytics UI |
| UX/UI design | Wireframes, user flows, design system, component library |
| Branding | Logos, visual identity (already shipped Tsuki Works brand to `assets/`) |
| Landing / marketing site | Public marketing pages, SEO |
| SMS/notifications UX | Copy + flows for Twilio SMS order confirmations |
| Documentation | User-facing help content, onboarding materials |

---

## 3. Shared Responsibilities

Responsibilities every team member participates in — not owned by a single person.

### Customer discovery (Phases 0–2 especially)
**Participants:** All 4
**Coordinator:** Meet (logistics — scheduling, discovery journal, synthesizing findings)

Each team member is expected to talk to at least 1–2 restaurant owners per sprint during Phases 0–2. The goal isn't to offload discovery onto product — it's to build shared product intuition across the team so engineering decisions stay grounded in real customer constraints.

### Customer support (from first pilot onwards)
**Participants:** All 4, on a weekly rotation
**Coordinator:** Daniel (support process, templates, escalation paths)

Early customer support is a learning signal, not a cost center. Everyone rotates so the whole team hears real friction firsthand. Daniel owns the support *system* (templates, escalation docs, response SLAs) but isn't the sole responder. Rotation schedule gets set once the first pilot restaurant is onboarded.

### On-call incident response
See §7 — separate from routine customer support. Handles production alerts and outages, not general inquiries.

### Documentation (engineering-side)
**Participants:** Whoever ships the feature documents it.

Daniel owns user-facing help content; engineering docs (API references, runbooks, architecture notes) are authored by whoever built the thing being documented.

---

## 4. Decision-Making Framework

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

## 5. Communication Cadence

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

## 6. Code Review Policy

- Every PR requires **at least 1 approval** before merge (enforced by `master` branch ruleset)
- Reviewer should be someone from a **different domain** when possible (cross-pollination)
- Review within **24 hours** of PR creation
- Author is responsible for merging after approval

### Review Rotation
| PR Domain | Primary Reviewer | Secondary |
|-----------|-----------------|-----------|
| Frontend (dashboard, marketing site) | Daniel | Meet |
| Core backend / API | Meet | Sandeep |
| Voice — STT | Kailash | Sandeep |
| Voice — LLM / prompts | Meet | Sandeep |
| Voice — TTS / audio / performance | Sandeep | Meet |
| Infrastructure (Cloud Run, CI/CD, GCP) | Meet | Kailash |
| Telephony / Security / Monitoring | Kailash | Sandeep |
| POS — Square | Kailash | Meet |
| POS — Toast | Meet | Kailash |
| POS — Clover | Sandeep | Kailash |

**Note on cross-pollination:** With 3 backend engineers and 1 frontend engineer, frontend PRs won't always get a cross-domain reviewer. Meet is the natural cross-domain backup for Daniel's frontend PRs (product context); where that's unavailable, Daniel self-merges after addressing automated checks.

**Note on voice-pipeline coupling:** STT (Kailash), LLM (Meet), and TTS (Sandeep) are split across three owners but tightly coupled — conversation quality and the < 1s latency budget depend on all three. Expect frequent pairing and mutual review across these three lanes; Sandeep is the secondary reviewer for STT and LLM since he owns the end-to-end performance contract.

---

## 7. On-Call (Post-MVP)

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

## 8. Availability & Commitments

> **Fill this out as a team — be honest about availability so sprints can be planned realistically.**

| Team Member | Weekly Hours Available | Full-time / Part-time | Other Commitments |
|-------------|----------------------|----------------------|-------------------|
| Meet | TBD | TBD | TBD |
| Sandeep | TBD | TBD | TBD |
| Kailash | TBD | TBD | TBD |
| Daniel | TBD | TBD | TBD |

---

## 9. Equity & Compensation

> **This section intentionally left blank.** Equity splits and compensation should be discussed separately with legal counsel. Document the agreement formally in an operating agreement or founders' agreement.

Key items to decide:
- Equity split between 4 founders
- Vesting schedule (standard: 4-year vest, 1-year cliff)
- IP assignment agreement
- Decision on salaries vs. no salary during early stage
