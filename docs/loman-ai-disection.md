# Loman AI — Complete Technical & Product Dissection

> Prepared for internal reference | Voice AI Restaurant Ordering Platform Analysis

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Product Overview](#2-product-overview)
3. [System Architecture](#3-system-architecture)
4. [User Journey — End to End](#4-user-journey--end-to-end)
5. [Core Technical Stack](#5-core-technical-stack)
6. [POS Integration Layer](#6-pos-integration-layer)
7. [Conversational AI Engine](#7-conversational-ai-engine)
8. [Operator Dashboard](#8-operator-dashboard)
9. [Data & Privacy](#9-data--privacy)
10. [Competitive Landscape](#10-competitive-landscape)
11. [Trust & Adoption Gap](#11-trust--adoption-gap)
12. [Business Model](#12-business-model)
13. [Strengths & Weaknesses](#13-strengths--weaknesses)
14. [Replication Assessment](#14-replication-assessment)

---

## 1. Executive Summary

Loman AI is a **24/7 Voice AI phone answering platform** purpose-built for restaurants. It intercepts inbound phone calls, conducts a full natural-language conversation to take a takeout order or reservation, and fires a clean structured ticket directly into the restaurant's POS system — with no human staff involvement.

The product is **pure SaaS** — no hardware, no field installation. A restaurant forwards their existing phone number to a Twilio-backed number and goes live in under 24 hours.

**Key claimed metrics:**
- 22% revenue increase from recaptured missed calls
- 17% reduction in labor costs
- 88% upsell consistency across all calls
- Handles unlimited simultaneous inbound calls

---

## 2. Product Overview

### What It Does

| Capability | Detail |
|---|---|
| Inbound call answering | 24/7, unlimited concurrent calls |
| Order taking | Full menu, modifiers, substitutions, corrections |
| Payment processing | Credit/debit over phone, syncs to POS |
| Reservation management | Books, modifies, cancels via OpenTable/Resy |
| FAQ handling | Hours, allergens, wait times, directions |
| Upselling | Contextual add-on suggestions on every order |
| Human escalation | Routes edge cases to staff via call transfer |
| Multilingual support | Multiple languages |
| SMS confirmation | Post-order summary to customer |

### What It Does NOT Do

- No physical hardware
- No in-person kiosk ordering
- No drive-thru integration (competitors like ConverseNow own that)
- No web/app ordering channel

### Deployment Model

```
Restaurant forwards existing phone number
              │
              ▼
         Twilio number
              │
              ▼
        Loman AI agent
              │
       ┌──────┴──────┐
       ▼             ▼
  POS ticket    Staff transfer
  (automated)   (if needed)
```

Setup time: **under 24 hours**. White-glove onboarding available.

---

## 3. System Architecture

### High Level

```
Customer (PSTN/Mobile)
         │
         ▼
┌─────────────────┐
│  Telephony Layer │  ← Twilio (inferred)
│  VoIP Gateway    │
└────────┬────────┘
         │ Audio stream (8kHz MULAW)
         ▼
┌─────────────────┐
│  ASR Engine     │  ← Deepgram / Whisper (inferred)
│  Real-time STT  │  ← ~300ms latency
└────────┬────────┘
         │ Transcript (streaming)
         ▼
┌──────────────────────────────┐
│  Conversational AI Engine    │
│  ├── Intent Classifier       │  ← Order / Reserve / FAQ / Escalate
│  ├── Menu RAG Context        │  ← Per-restaurant menu + modifiers
│  ├── Order State Machine     │  ← Accumulates items, corrections
│  └── Upsell Injection        │  ← Contextual add-on suggestions
└────────┬─────────────────────┘
         │ Structured order payload
         ▼
┌─────────────────┐
│  TTS Engine     │  ← ElevenLabs / Deepgram TTS (inferred)
│  Audio Response │  ← Streamed back to caller
└────────┬────────┘
         │
         ▼
┌──────────────────────┐
│  POS Integration     │  ← Toast / Square / Clover / Aloha / Olo
│  Payment Gateway     │  ← Stripe / DTMF card capture
└──────────────────────┘
         │
    ┌────┴────┐
    ▼         ▼
  KDS        Dashboard
(Kitchen)   (Owner)
```

### Latency Budget (End-to-End)

```
Customer speaks
    │  ~300ms  → Deepgram STT
    │  ~400ms  → LLM inference (streaming)
    │  ~200ms  → TTS generation
    │  ~100ms  → Network round trip
    ▼
Customer hears response
Total: ~1,000–1,200ms target
```

Any pipeline above ~1,500ms results in callers assuming the line is dead. This is the primary engineering constraint.

---

## 4. User Journey — End to End

### Step 1 — Customer Dials

Customer dials existing restaurant number. Twilio intercepts before it rings staff. AI answers immediately — no hold, no ring delay.

### Step 2 — Greeting & Intent Detection

```
AI:  "Thanks for calling Mario's Pizza. I can take your
      order, book a table, or answer questions.
      Press 0 anytime to speak with someone. How can I help?"
```

LLM classifies intent:
- **Order** → enter order flow
- **Reservation** → enter booking flow
- **FAQ** → retrieve from knowledge base
- **Press 0 / "speak to someone"** → immediate staff transfer

### Step 3 — Order Taking Loop

```
AI:   "What would you like to order?"
User: "Large pepperoni pizza"
AI:   "Got it. Anything else?"
User: "Caesar salad and a Coke"
AI:   "Large pepperoni, Caesar salad, Coke. Anything else?"
User: "Actually make the Coke a Sprite"
AI:   "Updated. Anything else or are you ready?"
```

Under the hood per utterance:
1. Deepgram transcribes in ~300ms
2. LLM maps speech against menu RAG
3. State machine updates accumulated order
4. Unrecognised items trigger clarification
5. TTS response generated and streamed back

### Step 4 — Order Confirmation Readback

```
AI:  "Let me confirm: Large Pepperoni Pizza $18.99,
      Caesar Salad $9.50, Sprite $3.00.
      Total $31.49. Is that correct?"
```

Corrections loop back into state machine. This step is mandatory — it is the primary accuracy gate.

### Step 5 — Name & Pickup Time

```
AI:  "What name for the order?"
User: "Sandeep"
AI:  "And when are you picking up?"
User: "30 minutes"
AI:  "Perfect. Order for Sandeep, ready in about 30 minutes."
```

### Step 6 — Ticket Fires to POS

```json
{
  "name": "Sandeep",
  "pickup_eta": "30min",
  "channel": "phone",
  "items": [
    { "id": "pizza_lg_pepperoni", "qty": 1, "price": 18.99 },
    { "id": "salad_caesar",       "qty": 1, "price": 9.50  },
    { "id": "drink_sprite",       "qty": 1, "price": 3.00  }
  ],
  "payment": "in_person",
  "total": 31.49
}
```

Ticket appears on KDS identically to a staff-entered order. Zero manual re-entry.

### Step 7 — SMS Confirmation (Optional)

```
"Order confirmed at Mario's Pizza
 Sandeep | Pickup ~7:45 PM
 Large Pepperoni, Caesar Salad, Sprite
 Total due at pickup: $31.49"
```

### Step 8 — Customer Picks Up & Pays

Staff sees named ticket on KDS. Customer pays at counter via existing POS terminal. No new hardware, no new payment workflow.

---

## 5. Core Technical Stack

| Layer | Inferred Technology | Confidence |
|---|---|---|
| Telephony | Twilio | High — industry standard |
| STT | Deepgram Nova-2 | High — best phone-quality ASR |
| LLM | GPT-4 / fine-tuned model | Medium — not disclosed |
| RAG / Menu context | Custom vector store | High — menu must be grounded |
| TTS | ElevenLabs or Deepgram TTS | Medium |
| Payment (phone) | Twilio DTMF + Stripe | High — PCI compliance |
| POS connectors | Per-vendor REST APIs | Confirmed |
| Dashboard | React / Next.js (likely) | Low — not disclosed |
| Infrastructure | AWS / GCP | Unknown |

### Why Deepgram over Whisper for Real-Time

| Criteria | Deepgram Nova-2 | OpenAI Whisper |
|---|---|---|
| Latency | ~300ms streaming | 1–3s batch |
| Phone audio (8kHz) | Native support | Requires resampling |
| Concurrent streams | Managed cloud scale | Self-hosted scaling burden |
| Accuracy (noisy audio) | High | High |
| Cost | Per minute | Per minute (OpenAI API) |

Deepgram wins on latency and native phone-quality audio support.

---

## 6. POS Integration Layer

This is the hardest engineering component and the primary moat.

### Confirmed Integrations

| POS | Type | Market |
|---|---|---|
| Toast | REST API | US restaurant dominant |
| Square | REST API | SMB dominant |
| Clover | REST API | Mid-market |
| Aloha (NCR) | Enterprise API | Large chains |
| Olo | Aggregation API | Multi-location chains |
| SpotOn | REST API | Mid-market |
| OpenTable | Reservations API | Front-of-house |
| Resy | Reservations API | Fine dining |

### Why This Is Hard

Each POS vendor has:
- Different authentication model (OAuth, API key, JWT)
- Different menu schema (item IDs, modifier groups, pricing rules)
- Different ticket/order format
- Different sandbox/certification process
- Different webhook patterns for order confirmation

A single POS integration takes **2–6 weeks** to build and certify correctly. Eight integrations represent 6–12 months of integration engineering alone.

### Ticket Normalisation Pattern

Loman must maintain an internal canonical order schema and map it to each POS format:

```
Loman canonical order
         │
    ┌────┴────┬─────────┬──────────┐
    ▼         ▼         ▼          ▼
 Toast     Square    Clover      Aloha
 format    format    format      format
```

---

## 7. Conversational AI Engine

### Intent Classification

First-pass classification on every utterance:

```
Utterance → Intent classifier
                │
    ┌───────────┼──────────────┐
    ▼           ▼              ▼
 Order       Reserve         FAQ
 flow        flow            lookup
                             │
                             └── Escalate (if unknown)
```

### Order State Machine

The core of the product. Not a simple Q&A loop — a formal state machine:

```
States:
  GREETING
  TAKING_ITEMS
  CLARIFYING_ITEM
  APPLYING_MODIFIER
  CONFIRMING_ORDER
  COLLECTING_NAME
  COLLECTING_PICKUP_TIME
  UPSELLING
  CONFIRMED
  ESCALATED
  FAILED

Transitions driven by:
  - Intent classification output
  - Menu RAG match confidence
  - Silence timeout
  - DTMF input (keypress)
  - Correction detection ("actually", "wait", "change that")
```

### Menu RAG

Each restaurant's menu is ingested as a structured vector store:

- Item names + aliases ("large pie" = "large pizza")
- Modifier groups ("toppings", "size", "crust type")
- Pricing rules
- Availability windows (lunch menu vs dinner menu)
- Allergen tags

LLM queries this context on every order utterance to ground responses against the actual menu rather than hallucinating items.

### Upsell Logic

Injected at the "Anything else?" transition point:

```
Order contains pizza → suggest drinks or dessert
Order contains entree → suggest sides
Order total < $20 → suggest add-on to increase ticket
Time of day = dinner → suggest combo meal
```

Claimed 88% consistency — AI never skips upsell unlike tired human staff.

---

## 8. Operator Dashboard

### Real-Time Features

| Feature | Detail |
|---|---|
| Live call transcript | Utterance-by-utterance, both speakers labeled |
| Active calls monitor | How many lines active right now |
| Order status | Orders fired, pending, completed |
| Revenue tracker | Per-call revenue attribution |

### Post-Call Analytics

| Metric | Purpose |
|---|---|
| Call completion rate | % of calls that result in confirmed order |
| Escalation rate | % handed off to human staff |
| Average order value | Baseline + upsell impact |
| Peak call times | Staffing optimisation |
| Failed intent rate | Where AI is struggling |
| Full call transcripts | Audit trail, dispute resolution |

### Menu Management

- Update menu items, prices, availability in real-time
- Changes propagate to AI context immediately
- No re-training required — RAG updates on save

---

## 9. Data & Privacy

### What Gets Recorded

| Data | Captured | Stored |
|---|---|---|
| Call audio (both parties) | Yes | Temporary |
| Full transcript | Yes | Long-term |
| Order details | Yes | Long-term |
| Caller phone number | Yes (Twilio metadata) | Configurable |
| Payment card data | DTMF only — never in audio | PCI scope minimised |

### Legal Requirements (Canada / Ontario Context)

| Requirement | Mechanism |
|---|---|
| PIPEDA compliance | Caller disclosure message at call start |
| Recording consent | "This call may be recorded for quality purposes" |
| PCI-DSS (if card over phone) | DTMF keypad capture — audio never contains card digits |
| Data retention | Configurable purge window |

### PCI Scope Minimisation

Card numbers are captured via **DTMF** (keypad tones), not spoken aloud. Twilio handles the DTMF capture layer in an isolated PCI-compliant environment. This means the LLM layer never sees or processes card data — a clean architectural boundary.

---

## 10. Competitive Landscape

| Competitor | Focus | Order Taking | Payment | POS Integration | Weakness vs Loman |
|---|---|---|---|---|---|
| **Loman** | Phone orders + reservations | Full | Yes | 6+ POS | No kiosk/drive-thru |
| **Slang.ai** | Reservations + FAQ | No | No | OpenTable / Resy | No order taking at all |
| **ConverseNow** | QSR drive-thru + phone | Full | Yes | Enterprise only | Requires enterprise scale |
| **SoundHound** | Drive-thru (major chains) | Drive-thru only | Via POS | Multi-system | Not accessible to SMB |
| **Hostie** | Calls + texts + email | Reservations only | No | Toast / Square | No full order flow |
| **OrderAI** | Pizza / delivery focused | Full | Yes | Limited | Vertical-specific |

### Market Gap Loman Does Not Cover

- **Drive-thru ordering** — owned by ConverseNow / SoundHound
- **In-restaurant kiosk** — no player dominates
- **Airport / travel F&B** — entirely unaddressed
- **Unified channel** (phone + kiosk + drive-thru) — nobody owns this yet

---

## 11. Trust & Adoption Gap

### The Statement: "Technology exists but owners can't trust it"

**Partially correct.** More precise breakdown:

| Operator Segment | Deployment Reality | Trust Level |
|---|---|---|
| Enterprise QSR (Wendy's, McDonald's) | Deployed at scale, actively iterating | Cautious — McDonald's/IBM pilot was paused |
| Mid-market chains (50–200 locations) | Available, pilots running | Conditional — SLA and accuracy thresholds required |
| Independent / single-location | Available, cheap to deploy | Low — high skepticism, unfamiliarity |
| Airport / hospitality / kiosk | Early deployment only | Very low — liability concerns, regulated environment |

### Root Causes of Trust Deficit

1. **Accent / noise sensitivity** — LLM misheard orders erode confidence fast
2. **Complex modifier handling** — "gluten free bun, no onions, extra sauce" pushes accuracy limits
3. **Single point of failure** — if API goes down during Friday dinner rush, entire phone channel dies
4. **No physical fallback** — unlike a kiosk that can show a touchscreen backup, a dead voice line has no graceful degradation
5. **Marketing stats vs audited performance** — "88% upsell consistency" is unverified externally

---

## 12. Business Model

### Revenue Model (Inferred)

| Model Component | Detail |
|---|---|
| Monthly SaaS fee | Per-location subscription |
| Per-call or per-order fee | Likely tiered on volume |
| Onboarding fee | White-glove setup |
| Enterprise tier | Multi-location, custom SLA |

Pricing not publicly disclosed — demo-gated sales motion indicates mid-market and enterprise focus despite SMB marketing.

### Unit Economics Drivers

- Low COGS once integrated — primarily API costs (Twilio + STT + LLM)
- High gross margin potential at scale
- POS integration cost is one-time per vendor, amortised across all customers on that POS
- Churn risk: restaurants close or switch POS systems

---

## 13. Strengths & Weaknesses

### Strengths

- Clean product scope — phone only, no hardware complexity
- Fast onboarding — under 24 hours is a genuine competitive advantage
- POS integration depth — hardest part done
- Self-improving — call transcripts generate training data automatically
- Scalable unit economics — marginal cost per call is cents

### Weaknesses

- No physical channel — can't expand to kiosk or drive-thru without a hardware partnership
- Phone-only limits TAM — as phone order volumes decline, product relevance narrows
- Single channel dependency — restaurants need more than phone automation
- Trust ceiling — independent operators remain hard to convert without a local sales motion
- No open pricing — creates friction in SMB self-serve adoption

---

## 14. Replication Assessment

### Feasibility for a 4-Developer Team

**Technically feasible.** The stack is composable from existing APIs.

| Component | Build Effort | Key Risk |
|---|---|---|
| Telephony (Twilio) | 1 week | None — well documented |
| STT pipeline (Deepgram) | 1 week | Latency optimisation |
| LLM order state machine | 3–4 weeks | Accuracy at edge cases |
| Menu RAG | 2 weeks | Ingestion pipeline |
| Square POS integration | 3–4 weeks | Certification process |
| Toast POS integration | 3–4 weeks | Enterprise partner approval |
| Dashboard MVP | 3–4 weeks | Real-time websocket complexity |
| TTS + voice response | 1 week | Latency budgeting |

**Total Phase 1 (Square only):** 10–14 weeks for 4 developers

### Where Loman's Real Moat Is

Not the AI. Not the voice pipeline. The moat is:

1. **Certified POS integrations** — 6+ integrations at production quality
2. **Operator trust** — established reference customers
3. **Proprietary call data** — every live call is training data competitors don't have
4. **Sales motion** — restaurant industry is relationship-driven, not self-serve

### Differentiation Opportunity

Given a team with embedded systems, kiosk, and computer vision background — the smarter build is **not a Loman clone** but a **unified ordering layer** covering:

- Phone (what Loman does)
- In-restaurant kiosk
- Drive-thru terminal
- Airport / travel F&B kiosk

This plays to hardware integration strengths and addresses a gap no current player owns.

---

*Document generated for internal competitive and product analysis.*
*Sources: Loman.ai public documentation, blog posts, and press releases.*
