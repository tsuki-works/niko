# Pickup vs. Delivery Flow (Design Spec)

**Date:** 2026-04-28
**Sprint:** 2.2 — Order Taking Excellence (#5)
**Tracking issue:** #105
**Owner:** Meet
**Status:** Approved — ready for implementation plan

## Goal

Make the pickup-vs-delivery flow correct end-to-end:
- Each restaurant declares whether it offers delivery; the system prompt branches accordingly.
- When delivery is requested, the captured address must be non-empty and contain at least one digit; bad addresses are rejected with feedback to Haiku to re-ask.
- The order confirmation read-back includes the delivery address verbatim when `order_type=delivery`.

## In scope

1. **Schema:** add `offers_delivery: bool = True` to `Restaurant`.
2. **Prompt rendering:** `app/llm/prompts.py` branches on `offers_delivery`. False → soft-pivot to pickup; True → existing flow plus an explicit address-readback rule.
3. **Server-side validator:** new `app/orders/validation.py` exposing `validate_delivery_address(addr: str | None) -> bool`. Returns `True` iff `addr.strip()` is non-empty and contains at least one digit.
4. **`_apply_update` integration:** when an `update_order` payload sets `delivery_address`, run the validator. If invalid, *discard the address from the patch* (the previous `delivery_address` — `None` or last-good — stays). The tool_result string includes `"Delivery address incomplete — please ask the caller for the full street address."` so Haiku re-asks on the next turn. Mirrors the existing pattern of feeding server-verified state back to the model.
5. **Read-back rule:** when `order_type=delivery`, the order confirmation read-back must include the delivery address verbatim.

## Out of scope

- **Address geocoding / distance / delivery zones.** No third-party geocoder dependency. Validation is purely "non-empty + has a digit".
- **Per-restaurant alternative-platform suggestion** ("we don't deliver, try DoorDash"). Would need a per-tenant config field; defer until a real restaurant asks.
- **Dashboard UI for editing `offers_delivery`.** Sprint 2.4 territory. Owner edits Firestore directly until then.
- **`offers_pickup` flag.** Pickup is always assumed available. If a ghost-kitchen tenant onboards (delivery-only), add the second flag in 30 seconds.
- **`/onboard-restaurant` skill changes.** Defaults to `True`; the skill flow doesn't ask. Owner toggles in Firestore.
- **Migration / backfill.** Pydantic default `True` covers existing Firestore docs (Niko Pizza Kitchen, Twilight Family Restaurant) on read.

## Approach

**Server-side state validation in `_apply_update`** with a single dedicated validator function. The validator stays small and pure (string in → bool out); `_apply_update` does the orchestration (drop the bad value, set the rejection message). The existing `tool_result` feedback pattern (post-apply subtotal) extends naturally to "post-apply address acceptance signal" — same loop, same shape.

### Why server-side validation, not prompt-only

Voice transcription is messy. Prompts can ask Haiku to validate, but across hundreds of calls the rule will leak. A deterministic server check rejects the bad payload regardless of what Haiku does, and the tool_result feedback gives Haiku a clean, structured signal to re-ask.

### Why a single boolean (not enum / multi-flag)

We have a known one-axis variation (does this restaurant deliver?) and zero current need for delivery-only tenants. Adding `offers_pickup` now is YAGNI. The schema can grow when a real ghost kitchen onboards.

## Schema changes

### `app/restaurants/models.py`

Add one field to `Restaurant`:

```python
offers_delivery: bool = True
```

Default `True` matches current behavior for the two existing tenants. No migration needed.

### `app/orders/validation.py` (NEW)

```python
"""Server-side validators for order field shapes (Sprint 2.2 #105).

Pure functions: input → bool. Orchestration (rejecting payloads,
shaping tool_result feedback) lives in _apply_update, not here.
"""

from __future__ import annotations


def validate_delivery_address(addr: str | None) -> bool:
    """A delivery address is acceptable if it is non-empty after
    stripping whitespace AND contains at least one digit.

    Voice transcription is noisy: callers say partial addresses
    ("14 Main"), Deepgram drops words, garbage like "uhh" gets
    captured. This is the minimum bar to filter clearly-broken
    captures without rejecting realistic short addresses. Geocoder-
    grade validation is out of scope.
    """
    if addr is None:
        return False
    stripped = addr.strip()
    if not stripped:
        return False
    return any(ch.isdigit() for ch in stripped)
```

### `app/llm/client.py`

In `_apply_update`, after the existing patch is computed but before it's merged:

- If the patch contains `delivery_address` and it fails `validate_delivery_address`, drop that key from the patch (the existing value — `None` or last-good — stays).
- Track whether the address was rejected so the caller can construct the appropriate `tool_result` string.

In `_summarize_order` (or a small wrapper around the existing tool_result construction), when an address rejection happened, append: `" Delivery address incomplete — please ask the caller for the full street address."` to the existing summary string. The subtotal summary stays intact; the rejection note is additional.

The exact glue (whether `_apply_update` returns a tuple `(Order, was_address_rejected)` or sets a flag in a different way) is an implementation detail for the plan.

## Prompt changes

### `_PREAMBLE` becomes branched on `offers_delivery`

Most of `_PREAMBLE` is identical across both branches. Two paragraphs differ:

**Intro line:**
- True: `"Place a pickup or delivery order from the menu below."`
- False: `"Place a pickup order from the menu below."`

**Conversation flow / address line:**
- True: `"If delivery, collect the caller's delivery address."` (existing)
- False: a new line replaces it: `"If the caller asks for delivery, say something like 'We're actually pickup-only — would pickup work for you?' and continue from there. Do not capture a delivery address; do not set order_type to delivery."`

The corrections block's "Order-type swap to delivery" rule is also conditionally suppressed when `offers_delivery=False`. Easiest implementation: render that bullet only when delivery is offered.

### Universal addition (both branches): address read-back

Append to the existing `Order confirmation read-back:` block (after the existing item-readback rules, before the "Use the subtotal returned by the update_order tool" rule):

> `"If order_type is delivery, also read the delivery address back as part of the summary. Example: '...for delivery to fourteen Main Street — your total is twenty-one ninety-nine. Does that sound right?'"`

This makes the address an explicit verification step. Avoids the failure mode where the read-back covers items + total but the address goes unconfirmed.

## Test plan

### Layer 1 — Unit tests (deterministic, no API)

**`tests/test_validation.py` (NEW)** — table-driven test for `validate_delivery_address`:

| Input | Expected |
|---|---|
| `"14 Main"` | True |
| `"Apartment 3"` | True |
| `"123"` | True |
| `"14 Spadina Ave"` | True |
| `"uhh"` | False |
| `""` | False |
| `"   "` | False |
| `None` | False |
| `"."` | False |
| `"Main Street"` (no digit) | False |

**`tests/test_llm_client.py`** — characterization test:
- Seed `Order(call_sid="CAtest", order_type=DELIVERY, delivery_address="14 Main")`. Apply a patch with `delivery_address="uhh"`. Assert the resulting Order's `delivery_address` is still `"14 Main"` (rejected) and the rejection message appears in the constructed tool_result.

**`tests/test_prompts.py`** — two new rendering tests:
1. `test_prompt_renders_delivery_offered_branch` — restaurant with `offers_delivery=True` (default). Assert prompt contains `"pickup or delivery"` and the address-readback instruction. Assert it does NOT contain `"pickup-only"`.
2. `test_prompt_renders_pickup_only_branch` — restaurant with `offers_delivery=False`. Assert prompt contains `"pickup-only"` and the soft-pivot phrasing. Assert it does NOT contain `"If delivery, collect"`.

### Layer 2 — Live-Haiku regression (gated)

Add a new fixture catalog `tests/fixtures/delivery_transcripts.py` with 3 scenarios. Use the same `CorrectionScenario` dataclass and runner pattern as `correction_transcripts.py` (rename or generalize the dataclass to `Scenario` if both files end up sharing it; otherwise duplicate is fine).

| Scenario id | Tenant config | Initial turns | Trigger turn | Assertion |
|---|---|---|---|---|
| `delivery_address_complete` | `offers_delivery=True` | (none) | `"I'd like a large margherita for delivery to 14 Spadina Avenue."` | order ends with `order_type=delivery`, `delivery_address` contains "14" and "Spadina" |
| `delivery_address_uhh_then_real` | `offers_delivery=True` | `"Large margherita for delivery."` | First trigger: `"My address is uhh."` (Haiku should re-ask per validator feedback). Then second trigger: `"14 Spadina Avenue."` | order ends with `delivery_address` containing "14" and "Spadina"; address is NOT "uhh" |
| `pickup_only_soft_pivot` | `offers_delivery=False` | (none) | `"Can I get a large margherita for delivery?"` | order ends with `order_type=pickup`; `delivery_address` is None |

The third scenario needs a tenant fixture variant — add a `_DEMO_PICKUP_ONLY_RESTAURANT` alongside the existing `_DEMO_RESTAURANT` in `tests/test_llm_integration.py` (or in the new fixture file), built with `offers_delivery=False`.

The "uhh-then-real" scenario is multi-turn: it tests that the validator's tool_result feedback actually causes Haiku to re-ask, then accepts the corrected address.

### Layer 3 — Manual e2e (pre-merge)

1. Place a real call to a delivery-supporting tenant (Twilight, default `offers_delivery=True`). Order an item, ask for delivery, give a real-style address. Verify the dashboard shows `order_type=delivery` and the address.
2. Toggle `offers_delivery=False` on Twilight in Firestore. Place a real call, ask for delivery. Verify Haiku soft-pivots, the order persists as pickup, no `delivery_address` is set. Revert the Firestore toggle after.

## Done criteria

- All Layer 1 unit tests green (validator table + `_apply_update` characterization + both prompt branches)
- All 3 Layer 2 live transcripts pass with `pytest -m live_llm`
- Both Layer 3 manual checks pass; results captured in PR description
- `niko-reviewer` sign-off (multi-tenant safety, no secret leakage, no call-quality regression in either branch)
- Sprint 2.2 (#5) checklist updated to mark "Pickup vs delivery flow" done

## Risks and mitigations

- **Risk:** Haiku ignores the rejection feedback and confirms the order with the bad address still in state. **Mitigation:** the validator drops the bad address before it lands; even if Haiku misreads the tool_result, `is_ready_to_confirm()` blocks delivery confirmation when `delivery_address is None`. Worst case: Haiku has to ask again.
- **Risk:** the rejection message bloats every tool_result on every turn. **Mitigation:** the message is only appended when an address rejection actually happened — non-delivery flows and successful delivery flows see the existing summary unchanged.
- **Risk:** branching `_PREAMBLE` makes the prompt builder harder to read. **Mitigation:** keep both branches in `_PREAMBLE` as one f-string with a small ternary on the differing lines, or extract a `_render_intro_line(restaurant)` helper. The diff stays small.
- **Risk:** existing tests assume `offers_delivery=True` implicit behavior; adding the field could break them. **Mitigation:** Pydantic default `True` preserves current semantics. Existing prompt tests should still pass — the address-readback rule is additive, the intro line is unchanged for delivery-supporting tenants.

## Files touched (anticipated)

- `app/restaurants/models.py` — add `offers_delivery: bool = True`
- `app/orders/validation.py` — NEW
- `app/llm/client.py` — `_apply_update` calls validator; tool_result construction adds rejection message when applicable
- `app/llm/prompts.py` — branch on `offers_delivery` in `_PREAMBLE`; add address-readback instruction in the read-back block
- `tests/test_validation.py` — NEW
- `tests/test_llm_client.py` — one new characterization test
- `tests/test_prompts.py` — two new rendering tests
- `tests/fixtures/delivery_transcripts.py` — NEW (3 live scenarios)
- `tests/test_llm_integration.py` — load the new fixture catalog under `@pytest.mark.live_llm`; add `_DEMO_PICKUP_ONLY_RESTAURANT` if scoping allows in this file (otherwise put it in the fixture file)
