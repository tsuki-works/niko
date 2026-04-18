# Product Proposal: AI Voice Agent for Restaurants
### A 24/7 AI-Powered Phone System That Takes Orders, Books Reservations, and Never Misses a Call

**Prepared by:** Meet
**For:** Meet, Sandeep, Kailash, Daniel — Dev Labs Founding Team
**Date:** April 18, 2026
**Status:** DRAFT — For Team Review & Discussion

---

## Table of Contents

1. [The Opportunity](#1-the-opportunity)
2. [What We're Building](#2-what-were-building)
3. [How It Works](#3-how-it-works)
4. [Feature Breakdown](#4-feature-breakdown)
5. [Competitive Landscape](#5-competitive-landscape)
6. [Our Advantage & Positioning](#6-our-advantage--positioning)
7. [Revenue Model](#7-revenue-model)
8. [Go-To-Market Strategy](#8-go-to-market-strategy)
9. [Technical Approach](#9-technical-approach)
10. [Roadmap & Timeline](#10-roadmap--timeline)
11. [Team & Roles](#11-team--roles)
12. [Budget & Costs](#12-budget--costs)
13. [Risks & Mitigations](#13-risks--mitigations)
14. [Decisions We Need to Make](#14-decisions-we-need-to-make)
15. [Next Steps](#15-next-steps)

---

## 1. The Opportunity

### The Problem: Restaurants Are Bleeding Money From Unanswered Phones

Restaurants depend on phone calls for takeout orders, delivery requests, reservations, and customer inquiries. But during peak hours — exactly when the phone rings most — staff are too busy cooking, serving, and running the floor to pick up.

**The numbers are staggering:**

| Statistic | Source |
|-----------|--------|
| **$20 billion** in annual revenue lost by U.S. restaurants from missed calls | QSR Magazine |
| **43%** of restaurant phone calls go unanswered | Hostie AI Research |
| **$292,000/year** in lost revenue per average restaurant from missed calls | Hostie AI Research |
| **85%** of callers won't try again — they call a competitor instead | Industry data |
| **32%** of calls missed during peak dinner hours (5-8 PM) | Hostie AI Research |
| **47%** of daily phone orders come in during that same peak window | Hostie AI Research |

The takeout and delivery market is massive and growing:
- **$284.7 billion** global food delivery market in 2026, projected to hit $468.5 billion by 2031
- **70%** of U.S. consumers order food delivery or takeout in a typical month
- **67%** of average restaurant revenue comes from orders placed online or by phone

**The core tension:** The highest-volume ordering window is the exact time restaurants are least able to answer the phone. Every missed call is a lost customer — likely permanently.

### The Solution: An AI That Answers Every Call, Perfectly, Every Time

We build an AI voice agent that plugs into a restaurant's existing phone number and handles calls like a trained employee — taking orders, answering questions, booking reservations, and processing payments — 24 hours a day, 7 days a week, with zero hold time and zero missed calls.

### Market Size

| Metric | Value |
|--------|-------|
| Voice AI in restaurants (2026) | $10 billion |
| Projected by 2029 | $49 billion |
| Total voice AI agent market (2024) | $2.4 billion |
| Projected by 2034 | $47.5 billion (34.8% CAGR) |
| Total U.S. restaurants | ~1 million |
| Restaurants with 30+ calls/day (our target) | ~300,000-400,000 |

Even capturing **1%** of the addressable U.S. restaurant market (3,000-4,000 restaurants) at $250/mo average revenue = **$9M-$12M ARR**.

---

## 2. What We're Building

### The One-Liner
> An AI phone agent that answers every restaurant call — takes orders, books reservations, answers questions, and sends orders straight to the kitchen — so restaurants never miss a sale.

### The Experience

**For the customer calling:**
1. They call the restaurant's normal phone number
2. A friendly, natural-sounding AI voice answers instantly — no hold time
3. The AI knows the full menu, hours, specials, and policies
4. It takes their order (with customizations), confirms it back, and processes payment
5. They receive an SMS confirmation
6. The order appears in the restaurant's POS system automatically

**For the restaurant:**
1. They sign up and connect their POS system
2. Their menu, hours, and policies are imported automatically
3. They assign our system to their phone number (or we provide one)
4. Calls start being handled immediately — 24/7
5. They monitor everything via a real-time dashboard: calls, orders, transcripts, revenue
6. Staff can focus on cooking and serving instead of answering phones

### What Makes This a Great Business

- **Recurring SaaS revenue** — monthly subscriptions, predictable
- **Clear ROI for customers** — we capture revenue they're currently losing
- **Low marginal cost per customer** — AI calls cost pennies; restaurants pay dollars
- **Network effects in data** — more calls = better AI = higher accuracy = more customers
- **Sticky product** — once orders flow through our system, switching cost is high
- **Massive market** — 1M+ restaurants in the U.S. alone

---

## 3. How It Works

### Call Flow (Simplified)

```
Customer calls restaurant
        │
        ▼
┌─────────────────────────────┐
│  Telephony Layer (Twilio)   │  Receives call, streams audio
└──────────┬──────────────────┘
           │ real-time audio
           ▼
┌─────────────────────────────┐
│  Speech-to-Text (Deepgram)  │  Converts speech → text in real-time
└──────────┬──────────────────┘
           │ transcribed text
           ▼
┌─────────────────────────────┐
│  AI Brain (LLM — Claude)    │  Understands intent, navigates menu,
│                             │  builds order, handles questions
│  Context: restaurant menu,  │
│  hours, policies, order     │
└──────────┬──────────────────┘
           │ response text
           ▼
┌─────────────────────────────┐
│  Text-to-Speech (ElevenLabs)│  Converts response → natural voice
└──────────┬──────────────────┘
           │ audio
           ▼
Customer hears AI response
(< 1 second total delay)
```

### Behind the Scenes

```
After order confirmed:
        │
        ├──▶ Order validated against menu database
        ├──▶ Payment captured (Stripe tokenization)
        ├──▶ Order pushed to POS system (Square, Toast, etc.)
        ├──▶ SMS confirmation sent to customer
        ├──▶ Call transcript + recording saved
        └──▶ Analytics updated on dashboard
```

**Key technical challenge:** The entire STT → LLM → TTS pipeline must complete in under 1 second for the conversation to feel natural. We achieve this by streaming every stage — the TTS starts speaking before the LLM finishes generating.

---

## 4. Feature Breakdown

### Tier 1 — Core (MVP)

| Feature | Description | Why It Matters |
|---------|-------------|----------------|
| **AI Call Answering** | Natural voice, answers instantly, 24/7 | Zero missed calls, zero hold time |
| **Order Taking** | Full menu navigation, customizations, modifiers | Captures revenue from phone orders |
| **Order Confirmation** | Reads back complete order before submitting | Reduces errors, builds trust |
| **POS Integration** | Orders pushed directly to Square (first) | No manual entry, no errors |
| **Menu Management** | Restaurant updates menu, AI reflects changes instantly | Always accurate, always current |
| **Call Transfer** | Routes complex requests to live staff | Safety net for edge cases |
| **Dashboard** | Call logs, transcripts, orders, basic analytics | Visibility and control for owners |
| **FAQ Handling** | Hours, location, allergens, policies | Handles 30-40% of calls that aren't orders |

### Tier 2 — Growth

| Feature | Description | Why It Matters |
|---------|-------------|----------------|
| **Payment Processing** | Secure card capture over phone (PCI-compliant) | Close the sale on the call |
| **Reservations** | Book tables via phone, sync to systems | Automates host stand work |
| **Upsell Engine** | Suggests add-ons, combos, popular items | Increases average order value |
| **SMS Notifications** | Order confirmations, wait time updates | Professional customer experience |
| **Multi-POS Support** | Toast, Clover, SpotOn, Aloha | Expands addressable market |
| **Advanced Analytics** | Revenue attribution, peak analysis, conversion funnel | Helps restaurants optimize operations |

### Tier 3 — Scale

| Feature | Description | Why It Matters |
|---------|-------------|----------------|
| **Multi-Language** | English, Spanish, French + auto-detection | Serves diverse customer base |
| **Multi-Location** | Shared menus, per-store config, aggregate analytics | Unlocks enterprise segment |
| **Repeat Caller Memory** | Recognizes callers, remembers preferences | Personalized experience, faster orders |
| **Self-Serve Onboarding** | Signup → live in minutes, no manual setup | Scalable customer acquisition |
| **OpenTable Sync** | Reservation integration | Connects to existing reservation systems |

---

## 5. Competitive Landscape

### Market Players

| Company | Price | Strengths | Weaknesses |
|---------|-------|-----------|------------|
| **Loman.ai** | $199-$399/mo + $149 setup + per-minute charges | Market leader, fast setup (24 hrs), strong POS integrations, payment processing | Per-minute charges add up (~$500/mo real cost for busy restaurants), higher effective cost |
| **Slang.ai** | $199-$600/mo (tiered) | Strong OpenTable integration (20x more restaurants than competitors), good for reservations | Redirects to online ordering instead of taking orders on the call, limited order-taking |
| **Certus AI** | Custom pricing | Multi-language (EN/ES/FR), accent-trained (South Asian, East Asian, Caribbean), complaint handling | 5-day setup, opaque pricing, less established |
| **ReachifyAI** | $149-$249/mo | Unlimited minutes (no per-minute charges), simple pricing | Newer entrant, less proven at scale |
| **Hostie AI** | Custom pricing | Strong analytics and research content | Not transparent on pricing or features |
| **Goodcall** | Custom pricing | General-purpose AI answering | Not restaurant-specific, generic |

### Key Observations

1. **Loman.ai is the clear market leader** — but their per-minute charges make real costs higher than advertised
2. **Slang.ai is strong on reservations** but weak on actual order-taking (redirects to online)
3. **No one has nailed transparent, simple pricing** — most have hidden fees or require custom quotes
4. **Setup time varies wildly** — from 24 hours (Loman) to 5 days (Certus)
5. **Multi-language is underserved** — only Certus does it well; huge opportunity in diverse metro areas
6. **All competitors are relatively young** — market is still being defined

---

## 6. Our Advantage & Positioning

### Where We Can Win

We don't need to out-feature Loman.ai on day one. We need to find positioning that resonates with a segment they're underserving.

### Proposed Positioning Options (Team Discussion Needed)

**Option A: "The Honest Pricing" Play**
- Flat monthly fee, no per-minute charges, no hidden costs
- "Know exactly what you'll pay. No surprises."
- Targets restaurants burned by usage-based pricing that balloons during busy months
- *Model: ReachifyAI is already doing this at $149-$249/mo — validates the demand*

**Option B: "The Small Restaurant Champion" Play**
- Purpose-built for independent and small-chain restaurants (not enterprise)
- Lower price point ($99-$199/mo), fastest possible onboarding
- "Built for the restaurants that need it most — not the ones with the biggest budgets"
- *Targets the long tail of 500K+ independent restaurants*

**Option C: "The All-In-One" Play**
- Orders + reservations + payments + analytics in one system (competitors often split these)
- "Everything your phone needs. One plan. One dashboard."
- *Targets restaurants tired of stitching together multiple tools*

> **Recommendation:** Start with **Option A** (transparent pricing) combined with elements of **Option B** (small restaurant focus). This gives us a clear differentiator against Loman.ai's per-minute billing while targeting the massive independent restaurant segment.

### Unfair Advantages We Can Build Over Time

- **Data flywheel** — every call improves our models for menu understanding, accent handling, and order accuracy
- **Restaurant knowledge graph** — structured data on menus, pricing, and operations across thousands of restaurants
- **Integration depth** — deeper POS integrations than "push order" (inventory sync, real-time availability, analytics)

---

## 7. Revenue Model

### Pricing Structure (Proposed)

| Plan | Monthly Price | Target Customer | Includes |
|------|--------------|-----------------|----------|
| **Starter** | **$99/mo** | Low-volume, small restaurants | Call answering, FAQ handling, call transfer, dashboard, basic analytics |
| **Pro** | **$199/mo** | Mid-volume, takeout-heavy restaurants | + Order taking, POS integration, payment processing, SMS confirmations, upsell engine |
| **Business** | **$349/mo** | Multi-location or high-volume | + Reservations, multi-language, advanced analytics, priority support |
| **Enterprise** | **Custom** | 10+ locations, custom needs | + Multi-location management, custom integrations, dedicated account manager |

- **No setup fees** (competitive advantage — Loman charges $149)
- **No per-minute charges** (competitive advantage — Loman and others charge extra)
- **Annual discount:** 20% off (2 months free)
- **Free 14-day trial** on any plan

### Revenue Projections (Conservative)

| Milestone | Restaurants | Avg Revenue/Mo | MRR | ARR |
|-----------|-------------|---------------|-----|-----|
| Month 6 (MVP launch) | 10 | $150 | $1,500 | $18,000 |
| Month 12 | 50 | $180 | $9,000 | $108,000 |
| Month 18 | 200 | $200 | $40,000 | $480,000 |
| Month 24 | 500 | $220 | $110,000 | $1,320,000 |
| Month 36 | 2,000 | $250 | $500,000 | $6,000,000 |

### Unit Economics (Target)

| Metric | Value |
|--------|-------|
| Average revenue per restaurant | $200/mo |
| Estimated cost per restaurant (AI APIs, telephony, infrastructure) | $30-50/mo |
| Gross margin | ~75-85% |
| Customer acquisition cost (CAC) target | < $500 |
| Lifetime value (LTV) at 18-mo avg retention | $3,600 |
| LTV:CAC ratio | > 7:1 |

---

## 8. Go-To-Market Strategy

### Phase 1: Founder-Led Sales (Months 1-6)

**Target: 10-20 restaurants in our local area**

- Personal outreach to restaurants we eat at / know the owners
- Cold walk-ins with a 1-page pitch: "We'll answer your phones for free for 2 weeks"
- Focus on **pizza shops, Indian restaurants, Chinese restaurants, Thai restaurants** — high phone-order volume
- Offer free pilot in exchange for feedback and a testimonial

**Why local first:**
- We can visit in person, watch calls happen, fix issues same-day
- Building relationships = referrals
- Restaurants trust people they've met face-to-face

### Phase 2: Inbound + Referrals (Months 6-12)

- Launch marketing website with ROI calculator
- SEO content: "How much revenue is your restaurant losing from missed calls?"
- Case studies from pilot restaurants (with revenue data)
- Referral program: existing customers get 1 month free per referral
- Partner with POS resellers and restaurant consultants

### Phase 3: Scaled Acquisition (Months 12-24)

- Google Ads targeting restaurant owners searching for phone solutions
- Restaurant industry trade shows and conferences
- Partnerships with POS companies (Square, Toast) for co-marketing
- Outbound sales team (first hire)

---

## 9. Technical Approach

### Architecture Summary

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Telephony** | Twilio Voice | Receive calls, stream audio, manage phone numbers |
| **Speech-to-Text** | Deepgram Nova-3 | Real-time audio → text (streaming, low latency) |
| **AI Brain** | Anthropic Claude / OpenAI GPT-4o | Conversation management, intent detection, order building |
| **Text-to-Speech** | ElevenLabs | Natural voice generation (streaming) |
| **Backend** | Python + FastAPI | API server, business logic, integrations |
| **Frontend** | Next.js + React | Restaurant dashboard |
| **Database** | PostgreSQL | Restaurants, menus, orders, calls |
| **Cache** | Redis | Call session state, real-time data |
| **Cloud** | AWS (ECS Fargate) | Hosting, auto-scaling |
| **Payments** | Stripe | SaaS billing; Square/Stripe tokenization for phone payments |
| **SMS** | Twilio | Order confirmations, notifications |
| **Auth** | Clerk or Auth0 | Restaurant owner login |

### Latency Target

The voice pipeline must feel like a natural conversation:

```
Caller speaks → STT (200-300ms) → LLM (300-500ms) → TTS (200-300ms) → Caller hears response
                                                                        Total: ~700-900ms
```

All three stages stream in parallel to minimize perceived delay.

### Estimated API Costs Per Call

| Service | Cost per 3-min call | Notes |
|---------|-------------------|-------|
| Twilio Voice | ~$0.04 | Inbound minutes |
| Deepgram STT | ~$0.02 | $0.0043/min Nova-3 |
| LLM (Claude Sonnet) | ~$0.03 | ~2K tokens in/out |
| ElevenLabs TTS | ~$0.05 | ~500 characters response |
| **Total per call** | **~$0.14** | |

At 500 calls/month per restaurant: **~$70/mo in API costs** → $200/mo revenue = **65% gross margin**
At scale with volume discounts: costs drop to ~$0.08/call → **80%+ gross margin**

---

## 10. Roadmap & Timeline

### High-Level Timeline

```
NOW ─────────────────────────────────────────────────────────────▶ 6 MONTHS

Week 1-2        Week 3-6          Week 7-14           Week 15-20         Week 21-26
┌──────────┐   ┌──────────────┐   ┌────────────────┐   ┌──────────────┐   ┌──────────────┐
│ PHASE 0  │   │  PHASE 1     │   │   PHASE 2      │   │  PHASE 3     │   │  PHASE 4     │
│ Setup &  │──▶│  POC         │──▶│   MVP          │──▶│  Beta        │──▶│  Production  │
│ Planning │   │  (Prove it   │   │  (Usable       │   │  (Paying     │   │  (Public     │
│          │   │   works)     │   │   product)     │   │   customers) │   │   launch)    │
└──────────┘   └──────────────┘   └────────────────┘   └──────────────┘   └──────────────┘
```

### Phase 0 — Foundation (Weeks 1-2)

| Task | Details |
|------|---------|
| Company & product naming | Brainstorm session, domain availability check |
| Tech stack finalization | Confirm choices from this proposal |
| Development environment | Repo, CI/CD, Docker, dev tooling |
| Third-party accounts | Twilio, Deepgram, ElevenLabs, AWS, Stripe |
| Team roles & availability | Confirm who does what, hours/week commitment |
| Legal basics | LLC formation, operating agreement |

**Exit gate:** All 4 members can run the project locally. Board is populated.

### Phase 1 — Proof of Concept (Weeks 3-6)

**Goal:** Make a real phone call where the AI takes a pizza order end-to-end.

| Milestone | Week |
|-----------|------|
| Receive inbound call via Twilio, play audio back | 3 |
| Real-time speech-to-text from caller | 3 |
| LLM processes speech, generates contextual response | 4 |
| Natural voice response plays back to caller | 4 |
| Full order conversation: greeting → menu → order → confirm | 5 |
| Basic web dashboard: view call log + orders | 5-6 |
| **POC demo day: live call demo to team** | **6** |

**What we're NOT building:** Multi-restaurant support, POS integration, payments, polished UI.

**Exit gate:** We can call the phone number, order a pizza, and see the order on a dashboard. Team is confident the core tech works.

### Phase 2 — MVP (Weeks 7-14)

**Goal:** A product a real restaurant can use for daily call handling.

| Sprint | Focus | Key Deliverables |
|--------|-------|------------------|
| Sprint 3 (Wk 7-8) | Multi-tenant + onboarding | Multiple restaurants, signup flow, menu editor |
| Sprint 4 (Wk 9-10) | Order taking excellence | Full menu navigation, customizations, error recovery |
| Sprint 5 (Wk 11-12) | POS integration | Square integration (menu import + order push) |
| Sprint 6 (Wk 13-14) | Dashboard + polish | Analytics, transcripts, call transfer, SMS, landing page |

**Exit gate:** 3-5 pilot restaurants onboarded and taking real orders through the system.

### Phase 3 — Beta (Weeks 15-20)

**Goal:** Validate with paying customers, add payment processing and more POS systems.

- Secure phone payment capture (PCI-compliant)
- Toast and Clover POS integrations
- Reservation booking
- Upsell engine
- Multi-language (English + Spanish)
- Advanced analytics
- Load testing (50+ concurrent calls)

**Exit gate:** 20-50 paying customers. MRR tracking active.

### Phase 4 — Production Launch (Weeks 21-26)

**Goal:** Public launch with self-serve signup.

- Self-serve onboarding (signup → live without our help)
- Billing system (Stripe subscriptions)
- Auto-scaling infrastructure
- Marketing campaign and content
- Customer support system

**Exit gate:** 100+ restaurants. Product is self-serve. 99.9% uptime.

---

## 11. Team & Roles

### Proposed Assignments

> **These are starting proposals — let's discuss and adjust based on everyone's actual skills, interests, and availability.**

| Member | Primary Role | Key Responsibilities |
|--------|-------------|---------------------|
| **Meet** | Product & Frontend | Product ownership, backlog prioritization, dashboard UI (Next.js), UX design, customer discovery, business ops |
| **Sandeep** | Backend & Voice Pipeline | Voice orchestrator (STT→LLM→TTS), prompt engineering, FastAPI backend, latency optimization |
| **Kailash** | Infrastructure & Integrations | AWS infrastructure, CI/CD, POS integrations (Square/Toast/Clover), Twilio setup, security |
| **Daniel** | Full-Stack & Growth | Full-stack support, analytics dashboard, SMS/notifications, marketing site, documentation, early customer support |

### Working Structure

| Cadence | Format | Duration |
|---------|--------|----------|
| Sprint planning | Video call (biweekly Monday) | 30 min |
| Daily standup | Async in Slack/Discord by 10 AM | — |
| Sprint review + retro | Video call (biweekly Friday) | 30 min |
| Founder check-in | Monthly video call | 30 min |

### Critical Question: Availability

We need honest answers from each person:

| Question | Why It Matters |
|----------|---------------|
| How many hours/week can you commit? | Determines sprint velocity and timeline |
| Are you full-time or part-time on this? | Shapes role expectations |
| Any blackout periods in the next 6 months? | Prevents surprise capacity drops |
| Other commitments (job, school, etc.)? | Realistic planning |

If we're all part-time (10-15 hrs/week each), the timeline extends to ~9-12 months instead of 6. That's fine — but we need to know upfront.

---

## 12. Budget & Costs

### Monthly Operating Costs (Development Phase)

| Item | Monthly Cost | Notes |
|------|-------------|-------|
| Twilio (dev/test) | $20-50 | Phone number + test calls |
| Deepgram | $0 (free tier) → $49 | 45k min free, then pay-as-you-go |
| ElevenLabs | $0 (free tier) → $22 | Free tier for testing, Starter for more |
| LLM API (Claude/OpenAI) | $20-50 | Development and testing |
| AWS (dev environment) | $50-100 | EC2/ECS, RDS, Redis |
| Domain + email | $15-30 | Once we have a name |
| GitHub (Teams) | $0 (free) → $16 | Free for public repos, $4/user for private |
| **Total (dev phase)** | **$100-300/mo** | |

### One-Time Costs

| Item | Cost | Notes |
|------|------|-------|
| LLC formation | $50-500 | Varies by state |
| Domain name | $10-50 | Depends on availability |
| Logo/branding | $0-500 | DIY or freelancer |

### Cost Per Restaurant (Once Live)

| Item | Cost/mo/restaurant | At 100 restaurants |
|------|-------------------|-------------------|
| Twilio (calls + SMS) | $30-50 | $3,000-5,000 |
| Deepgram STT | $10-20 | $1,000-2,000 |
| ElevenLabs TTS | $15-25 | $1,500-2,500 |
| LLM API | $10-20 | $1,000-2,000 |
| Infrastructure share | $5-10 | $500-1,000 |
| **Total per restaurant** | **$70-125** | **$7,000-12,500** |
| **Revenue per restaurant** | **$200 avg** | **$20,000** |
| **Gross margin** | **~50-65%** | **Improves with scale** |

---

## 13. Risks & Mitigations

| # | Risk | Impact | Likelihood | Mitigation |
|---|------|--------|------------|------------|
| 1 | **Voice latency feels unnatural** | High — unusable product | Medium | Stream all stages; evaluate multiple providers in POC; latency budget of 1s |
| 2 | **AI gets orders wrong** | High — lost trust, lost customers | Medium | Mandatory order read-back; menu validation layer; constrained prompts; human escalation path |
| 3 | **POS integration harder than expected** | Medium — delays MVP | High | Start with Square (best API docs); budget 4 weeks; build abstraction layer for future POS |
| 4 | **PCI compliance for payments is complex** | Medium — delays payment feature | High | Use Stripe/Square tokenization to minimize PCI scope; defer payments to Phase 3 |
| 5 | **Can't acquire first 10 restaurants** | High — no product-market fit signal | Medium | Free pilot program; personal network; local walk-ins; pivot positioning if needed |
| 6 | **Loman.ai or competitors have head start** | Medium — harder to win customers | High | Don't compete on features day 1; compete on price, transparency, and underserved segments |
| 7 | **Team bandwidth (4 part-time people)** | High — missed deadlines | High | Ruthless scope prioritization; extend timeline rather than cut quality; honest availability tracking |
| 8 | **API costs higher than projected** | Medium — margin squeeze | Low | Volume discounts; negotiate enterprise rates; evaluate open-source STT/TTS alternatives |
| 9 | **LLM provider changes pricing or ToS** | Medium — cost/capability disruption | Low | Build provider abstraction; avoid vendor lock-in; keep option to switch LLMs |
| 10 | **Legal/IP concerns** | High — existential if not addressed | Low | Original branding (no Loman.ai similarities); own codebase; consult lawyer before launch |

---

## 14. Decisions We Need to Make

These decisions are **blocking or near-blocking** for progress. Let's discuss and resolve in our first team meeting.

### Must Decide Before Starting (Week 1)

| # | Decision | Options | My Recommendation | Notes |
|---|----------|---------|-------------------|-------|
| 1 | **Company name** | Brainstorm together | — | Blocks domain, branding, legal |
| 2 | **Product name** | Same as company or separate | Same name for simplicity | Can rebrand later |
| 3 | **Are we all in?** | Full-time / part-time / advisory | Be honest | Determines timeline and equity |
| 4 | **Equity split** | Equal / weighted / TBD | Discuss with lawyer | Don't skip this conversation |

### Should Decide Before POC (Week 2)

| # | Decision | Options | My Recommendation |
|---|----------|---------|-------------------|
| 5 | **Backend language** | Python / Node.js / Go | Python — best AI ecosystem |
| 6 | **LLM provider** | Claude / GPT-4o / open-source | Claude Sonnet — strong instruction following |
| 7 | **STT provider** | Deepgram / OpenAI Whisper / AssemblyAI | Deepgram — fastest real-time streaming |
| 8 | **TTS provider** | ElevenLabs / PlayHT / OpenAI TTS | ElevenLabs — most natural voices |
| 9 | **Telephony** | Twilio / Telnyx / Vonage | Twilio — most mature, best docs |
| 10 | **Cloud provider** | AWS / GCP / Azure | AWS — broadest services, startup credits |
| 11 | **First POS integration** | Square / Toast / Clover | Square — most accessible API, widely used |

### Can Decide Later

| # | Decision | When |
|---|----------|------|
| 12 | Pricing tiers | Before beta launch |
| 13 | Positioning strategy | Before marketing site |
| 14 | Hiring plan | After product-market fit |
| 15 | Fundraising | After revenue or traction |

---

## 15. Next Steps

### This Week

- [ ] **Everyone:** Read this proposal and the supporting docs
- [ ] **Everyone:** Fill out availability commitment (hours/week, full/part-time)
- [ ] **Schedule:** Team meeting to discuss proposal, make Week 1 decisions
- [ ] **Brainstorm:** Company and product names (come with 3-5 ideas each)

### After Team Meeting

- [ ] Finalize company name and buy domain
- [ ] Set up GitHub org and repository
- [ ] Set up Slack/Discord with team channels
- [ ] Set up project board (GitHub Projects — we can migrate later)
- [ ] Create shared accounts for third-party services
- [ ] Begin Phase 0 sprint

### Supporting Documents (Already Created)

| Document | What's Inside |
|----------|--------------|
| `01-product-requirements-document.md` | Detailed PRD with all features, user stories, non-functional requirements |
| `02-product-roadmap.md` | Full phased roadmap with milestones and exit criteria |
| `03-technical-architecture.md` | System architecture, data model, tech stack deep-dive, security |
| `04-sprint-tracking-and-backlog.md` | Sprint process, board setup guide, 50+ backlog items with story points |
| `05-team-roles-and-responsibilities.md` | Role details, decision framework, code review policy, on-call rotation |

---

*This proposal is a starting point. It's meant to get us aligned and moving — not to be perfect. Let's discuss, poke holes, and make it ours.*

---

**Prepared for Dev Labs (Company Name TBD)**
**April 18, 2026**
