# Restaurant Order Platform — Dashboard

Next.js dashboard for an AI voice ordering platform. Phone callers talk to an AI agent, orders land in Firestore, this dashboard surfaces them for the kitchen.

Competitive context: loman.ai, Canadian market focus. Expansion beyond ordering (reservations, upsell, loyalty) comes after Phase 1.

**Team:** Kailash (telephony), Meet (LLM/backend), Sandeep (TTS), Daniel (this codebase).

## Scope (Phase 1 — POC, Weeks 3-6)

**In scope:**

- Single demo restaurant (`niko-pizza-kitchen`), pizza menu
- Orders feed with live updates; order detail view
- One dashboard-side mutation: cancelling a confirmed order
- Firestore as the data store — read server-side via firebase-admin, live via `onSnapshot` client-side
- English only, dark + light modes
- No auth (demo context). Minimal or no gating.

**Deferred to Phase 2+:**

- Multi-tenancy (multiple restaurants, locations)
- Auth / roles
- Bilingual EN-CA / FR-CA (Bill 96 requirement for Quebec)
- Provincial tax (GST/HST/PST/QST) and `total` calculation
- Staff workflow statuses (preparing / ready / completed)
- POS write-back to Square
- Payments
- Call recording playback, transcripts view
- Structured modifiers with IDs and price deltas (POC uses free-text)
- Integer-cents money (POC uses floats to match backend)

A more complete deferred list with migration notes is at the bottom.

## Backend contract

The backend is the source of truth. This dashboard is a reader of Firestore docs that FastAPI writes.

- **Pydantic models live at `app/orders/models.py`** in the monorepo. When they change, `lib/schemas/order.ts` updates to match.
- **`lib/schemas/order.ts`** is the single source of truth on the dashboard side. Every Firestore read goes through the Zod converter it exports — no ad-hoc parsing of `doc.data()` anywhere.
- **Field names stay snake_case** on the dashboard (`call_sid`, `caller_phone`, `unit_price`, `line_total`, `order_type`, `delivery_address`, `created_at`, `confirmed_at`). That's what's in Firestore. Do not rename to camelCase on read — naming consistency with the backend matters more than TS idiom.
- **FastAPI owns order creation and all writes during a call** (`in_progress` → `confirmed`). The dashboard only writes to transition a `confirmed` order to `cancelled`.
- **The voice pipeline (Twilio → Deepgram → Claude Haiku → ElevenLabs → Firestore) is not this codebase's concern.** If a new capability needs server-side logic touching the pipeline, it goes in FastAPI. Don't recreate it in Next.js.

## Domain glossary

Use these terms precisely.

- **Restaurant** — the tenant (one, for now: `niko-pizza-kitchen`, displayed as "Niko Pizza Kitchen").
- **Order** — what the agent captures on a call. Firestore doc keyed by `call_sid`.
- **Line item** — one entry on an order. Has `name`, `category` (pizza / side / drink), optional `size`, `quantity`, `unit_price`, free-text `modifications` list, `line_total`.
- **Call** — the inbound phone interaction. Identified by Twilio's `call_sid`. The dashboard links orders to calls by `call_sid`; call records themselves aren't surfaced in Phase 1.
- **Agent** — the AI voice agent (Claude Haiku 4.5).
- **Status** — `in_progress` (call live, order still being built), `confirmed` (caller confirmed, call ended cleanly), `cancelled` (caller cancelled, call failed, or staff-cancelled via dashboard). No other values.

Always "order," never "ticket." Always "call," never "session."

## Stack

### Platform (not this codebase)

- **Telephony:** Twilio → FastAPI `/voice` on GCP Cloud Run
- **STT:** Deepgram Nova-2 streaming
- **LLM:** Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) via Anthropic API
- **TTS:** ElevenLabs streaming
- **POS (Phase 2+):** Square
- **Latency contract:** <1s end-to-end on the voice pipeline

### This codebase

- Next.js 15+ App Router, React Server Components
- React 19
- TypeScript strict mode
- Tailwind CSS v4, OKLCH tokens in `app/globals.css` (`@theme inline`)
- ShadCN/ui, `new-york` style, `neutral` base
- Primary color: emerald (ties to "confirmed" = the product's success state)
- Fonts: Geist Sans + Geist Mono via `geist` package
- Border radius: `0.75rem`
- lucide-react icons
- next-themes for dark mode (class strategy)
- **firebase-admin** (server) and **firebase** web SDK (client, for `onSnapshot`)
- Zod for schema validation of every Firestore read
- React Hook Form + Zod resolver for any forms (not needed in Phase 1)
- date-fns for relative time formatting
- libphonenumber-js for phone formatting
- pnpm, ESLint (from `create-next-app`)

## Architecture

### Frontend / backend split

The Next.js app **is not the backend.** FastAPI on Cloud Run owns the voice pipeline and writes orders to Firestore. This dashboard reads Firestore and performs exactly one mutation (cancel).

Never recreate FastAPI's responsibilities in Next.js.

### Server-first

- Default to Server Components. `"use client"` only when you need interactivity, browser APIs, stateful hooks, or `onSnapshot`.
- Initial data fetch in Server Components via `firebase-admin`. Pass down as props.
- Real-time subscriptions in Client Components via `onSnapshot`, seeded from the server-rendered initial state.
- Server Actions for the cancel mutation. No `app/api/` routes in Phase 1.

### Real-time via Firestore

- `onSnapshot` on the client. No SSE, no WebSockets, no polling.
- Pattern: Server Component renders from `firebase-admin`; Client Component receives initial data as a prop and subscribes for updates.
- Scope subscriptions narrowly — at the component that needs the feed, not at the layout.
- Clean up listeners on unmount.

## File structure

```
app/
  (dashboard)/
    layout.tsx                top bar + theme provider
    page.tsx                  orders feed (Server Component)
    loading.tsx               table skeleton
    orders/
      [id]/
        page.tsx              order detail (Server Component)
        loading.tsx
        not-found.tsx
  actions/
    cancel-order.ts           Server Action
  globals.css
  layout.tsx                  root (fonts, ThemeProvider, Toaster)
components/
  ui/                         ShadCN primitives
  orders/
    orders-feed.tsx           Client: onSnapshot + rendering
    orders-table.tsx          presentational
    order-detail.tsx          presentational
    cancel-order-button.tsx   Client: AlertDialog + optimistic update
  shared/
    local-time.tsx            tz-aware time rendering
    theme-toggle.tsx
lib/
  firebase/
    admin.ts                  firebase-admin init (server only)
    client.ts                 web SDK init (client only)
    converters.ts             Zod-validated orderConverter
  schemas/
    order.ts                  Zod schemas + display helpers
  formatters/
    money.ts                  formatCAD()
  status-styles.ts            order status → badge style
  utils.ts                    cn helper
scripts/
  seed-orders.ts              emulator seeding
```

## Data flow

- **Read path:** Server Component → `firebase-admin` with `orderConverter` → props → Client Component → `onSnapshot` with the same converter for live updates.
- **Cancel path:** `<CancelOrderButton>` → Server Action → admin SDK write → `revalidatePath`. `onSnapshot` will also fire and reconcile.
- **URL state (`searchParams`)** for status filter. Not client state.
- **FastAPI writes are the source of truth for new orders** — the dashboard reacts, it never races.
- **Dashboard cancel writes do race with FastAPI** in principle. In Phase 1 we only cancel `confirmed` orders (FastAPI is done by then), so no practical race. Flag a code comment rather than solving now.

## Firestore conventions

- **Collections:** `orders`. Documents keyed by `call_sid`.
- **Every read validates through `OrderSchema`** via the converter in `lib/firebase/converters.ts`. On parse failure, log and throw — never silently coerce.
- **Timestamps:** Firestore `Timestamp` on the wire, JS `Date` after the converter. Never let a raw `Timestamp` cross an RSC → Client Component boundary — it won't serialize.
- **Money is stored as `number` (float)** to match the backend and Firestore's native number type. Do not convert to integer cents on read. This is a conscious POC choice — migration plan in deferred section.
- **Computed fields** (`line_total`, `subtotal`) are persisted by FastAPI on write. The dashboard reads them as values; do not recompute.
- **`modifications` is `list[str]`** — free-text strings. Render them as-is. Phase 2 will restructure with IDs and price deltas.

## Component conventions

### ShadCN and accessibility

- Never break Radix behavior. Focus management, ARIA, keyboard nav come from Radix through ShadCN.
- `asChild` children must be focusable (`button`, `a`, `input` — never `div`).
- Every interactive control has an accessible name.
- Icon-only buttons require `aria-label`.
- Preserve focus traps in dialogs, dropdowns, popovers.

### Forms

Not used in Phase 1. When we add them:

- React Hook Form + Zod resolver.
- ShadCN Form primitives (they wire ARIA).
- Phone fields: `libphonenumber-js`, E.164 storage.

### Tables

- TanStack Table for anything beyond trivial display. (Phase 1 orders table can be hand-rolled since it's ~5 columns of read-only data.)
- Right-align numeric columns (subtotal, quantity).
- `font-variant-numeric: tabular-nums` on currency and ID columns so `$18.99` and `$9.00` align.
- Filter / sort state via URL `searchParams`.
- **Status** always rendered via `lib/status-styles.ts`. New status values get added to that file (and to the Zod enum) before any component uses them.
- **Timestamps** render in `America/Toronto` via `<LocalTime />`. Never rely on browser tz — the restaurant's tz is what matters.

### Empty states

Every list surface has a considered empty state. The orders feed empty state is the first thing the team will show on demo day — explain what to expect ("Calls to +1 647-905-8093 will appear here in real time"), don't ship default "No results" text.

### Icons

- lucide-react only.
- `h-4 w-4` inline with text, `h-5 w-5` for buttons.

## Styling

- Tailwind v4. Theme in CSS (`@theme inline` in `app/globals.css`), not `tailwind.config.ts`.
- All theme colors are OKLCH tokens. No hex or rgb in components — extend tokens in `globals.css` instead.
- Dark mode via next-themes, class strategy.
- `cn()` from `lib/utils.ts` for conditional classes.
- Container queries preferred over media queries for component-level responsive behavior.
- Headings use font-weight 500, not 600+ — dashboard density makes heavier weights read cramped.
- Two weights: 400 and 500.

## Performance

- `next/image` for images.
- `next/font` via the `geist` package for fonts.
- Route-level `loading.tsx` and `error.tsx`.
- No `"use client"` on `layout.tsx` or `page.tsx`.
- Firestore subscriptions live at the lowest component that needs them, not in layouts.
- `export const dynamic = 'force-dynamic'` on the orders feed page — it's a live dashboard, caching is the wrong default.

## Type safety

- Strict mode. No `any` — use `unknown` + narrowing.
- **`lib/schemas/order.ts` is the source of truth** for every Firestore document shape. TS types via `z.infer`.
- Server Actions return discriminated unions (`{ success: true, data } | { success: false, error }`). Don't throw.
- Exhaustive `switch` on `OrderStatus` — `never` assertion in default branches. If the Zod enum grows, every switch is a compile error until updated.
- **Money is `number` (float) in Phase 1.** Don't fight it — the backend decided. All arithmetic should go through helpers in `lib/formatters/money.ts` so the Phase 2 Decimal migration is a file-scoped change.

## State management

- URL state (`searchParams`) first — filter tabs, selected order implied by route.
- Server state from RSC fetch + Firestore `onSnapshot`. Don't duplicate into a client store.
- Local component state via `useState` / `useReducer`.
- `useOptimistic` for the cancel mutation.
- No Zustand in Phase 1. No Redux ever.

## Accessibility

- WCAG 2.1 AA.
- `eslint-plugin-jsx-a11y` enforced.
- Keyboard navigation works on every flow.
- Color contrast 4.5:1 normal, 3:1 large.
- **Real-time surfaces** announce new orders via `aria-live="polite"`. Throttle — at most one announcement per 2s.
- Audio players (Phase 2) need keyboard controls, visible focus, and text transcripts as equivalents.

## Testing

- Vitest for unit tests. Phase 1 minimum: `orderConverter` round-trip, `formatCAD`, `orderShortId`, `formatLineItemTitle`, `status-styles` completeness.
- Playwright deferred until Phase 2 unless demo-day smoke tests feel needed.
- **Firebase Emulator Suite** for integration tests. Never hit production Firestore in tests.
- A `scripts/seed-orders.ts` inserts sample orders against the emulator for manual iteration.

## PR review focus

In order:

1. Correctness and logic errors
2. **Schema consistency** — Firestore doc shape matches `OrderSchema`; no ad-hoc fields or inline `as any` coercions
3. RSC / Client boundary violations — unnecessary `"use client"`; `firebase-admin` imported on the client; `firebase` web SDK imported on the server; raw Firestore `Timestamp` crossing RSC props
4. Listener leaks — `onSnapshot` without cleanup
5. Accessibility regressions (Radix, ARIA, focus, keyboard, `aria-live`)
6. Convention adherence (OKLCH tokens, URL state, Zod schemas via converter, status-styles map)
7. Performance (missing `next/image`, over-broad subscriptions, caching a live page)
8. Secrets — never in committed code; `.env.example` stays current

Skip:

- Style nits that don't affect behavior
- Generated files in `components/ui/`
- Lock files, `.next/`, `node_modules/`

## Before suggesting changes

- Adding `"use client"` → confirm it's actually needed (interactivity, browser API, `onSnapshot`)
- Building server-side business logic → confirm it doesn't belong in FastAPI
- Creating `app/api/` → confirm a Server Action wouldn't be better
- Renaming fields to camelCase → don't; mirror the Pydantic model
- Switching money to integer cents → don't; backend is float in Phase 1
- Parsing `doc.data()` directly → route it through the converter
- Adding a new order status → update `OrderStatusSchema` and `status-styles.ts` in the same PR
- Rendering a raw timestamp → wrap in `<LocalTime />`
- Hardcoding `$` or `CAD` → use `formatCAD()`
- Introducing a color not in the theme → extend `globals.css` tokens, don't inline
- Adding a user-facing string → English is fine in Phase 1; no i18n plumbing needed yet

## Deferred to Phase 2+

Architectural constraints to leave room for, without building now. If a Phase 1 decision would paint us into a corner on any of these, flag it in the PR.

- **Money as Decimal / integer cents.** Backend writes floats today. Migration plan: introduce a `Money` type in `lib/formatters/money.ts`, swap storage representation on the backend, update the converter to translate. Every component already routes through `formatCAD()`, so the refactor is file-scoped.
- **Staff workflow statuses** (`preparing`, `ready`, `completed`). Requires backend `OrderStatus` expansion and new transition endpoints (FastAPI). Dashboard gets additional action buttons on the order detail view. `status-styles.ts` and the Zod enum absorb the new values.
- **Structured modifiers.** Today: `modifications: list[str]`. Phase 2: `list[{id, group_id, group_name, name, price_delta}]`. Breaks analytics and POS integration if left as strings. Backend-driven migration.
- **Multi-tenancy.** Every query scoped by `restaurant_id` (and `location_id`). Centralized data access layer around Firestore enforces it. Don't scatter filters in components when the time comes.
- **Auth & roles.** `owner`, `manager`, `staff`. Role checks at the Server Action / Firestore security rule level, not UI-only.
- **Bilingual EN-CA / FR-CA.** `next-intl`, locale URL segment, message catalogs. Required before Quebec launch (Bill 96). Never machine-translate FR-CA without human review — Quebec French diverges from France French, especially in restaurant vocabulary.
- **Provincial tax.** GST / HST / PST / QST computed server-side (FastAPI), keyed by the location's province. Never compute tax in the browser.
- **Multi-location.** Each location has its own timezone, hours, menu. `<LocalTime />` already accepts a tz prop; use that pattern.
- **`order_number`.** Today we display a short-ID derived from `call_sid`. A real human-readable `order_number` (sequential with prefix, e.g. `P-0042`) belongs on the backend — the agent needs to read it to the caller, so it can't be dashboard-only.
- **Call recording / transcript playback.** Requires exposing FastAPI's recording URL + transcript fields on the order document, and an audio player with keyboard controls and text equivalents.
- **POS write-back (Square).** Adapter in `lib/pos/` when we get there.
- **Payments.** After POS.
- **Connection-state live indicator.** Phase 1 shows solid green when subscribed. Phase 2 should reflect Firestore reconnect / disconnect states (amber "Reconnecting…", red "Disconnected" after N seconds).