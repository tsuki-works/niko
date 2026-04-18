# Technical Architecture Document
## AI Voice Agent for Restaurants

**Version:** 1.0
**Date:** April 18, 2026
**Status:** Draft — Pending Team Review

---

## 1. System Overview

```
                          ┌─────────────────────────────────────┐
                          │           RESTAURANT DASHBOARD       │
                          │         (Next.js Web App)            │
                          │  Menu Mgmt | Analytics | Settings    │
                          └──────────────┬──────────────────────┘
                                         │ REST/WebSocket
                                         ▼
┌──────────┐    SIP/PSTN    ┌─────────────────────────────┐    ┌──────────────┐
│ Customer  │───────────────▶│     TELEPHONY GATEWAY        │    │  POS Systems │
│  (Phone)  │◀───────────────│   (Twilio / Telnyx)          │    │  Square/Toast│
└──────────┘    Audio        └──────────┬──────────────────┘    └──────┬───────┘
                                        │ WebSocket (audio stream)      │ API
                                        ▼                               │
                             ┌──────────────────────┐                   │
                             │   VOICE ORCHESTRATOR  │                  │
                             │   (Core Backend)      │◀─────────────────┘
                             │                       │
                             │  ┌─────────────────┐  │
                             │  │  STT Engine      │  │  Deepgram / Whisper
                             │  │  (Speech→Text)   │  │
                             │  └────────┬────────┘  │
                             │           ▼           │
                             │  ┌─────────────────┐  │
                             │  │  LLM Engine      │  │  Claude / GPT-4
                             │  │  (Conversation)  │  │
                             │  └────────┬────────┘  │
                             │           ▼           │
                             │  ┌─────────────────┐  │
                             │  │  TTS Engine      │  │  ElevenLabs / PlayHT
                             │  │  (Text→Speech)   │  │
                             │  └─────────────────┘  │
                             └──────────┬─────────────┘
                                        │
                                        ▼
                             ┌──────────────────────┐
                             │     DATA LAYER        │
                             │  PostgreSQL + Redis    │
                             │  Call logs, orders,    │
                             │  menus, transcripts    │
                             └──────────────────────┘
```

---

## 2. Recommended Tech Stack

### Backend (Voice Orchestrator + API)
| Component | Recommended | Alternative | Rationale |
|-----------|-------------|-------------|-----------|
| **Language** | Python 3.12+ | Node.js (TypeScript) | Best AI/ML ecosystem, fastest prototyping for LLM apps |
| **Web Framework** | FastAPI | Django / Express | Async-native, WebSocket support, auto-generated API docs |
| **Task Queue** | Celery + Redis | Bull (Node) | Background jobs: transcription, analytics, notifications |
| **WebSocket** | FastAPI WebSocket | Socket.IO | Real-time audio streaming from telephony provider |

### Frontend (Restaurant Dashboard)
| Component | Recommended | Alternative | Rationale |
|-----------|-------------|-------------|-----------|
| **Framework** | Next.js 15 (React) | SvelteKit | SSR, great DX, huge ecosystem, easy deployment |
| **UI Library** | shadcn/ui + Tailwind | MUI / Chakra | Lightweight, customizable, modern look |
| **State Management** | TanStack Query | SWR / Redux | Server-state focused, caching, real-time updates |
| **Charts** | Recharts | Chart.js | React-native charting for analytics dashboard |

### Voice / AI Pipeline
| Component | Recommended | Alternative | Rationale |
|-----------|-------------|-------------|-----------|
| **Telephony** | Twilio Voice | Telnyx / Vonage | Most mature API, best docs, programmable voice |
| **STT (Speech-to-Text)** | Deepgram Nova-3 | OpenAI Whisper API | Real-time streaming, low latency, high accuracy |
| **LLM (Conversation)** | Anthropic Claude Sonnet | OpenAI GPT-4o | Strong instruction following, structured output |
| **TTS (Text-to-Speech)** | ElevenLabs | OpenAI TTS / PlayHT | Most natural voices, low latency streaming |

### Infrastructure
| Component | Recommended | Alternative | Rationale |
|-----------|-------------|-------------|-----------|
| **Cloud** | AWS | GCP / Azure | Broadest service offering, best for startups (credits) |
| **Compute** | ECS Fargate (containers) | EC2 / Lambda | Serverless containers, auto-scaling, no server mgmt |
| **Database** | PostgreSQL (RDS) | Supabase / PlanetScale | Reliable, scalable, great for structured restaurant data |
| **Cache** | Redis (ElastiCache) | Memcached | Session state, call state, real-time data |
| **Object Storage** | S3 | — | Call recordings, transcripts, menu images |
| **CDN** | CloudFront | — | Low-latency asset delivery |
| **DNS** | Route 53 | Cloudflare | Integrated with AWS |
| **Monitoring** | Datadog | Grafana + Prometheus | Full-stack observability (traces, logs, metrics) |
| **CI/CD** | GitHub Actions | GitLab CI | Integrated with GitHub, simple YAML config |

### Third-Party Services
| Service | Provider | Purpose |
|---------|----------|---------|
| **Payments** | Stripe | Subscription billing for our SaaS |
| **Phone Payments** | Square/Stripe tokenization | PCI-compliant card capture over phone |
| **SMS** | Twilio SMS | Order confirmations, notifications |
| **Email** | SendGrid / Resend | Transactional emails, reports |
| **Auth** | Clerk / Auth0 | Restaurant owner authentication |
| **Error Tracking** | Sentry | Exception monitoring |

---

## 3. Core Services Architecture

### 3.1 Voice Orchestrator Service
The central service managing the real-time call pipeline.

```
Inbound Call (Twilio)
    │
    ▼
┌─ Call Session Manager ──────────────────────────┐
│                                                   │
│  1. Audio In → STT (Deepgram streaming)           │
│  2. Text → LLM (Claude/GPT with restaurant context)│
│  3. LLM Response → TTS (ElevenLabs streaming)     │
│  4. Audio Out → Caller                            │
│                                                   │
│  State: conversation history, order-in-progress,  │
│         menu context, customer info               │
└───────────────────────────────────────────────────┘
```

**Key Design Decisions:**
- **Streaming everything** — STT, LLM, and TTS all use streaming APIs to minimize latency
- **Turn-based with interruption** — Detect when caller starts speaking during TTS, stop playback, process new input
- **Stateful sessions** — Each call maintains conversation state in Redis for fast access
- **Timeout handling** — Detect silence, prompt caller, gracefully end abandoned calls

### 3.2 Restaurant Context Engine
Provides the LLM with restaurant-specific knowledge for each call.

```
For each call, build a context payload:
├── Restaurant profile (name, address, hours, policies)
├── Full menu (categories, items, prices, modifiers, allergens)
├── Current availability (out-of-stock items, temporary closures)
├── Active promotions and upsell rules
├── Call handling rules (when to transfer, greeting script)
└── Caller history (if repeat caller — past orders, preferences)
```

This context is injected into the LLM system prompt at the start of each call and updated mid-call if menu changes occur.

### 3.3 Order Processing Service
Handles order lifecycle from creation to POS submission.

```
Order Flow:
1. AI builds order object during conversation
2. Order confirmed by caller (read-back)
3. Order validated (items exist, prices match, modifiers valid)
4. Payment captured (if phone payment enabled)
5. Order submitted to POS via integration
6. Confirmation SMS sent to caller
7. Order tracked for status updates
```

### 3.4 POS Integration Layer
Abstraction layer for multiple POS systems.

```python
# Conceptual interface
class POSIntegration(ABC):
    async def sync_menu(self) -> Menu
    async def submit_order(self, order: Order) -> OrderConfirmation
    async def check_item_availability(self, item_id: str) -> bool
    async def get_order_status(self, order_id: str) -> OrderStatus

class SquareIntegration(POSIntegration): ...
class ToastIntegration(POSIntegration): ...
class CloverIntegration(POSIntegration): ...
```

---

## 4. Data Model (Core Entities)

```
Restaurant
├── id, name, phone, address, timezone
├── hours (operating hours per day)
├── settings (greeting, transfer rules, AI config)
├── subscription (plan, billing status)
│
├── Menu
│   ├── Categories
│   │   └── Items
│   │       ├── name, description, price
│   │       ├── modifiers (size, toppings, etc.)
│   │       ├── allergens, dietary tags
│   │       └── available (boolean)
│   └── Upsell Rules
│
├── Calls
│   ├── id, caller_phone, started_at, ended_at, duration
│   ├── transcript (full conversation)
│   ├── intent (order, question, reservation, other)
│   ├── outcome (completed, transferred, voicemail, abandoned)
│   └── recording_url
│
├── Orders
│   ├── id, call_id, type (pickup/delivery)
│   ├── items (with modifiers and quantities)
│   ├── total, tax, tip
│   ├── payment_status
│   ├── pos_order_id (from POS integration)
│   └── status (pending, confirmed, preparing, ready, completed)
│
└── Reservations
    ├── id, call_id, party_size, date, time
    ├── customer_name, customer_phone
    └── status (confirmed, cancelled, no-show)
```

---

## 5. Security Considerations

| Area | Approach |
|------|----------|
| **Authentication** | JWT tokens for dashboard, API keys for integrations |
| **Phone payments** | Use Stripe/Square tokenization — never store raw card numbers |
| **PCI compliance** | Minimize scope via third-party tokenization; use payment vault |
| **Data encryption** | TLS in transit, AES-256 at rest for sensitive data |
| **Call recordings** | Encrypted at rest in S3, retention policy configurable |
| **Multi-tenancy** | Row-level security, tenant isolation at DB level |
| **Rate limiting** | API rate limits, call volume throttling |
| **Secrets management** | AWS Secrets Manager / environment variables |

---

## 6. Latency Budget

For a natural phone conversation, total response time must be **< 1 second**.

```
Caller finishes speaking
  │
  ├── STT processing:        ~200-300ms  (streaming, partial results faster)
  ├── LLM inference:         ~300-500ms  (streaming, first token ~200ms)
  ├── TTS generation:        ~200-300ms  (streaming, first audio chunk ~100ms)
  │
  └── Total perceived delay: ~500-800ms  (with streaming overlap)
```

**Optimization strategies:**
- Stream STT → LLM → TTS in pipeline (don't wait for full completion)
- Use LLM streaming to start TTS before full response is generated
- Cache common responses (greetings, FAQs)
- Keep WebSocket connections warm (no cold start)

---

## 7. POC vs MVP vs Production Infrastructure

| Component | POC | MVP | Production |
|-----------|-----|-----|------------|
| Compute | Single EC2 / local | ECS Fargate (2 tasks) | ECS Fargate (auto-scale) |
| Database | SQLite / local Postgres | RDS PostgreSQL (single) | RDS PostgreSQL (multi-AZ) |
| Cache | Local Redis | ElastiCache (single) | ElastiCache (cluster) |
| Storage | Local filesystem | S3 (single region) | S3 (cross-region replication) |
| Monitoring | Console logs | Sentry + CloudWatch | Datadog full stack |
| CI/CD | Manual deploy | GitHub Actions → ECS | GitHub Actions + staging env |
| Domains | ngrok tunnel | Custom domain (single) | Custom domains + CDN |
| Cost estimate | ~$50/mo | ~$200-400/mo | ~$1,000-3,000/mo |

---

## 8. Development Environment Setup (POC)

```bash
# Prerequisites
- Python 3.12+
- Node.js 20+
- Docker + Docker Compose
- PostgreSQL 16 (or Docker)
- Redis (or Docker)

# Quick start (target)
git clone <repo>
cp .env.example .env          # Add API keys
docker-compose up -d           # Start Postgres + Redis
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver     # Backend API

cd frontend
npm install
npm run dev                    # Dashboard at localhost:3000
```

### Required API Keys for Development
- Twilio (Account SID, Auth Token, Phone Number)
- Deepgram (API Key)
- Anthropic or OpenAI (API Key)
- ElevenLabs (API Key)
- Square (Sandbox Application ID, Access Token)
