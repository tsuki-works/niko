# Restaurant Order Platform — Dashboard

Next.js dashboard for an AI-powered voice ordering platform for restaurants. Phone callers talk to an AI agent; orders land in Firestore; this dashboard lets staff see what's coming in.

Competitive context: loman.ai, Canadian market focus. Expect expansion beyond ordering (reservations, upsell flows, loyalty) after Phase 1.

**Team:** Kailash (telephony), Meet (LLM/backend), Sandeep (TTS), Daniel (this codebase — dashboard + Firestore schema).

## Scope (Phase 1 — POC, Weeks 3-6)

**In scope for now:**

- Single demo restaurant (pizza menu)
- Read-only-ish dashboard: incoming orders feed, order detail view, basic status updates
- Firestore as the data store, read both server-side (Firebase Admin) and client-side (onSnapshot for live updates)
- English-only UI
- No auth (demo context) or minimal shared-secret gating — do **not** invest in auth plumbing yet

**Deferred to Phase 2+ (track decisions now, but don't build):**

- Multi-tenancy (multiple restaurants, locations)
- Roles / proper auth
- Bilingual EN-CA / FR-CA (Bill 96 requirement — mandatory before production in Quebec)
- Provincial tax (GST/HST/PST/QST)
- POS write-back to Square (Phase 1 stops at Firestore)
- Payments

When making architectural choices now, pick options that don't **block** Phase 2+ — but don't over-engineer. A deferred-items checklist is at the bottom of this doc.

## Domain glossary

Use these terms precisely. Don't invent synonyms.

- **Restaurant** — the tenant (one, for now).
- **Location** — physical venue (one, for now).
- **Menu** — items, categories, modifiers. Pizza demo menu for POC.
- **Item** — sellable thing. Name, price, description, image, availability.
- **Modifier / Modifier group** — customizations with min/max rules.
- **Call** — single inbound phone interaction with the AI agent. Has recording, transcript, duration, outcome.
- **Order** — finalized or in-progress purchase, linked to a call.
- **Agent** — the AI voice agent (Claude Haiku 4.5 via the Anthropic API).
- **Handoff** — live-call transfer from agent to a human.

Always "Order," never "Ticket." Always "Call," never "Session."

## Stack

### Platform (for context — not this codebase)

- **Telephony:** Twilio (inbound → FastAPI `/voice` endpoint)
- **Backend:** FastAPI on GCP Cloud Run
- **STT:** Deepgram Nova-2 streaming
- **LLM:** Claude Haiku 4.5 via Anthropic API (`claude-haiku-4-5-20251001`)
- **TTS:** ElevenLabs streaming
- **POS (Phase 2+):** Square
- **Latency contract:** <1s end-to-end (voice pipeline, not dashboard)

### This codebase (dashboard)

- Next.js 15+ App Router, React Server Components
- React 19
- TypeScript strict mode
- Tailwind CSS v4, oklch-based CSS variables
- ShadCN/ui (Radix underneath)
- lucide-react icons
- next-themes for dark mode
- **Firestore** via `firebase-admin` (server) and `firebase` web SDK (client, for `onSnapshot`)
- TanStack Table for tables
- Zod for schema validation (including Firestore document shapes)
- React Hook Form with Zod resolver
- Zustand only when RSC/URL state isn't enough (rarely)
- pnpm, Biome

## Architecture

### Frontend / backend split

The Next.js app **is not the backend.** FastAPI on Cloud Run owns the voice pipeline and writes orders to Firestore. This dashboard:

- Reads Firestore (server-side for initial render, client-side `onSnapshot` for live updates)
- Performs dashboard-local mutations (e.g. mark order ready) via Firestore writes or a thin FastAPI endpoint
- Does **not** own business logic for order-taking, LLM prompting, or audio processing

Never recreate FastAPI's responsibilities in Next.js. If a new capability needs server-side logic that touches the voice pipeline, it goes in FastAPI.

### Server-first (for the dashboard)

- Default to Server Components. Only add `"use client"` when you need interactivity, browser APIs, stateful hooks, or Firestore `onSnapshot`.
- Initial data fetch in Server Components via `firebase-admin`. Pass down as props.
- Real-time subscriptions in Client Components via `onSnapshot`, seeded from the server-rendered initial state.
- Server Actions only for dashboard-local concerns. No `app/api/` routes unless it's a webhook from FastAPI (probably not needed in Phase 1).

### Real-time via Firestore

- Use `onSnapshot` on the client. Firestore gives real-time for free — no SSE, no WebSockets, no polling.
- Pattern: Server Component renders from `firebase-admin`; Client Component receives initial data as a prop and subscribes for updates.
- Scope subscriptions narrowly — subscribe at the component that needs the feed, not at the layout.
- Clean up listeners on unmount. Always.

## File structure

```
app/
  (dashboard)/
    layout.tsx
    page.tsx               overview / orders feed
    orders/
      page.tsx
      [id]/page.tsx
    calls/                 (Phase 1 stretch — optional)
    menu/                  (Phase 2+)
    settings/              (Phase 2+)
  globals.css
components/
  ui/                      ShadCN primitives
  orders/
  shared/
lib/
  firebase/
    admin.ts               firebase-admin init (server only)
    client.ts              firebase web SDK init (client only)
    converters.ts          Firestore <-> Zod-validated TS type converters
  schemas/                 Zod schemas (orders, calls, items, ...)
  formatters/              currency, phone, date
  status-styles.ts         order/call status → badge style (single source)
  utils.ts                 cn, etc.
hooks/
  use-orders-feed.ts       onSnapshot wrapper
types/
```

## Data flow

- **Read path:** Server Component → `firebase-admin` → props → Client Component → `onSnapshot` for live updates.
- **Dashboard writes (e.g. status change):** client-side Firestore write, or Server Action → `firebase-admin` write. For POC, direct client writes are fine with permissive security rules; tighten for Phase 2.
- **URL state (`searchParams`)** for filters, sorting, pagination, date ranges — not client state.
- `useOptimistic` for snappy status toggles.
- Firestore writes from FastAPI are the source of truth for new orders — the dashboard reacts to them, never races them.

## Firestore conventions

- **One collection per top-level entity:** `orders`, `calls`, `menu_items` (pizza demo).
- **Every document validates through a Zod schema** on read. Use `.withConverter()` to plug Zod validation into both admin and client SDKs. If a doc fails validation, log and surface as a typed error — don't silently coerce.
- **Timestamps** stored as Firestore `Timestamp`, converted to `Date` on read. Never strings.
- **Money** stored as integer cents plus currency code. Never floats. (See Type Safety.)
- **Document IDs** from Firestore auto-ID or a purpose-built ULID helper — never user-supplied.
- **Denormalize for read performance.** Order documents embed the line items and totals snapshot; don't rely on joins that Firestore doesn't have.

## Component conventions

### ShadCN and accessibility

- Never break Radix behavior. ShadCN wraps Radix — focus management, ARIA, keyboard nav come from Radix.
- `asChild` children must be focusable (`button`, `a`, `input` — never `div`).
- Every interactive control has an accessible name (visible text, `aria-label`, `aria-labelledby`).
- Icon-only buttons require `aria-label`.
- Preserve focus traps in dialogs, dropdowns, popovers.

### Forms

- React Hook Form + Zod for all non-trivial forms.
- ShadCN Form primitives (`FormField`, `FormItem`, `FormLabel`, `FormMessage`) — they wire ARIA correctly.
- `aria-required="true"` on required fields.
- Phone fields: `libphonenumber-js`, store E.164, display formatted.

### Tables

- TanStack Table for anything beyond trivial display.
- Right-align numeric columns (counts, currencies, durations).
- Filtering, sorting, pagination via URL `searchParams`.
- **Currency columns** always formatted via `Intl.NumberFormat('en-CA', { style: 'currency', currency: 'CAD' })`. Never display raw cents.
- **Order status** uses a single badge mapping from `lib/status-styles.ts`: `pending` (amber), `confirmed` (blue), `preparing` (indigo), `ready` (green), `completed` (gray), `cancelled` (red), `failed` (red). New statuses go in this file first.
- **Timestamps** render in the restaurant's local time. Use a `<LocalTime />` component — even in POC, don't render browser-local by accident.

### Empty states

Every list surface (orders, calls) has a considered empty state. Explain what the surface is for and what the user should expect to see. No default "No results" text — during demo day an empty dashboard is the first thing Kailash/Meet will show.

### Icons

- lucide-react only.
- `h-4 w-4` inline with text, `h-5 w-5` for buttons.

## Styling

- Tailwind v4 — config in CSS (`@theme` in `globals.css`), not `tailwind.config.ts`.
- Theme colors use oklch. No hex or rgb for theme tokens — extend the set in `globals.css`.
- Dark mode via next-themes, class strategy.
- `cn()` from `lib/utils.ts` for conditional classes.
- Container queries preferred over media queries for component-level responsive behavior.

## Performance

- `next/image` for images.
- `next/font` for fonts.
- Dynamic imports for heavy client components where it helps.
- `loading.tsx` at route level.
- `error.tsx` at route level.
- No `"use client"` at the top of `layout.tsx` / `page.tsx` unless necessary.
- Keep Firestore subscriptions at the lowest component that needs them.

## Type safety

- TypeScript strict mode. No `any` — use `unknown` + narrowing.
- **Zod schemas are the source of truth** for every Firestore document shape. TS types derived via `z.infer`.
- Server Actions (where used) return discriminated unions (`{ success: true, data } | { success: false, error }`).
- Status enums (`OrderStatus`, `CallOutcome`) are Zod enums. Exhaustive `switch` required — `never` assertion in default branches.
- **Money is never `number`.** Store integer cents in Firestore; wrap in a `Money` type (`{ amount: number; currency: 'CAD' }`) at the boundary. All arithmetic goes through helpers in `lib/formatters/money.ts`.

## State management

- URL state first — filters, pagination, selected order, tabs, date ranges.
- Server state from RSC fetch + Firestore `onSnapshot`. Don't duplicate into client state.
- Local component state via `useState` / `useReducer`.
- Zustand only for genuinely global client state. For POC, probably none needed.
- No Redux.

## Accessibility

- Target WCAG 2.1 AA.
- `eslint-plugin-jsx-a11y` enforced.
- Keyboard navigation on every interactive flow.
- Color contrast 4.5:1 normal text, 3:1 large text.
- **Audio players** (call recordings, when added) need keyboard controls and visible focus. Transcripts always available as text, not only audio.
- **Real-time surfaces** announce new orders via `aria-live="polite"`. Throttle — don't spam the region.

## Testing

- Vitest for unit tests (schemas, formatters, status-styles).
- Playwright for E2E (smoke tests before demo day; axe scan on key routes).
- Zod schemas get round-trip tests (`parse(valid)` succeeds; `parse(invalid)` fails clearly).
- Firestore: use the Firebase Emulator Suite for integration tests, never hit production.
- For POC, prioritize: schema validity, money formatting, status badge mapping, empty states render.

## PR review focus

In order:

1. Correctness and logic errors
2. **Firestore schema consistency** — document shape matches the Zod schema; no ad-hoc fields added without updating the schema
3. **Money handled as cents, never float**
4. RSC/client boundary violations — unnecessary `"use client"`, Firestore web SDK imported on the server or admin SDK on the client
5. Listener leaks — `onSnapshot` without cleanup
6. Accessibility regressions (Radix, ARIA, focus, keyboard)
7. Convention adherence (oklch tokens, URL state, Zod schemas, status-styles map)
8. Performance (missing `next/image`, bloated client bundles, over-broad subscriptions)

Skip:

- Style nits that don't affect behavior
- Generated files in `components/ui/`
- Lock files, `node_modules/`, `.next/`

## Before suggesting changes

- Adding `"use client"` → confirm it's actually needed (interactivity, browser API, or `onSnapshot`)
- Building server-side business logic → confirm it doesn't belong in FastAPI instead
- Creating an API route → confirm it's not duplicating what FastAPI or a Server Action should do
- Adding client state → confirm URL state or Firestore state wouldn't be better
- Introducing a color → confirm it uses an oklch token
- Adding a Firestore field → add to the Zod schema in the same PR
- Math on prices with `number` → switch to cents via `lib/formatters/money.ts`
- Rendering a raw timestamp → wrap in `<LocalTime />`
- New status value → add to Zod enum and `status-styles.ts`
- New user-facing string → acceptable in English for Phase 1; flag for i18n in Phase 2

## Deferred to Phase 2+

Track these as architectural constraints to leave room for, without building them now:

- **Multi-tenancy.** For Phase 2, every query scoped by restaurant (and location). Data access layer around Firestore to enforce it. Don't scatter `restaurantId` filters in components — centralize from day one of Phase 2.
- **Auth & roles.** `owner`, `manager`, `staff`. Role checks at the Server Action / Firestore security rule level, not UI-only.
- **Bilingual EN-CA / FR-CA.** `next-intl`, locale URL segment, message catalogs. Required before Quebec launch (Bill 96). Do not machine-translate FR-CA without human review.
- **Provincial tax.** GST / HST / PST / QST. Tax calc server-side (FastAPI), keyed by the location's province. Never compute tax in the browser.
- **Multi-location.** Locations have their own timezones, hours, menus. `<LocalTime />` already accepts a tz prop — use that pattern.
- **Phone formatting by locale.** E.164 storage is already in place; display formatting can localize when we add FR-CA.
- **POS write-back (Square).** Adapter pattern in `lib/pos/` when we get there.
- **Payments.** Out of scope until after POS integration.

If a Phase 1 decision would paint us into a corner on any of the above, flag it in the PR.