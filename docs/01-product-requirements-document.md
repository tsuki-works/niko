# Product Requirements Document (PRD)
## AI Voice Agent for Restaurants — 24/7 Phone Answering System

**Version:** 1.0
**Date:** April 18, 2026
**Authors:** Meet, Sandeep, Kailash, Daniel
**Status:** Draft

---

## 1. Executive Summary

We are building an AI-powered voice phone agent specifically designed for restaurants. The system answers incoming calls 24/7, takes pickup and delivery orders, books reservations, answers customer questions (menu, hours, allergens, etc.), processes payments, and integrates directly with existing POS systems. The goal is to help restaurants capture revenue from missed calls, reduce staff workload, and maintain consistent customer service quality — especially during peak hours.

---

## 2. Problem Statement

Restaurants lose significant revenue due to:
- **Missed calls** during peak hours when staff are too busy to answer
- **Hold times** that cause customers to hang up and order from competitors
- **Inconsistent service** depending on which staff member answers
- **Labor costs** for dedicated phone staff, especially for takeout/delivery-heavy restaurants
- **After-hours missed opportunities** — calls after closing go unanswered

Industry data suggests restaurants miss 20-30% of incoming calls, each representing potential lost revenue of $20-50+ per order.

---

## 3. Target Market

### Primary
- **Single-location restaurants** with high phone order volume (pizza, Chinese, Indian, Thai, etc.)
- **Multi-unit restaurant groups** (2-20 locations) looking to standardize phone service
- **Ghost kitchens / delivery-only** operations reliant on direct orders

### Secondary
- **Enterprise restaurant chains** (20+ locations)
- **Catering businesses** with frequent phone inquiries
- **Food trucks and pop-ups** with inconsistent phone availability

### Ideal Customer Profile
- Receives 30+ phone calls/day
- 25%+ of revenue from takeout/delivery
- Uses a modern POS system (Square, Toast, Clover, SpotOn, etc.)
- Pain point: missed calls during peak service hours

---

## 4. Core Features

### 4.1 Inbound Call Handling
| Feature | Description | Priority |
|---------|-------------|----------|
| AI Voice Agent | Natural, human-like voice conversations | P0 (Must Have) |
| Concurrent Calls | Handle multiple simultaneous calls (up to 50) | P0 |
| Call Transfer | Intelligent routing to live staff for complex requests | P0 |
| Voicemail + Transcription | Capture and transcribe voicemails when needed | P1 |
| Multi-language Support | Support for English + Spanish (more later) | P1 |
| Interruption Handling | Gracefully handle callers who interrupt mid-sentence | P0 |

### 4.2 Order Taking
| Feature | Description | Priority |
|---------|-------------|----------|
| Menu Navigation | Walk callers through the full menu | P0 |
| Customizations | Handle modifications, special requests, dietary needs | P0 |
| Order Confirmation | Read back full order before confirming | P0 |
| Pickup & Delivery | Support both order types with appropriate info collection | P0 |
| Upsell Engine | Suggest add-ons, combos, and popular items | P1 |
| Out-of-Stock Handling | Real-time awareness of unavailable items | P1 |

### 4.3 Reservation Management
| Feature | Description | Priority |
|---------|-------------|----------|
| Table Booking | Book reservations based on availability | P1 |
| Reservation Confirmation | SMS confirmation to customer | P1 |
| Waitlist Management | Add callers to waitlist during busy periods | P2 |
| Reservation Sync | Sync with OpenTable and other platforms | P2 |

### 4.4 Customer Service / FAQ
| Feature | Description | Priority |
|---------|-------------|----------|
| Business Info | Hours, location, parking, directions | P0 |
| Menu Questions | Allergens, ingredients, dietary info | P0 |
| Order Status | Check status of existing orders | P1 |
| Wait Times | Provide estimated wait times | P2 |

### 4.5 Payment Processing
| Feature | Description | Priority |
|---------|-------------|----------|
| Phone Payment | Securely capture credit card info over phone | P1 |
| PCI Compliance | Meet PCI-DSS standards for card data | P0 (when payments enabled) |
| Payment Confirmation | Confirm payment success to caller | P1 |

### 4.6 Restaurant Dashboard
| Feature | Description | Priority |
|---------|-------------|----------|
| Live Call Monitor | View active and recent calls | P0 |
| Call Transcripts | Full transcript of every call | P0 |
| Analytics | Revenue, call volume, peak times, conversion rates | P1 |
| Menu Management | Update menu items, prices, availability in real-time | P0 |
| Business Info Editor | Update hours, address, policies | P0 |
| Settings & Config | Configure agent behavior, greetings, transfer rules | P0 |

### 4.7 POS Integrations
| Feature | Description | Priority |
|---------|-------------|----------|
| Square | Full order sync | P0 (MVP) |
| Toast | Full order sync | P1 |
| Clover | Full order sync | P1 |
| SpotOn | Full order sync | P2 |
| Aloha (NCR) | Full order sync | P2 |

### 4.8 Notifications
| Feature | Description | Priority |
|---------|-------------|----------|
| Outbound SMS | Order confirmations, wait time updates | P1 |
| Email Notifications | Daily/weekly summaries for restaurant owners | P2 |
| Real-time Alerts | Notify staff of high-priority calls or issues | P1 |

---

## 5. User Stories

### Restaurant Owner
- As a restaurant owner, I want the AI to answer all phone calls so I never miss a potential order
- As a restaurant owner, I want to see analytics on call volume and revenue so I can optimize staffing
- As a restaurant owner, I want to update my menu instantly and have the AI reflect changes immediately

### Restaurant Staff
- As a restaurant manager, I want calls automatically handled so my team can focus on in-house customers
- As a host, I want reservations automatically booked so I don't have to juggle the phone and the door

### Customer (Caller)
- As a customer, I want to quickly place an order by phone without waiting on hold
- As a customer, I want accurate answers about menu items, allergens, and hours
- As a customer, I want a natural conversation, not a rigid phone tree

---

## 6. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Uptime | 99.9% availability |
| Latency | < 500ms voice response time |
| Accuracy | > 95% order accuracy |
| Concurrent calls | 50+ per restaurant |
| Onboarding time | < 48 hours from signup to live |
| Data security | PCI-DSS compliant, SOC 2 Type II (production) |
| Scalability | Support 1,000+ restaurant accounts |

---

## 7. Out of Scope (V1)

- Outbound calling campaigns (marketing, follow-ups)
- In-app ordering (web/mobile — phone only)
- Kitchen display system (KDS) integration
- Loyalty program management
- Multi-brand support within single account
- White-label / reseller program

---

## 8. Success Metrics

| Metric | Target |
|--------|--------|
| Call answer rate | > 99% (vs ~70-80% with human staff) |
| Order conversion rate | > 60% of order-intent calls |
| Average order value lift | > 15% (via upsell engine) |
| Customer satisfaction | > 4.0/5.0 post-call rating |
| Restaurant churn | < 5% monthly |
| Setup to live | < 48 hours |

---

## 9. Competitive Landscape

| Competitor | Strengths | Weaknesses |
|------------|-----------|------------|
| Loman.ai | Market leader, strong POS integrations, fast onboarding | Higher price point ($199-$399/mo) |
| Certus AI | Restaurant-focused | Fewer integrations |
| Slang.ai | Voice AI for restaurants | Limited ordering capabilities |
| Generic AI (Bland, Vapi) | Flexible platform | Not restaurant-specific |

### Our Differentiation (TBD — Team Discussion Needed)
- Competitive pricing strategy
- Unique branding and positioning
- Potential feature gaps we can fill
- Better onboarding experience
- Superior analytics/insights

---

## 10. Pricing Strategy (Proposed)

| Plan | Price | Features |
|------|-------|----------|
| **Starter** | $149/mo | Call answering, FAQ, customer inquiries, call transfer, dashboard |
| **Pro** | $299/mo | + Order taking, POS integration, payment processing, reservations |
| **Enterprise** | Custom | + Multi-location, custom integrations, dedicated support |

*Setup fee: $99 (waived for annual plans)*

> **Note:** Pricing is a draft proposal. Team should discuss and validate against market research and cost modeling.

---

## 11. Open Questions

1. **Company name** — Needed before any branding/marketing work
2. **Differentiation strategy** — What makes us different from Loman.ai beyond price?
3. **First POS integration** — Which POS system do we build first? (Recommend Square for accessibility)
4. **Voice provider** — Which TTS/STT provider? (Options: ElevenLabs, Deepgram, OpenAI, AssemblyAI)
5. **LLM provider** — OpenAI GPT-4, Anthropic Claude, or open-source?
6. **Telephony provider** — Twilio, Vonage, or Telnyx?
7. **Hosting** — AWS, GCP, or Azure?
8. **Legal** — Do we need a lawyer review before launch? (IP concerns, PCI compliance)
