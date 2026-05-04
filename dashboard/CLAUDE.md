# Niko — Dashboard

Next.js dashboard for Niko, an AI voice ordering platform for restaurants. Phone callers talk to an AI agent; calls and orders land in Firestore; this dashboard surfaces them for the restaurant.

Current pilot: Niko Pizza Kitchen (`niko-pizza-kitchen`).

**Team:** Kailash (telephony), Meet (LLM/backend), Sandeep (TTS), Daniel (this codebase — frontend).

## Design system is authoritative

All visual decisions — colors, typography, spacing, component anatomy, status treatment — live in `design-system.md` at the repo root. That document is the source of truth. If something in this file conflicts with `design-system.md`, the design system wins for visuals; this file wins for everything else.

The brand color is **moonlight indigo** (`oklch(0.7 0.14 260)` dark / `oklch(0.52 0.16 260)` light). Used sparingly — active sidebar nav, focus rings, brand moments. Never for primary CTAs (those are foreground-inverted monochrome).

## Backend contract

The backend is the source of truth. This dashboard is a reader of Firestore docs that FastAPI writes.

- **Pydantic models live at `app/orders/models.py`** in the monorepo. When they change, `lib/schemas/order.ts` updates to match.
- **`lib/schemas/order.ts`** is the single source of truth on the dashboard side. Every Firestore read goes through the Zod converter exported from there — no ad-hoc parsing of `doc.data()` anywhere.
- **Field names stay snake_case** on the dashboard (`call_sid`, `caller_phone`, `unit_price`, `line_total`, `order_type`, `delivery_address`, `created_at`, `confirmed_at`). That's what's in Firestore. Don't rename to camelCase on read.
- **FastAPI owns order creation and status transitions during a call.** The dashboard writes for staff workflow transitions (Start preparing, Mark ready, Mark completed) and for cancellation.
- **The voice pipeline (Twilio → Deepgram → Claude Haiku → ElevenLabs → Firestore) is not this codebase's concern.** New capabilities touching the pipeline go in FastAPI.

## Domain glossary

- **Restaurant** — the tenant. `niko-pizza-kitchen` is the pilot. Multi-tenancy comes after pilot.
- **Order** — what the agent captures on a call. Firestore doc keyed by `call_sid`.
- **Line item** — one entry on an order. Has `name`, `category` (pizza / side / drink), optional `size`, `quantity`, `unit_price`, free-text `modifications` list, `line_total`.
- **Call** — the inbound phone interaction. Identified by Twilio's `call_sid`. Surfaced in `/calls` with its full event timeline (LLM turns, audio, agent and caller utterances).
- **Agent** — the AI voice agent (Claude Haiku 4.5).
- **Status** — `in_progress` (rendered as "Live"), `confirmed`, `preparing`, `ready`, `completed`, `cancelled`. No other values.

Always "order," never "ticket." Always "call," never "session."

## Stack

### Platform (not this codebase)

- **Telephony:** Twilio → FastAPI `/voice` on GCP Cloud Run
- **STT:** Deepgram Nova-2 streaming
- **LLM:** Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) via Anthropic API
- **TTS:** ElevenLabs streaming
- **Latency contract:** <1s end-to-end on the voice pipeline

### This codebase

- Next.js 15+ App Router, React Server Components
- React 19, TypeScript strict mode
- Tailwind CSS v4, OKLCH tokens in `app/globals.css` (`@theme inline`)
- ShadCN/ui, `new-york` style, `neutral` base
- Geist Sans + Geist Mono via `geist`
- lucide-react icons
- next-themes (class strategy, dark default)
- **firebase-admin** (server) and **firebase** web SDK (client, for `onSnapshot`)
- Zod for schema validation of every Firestore read
- React Hook Form + Zod resolver for forms
- date-fns for relative time
- libphonenumber-js for phone formatting
- pnpm, ESLint

## Architecture

### Frontend / backend split

The Next.js app is not the backend. FastAPI on Cloud Run owns the voice pipeline and writes to Firestore. This dashboard reads Firestore and performs staff-workflow + cancel mutations.

Don't recreate FastAPI's responsibilities in Next.js.

### Server-first

- Default to Server Components. `"use client"` only when you need interactivity, browser APIs, stateful hooks, or `onSnapshot`.
- Initial data fetch in Server Components via `firebase-admin`. Pass down as props.
- Real-time subscriptions in Client Components via `onSnapshot`, seeded from server-rendered initial state.
- Server Actions for mutations. No `app/api/` routes.

### Real-time via Firestore

- `onSnapshot` on the client. No SSE, no WebSockets, no polling.
- Pattern: Server Component renders from `firebase-admin`; Client Component receives initial data as a prop and subscribes for updates.
- Scope subscriptions narrowly — at the component that needs the feed, not at the layout.
- Clean up listeners on unmount.

## File structure

```
app/
  (dashboard)/
    layout.tsx                top bar + theme provider + sidebar
    page.tsx                  overview
    orders/
      page.tsx                orders feed (live)
      [id]/page.tsx           order detail
    calls/
      page.tsx                calls list
      [id]/page.tsx           call timeline
    menu/
      page.tsx                menu management
    settings/
      page.tsx                restaurant settings, hours, fallback
  actions/                    Server Actions, organized by domain
  globals.css
  layout.tsx                  root (fonts, ThemeProvider, Toaster)
components/
  ui/                         ShadCN primitives
  orders/
    orders-feed.tsx
    orders-table.tsx
    order-detail.tsx
    status-badge.tsx          THE status component — see design-system.md
    cancel-order-button.tsx
    workflow-actions.tsx      Start preparing / Mark ready / Complete
  calls/
    calls-table.tsx
    call-timeline.tsx
    call-recording-player.tsx
  menu/
    menu-section.tsx
    menu-item-row.tsx
  settings/
    restaurant-info-form.tsx
    hours-form.tsx
  shared/
    sidebar.tsx
    page-header.tsx
    live-indicator.tsx
    local-time.tsx
    theme-toggle.tsx
    empty-state.tsx
lib/
  firebase/
    admin.ts
    client.ts
    converters.ts
  schemas/
    order.ts
    call.ts
    menu-item.ts
    settings.ts
  formatters/
    money.ts                  formatCAD()
    phone.ts                  E.164 → display
    duration.ts               seconds → "2 min 13 sec"
  status-styles.ts
  utils.ts
```

## Firestore conventions

- **Collections:** `orders` (key: `call_sid`), `calls` (key: `call_sid`), `menu_items`, `settings/restaurant`.
- **Every read validates through a Zod schema** via converters in `lib/firebase/converters.ts`. On parse failure, log and throw — never silently coerce.
- **Timestamps:** Firestore `Timestamp` on the wire, JS `Date` after the converter. Never let a raw `Timestamp` cross an RSC → Client Component boundary — it won't serialize.
- **Money is stored as `number` (float)** to match the backend. Don't convert to integer cents on read. (See "Deferred" — Decimal migration is planned.)
- **Computed fields** (`line_total`, `subtotal`) are persisted by FastAPI on write. Read as values; don't recompute on the dashboard.

## Component conventions

The visual specifics for every component (anatomy, sizing, color, type) live in `design-system.md`. Highlights below for code-review purposes.

### Status badges

The single most important component in the product. Always rendered via `<StatusBadge status={...} />` from `components/orders/status-badge.tsx`. New status values get added to `lib/status-styles.ts` and `OrderStatusSchema` *before* any UI uses them. Live status pulses; nothing else animates.

### Tables

- Rows: 36-44px tall (compact / default). Not 64px.
- Numeric columns right-aligned, mono font, tabular-nums.
- Status column always last-but-one; action column always last.
- Empty states are intentional — describe what will appear here.

### Forms

- React Hook Form + Zod resolver.
- ShadCN Form primitives (they wire ARIA correctly).
- Phone fields: `libphonenumber-js`, E.164 storage.
- Inputs 36px tall, 6px radius. Focus state uses `--brand` outline.

### Real-time announcements

`aria-live="polite"` regions announce new orders ("New order #F046 from +1 416…"). Throttle to one announcement per 2 seconds.

## Type safety

- Strict mode. No `any` — use `unknown` + narrowing.
- `lib/schemas/*.ts` are the source of truth for every Firestore document shape. TS types via `z.infer`.
- Server Actions return discriminated unions (`{ success: true, data } | { success: false, error }`). Don't throw.
- Exhaustive `switch` on `OrderStatus` — `never` assertion in default branches. If the enum grows, every switch is a compile error until updated.
- Money arithmetic goes through `lib/formatters/money.ts` so the future Decimal migration is file-scoped.

## State management

- URL state (`searchParams`) first — filter tabs, selected order implied by route.
- Server state from RSC fetch + Firestore `onSnapshot`. Don't duplicate into a client store.
- Local component state via `useState` / `useReducer`.
- `useOptimistic` for mutations.
- No Zustand unless there's a genuinely global concern. No Redux ever.

## Accessibility

- WCAG 2.1 AA.
- `eslint-plugin-jsx-a11y` enforced.
- Keyboard navigation on every flow.
- Status communicated by both color AND label (badge has dot AND text).
- Real-time changes via `aria-live="polite"`, throttled.
- Focus rings on every interactive element (`--brand` color, 2px outline, 2px offset).

## Testing

- Vitest for unit tests. Targets: schema converters, formatters, status-styles completeness, money helpers, exhaustive switches on enums.
- Playwright deferred until staffing supports it.
- Firebase Emulator Suite for integration tests. Never hit production Firestore in tests.
- `scripts/seed-orders.ts`, `scripts/seed-calls.ts`, `scripts/seed-menu.ts` populate the emulator for manual iteration.

## PR review focus

In order:

1. Correctness and logic errors
2. **Schema consistency** — Firestore doc shape matches the Zod schema; no ad-hoc fields, no `as any` coercions
3. **Design system adherence** — uses tokens from `globals.css`, badges via `<StatusBadge>`, type scale from `design-system.md`
4. RSC / Client boundary violations — unnecessary `"use client"`; admin SDK on the client; web SDK on the server; raw Firestore `Timestamp` crossing RSC props
5. Listener leaks — `onSnapshot` without cleanup
6. Accessibility — Radix behaviour intact, ARIA, focus, keyboard, `aria-live`
7. Performance (missing `next/image`, over-broad subscriptions, caching live pages)
8. Secrets — never in committed code

Skip: style nits that don't affect behavior, generated `components/ui/` files, lock files.

## Before suggesting changes

- Adding `"use client"` → confirm it's actually needed
- Server-side business logic → confirm it doesn't belong in FastAPI
- New `app/api/` route → confirm a Server Action wouldn't be better
- Renaming fields to camelCase → don't; mirror the Pydantic model
- Switching money to integer cents → don't; backend is float, planned migration is Phase 2
- Parsing `doc.data()` directly → route through the converter
- New order status → update `OrderStatusSchema` and `lib/status-styles.ts` in the same PR
- Rendering a raw timestamp → wrap in `<LocalTime />`
- Hardcoding `$` or `CAD` → use `formatCAD()`
- Introducing a color → must come from `globals.css` tokens. No hex, no rgb, no `bg-emerald-500` Tailwind palette classes
- Status displayed without `<StatusBadge>` → wrong; use the component
- Page title with custom typography → wrong; use the page header pattern from `design-system.md`
- New user-facing string → English-only is fine for pilot; flag for i18n when Quebec launch enters scope

## Deferred

Architectural constraints to leave room for, without building now.

- **Multi-tenancy.** Every query scoped by `restaurant_id` (and `location_id`). Centralized data access layer when the second restaurant signs.
- **Auth & roles.** `owner`, `manager`, `staff`. Role checks at Server Action / Firestore security rule level, not UI-only.
- **Bilingual EN-CA / FR-CA.** `next-intl`, locale URL segment, message catalogs. Required before Quebec launch (Bill 96). Never machine-translate FR-CA without human review.
- **Provincial tax.** GST / HST / PST / QST computed server-side (FastAPI), keyed by location's province. Never compute tax in the browser.
- **Multi-location.** Each location has its own timezone, hours, menu. `<LocalTime />` already accepts a tz prop.
- **Money as Decimal / integer cents.** Backend writes floats today. Migration is file-scoped because all formatting goes through `lib/formatters/money.ts`.
- **Structured modifiers.** Today: `modifications: list[str]`. Phase 2: structured with IDs and price deltas. Backend-driven migration.
- **POS write-back (Square).** Adapter in `lib/pos/` when the integration enters scope.
- **Connection-state live indicator.** Currently shows green-when-subscribed only. Phase 2: amber "Reconnecting…" and red "Disconnected" states.
- **Touch-optimized density.** 36px rows are fine on desktop and iPad. If Niko ships an iPhone or small kitchen-display experience, rows grow to 44px minimum.