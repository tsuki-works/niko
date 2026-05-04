# Niko Design System

Reference for everyone building or reviewing UI in the Niko dashboard. When in doubt, this document wins over personal preference.

## Design principles

1. **Operational over decorative.** This is software for people during a Friday rush. Every pixel should help someone do their job faster. If it's pretty but slows scanning, cut it.
2. **Status is the loudest signal.** A line cook glances at the screen for 0.4 seconds. Order status must register in that window — even from four feet away.
3. **Density wins.** Show 20 orders on a screen, not 5. Restaurant workers should never scroll to see what's in queue.
4. **Dark mode is primary.** Kitchens are dark; back-of-house monitors run dark; this is what staff will use 90% of the time. Light mode is for office contexts (managers, owners doing analytics).
5. **One brand color, used sparingly.** Color carries meaning here — let status colors do the chromatic work. The brand is expressed through type, layout, and restraint.

## Color system

All colors are OKLCH. Both modes use the same hue families so the product feels unified across themes.

### Neutral scale

The bones of the UI. Cool gray (slight blue lean) — feels like a precision tool, not a coffee shop.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--background` | `oklch(0.14 0.005 250)` | `oklch(1 0 0)` | Page background |
| `--surface-1` | `oklch(0.18 0.005 250)` | `oklch(0.98 0.003 250)` | Cards, sidebar |
| `--surface-2` | `oklch(0.22 0.005 250)` | `oklch(0.96 0.003 250)` | Inputs, hover surfaces |
| `--surface-3` | `oklch(0.26 0.005 250)` | `oklch(0.93 0.005 250)` | Popovers, active states |
| `--border-subtle` | `oklch(1 0 0 / 0.06)` | `oklch(0 0 0 / 0.06)` | Hairlines between same-elevation items |
| `--border` | `oklch(1 0 0 / 0.10)` | `oklch(0 0 0 / 0.10)` | Default borders |
| `--border-strong` | `oklch(1 0 0 / 0.18)` | `oklch(0 0 0 / 0.18)` | Focus, hover, emphasis |
| `--foreground` | `oklch(0.98 0 0)` | `oklch(0.18 0.005 250)` | Primary text |
| `--foreground-muted` | `oklch(0.72 0.005 250)` | `oklch(0.42 0.005 250)` | Secondary text, labels |
| `--foreground-subtle` | `oklch(0.5 0.005 250)` | `oklch(0.58 0.005 250)` | Captions, metadata |
| `--foreground-faint` | `oklch(0.35 0.005 250)` | `oklch(0.72 0.005 250)` | Disabled, placeholders |

### Brand accent

One color, used in: logo accent, focus rings, active nav state background, "live" indicator pulse. Nowhere else.

| Token | Dark | Light |
|---|---|---|
| `--brand` | `oklch(0.7 0.14 260)` | `oklch(0.52 0.16 260)` |
| `--brand-muted` | `oklch(0.7 0.14 260 / 0.16)` | `oklch(0.52 0.16 260 / 0.10)` |
| `--brand-foreground` | `oklch(0.98 0 0)` | `oklch(0.98 0 0)` |

The hue (260°) lands between blue and indigo — moonlight, fitting "Niko" without being literal about it.

### Primary action

Primary buttons invert the foreground/background. No brand-colored CTAs.

| Token | Dark | Light |
|---|---|---|
| `--primary` | `oklch(0.98 0 0)` | `oklch(0.18 0.005 250)` |
| `--primary-foreground` | `oklch(0.18 0.005 250)` | `oklch(0.98 0 0)` |
| `--primary-hover` | `oklch(0.92 0 0)` | `oklch(0.28 0.005 250)` |

This is the Linear / Vercel / Raycast school. Pure-contrast CTAs read instantly without competing with status colors.

### Status colors

The most important system in the entire product. Each status has three tokens: a primary (for dots, accents), a background (for badges), and a foreground (for text on the badge).

Hue assignments are deliberate: warmer = more attention required, cooler = settled state.

| Status | Hue | Meaning | Dark badge bg | Dark badge fg | Light badge bg | Light badge fg |
|---|---|---|---|---|---|---|
| `live` (in_progress) | Amber 75° | Active call, attention | `oklch(0.78 0.16 75 / 0.18)` | `oklch(0.85 0.14 75)` | `oklch(0.94 0.08 75)` | `oklch(0.42 0.18 75)` |
| `confirmed` | Blue 235° | Ready to work on | `oklch(0.7 0.14 235 / 0.18)` | `oklch(0.78 0.13 235)` | `oklch(0.95 0.04 235)` | `oklch(0.4 0.16 235)` |
| `preparing` | Violet 290° | In progress | `oklch(0.65 0.2 290 / 0.2)` | `oklch(0.78 0.16 290)` | `oklch(0.95 0.05 290)` | `oklch(0.42 0.2 290)` |
| `ready` | Green 155° | Done waiting, pickup time | `oklch(0.72 0.18 155 / 0.2)` | `oklch(0.82 0.16 155)` | `oklch(0.94 0.07 155)` | `oklch(0.38 0.16 155)` |
| `completed` | Neutral | Archived | `oklch(0.5 0.005 250 / 0.3)` | `oklch(0.72 0.005 250)` | `oklch(0.95 0.003 250)` | `oklch(0.45 0.005 250)` |
| `cancelled` / `failed` | Red 25° | Problem | `oklch(0.65 0.22 25 / 0.18)` | `oklch(0.78 0.18 25)` | `oklch(0.95 0.04 25)` | `oklch(0.45 0.2 25)` |

**Anti-patterns:**
- Don't add a 7th status hue. If you need to distinguish more states, find a non-color encoding (icon, position, weight).
- Don't use status colors anywhere except status. No "info blue" buttons, no "success green" links. The vocabulary stays small.

### Status badge anatomy

Every status badge has the same structure, no exceptions:

- A 6px colored dot (the status primary), `border-radius: 50%`
- 6px horizontal gap
- The label, sentence case, font-weight 500, 12px
- Tinted background using the status badge background token
- Solid 1px border using a low-alpha version of the status primary, `border-radius: 999px` (full pill)
- Padding: `4px 10px 4px 8px` (slight left bias accommodates the dot)

For `live` status only: the dot pulses at 1.5s intervals. This is the single piece of motion in the entire UI.

## Typography

One typeface family. Two weights. Five sizes. No exceptions, no decorative fonts.

### Family

- `--font-sans`: Geist Sans (via `geist` package). Used for all UI text.
- `--font-mono`: Geist Mono. Used for: order IDs (`#F045`), call SIDs, phone numbers, currency in tables, code, timestamps in detail views.

No serif. No display font. The previous design used a Cooper-style display font for headings — that's why it read "boutique." Cut it.

### Scale

| Class | Size | Line height | Weight | Use |
|---|---|---|---|---|
| `text-xs` | 11px | 14px | 500 | Column headers, eyebrow labels (uppercase tracking) |
| `text-sm` | 13px | 18px | 400 / 500 | Table cells, secondary text |
| `text-base` | 14px | 20px | 400 / 500 | Default body, button labels |
| `text-md` | 16px | 22px | 500 | Card titles, item names |
| `text-lg` | 18px | 24px | 500 | Section headers, order detail title |
| `text-xl` | 22px | 28px | 600 | Page titles |
| `text-2xl` | 28px | 32px | 600 | KPI numbers (the only place 28px appears) |

### Rules

- Two weights only: 400 (regular) and 500 (medium). 600 reserved for page titles and KPI numbers, that's it.
- Sentence case for everything. Never Title Case. Never ALL CAPS — except column headers (`text-xs` with `letter-spacing: 0.04em` and `text-transform: uppercase`).
- Tabular numerals (`font-variant-numeric: tabular-nums`) on every number that appears in a column or stat: order IDs, prices, durations, timestamps, counts.
- Mono font for IDs and prices in tables. Sans for IDs and prices in body prose.

## Spacing and density

Restaurants are not Notion. Tighten everything.

### Scale

Use these values exclusively. Don't introduce 14px, 22px, etc.

`4 / 6 / 8 / 12 / 16 / 20 / 24 / 32 / 48 / 64`

### Density rules

| Element | Old | New |
|---|---|---|
| Table row height | ~64px | 36px (compact), 44px (default) |
| Table cell padding | 16-20px | 8px vertical, 12px horizontal |
| Card padding | 20-24px | 16px |
| Card padding (large/feature) | 24-32px | 20px |
| Page padding | 32px+ | 24px |
| Sidebar width | ~240px | 200px |
| Header bar height | ~80px | 56px |
| Section gap | 24-32px | 16px between cards, 24px between sections |
| Button height (default) | ~40px | 32px (default), 28px (compact, for table actions), 36px (large CTAs) |
| Input height | ~44px | 36px |

### Border radius

Smaller than before. Big radii read consumer/playful, smaller radii read precise.

- `--radius-xs`: 4px (badges with internal content, dots)
- `--radius-sm`: 6px (buttons, inputs, tags)
- `--radius-md`: 8px (cards)
- `--radius-lg`: 12px (large feature panels — rare)
- `--radius-pill`: 999px (status pills only)

The old `0.75rem` (12px) default was too rounded. Pull back to 8px as the default.

## Components

### Buttons

Three variants, three sizes.

**Variants:**

- **Primary** — for the single most important action on a page. Inverted foreground/background. `bg: var(--primary)`, `color: var(--primary-foreground)`. Used for: "Confirm", "Save", main CTAs. **Maximum one per visible region.**
- **Secondary** — for non-primary actions. `bg: var(--surface-2)`, `color: var(--foreground)`, `border: 1px solid var(--border)`. Used for: "Cancel", side actions, table-row actions.
- **Ghost** — for tertiary actions. Transparent background, `color: var(--foreground-muted)`, no border. Becomes `bg: var(--surface-2)` on hover. Used for: icon buttons, sidebar nav items, dismiss buttons.

**Sizes:**

- `sm`: 28px height, 12px horizontal padding, 13px text. For table rows.
- `default`: 32px height, 14px horizontal padding, 14px text. Most contexts.
- `lg`: 36px height, 16px horizontal padding, 14px text. Form CTAs, primary actions on detail pages.

Icon-only buttons are square (28x28, 32x32, 36x36) with the same heights.

### Status badges

See "Status badge anatomy" above. This is the most important component in the product. Spec it once, use it everywhere.

```tsx
<StatusBadge status="confirmed" />
// renders: [● Confirmed]
```

Live badge gets a `data-pulse` attribute that drives the dot's keyframe animation.

### Cards

The default container. Three variants by visual weight.

- **Plain** — `bg: var(--surface-1)`, no border, no padding default. For grouping without visual emphasis.
- **Bordered** — `bg: var(--surface-1)`, `border: 1px solid var(--border-subtle)`, `padding: 16px`. The default card. Used for KPIs, list items, detail panels.
- **Subtle** — `bg: var(--surface-2)`, no border, `padding: 12px 16px`. Used for the subtotal section in order detail, secondary panels.

No card-within-card-within-card nesting. Maximum two levels.

### Tables

The orders feed and calls list are tables, not card grids. Treat them with respect.

- Header row: `text-xs`, uppercase, `letter-spacing: 0.04em`, `color: var(--foreground-muted)`, `padding: 10px 12px`.
- Header divider: 1px `var(--border-subtle)` below header, no per-column dividers.
- Body rows: 36px height (compact) or 44px (default). 13px text.
- Row dividers: 1px `var(--border-subtle)`. No alternating row colors.
- Hover: `bg: var(--surface-2)`. Rows that are links also get `cursor: pointer`.
- Numeric columns: right-aligned, mono font, tabular-nums.
- ID columns: mono font, `text-foreground` (full strength).
- Status column: status badge, left-aligned, 100px column width fits the longest current status pill.
- Action column: 80-100px width, right-aligned, `sm` button.
- First and last columns: `padding-left` / `padding-right` matches container, no extra column gutter.

### Forms

- Labels above inputs, `text-sm`, `text-foreground-muted`, 6px below label.
- Inputs: 36px height, `bg: var(--surface-2)`, 1px border `var(--border)`, 6px radius.
- Focus state: `border-color: var(--brand)`, plus 3px outline `var(--brand-muted)`. No box-shadow ringing.
- Helper text below input, `text-sm`, `text-foreground-subtle`, 6px above text.
- Error state: border red status, helper text red status fg.
- Required indicator: tiny dot or asterisk to the right of the label, `text-foreground-muted`. Don't write "(required)" — too noisy.

### Live indicator

Top-right of any page that has live data. Format:

```
● Live
```

- 8px dot, `bg: var(--status-ready)` (green) when subscribed and healthy
- Dot pulses at 1.5s
- Label `text-sm`, `color: var(--foreground-muted)`
- When connection drops: dot becomes amber, label becomes "Reconnecting…"
- When fully disconnected for >10s: dot becomes red, label becomes "Disconnected"

Phase 1 ships the green-only state; the amber/red states are stubbed but don't do anything yet.

### KPI cards (overview page)

Inline, not boxed. Single horizontal strip across the top.

```
ORDERS TODAY              ORDERS THIS WEEK         AVG ORDER VALUE         COMPLETION RATE
24                        140                      $14.82                  87%
                          rolling 7 days           rolling 7 days          confirmed → completed
```

- Eyebrow label: `text-xs`, uppercase, `letter-spacing: 0.04em`, `color: var(--foreground-muted)`
- Number: `text-2xl`, weight 600, mono font, tabular-nums
- Caption: `text-sm`, `color: var(--foreground-subtle)`, below number
- Separators between KPIs: 1px `var(--border-subtle)` vertical lines, full height of the strip
- Padding: 16px around each KPI

This replaces the four boxy KPI cards in the current overview design — they take too much vertical space.

## Layout patterns

### Page header

Every authenticated page starts with the same structure:

```
[Page Title]                                                  [Live indicator] [Page actions]
[Subtitle / metadata]
```

- Page title: `text-xl`, weight 600
- Subtitle: `text-sm`, `color: var(--foreground-muted)`, can include the restaurant name and key metadata
- Right side: live indicator (if applicable), page-level actions (rare — most actions live in tables/cards)
- Bottom margin: 24px before next section
- No bottom border on page header. Let the content's own structure define separation.

### Sidebar

- 200px wide, full height, `bg: var(--surface-1)`
- Niko logo at top: 32px tall, just the moon icon + "Niko" wordmark in `text-base`, weight 600. No "by Tsuki Works" — that's a marketing-site detail, not a product-UI detail. (Move it to Settings → About.)
- Nav items: 32px tall, 12px horizontal padding, 6px radius, 8px gap between
- Inactive nav: `color: var(--foreground-muted)`, transparent bg
- Hover: `bg: var(--surface-2)`, `color: var(--foreground)`
- Active: `bg: var(--brand-muted)`, `color: var(--foreground)`. Full pill — no left-border accent. The brand-muted background alone carries the active signal; an accent rail competes with it.
- Icons: 16px, lucide
- Footer: a small block with the user/restaurant identifier and a settings shortcut

### Order detail layout

Two-column on screens >960px:

- **Left (60%)** — Caller card, items list, totals
- **Right (40%)** — Call recording + transcript preview, metadata sidebar

On narrow screens, single column with the call recording moved to the bottom.

The current single-column layout wastes the right half of the screen. The two-column treatment is denser and gives the call recording / transcript a proper home (which is currently a dead button).

### Empty states

Centered in their container. Three parts:

- A 32px lucide icon, `color: var(--foreground-faint)`
- A short title, `text-md`, weight 500. "No orders yet."
- A one-line description, `text-sm`, `color: var(--foreground-muted)`. Tell the user what will happen here.
- Optional: a single primary action, only when there's a clear next step.

Empty states are not throwaway. The first time someone opens this app — or the first time after-hours when no orders are in queue — the empty state IS the page. Make it intentional.

## Motion

Almost none. This is a tool, not an experience.

The exceptions:

- **Live status pulse** — the only continuous animation. Dot scales 1 → 1.15 → 1 over 1.5s, infinite.
- **Row enter** — when a new order arrives, the row fades + slides 4px down, 200ms ease-out. Once. Then it's static.
- **Focus rings** — appear instantly, no transition.
- **Hover state changes** — 100ms linear background-color transition. No transform, no scale.

No spring physics. No staggered list animations. No skeleton shimmer (use a static muted block).

## Accessibility

- WCAG 2.1 AA contrast on all text. The dark-mode `--foreground-muted` value is calibrated to clear 4.5:1 against `--background` and `--surface-1`.
- Focus rings visible on every interactive element. Use the brand-muted outline.
- Status is never communicated by color alone — the pill always has both the dot AND the label.
- Live region (`aria-live="polite"`) announces new orders, throttled to 1 per 2 seconds.
- Keyboard navigation: `Tab` cycles interactive elements in DOM order; tables use `Tab` to enter and arrow keys to navigate cells (or `Tab` only — both fine, just be consistent).
- Screen-reader labels on icon-only buttons.

## What this replaces from the current design

| Current | New |
|---|---|
| Cream-on-near-black palette | Cool neutral grays + status colors |
| Cooper-style display font for headings | Geist Sans throughout |
| Emerald primary | Monochromatic (foreground-inverted) primary |
| ~64px table rows | 36-44px table rows |
| Boxy KPI cards | Inline KPI strip |
| "Niko / by Tsuki Works" sidebar lockup | "Niko" wordmark only |
| Pill badges with low contrast | Status badges with dot + tinted bg |
| 0.75rem default radius | 0.5rem default radius |
| Multiple text colors carrying meaning | Status colors for status only |

## Open questions

1. **Pulse on `live` status** — confirmed visually pleasing on demo day, but kitchen displays running 24/7 may not want continuous motion. Worth A/B testing with a real venue.
2. **Two-column order detail** — assumes a desktop primary, but if Niko ships an iPad-on-a-stand kitchen display, single-column might be better. Decide before building Phase 2 staff workflow.
3. **Brand color usage** — current scope is tiny (logo, focus, active nav). If the brand needs more presence in Phase 2 marketing surfaces (signup, billing, plan upgrade), expand the brand token set then.
4. **Print styles** — staff occasionally print order tickets. Add a print stylesheet when receipt printing becomes a requirement.