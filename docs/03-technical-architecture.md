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
                             │  │  TTS Engine      │  │  Deepgram Aura
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
| **Telephony** | Twilio Voice | Telnyx / Vonage | Most mature API, best docs, programmable voice. $15 trial credit for POC; migrate to Telnyx once volume makes per-minute margin matter |
| **STT (Speech-to-Text)** | Deepgram Nova-2 (streaming) | OpenAI Whisper API | Real-time streaming, low latency, high accuracy. $200 free credit covers POC |
| **LLM (Conversation)** | Anthropic Claude Haiku 4.5 (POC/MVP) → Sonnet (production) | OpenAI GPT-4o | Haiku is cheap + fast with strong instruction following for constrained menu flows. Upgrade to Sonnet for harder conversations once funded. Pay-as-you-go via Console during bootstrap; Claude for Startups is VC-gated, revisit after raising |
| **TTS (Text-to-Speech)** | Deepgram Aura | ElevenLabs / Cartesia / OpenAI TTS | Native mulaw 8 kHz output (drop-in for Twilio); reuses the Deepgram key already used for STT; server-to-server design (no abuse-detector blocks on Cloud Run) |

### Infrastructure

Guiding principle for Phase 0/1/2: **free-tier-first**. Swap to paid tiers once revenue or startup credits justify it.

| Component | Recommended (POC → MVP) | Production swap | Rationale |
|-----------|------------------------|------------------|-----------|
| **Cloud** | GCP | Stay on GCP | $300 credit (90d) + always-free Cloud Run; strong free-tier bundle |
| **Compute** | Cloud Run (single service, scale-to-zero) | Cloud Run (min-instances≥1, higher concurrency) | Managed containers, auto-scale, $0 when idle. 60min request timeout accommodates phone calls |
| **Database** | Firestore (free tier) | Cloud SQL (PostgreSQL) | Firestore free tier covers POC/MVP scale; migrate to Cloud SQL when relational queries or multi-restaurant analytics demand it |
| **Cache** | In-process (per-container) → Memorystore Redis | Memorystore Redis | Skip managed cache during POC; add when session-state concurrency needs cross-instance sharing |
| **Object Storage** | Google Cloud Storage (free tier: 5GB) | GCS standard | Call recordings, transcripts, menu images |
| **CDN** | Cloud CDN (only if needed) | Cloud CDN | Cloud Run fronts requests directly during POC; add CDN for static assets at MVP |
| **DNS** | Cloud DNS | Cloud DNS | Integrated with GCP |
| **Monitoring** | Cloud Logging + Cloud Trace (free tier) | Datadog or Grafana Cloud | Start with GCP-native observability; move to Datadog when tracing across services gets painful |
| **Secrets** | Secret Manager | Secret Manager | Referenced by Cloud Run env at deploy time |
| **CI/CD** | GitHub Actions → Cloud Run | Same, plus staging env | Unlimited free minutes on public repos; single workflow deploys on push to `master` |

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
│  3. LLM Response → TTS (Deepgram Aura streaming)  │
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
| Compute | Cloud Run (scale-to-zero, 1 service) | Cloud Run (min-instances=1) | Cloud Run (min-instances≥2, higher concurrency) |
| Database | Firestore (free tier) | Firestore or Cloud SQL (small) | Cloud SQL PostgreSQL (HA, read replicas) |
| Cache | In-process only | Memorystore Redis (basic) | Memorystore Redis (standard HA) |
| Storage | GCS (free tier: 5GB) | GCS standard (single region) | GCS multi-region |
| Monitoring | Cloud Logging + Trace | + Sentry | Datadog / Grafana Cloud full stack |
| CI/CD | GitHub Actions → Cloud Run | Same, auto on `master` merge | + staging env + canary deploy |
| Domains | `*.run.app` default | Custom domain (single) | Custom domains + Cloud CDN |
| Cost estimate | **~$0–20/mo** (credits + telephony) | ~$80–200/mo | ~$800–2,500/mo |

---

## 8. Development Environment Setup (POC)

```bash
# Prerequisites
- Python 3.12+
- Node.js 20+
- Docker (for local parity with Cloud Run)
- gcloud CLI (for deploys; not needed for local dev)

# Quick start (target)
git clone <repo>
cp .env.example .env          # Add API keys
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
uvicorn app.main:app --reload  # FastAPI serves API + static web/

# For Twilio webhook testing, expose localhost:
ngrok http 8000
```

### Required API Keys for Development
- Twilio (Account SID, Auth Token, Phone Number)
- Deepgram (API Key — used for both STT and TTS)
- Anthropic (API Key)
- Square (Sandbox Application ID, Access Token)
- GCP service account JSON (for Firestore + Secret Manager)

---

## 9. Deployment Model

**Two Cloud Run services in one GCP project, each auto-deployed from `master` on a paths filter.**

```
Push to master
      │
      ├── app/** changes
      │     │
      │     ▼
      │   .github/workflows/deploy.yml
      │     │
      │     ├── Build python image from /Dockerfile
      │     ├── Push to Artifact Registry
      │     └── gcloud run deploy niko (region us-central1)
      │
      └── dashboard/** changes
            │
            ▼
          .github/workflows/deploy-dashboard.yml
            │
            ├── Build Next.js standalone image from /dashboard/Dockerfile
            ├── Inject NEXT_PUBLIC_FIREBASE_* as build args (baked into client bundle)
            ├── Push to Artifact Registry
            └── gcloud run deploy niko-dashboard with NIKO_API_BASE_URL env
```

**Why two services (not one):**
- Daniel's dashboard is a real server-runtime Next.js app (RSC, Server Actions, `onSnapshot`) — it can't be statically exported, so it needs a Node runtime separate from FastAPI's Python runtime.
- Independent rollback and scaling: a bad dashboard deploy can't take the voice pipeline offline, and the API can scale on call volume while the dashboard scales on browser sessions.
- Separate logs and metrics per surface — easier to triage.
- Idle cost stays near $0 because Cloud Run scales both to zero.

**API Dockerfile shape (`/Dockerfile`):**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
ENV PORT=8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**Dashboard Dockerfile shape (`/dashboard/Dockerfile`):**
```dockerfile
# Multi-stage: deps → build (with NEXT_PUBLIC_* args) → runtime
FROM node:20-alpine AS deps
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:20-alpine AS build
ARG NEXT_PUBLIC_FIREBASE_API_KEY
# ... other NEXT_PUBLIC_FIREBASE_* args
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm run build  # output: "standalone" → /app/.next/standalone

FROM node:20-alpine AS runtime
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 8080
CMD ["node", "server.js"]
```

**GitHub Actions workflows:**
- `.github/workflows/deploy.yml` — API. Trigger: any push to `master`.
- `.github/workflows/deploy-dashboard.yml` — UI. Trigger: push to `master` with paths in `dashboard/**` (skips deploys on backend-only changes).
- Both use Workload Identity Federation — no long-lived service-account JSON anywhere.

**Secrets / env vars:**
- Store API keys (Twilio, Deepgram, Anthropic, Square) in **Secret Manager**
- Reference them from Cloud Run via `--set-secrets` at deploy time — never bake secrets into the image

**Escape hatches:**
- **Cloud Run WebSocket strain:** long-lived audio streams count against per-instance concurrency. If POC exposes issues, move just the voice worker to Fly.io (WebSocket-native networking) and keep the dashboard on Cloud Run.
- **Cold starts:** scale-to-zero adds ~1–2s on the first request after idle. Acceptable for POC; set `--min-instances=1` (~$5/mo) when the first restaurant goes live.
