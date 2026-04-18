# Sprint Tracking & Product Backlog
## AI Voice Agent for Restaurants

**Version:** 1.0
**Date:** April 18, 2026
**Status:** Draft

---

## 1. Sprint Methodology

We will use a **modified Scrum** approach adapted for a small 4-person team.

### Sprint Structure
| Parameter | Value |
|-----------|-------|
| Sprint duration | **2 weeks** |
| Sprint planning | Monday of Sprint Day 1 (30 min) |
| Daily standup | Async in Slack/Discord — post by 10 AM |
| Sprint review/demo | Friday of Sprint Day 10 (30 min) |
| Sprint retrospective | Friday of Sprint Day 10 (15 min, after review) |

### Async Daily Standup Format
Each team member posts daily in the `#standups` channel:

```
**Yesterday:** What I completed
**Today:** What I'm working on
**Blockers:** Anything blocking progress (or "None")
```

### Story Points
We use a simplified point system:

| Points | Effort | Example |
|--------|--------|---------|
| 1 | A few hours | Fix a bug, update config |
| 2 | ~1 day | Add a new API endpoint, UI component |
| 3 | 2-3 days | Integrate a third-party service |
| 5 | ~1 week | Build a full feature (e.g., menu editor) |
| 8 | 1-2 weeks | Major subsystem (e.g., POS integration) |

**Target velocity per sprint (4-person team):** 20-30 points
*Adjust based on whether team members are full-time or part-time*

---

## 2. Recommended Tracking Tool

### Option A: GitHub Projects (Recommended for Starting)
- Free, integrated with code repository
- Kanban board + table views
- Custom fields for priority, story points, sprint assignment
- Automation (auto-move cards when PRs merge)
- **Setup: Create a GitHub Project board with these columns:**

```
📋 Backlog → 🔜 Sprint Ready → 🏗️ In Progress → 👀 In Review → ✅ Done
```

### Option B: Linear (Recommended When Scaling)
- Purpose-built for engineering teams
- Sprints/cycles built in
- Better analytics and velocity tracking
- Free for small teams
- Consider switching when team grows or after MVP

### Option C: Notion (If Team Prefers All-in-One)
- Docs + project tracking in one place
- More flexible but less structured
- Good for early-stage, harder to enforce process

> **Recommendation:** Start with **GitHub Projects** for simplicity and code integration. Migrate to **Linear** after MVP if more structure is needed.

---

## 3. Board Setup (GitHub Projects)

### Custom Fields
| Field | Type | Values |
|-------|------|--------|
| Priority | Single Select | P0-Critical, P1-High, P2-Medium, P3-Low |
| Story Points | Number | 1, 2, 3, 5, 8 |
| Sprint | Iteration | Sprint 1, Sprint 2, etc. |
| Phase | Single Select | Phase 0, Phase 1 (POC), Phase 2 (MVP), Phase 3 (Beta), Phase 4 (Prod) |
| Type | Single Select | Feature, Bug, Chore, Spike, Design |
| Owner | Single Select | Meet, Sandeep, Kailash, Daniel |

### Labels
```
frontend          — Dashboard/UI work
backend           — API/server work
voice-pipeline    — STT/LLM/TTS work
pos-integration   — POS system integrations
infrastructure    — DevOps, CI/CD, cloud
design            — UI/UX design work
documentation     — Docs, specs, guides
```

---

## 4. Product Backlog

### Phase 0: Foundation (Sprint 0)

| ID | Title | Type | Points | Priority | Owner |
|----|-------|------|--------|----------|-------|
| F-001 | Decide on company name | Chore | 1 | P0 | All |
| F-002 | Create GitHub org and repository | Chore | 1 | P0 | TBD |
| F-003 | Set up project board with columns and fields | Chore | 1 | P0 | TBD |
| F-004 | Set up Slack/Discord with channels | Chore | 1 | P0 | TBD |
| F-005 | Finalize tech stack decisions | Spike | 2 | P0 | All |
| F-006 | Set up dev environment (Docker Compose, env vars) | Chore | 3 | P0 | TBD |
| F-007 | Create monorepo structure (backend + frontend) | Chore | 2 | P0 | TBD |
| F-008 | Set up CI/CD pipeline (lint, test, build) | Chore | 3 | P1 | TBD |
| F-009 | Create shared API key accounts (Twilio, Deepgram, etc.) | Chore | 1 | P0 | TBD |
| F-010 | LLC formation and operating agreement | Chore | 2 | P1 | TBD |

**Sprint 0 Total: ~17 points**

---

### Phase 1: POC (Sprints 1-2)

| ID | Title | Type | Points | Priority | Owner |
|----|-------|------|--------|----------|-------|
| P-001 | Set up Twilio account and provision phone number | Chore | 1 | P0 | TBD |
| P-002 | Build inbound call handler (Twilio webhook → server) | Feature | 3 | P0 | TBD |
| P-003 | Implement real-time STT with Deepgram streaming | Feature | 5 | P0 | TBD |
| P-004 | Build LLM conversation engine with restaurant context | Feature | 5 | P0 | TBD |
| P-005 | Implement TTS streaming response to caller | Feature | 5 | P0 | TBD |
| P-006 | End-to-end audio pipeline (STT → LLM → TTS in real-time) | Feature | 5 | P0 | TBD |
| P-007 | Create hardcoded demo restaurant menu (JSON/DB) | Chore | 1 | P0 | TBD |
| P-008 | Build order-taking conversation flow | Feature | 5 | P0 | TBD |
| P-009 | Implement order confirmation read-back | Feature | 2 | P0 | TBD |
| P-010 | Store call logs and transcripts to database | Feature | 3 | P1 | TBD |
| P-011 | Build basic dashboard — call log viewer | Feature | 3 | P1 | TBD |
| P-012 | Build basic dashboard — order viewer | Feature | 3 | P1 | TBD |
| P-013 | Implement call transfer (DTMF or voice command) | Feature | 3 | P1 | TBD |
| P-014 | Handle interruptions (barge-in detection) | Feature | 3 | P1 | TBD |
| P-015 | POC demo preparation and testing | Chore | 2 | P0 | All |

**Phase 1 Total: ~49 points (~2 sprints)**

---

### Phase 2: MVP (Sprints 3-6)

| ID | Title | Type | Points | Priority | Owner |
|----|-------|------|--------|----------|-------|
| M-001 | Multi-tenant data model (restaurants, menus, users) | Feature | 5 | P0 | TBD |
| M-002 | Restaurant signup and onboarding API | Feature | 5 | P0 | TBD |
| M-003 | Authentication system (Clerk/Auth0 integration) | Feature | 3 | P0 | TBD |
| M-004 | Menu management CRUD API | Feature | 3 | P0 | TBD |
| M-005 | Menu editor UI (add/edit/delete categories, items, modifiers) | Feature | 5 | P0 | TBD |
| M-006 | Business info management (hours, address, policies) | Feature | 2 | P0 | TBD |
| M-007 | Agent greeting and behavior configuration | Feature | 3 | P0 | TBD |
| M-008 | Dynamic menu context loading for LLM (per restaurant) | Feature | 3 | P0 | TBD |
| M-009 | Full menu navigation conversation flow | Feature | 5 | P0 | TBD |
| M-010 | Item customization and modifier handling | Feature | 5 | P0 | TBD |
| M-011 | Pickup vs. delivery flow (address collection) | Feature | 3 | P0 | TBD |
| M-012 | Order validation (items exist, prices correct) | Feature | 3 | P0 | TBD |
| M-013 | Square POS integration — menu sync | Feature | 8 | P0 | TBD |
| M-014 | Square POS integration — order submission | Feature | 8 | P0 | TBD |
| M-015 | Square POS integration — item availability | Feature | 3 | P1 | TBD |
| M-016 | Dashboard — call history with transcripts | Feature | 3 | P0 | TBD |
| M-017 | Dashboard — order history and status | Feature | 3 | P0 | TBD |
| M-018 | Dashboard — basic analytics (calls/day, revenue) | Feature | 5 | P1 | TBD |
| M-019 | Dashboard — settings page | Feature | 3 | P0 | TBD |
| M-020 | Voicemail with transcription | Feature | 3 | P1 | TBD |
| M-021 | Outbound SMS order confirmations (Twilio) | Feature | 3 | P1 | TBD |
| M-022 | Call transfer to live staff | Feature | 3 | P1 | TBD |
| M-023 | Landing page / marketing site | Feature | 5 | P1 | TBD |
| M-024 | Error handling and graceful degradation | Feature | 3 | P0 | TBD |
| M-025 | Integration and end-to-end testing | Chore | 5 | P0 | TBD |

**Phase 2 Total: ~100 points (~4 sprints)**

---

### Phase 3+ Backlog (Unprioritized — Groom Before Sprint Planning)

| ID | Title | Type | Points | Priority |
|----|-------|------|--------|----------|
| B-001 | Secure phone payment capture (PCI-compliant) | Feature | 8 | P1 |
| B-002 | Reservation booking flow | Feature | 5 | P1 |
| B-003 | Repeat caller recognition (caller ID) | Feature | 3 | P1 |
| B-004 | Toast POS integration | Feature | 8 | P1 |
| B-005 | Clover POS integration | Feature | 8 | P1 |
| B-006 | Upsell engine (suggest add-ons) | Feature | 5 | P1 |
| B-007 | Multi-language support (Spanish) | Feature | 5 | P1 |
| B-008 | Advanced analytics dashboard | Feature | 8 | P1 |
| B-009 | Self-serve signup and billing (Stripe) | Feature | 8 | P0 |
| B-010 | Auto-scaling infrastructure | Chore | 5 | P1 |
| B-011 | Load testing (50+ concurrent calls) | Chore | 3 | P1 |
| B-012 | Security audit | Chore | 5 | P1 |
| B-013 | Multi-location support | Feature | 8 | P2 |
| B-014 | OpenTable reservation sync | Feature | 5 | P2 |
| B-015 | Webhook integration for custom POS | Feature | 5 | P2 |

---

## 5. Sprint Planning Template

Use this template at the start of each sprint:

```markdown
# Sprint [N] — [Start Date] to [End Date]

## Sprint Goal
[One sentence describing what this sprint delivers]

## Committed Items
| ID | Title | Points | Owner | Status |
|----|-------|--------|-------|--------|
|    |       |        |       |        |

## Total Points Committed: [X]

## Notes / Risks
- [Any known risks or dependencies]

## Sprint Review Notes (fill at end)
- **Completed:** [X] / [Y] points
- **Carried Over:** [list items]
- **Key Learnings:** [what went well, what didn't]
```

---

## 6. Definition of Done

A backlog item is "Done" when:

- [ ] Code is written and follows project conventions
- [ ] Unit tests pass (if applicable)
- [ ] Code reviewed by at least 1 other team member
- [ ] PR merged to `main` branch
- [ ] Feature works in dev/staging environment
- [ ] Documentation updated (if API changes or new feature)
- [ ] No known critical bugs introduced

---

## 7. Suggested Sprint Schedule (First 6 Sprints)

| Sprint | Dates | Phase | Focus |
|--------|-------|-------|-------|
| Sprint 0 | Week 1-2 | Phase 0 | Foundation, tooling, setup |
| Sprint 1 | Week 3-4 | Phase 1 | Telephony + STT + TTS pipeline |
| Sprint 2 | Week 5-6 | Phase 1 | LLM conversation + POC demo |
| Sprint 3 | Week 7-8 | Phase 2 | Multi-tenant, menu mgmt, onboarding |
| Sprint 4 | Week 9-10 | Phase 2 | Order taking excellence |
| Sprint 5 | Week 11-12 | Phase 2 | Square POS integration |
| Sprint 6 | Week 13-14 | Phase 2 | Dashboard, polish, MVP launch |
