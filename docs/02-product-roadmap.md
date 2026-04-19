# Product Roadmap
## AI Voice Agent for Restaurants

**Version:** 1.0
**Date:** April 18, 2026
**Status:** Draft

---

## Roadmap Overview

```
Phase 0: Foundation     [Weeks 1-2]     ░░░░░░
Phase 1: POC            [Weeks 3-6]     ░░░░░░░░░░░░
Phase 2: MVP            [Weeks 7-14]    ░░░░░░░░░░░░░░░░░░░░░░░░
Phase 3: Beta           [Weeks 15-20]   ░░░░░░░░░░░░░░░░░░
Phase 4: Production     [Weeks 21-26]   ░░░░░░░░░░░░░░░░░░
Phase 5: Growth         [Week 27+]      ░░░░░░░░░░░░░░░░░░░░░░→
```

**Total time to production launch: ~6 months**

---

## Phase 0: Foundation & Setup (Weeks 1-2)
*Goal: Team alignment, tooling, and infrastructure bootstrapping*

### Deliverables
- [ ] Finalize company name and branding direction
- [ ] Set up development environment and tooling
  - Git repository (GitHub/GitLab)
  - CI/CD pipeline
  - Project management board (see Sprint Tracking doc)
  - Communication channels (Slack/Discord)
- [ ] Finalize tech stack decisions (see Architecture doc)
- [ ] Set up cloud infrastructure (dev environment)
- [ ] Create shared accounts for all third-party services
- [ ] Legal: Basic LLC formation, operating agreement between founders

### Exit Criteria
- All 4 team members can clone repo, run dev environment locally
- Project board is set up with Phase 1 backlog populated
- Tech stack decisions documented and agreed upon

---

## Phase 1: Proof of Concept (Weeks 3-6)
*Goal: Demonstrate that the core AI voice → order pipeline works end-to-end*

### Scope
Build a **single, hardcoded restaurant** demo that can:
1. Receive an inbound phone call via Twilio (or equivalent)
2. Greet the caller with a natural AI voice
3. Understand the caller's intent (order, question, reservation)
4. Walk through a hardcoded menu and take a simple order
5. Confirm the order back to the caller
6. Log the order to a simple database (no POS integration yet)
7. Display the order on a basic web dashboard

### Key Technical Milestones
| # | Milestone | Owner | Target |
|---|-----------|-------|--------|
| 1 | Telephony setup — receive inbound call, play audio | TBD | Week 3 |
| 2 | STT pipeline — real-time speech-to-text from caller | TBD | Week 3 |
| 3 | LLM conversation engine — intent detection + menu navigation | TBD | Week 4 |
| 4 | TTS pipeline — natural voice responses to caller | TBD | Week 4 |
| 5 | End-to-end call flow — full order conversation | TBD | Week 5 |
| 6 | Basic dashboard — view call logs and orders | TBD | Week 5-6 |
| 7 | POC demo day — live demo to team | All | Week 6 |

### What Success Looks Like
- A real phone call where the AI takes a pizza order naturally
- < 1 second response latency in conversation
- Order appears on a dashboard after the call
- Team is confident the approach is viable

### What We're NOT Building Yet
- POS integration
- Payment processing
- Multi-restaurant support
- Production-grade infrastructure
- Polished UI

---

## Phase 2: Minimum Viable Product (Weeks 7-14)
*Goal: A product that a real restaurant could use for basic call handling*

### Sprint 2.1 — Core Platform (Weeks 7-8)
- [ ] Multi-tenant architecture — support multiple restaurants
- [ ] Restaurant onboarding flow — signup, configure, go live
- [ ] Dynamic menu management — restaurants can add/edit their menu
- [ ] Business info configuration — hours, address, policies
- [ ] Agent personality/greeting customization

### Sprint 2.2 — Order Taking Excellence (Weeks 9-10)
- [ ] Full menu navigation with categories and modifiers
- [ ] Item customizations and special requests
- [ ] Order confirmation and read-back
- [ ] Pickup vs. delivery flow (collect address for delivery)
- [ ] Order queueing and notification to restaurant
- [ ] Basic error recovery (misheard items, corrections)

### Sprint 2.3 — First POS Integration (Weeks 11-12)
- [ ] Square POS integration (recommended first integration)
  - Menu sync (import menu from Square)
  - Order push (send confirmed orders to Square)
  - Item availability sync
- [ ] Webhook system for real-time order status
- [ ] Integration testing with real Square sandbox

### Sprint 2.4 — Dashboard & Polish (Weeks 13-14)
- [ ] Restaurant dashboard
  - Call history with transcripts
  - Order history and status
  - Menu editor (CRUD)
  - Business hours and info editor
  - Basic analytics (calls/day, orders/day, revenue)
- [ ] Call transfer to live staff (when AI can't handle)
- [ ] Voicemail with transcription
- [ ] Outbound SMS for order confirmations
- [ ] Landing page / marketing site

### MVP Exit Criteria
- 3-5 real restaurants onboarded and using the system
- Orders flowing from phone → AI → Square POS reliably
- Restaurant owners can self-manage their menu and settings
- < 5% call failure rate
- Core team confident in product-market fit signal

---

## Phase 3: Beta Launch (Weeks 15-20)
*Goal: Validate with paying customers, harden reliability, add key features*

### Sprint 3.1 — Payments & Reservations (Weeks 15-16)
- [ ] Secure payment capture over phone (PCI-compliant via Stripe/Square)
- [ ] Basic reservation booking
- [ ] Customer caller ID recognition (repeat callers)

### Sprint 3.2 — Additional POS Integrations (Weeks 17-18)
- [ ] Toast POS integration
- [ ] Clover POS integration
- [ ] Generic webhook integration (for unsupported POS systems)

### Sprint 3.3 — Intelligence & Reliability (Weeks 19-20)
- [ ] Upsell engine — suggest add-ons based on order
- [ ] Multi-language support (English + Spanish)
- [ ] Advanced analytics dashboard
  - Revenue attribution
  - Peak time analysis
  - Call outcome breakdown
  - Conversion funnel
- [ ] Error monitoring, alerting, and on-call rotation
- [ ] Load testing — verify 50+ concurrent calls per restaurant
- [ ] Security audit and penetration testing

### Beta Exit Criteria
- 20-50 paying restaurant customers
- Monthly recurring revenue (MRR) tracking active
- < 2% call failure rate
- Customer NPS > 30
- Payment processing live and PCI-compliant
- At least 2 POS integrations production-ready

---

## Phase 4: Production Launch (Weeks 21-26)
*Goal: Public launch, scale infrastructure, formalize operations*

### Sprint 4.1 — Scale & Harden (Weeks 21-22)
- [ ] Auto-scaling infrastructure for call volume spikes
- [ ] Database optimization and caching layer
- [ ] CDN and edge deployment for low-latency voice
- [ ] Disaster recovery and backup procedures
- [ ] SOC 2 Type II compliance preparation

### Sprint 4.2 — Self-Serve & Growth (Weeks 23-24)
- [ ] Self-serve signup and onboarding (no manual setup needed)
- [ ] Billing system (Stripe subscriptions — Starter/Pro/Enterprise)
- [ ] In-app help center and documentation
- [ ] Automated menu import from POS
- [ ] Onboarding wizard with guided setup

### Sprint 4.3 — Launch (Weeks 25-26)
- [ ] Public launch marketing campaign
- [ ] Content marketing (blog, case studies, ROI calculator)
- [ ] SEO-optimized landing pages for each POS integration
- [ ] Customer support system (Intercom or equivalent)
- [ ] Sales playbook and demo environment

### Production Launch Criteria
- 100+ restaurant accounts
- Self-serve signup operational
- 99.9% uptime over trailing 30 days
- Support team and processes in place

---

## Phase 5: Growth & Expansion (Week 27+)
*Goal: Scale customer base, add advanced features, expand market*

### Planned Features (Prioritize Based on Customer Feedback)
- [ ] SpotOn, Aloha (NCR), Olo integrations
- [ ] OpenTable reservation sync
- [ ] Multi-location management (shared menus, per-store config)
- [ ] Advanced upsell with ML-based recommendations
- [ ] Outbound calling (order ready notifications)
- [ ] Kitchen Display System (KDS) integration
- [ ] White-label / reseller program
- [ ] API for third-party developers
- [ ] Catering-specific workflows
- [ ] Loyalty program integration

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Voice latency too high for natural conversation | High | Medium | Evaluate multiple STT/TTS providers early in POC; consider streaming |
| POS integration complexity underestimated | High | High | Start with Square (best API docs); budget extra time |
| LLM hallucinations in order taking | High | Medium | Constrained prompts, menu validation layer, order confirmation step |
| PCI compliance for payments is complex | Medium | High | Use Stripe/Square tokenization to minimize PCI scope |
| Difficulty acquiring first 10 restaurants | High | Medium | Personal network, local restaurants, offer free pilot |
| Competitors (Loman.ai) have head start | Medium | High | Focus on underserved segments, better pricing, superior UX |
| Team bandwidth (4 people, potentially part-time) | High | High | Ruthless scope management, extend timelines if needed |

---

## Key Decisions (Resolved — Phase 0)

Guiding principle: **free-tier-first**. We have no outside funding, so every pick minimizes fixed cost for POC/MVP and documents the paid successor we'd move to once revenue or credits justify the swap. Telephony is the only category with no real free tier — it's metered from day one.

| Decision | Pick | Free tier / cost at POC | Successor (post-funding) |
|----------|------|------------------------|--------------------------|
| Company name | **Tsuki Works** | — | — |
| Telephony | **Twilio Voice** | $15 trial credit; ~$0.0085/min inbound US after | Telnyx (~40% cheaper/min at scale) |
| STT | **Deepgram (Nova-2 streaming)** | $200 free credit — weeks of POC testing | Stay on Deepgram |
| TTS | **ElevenLabs** | 10k chars/mo free tier | ElevenLabs Pro ($22/mo) or Cartesia for lower latency |
| LLM | **Anthropic Claude Haiku 4.5** | Apply to Claude for Startups for credits; cheap + fast, strong instruction-following for constrained menu flows | Claude Sonnet for harder conversations |
| Primary POS (MVP) | **Square** | Developer sandbox + API free | — (Toast/Clover added Phase 3) |
| Hosting | **GCP — Cloud Run + Firestore** | $300 credit (90d) + always-free Cloud Run (2M req/mo) + Firestore free tier. Scales to zero = $0 when idle. | Stay on GCP; raise tier + min-instances when funded |
| Frontend framework | **Next.js 15 (static export)** | Built inside monolith — no separate Vercel account needed | Split to Vercel Pro if dashboard grows beyond static export |
| Backend language | **Python 3.12 + FastAPI** | — | — |
| Deployment model | **Single Docker image → Cloud Run, auto-deploy from `master`** | GitHub Actions: unlimited free minutes on public repos | — |
| CI/CD | **GitHub Actions** | Free forever (public repo) | — |

### Deployment shape (monolith)

```
niko/
├── app/                    # FastAPI: voice, dashboard API, static serving
│   ├── voice/             # Twilio webhooks, STT/LLM/TTS orchestration
│   ├── dashboard/         # Dashboard REST API
│   └── main.py            # FastAPI app + static mount
├── web/                   # Next.js (static export, built in Docker)
├── Dockerfile             # Multi-stage: node builds web/, python serves
└── .github/workflows/
    └── deploy.yml         # push master → build → Artifact Registry → Cloud Run
```

One service, one URL, one observability surface. Cloud Run's scale-to-zero covers the idle cost. Split into separate services only when Phase 3+ scaling demands it.

### Known quirks to watch

- **Cloud Run WebSocket** — 60min request timeout (fine for phone calls); long-lived connections count against concurrency. Fly.io is the escape hatch if audio streaming strains Cloud Run.
- **Cloud Run cold starts** (~1–2s) when scaled to zero — unnoticeable for dashboard, potentially felt on first call of the day. Min-instances=1 costs ~$5/mo when we want to eliminate it.
- **Telephony cost** — not free; budget ~$20–50 for POC testing.
- **Vercel free tier** is not used — Next.js is built inside the Docker image and served by FastAPI, which keeps the monolith model clean and sidesteps Vercel's commercial-use restriction on Hobby.
