# Basic Error Recovery — Caller Corrections (Design Spec)

**Date:** 2026-04-28
**Sprint:** 2.2 — Order Taking Excellence (#5)
**Tracking issue:** #103
**Owner:** Meet
**Status:** Approved — ready for implementation plan

## Goal

When a caller corrects something the AI already captured in the order, niko emits a single `update_order` call carrying the corrected full state. The order in Firestore matches what the caller actually intends.

## In scope (six correction patterns)

1. **Remove item** — "take off the Coke" / "remove the second pizza"
2. **Substitute item** — "change the Margherita to a calzone" / "I meant pepperoni, not Margherita"
3. **Quantity change** — "make that 2, not 1"
4. **Size change** — "I said large, not medium"
5. **Order-type swap** — "actually make that delivery" / "switch to pickup"
6. **Delivery-address fix** — "no, my address is 14, not 40"

## Out of scope

- **Full reset / "cancel everything, start over."** Status `cancelled` already exists for whole-call cancellations; a mid-call full restart is a bigger UX call deferred to a later slice.
- **Misheard-item recovery from STT errors.** Belongs to Kailash/Sandeep call-quality work (#82, #83).
- **New tool affordances** (`remove_item`, `change_item`, `clear_order`). The existing `update_order` already takes the FULL current order state each turn — every correction in scope is expressible without new tools. New tools are a possible follow-up if real-call data shows prompt-only is insufficient.
- **Server-side validation of LLM diffs** (e.g. detecting "added on top instead of replaced"). Defer until we have real-call signal that motivates it.
- **"Caller asks to remove an item that isn't in the order"** handling. Worth a follow-up tuning pass once we have real-call data; not specified in this slice.

## Approach

**Pure prompt extension.** Add a new `Caller corrections:` block to `_PREAMBLE` in `app/llm/prompts.py`, placed **after the existing `Item customizations:` block and before `Order confirmation read-back:`**. No new code paths, no new tools, no schema changes.

The existing `update_order` tool already takes the FULL current order state each turn (see tool description: "Emit the FULL current order state each time, not a diff"). Every correction in scope is expressible by emitting a new full state. The risk is that Haiku, faced with a correction, emits the corrected item *alongside* the wrong one instead of replacing it — the prompt's job is to make the "replace, don't add" rule explicit.

### Why prompt-only over alternatives

- **Prompt + server-side guardrails** (defensive logic in `_apply_update`): tempting, but logging anomalies without acting on them adds noise; we should let real-call signal motivate this.
- **New tools** (`remove_item`, etc.): higher surface, more failure modes, more tests. Premature for "basic" recovery.

## Prompt rule additions

New section to insert into `_PREAMBLE`:

```
Caller corrections:
- When the caller corrects something already in the order, emit ONE
  update_order with the FULL corrected state. Replace the wrong item —
  never leave it alongside the new one.
- Removals ("take off the Coke", "remove the second pizza"): emit
  update_order without that item.
- Substitutions ("change the Margherita to a calzone", "I meant
  pepperoni, not Margherita"): swap the item, carry the quantity through
  unless the caller restated it.
- Quantity or size changes ("make that 2", "I said large"): same item
  line with the new value — never duplicate the line. Use the menu's
  unit_price for the new size.
- Order-type swap to delivery: ask for the address before the next
  read-back. Swap to pickup: clear delivery_address.
- Delivery-address fix: send the full corrected address, not a partial.
- After a correction, briefly acknowledge what changed in one short
  phrase ("Replaced with a large.", "Two now.") — do NOT re-read the
  whole order; that happens at the confirmation step.
```

## Test plan

### Layer 1 — unit tests against `_apply_update`

Cheap, deterministic, no API. Add cases to `tests/test_llm_client.py` asserting that, given a starting order and an `update_order` payload representing each correction, the resulting `Order` matches expectation. Most of these likely already pass — `_apply_update` does a full overwrite — so this layer **locks in** existing behavior so we don't regress.

| # | Initial order | Correction payload | Expected end state |
|---|---|---|---|
| 1 | `[Margherita L, Coke]` | `[Margherita L]` | Coke gone |
| 2 | `[Margherita L]` | `[Calzone L]` | Substituted |
| 3 | `[Margherita L ×1]` | `[Margherita L ×2]` | Quantity bumped, no dupe |
| 4 | `[Margherita M $12.99]` | `[Margherita L $14.99]` | Size + unit_price swapped |
| 5 | `[Margherita L]` `order_type=delivery` `address="14 X"` | same items, `order_type=pickup`, `delivery_address=null` | Type swapped, address cleared |
| 6 | `delivery_address="40 Main St"` | `delivery_address="14 Main St"` | Full overwrite |

### Layer 2 — live-Haiku transcript regression suite (gated)

Layer 1 proves the *code* handles correct payloads. It cannot prove the *prompt* causes Haiku to emit those payloads. Add a marker-gated suite:

- Marker: `@pytest.mark.live_llm` — skipped in CI by default; runnable locally and pre-merge with `pytest -m live_llm`.
- Fixture catalog: `tests/fixtures/correction_transcripts.py` listing one scripted caller turn per correction pattern, paired with an expected end-state `Order`.

This catalog becomes the **regression suite** — every new correction bug found later gets added as a row, and the prompt cannot regress on it.

### Layer 3 — prompt rendering test

One test in `tests/test_prompts.py` asserting the new `Caller corrections:` section appears in the output of `build_system_prompt` for a representative restaurant fixture.

## Done criteria

- All Layer 1 unit tests green
- All 6 Layer 2 live-Haiku transcripts pass when run with `pytest -m live_llm` (verified once locally, captured in PR description)
- Layer 3 rendering test green
- One end-to-end test call placed by hand against the live deploy: caller substitutes one item *and* changes order type to delivery; both reflect correctly in the dashboard
- `niko-reviewer` sign-off (multi-tenant safety, prompt clarity, no regression in voice tone)

## Risks and mitigations

- **Risk:** Haiku ignores the new rule under voice-call latency pressure and still ships duplicate items. **Mitigation:** Layer 2 catches this pre-merge; if observed, escalate to Approach B (server-side guardrails) in a follow-up.
- **Risk:** New prompt block bloats token count and increases first-token latency. **Mitigation:** the block is ~10 lines; system-prompt tokens are cached server-side by Anthropic on warm calls; net latency impact should be negligible. Measure on the e2e test call.
- **Risk:** Order-type swap to delivery without an address yet creates an inconsistent state if the caller hangs up before answering. **Mitigation:** the prompt instructs Haiku to ask for address *before the next read-back*; the existing confirmation flow blocks `status="confirmed"` without a coherent order, so a hangup leaves the order in `in_progress` (correct).

## Files touched (anticipated)

- `app/llm/prompts.py` — new `Caller corrections:` block in `_PREAMBLE`
- `tests/test_llm_client.py` — six new unit cases
- `tests/test_prompts.py` — one new rendering case
- `tests/fixtures/correction_transcripts.py` — new (Layer 2 catalog)
- `tests/test_llm_integration.py` — wire the Layer 2 catalog through with `@pytest.mark.live_llm`
