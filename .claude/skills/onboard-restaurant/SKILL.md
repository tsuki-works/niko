---
name: onboard-restaurant
description: Onboard a new restaurant tenant from its public website. Fetches name, phone, address, hours, and menu, fills the gaps by asking the user for anything missing, writes a menu JSON file, and runs `scripts/provision_restaurant.py`. Use when the user says "add a restaurant", "onboard <name>", "set up a new tenant", or hands you a restaurant URL.
---

# Onboard Restaurant

End-to-end onboarding for a new restaurant tenant. The team gives a URL; this skill produces a Firestore tenant doc, a menu JSON file checked into the repo, and a Twilio number wired to our `/voice` webhook.

This is the **admin-assisted** path documented in Sprint 2.1 — a true self-serve signup wizard is parked for Sprint 4.2. The script underneath (`scripts/provision_restaurant.py`) and the data model (`app/restaurants/models.py::Restaurant`, Firestore `restaurants/{id}`) are the source of truth — keep this skill in sync if either changes.

## Inputs

Required from the user (the only thing they have to give you to start):

- **Website URL** (e.g. `https://twilightrestaurant.com/`) — entry point for scraping.

Optional hints — accept if offered:

- Display phone (E.164) if it's not on the site
- Preferred area code for the new Twilio number (defaults to the area code of the display phone)
- Restaurant slug / `rid` (defaults to a slug derived from the name)
- Forwarding mode: `always` | `busy` | `noanswer` (default `always`)

## What "done" looks like

1. A menu file at `restaurants/<rid>.json` in the shape `{"pizzas": [...], "sides": [...], "drinks": [...]}`.
2. A Firestore doc `restaurants/<rid>` with name, phones, address, hours, menu, `forwarding_mode`.
3. A Twilio number purchased and pointed at `${BACKEND_URL}/voice`.
4. The team knows what number to forward the restaurant's existing line to.

## Flow

### 1. Crawl the site

Use `WebFetch` to pull these paths in parallel (skip 404s):

- `/` — name, phone, address, hours, navigation hints
- `/menu`, `/menu/`, `/our-menu`, `/food`
- `/about`, `/about-us`
- `/contact`, `/contact-us`, `/locations`
- `/order`, `/order-online` — often the highest-value page; usually routes to a third party (UberEats, SkipTheDishes, DoorDash, ChowNow, Toast) where the menu is fully structured

Prompt template per fetch: *"Extract: restaurant name, phone, full address, hours of operation, and every menu item with name, description, and price. Group menu items by category. Return as JSON when possible, otherwise structured markdown. Note explicitly if the menu is image-only or behind a third-party widget."*

If a page redirects to a third-party ordering site, follow the redirect and extract from there. **In practice UberEats has the highest hit rate for Canadian restaurants** — DoorDash and ChowNow frequently return 403 to `WebFetch`. SkipTheDishes is hit-or-miss. If WebFetch's response looks truncated (categories listed but empty `items: []`), re-fetch with a focused prompt asking for only those specific sections.

### 1a. Image-based menus — OCR via Read

If the menu page is image-only (common for independents — JPG/PNG menu boards in a gallery), don't give up — Claude can read images directly:

1. Ask `WebFetch` for the raw image URLs on the menu page (prompt: *"List every img src URL on this page, one per line. Also list any PDF links."*).
2. Filter to plausible menu images by filename (e.g. `menu`, `prices`, `card`) or by selecting the largest images. Skip obvious food-photo filenames (`IMG_*`, `Take-Out-*`, `chicken-wings.jpg`).
3. Download to a temp path: `curl -sL --max-time 15 -o /tmp/menu_<n>.jpg <url>` (Windows: resolve with `cygpath -w /tmp/menu_<n>.jpg` before passing to `Read`).
4. Use the `Read` tool on the file — Claude is multimodal and will see the image content. Extract items + prices from what's visible.
5. If the image is illegible (low resolution, decorative font), say so and ask the user to paste.

This is the fallback when the site has no third-party ordering link. **If both UberEats/DoorDash/Skip and on-page images fail, ask the user to paste the menu** rather than guessing.

### 2. Map to the data model

Build a draft `Restaurant`:

| Field | Source |
|---|---|
| `id` | slug from name: lowercase, hyphens, ASCII only (e.g. "Twilight Family Restaurant" → `twilight-family-restaurant`) |
| `name` | site header / `<title>` / about page |
| `display_phone` | E.164 — convert any North American format to `+1XXXXXXXXXX` |
| `address` | full street address |
| `hours` | one-line summary, e.g. `Mon-Sun, 11am-10pm` (collapse identical days) |
| `menu` | see "Menu shape" below |
| `forwarding_mode` | default `always` unless user says otherwise |

`twilio_phone` is filled by the provision script — do not set it yourself.

### 3. Menu shape — important constraint

The LLM prompt builder (`app/llm/prompts.py::_format_menu`) currently renders **only three keys**: `pizzas`, `sides`, `drinks`. Any other top-level keys are silently dropped from what the AI sees on calls.

For a non-pizza restaurant, map the categories pragmatically:

- **`pizzas`** → mains / entrees / specialties (whatever the restaurant's headline category is)
- **`sides`** → appetizers, sides, desserts
- **`drinks`** → drinks, beverages

Per-item shape:

```json
// pizzas (must have sizes dict)
{"name": "Butter Chicken", "description": "...", "sizes": {"regular": 14.99, "large": 18.99}}

// sides / drinks (single price)
{"name": "Garlic Naan", "price": 3.99}
```

If the source menu has only a single price for a "pizza"-bucket item, still use the `sizes` shape: `"sizes": {"regular": <price>}`. The prompt formatter expects it.

When you flatten a multi-category menu into these three buckets, **tell the user** what you collapsed and offer to revise. Also flag it as a follow-up: `app/llm/prompts.py` should support dynamic categories before we onboard >2-3 non-pizza restaurants — open an issue if one isn't tracked.

### 4. Identify gaps and ask

For each required field that's missing or low-confidence, ask the user. Batch the questions in a single message; don't drip them one at a time.

A required field is "low-confidence" when:

- The site returned no useful text for it (image-only menu, JS-only render, paywalled)
- Multiple conflicting values were found (two different phone numbers across pages)
- The format is ambiguous (e.g. hours listed per-location with no clear primary)

Example gap-fill prompt:

> I pulled what I could from twilightrestaurant.com but a few things need confirming:
>
> 1. **Menu** — the menu page is image-only. Paste the menu items, link a structured source (DoorDash/Uber/ChowNow), or upload an image.
> 2. **Hours** — site shows "Open Daily" with no times. Confirm hours, e.g. `Mon-Sun, 11am-10pm`.
> 3. **Area code for the new Twilio number** — display phone is `+1-416-754-6894` so I'll default to **416**. Override?

Never invent a missing field. If menu items can't be obtained, the skill stops and waits — provisioning a tenant with no menu means the AI has nothing to sell.

### 5. Write the menu file

Save to `restaurants/<rid>.json` (create the dir if missing — it's not gitignored, this file lands in the PR). Pretty-print with 2-space indent. Schema: top-level `{"pizzas": [...], "sides": [...], "drinks": [...]}`.

### 6. Dry-run the provision script first

Always dry-run before spending money:

```bash
python -m scripts.provision_restaurant \
  --rid <rid> \
  --name "<Name>" \
  --display-phone <+1XXXXXXXXXX> \
  --address "<Address>" \
  --hours "<Hours>" \
  --area-code <NXX> \
  --menu-file restaurants/<rid>.json \
  --dry-run
```

Show the user the dumped JSON. Confirm the data is correct.

### 7. List Twilio number candidates and let the user pick

Before buying anything, surface 3-5 candidate numbers from Twilio's inventory so the team can pick a memorable one (or one in the right city) instead of accepting the first hit.

```bash
python -m scripts.list_twilio_numbers --area-code <NXX> --limit 5
```

Required env: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` (fetch via `/shared-creds` if not in `.env`). The script is read-only — no purchase happens.

Present the output to the user as a numbered list and ask them to pick one. Example:

> Found these in 416:
>
> 1. **+14165550101** — Toronto, ON
> 2. **+14165550149** — Toronto, ON
> 3. **+14165550412** — Toronto, ON
> 4. **+14165550767** — Toronto, ON
> 5. **+14165550889** — Toronto, ON
>
> Which one should I buy? (1–5, or paste a different E.164)

If the user has a strong preference for digit patterns ("ends in 4321", "no 666"), respect it — the script can be re-run with a higher `--limit` to surface more options.

### 8. Live run — confirm cost with the chosen number

The live run **purchases the picked Twilio number** (~$1/month per number, real money charged to the shared Twilio account). Before running without `--dry-run`:

> Ready to provision **<Name>**. This will:
> - Buy **<chosen E.164>** (~$1/mo charged to the shared Twilio account)
> - Configure its voice webhook → `${BACKEND_URL}/voice`
> - Write `restaurants/<rid>` to Firestore
>
> Confirm to proceed (yes / no)?

A "yes" earlier in the same session does **not** carry forward — re-confirm every time. Once confirmed:

```bash
python -m scripts.provision_restaurant \
  --rid <rid> \
  --name "<Name>" \
  --display-phone <+1XXXXXXXXXX> \
  --address "<Address>" \
  --hours "<Hours>" \
  --phone-number <chosen E.164> \
  --menu-file restaurants/<rid>.json
```

Note `--phone-number` (not `--area-code`) — this buys the specific number the user picked rather than re-searching.

Required env for the live run:

- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` — fetch via `/shared-creds` if not in `.env`
- `BACKEND_URL` — current Cloud Run URL (e.g. `https://niko-ciyyvuq2pq-uc.a.run.app`)
- `GOOGLE_CLOUD_PROJECT=niko-tsuki`, `GOOGLE_APPLICATION_CREDENTIALS` — Firestore auth

If `BACKEND_URL` isn't set, ask the user — there's no auto-discovery.

### 8. Hand off

After a successful live run, surface to the user:

```
✔ Provisioned <Name>
  rid:           <rid>
  twilio_phone:  +1XXXXXXXXXX  ← restaurant forwards their existing line here
  display_phone: +1XXXXXXXXXX
  menu file:     restaurants/<rid>.json (commit this)

Next steps:
  - Forward inbound calls on <display_phone> → <twilio_phone>
  - Place a test call to <twilio_phone>
  - Open a PR with the new menu file
```

If we're on `master` when this finished, kick into `/pr-driven-dev` rescue flow before committing the menu file.

## Hard rules

- **Never** run the provision script without `--dry-run` first.
- **Never** run the live (number-buying) step without explicit user confirmation in this session — a prior "yes" doesn't carry across runs.
- **Never** commit `.env` files or Twilio credentials to the menu JSON or anywhere else. Use `/shared-creds` to fetch creds; they belong in `.env` only.
- **Never** invent menu items, prices, hours, or addresses. If you can't find it, ask. A wrong price quoted on a real call is worse than a delayed onboarding.
- **Never** reuse an existing `rid`. Before writing, check: `gh api -X GET "/repos/tsuki-works/niko/contents/restaurants" 2>/dev/null` or `ls restaurants/` and refuse if `<rid>.json` already exists. If the user wants to overwrite, they must say so explicitly.
- **Never** skip the candidate-listing step (`list_twilio_numbers.py`) and let the provision script auto-pick the first available number. The whole point of the two-step flow is human choice over which digits we lock in.

## Common gotchas

- **Image-only menus.** Most independent restaurants post their menu as a JPG/PDF. The OCR step is a manual paste from the user — don't try to OCR yourself.
- **Third-party ordering widgets.** ChowNow, Toast, DoorDash often have the structured menu. Follow redirects once. If the widget is a JS iframe, ask for the direct ordering URL.
- **Multi-location chains.** The skill onboards **one tenant** at a time — one phone number, one address. If the site lists 5 locations, ask which one.
- **Non-NANP phone numbers.** The provision script searches Twilio's CA inventory first, then falls back to US. If the restaurant is outside CA/US, this skill doesn't currently work — surface that and stop.
- **`pizzas`-only prompt rendering** — see step 3. Onboarding many non-pizza restaurants will eventually require generalizing `app/llm/prompts.py`.

## Output template (what to show the user when starting)

```
Onboarding from <URL>

Found:
  ✓ Name:          <name>
  ✓ Phone:         <phone>
  ? Address:       <best-guess or ✗ missing>
  ? Hours:         <best-guess or ✗ missing>
  ? Menu:          <N items across X categories | ✗ image-only — needs paste>

Need from you:
  - <gap 1>
  - <gap 2>

Once confirmed I'll write `restaurants/<rid>.json`, dry-run the provision script, and ask once more before buying the Twilio number.
```
