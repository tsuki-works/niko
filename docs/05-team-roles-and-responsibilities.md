# Team Roles & Responsibilities
## AI Voice Agent for Restaurants

**Version:** 1.0
**Date:** April 18, 2026
**Status:** Draft — Needs Team Discussion

---

## 1. Team Overview

We are a 4-person founding team. Each member will wear multiple hats, but having primary ownership areas ensures accountability and reduces coordination overhead.

> **Important:** The role assignments below are a starting proposal. Discuss and adjust based on each person's actual skills, interests, and availability during the Week 1 kickoff.

---

## 2. Proposed Role Assignments

### Meet — Product & Frontend Lead
**Primary:** Product management, frontend development, UX
**Secondary:** Business operations, customer research

| Responsibility | Details |
|---------------|---------|
| Product ownership | Maintain PRD, prioritize backlog, define requirements |
| Frontend development | Restaurant dashboard (Next.js), landing page |
| UX/UI design | Wireframes, user flows, design system |
| Customer discovery | Talk to restaurant owners, gather feedback |
| Sprint planning | Facilitate planning sessions, maintain board |
| Business ops | Legal, finance, company formation |

### Sandeep — Backend & Voice Pipeline Lead
**Primary:** Voice orchestrator, AI/LLM pipeline, core backend
**Secondary:** Infrastructure, performance optimization

| Responsibility | Details |
|---------------|---------|
| Voice pipeline | STT → LLM → TTS real-time streaming architecture |
| LLM engineering | Prompt engineering, conversation flows, context management |
| Core backend API | FastAPI services, data models, business logic |
| Audio engineering | Latency optimization, barge-in detection, audio quality |
| Performance | Ensure < 1 second voice response latency |

### Kailash — Infrastructure & Integrations Lead
**Primary:** DevOps, cloud infrastructure, POS integrations
**Secondary:** Backend development, security

| Responsibility | Details |
|---------------|---------|
| Cloud infrastructure | AWS setup, ECS, RDS, ElastiCache, S3 |
| CI/CD | GitHub Actions pipelines, automated testing, deploys |
| POS integrations | Square, Toast, Clover API integrations |
| Telephony | Twilio setup, phone number management, webhooks |
| Monitoring | Logging, alerting, error tracking (Sentry/Datadog) |
| Security | Authentication, data encryption, PCI compliance |

### Daniel — Full-Stack & Growth Lead
**Primary:** Full-stack development, analytics, growth
**Secondary:** Customer support, documentation

| Responsibility | Details |
|---------------|---------|
| Full-stack dev | Support both frontend and backend as needed |
| Analytics | Dashboard analytics, reporting, data pipeline |
| SMS/notifications | Twilio SMS, email notifications, order confirmations |
| Growth | Marketing site, SEO, content, customer acquisition |
| Documentation | API docs, internal guides, onboarding materials |
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

- Every PR requires **at least 1 approval** before merge
- Reviewer should be someone from a **different domain** when possible (cross-pollination)
- Review within **24 hours** of PR creation
- Author is responsible for merging after approval

### Review Rotation
| PR Domain | Primary Reviewer | Secondary |
|-----------|-----------------|-----------|
| Frontend | Daniel | Sandeep |
| Backend / API | Meet | Kailash |
| Voice pipeline | Kailash | Daniel |
| Infrastructure | Sandeep | Meet |
| POS integrations | Daniel | Sandeep |

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
