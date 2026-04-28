# Pickup vs. Delivery Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Branch the system prompt on a new `Restaurant.offers_delivery` flag, validate captured delivery addresses server-side (non-empty + ≥1 digit), reject invalid addresses with feedback to Haiku to re-ask, and require the read-back to include the delivery address verbatim.

**Architecture:** Six layered tasks, mostly TDD. New pure validator (`app/orders/validation.py`) called from a new `_apply_validation` helper in the LLM client *before* `_apply_update` runs — keeps `_apply_update` as a dumb dict-merger and concentrates orchestration in the LLM client. Schema gets a single `offers_delivery: bool = True` field. Prompt branches in `build_system_prompt`. Three live-Haiku scenarios prove the validator-feedback loop closes.

**Tech Stack:** Python 3.12, Pydantic v2 (Restaurant + Order models), pytest, Anthropic SDK (Haiku 4.5).

**Spec:** `docs/superpowers/specs/2026-04-28-pickup-delivery-design.md`
**Tracking issue:** [#105](https://github.com/tsuki-works/niko/issues/105)
**Branch:** `feat/105-pickup-delivery` (already created; spec already committed at `e1e68bd`)

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `app/orders/validation.py` | Create | Pure `validate_delivery_address(addr) -> bool` — no orchestration |
| `app/restaurants/models.py` | Modify | Add `offers_delivery: bool = True` to `Restaurant` |
| `app/llm/prompts.py` | Modify | Branch `_PREAMBLE` on `offers_delivery`; add address-readback rule (universal) |
| `app/llm/client.py` | Modify | New `_apply_validation(patch) -> (cleaned_patch, list[str])` helper; call it before `_apply_update` in both `generate_reply` and `stream_reply`; append rejection messages to tool_result |
| `tests/test_validation.py` | Create | Table-driven tests for the validator |
| `tests/test_restaurants_storage.py` | Modify | Tiny test that `Restaurant` defaults `offers_delivery=True` |
| `tests/test_prompts.py` | Modify | Two new rendering tests (`offers_delivery=True` and `offers_delivery=False` branches) |
| `tests/test_llm_client.py` | Modify | One characterization test: bad delivery address is dropped + tool_result carries rejection message |
| `tests/fixtures/delivery_transcripts.py` | Create | 3 live-Haiku scenarios (reuses `CorrectionScenario` from `correction_transcripts.py`) |
| `tests/test_llm_integration.py` | Modify | Add `_DEMO_PICKUP_ONLY_RESTAURANT` fixture; parametrized live test consuming the new catalog, gated on `@pytest.mark.live_llm` |

Files split by responsibility, not technical layer: validator is its own pure module so it stays testable and independently reusable; the LLM client owns orchestration; prompt content lives next to the prompt builder.

---

## Task 1: Validator — `validate_delivery_address`

**Files:**
- Create: `app/orders/validation.py`
- Create: `tests/test_validation.py`

- [ ] **Step 1: Write the failing test file**

Create `tests/test_validation.py` with this content:

```python
"""Unit tests for app.orders.validation (Sprint 2.2 #105)."""

import pytest

from app.orders.validation import validate_delivery_address


@pytest.mark.parametrize(
    "addr, expected",
    [
        # Acceptable: non-empty + has at least one digit
        ("14 Main", True),
        ("Apartment 3", True),
        ("123", True),
        ("14 Spadina Ave", True),
        ("  14 Spadina  ", True),  # surrounding whitespace tolerated
        # Rejected: empty, whitespace-only, missing digit, garbage
        ("", False),
        ("   ", False),
        (None, False),
        (".", False),
        ("uhh", False),
        ("Main Street", False),  # no digit
        ("yes that's right", False),  # no digit
    ],
)
def test_validate_delivery_address(addr, expected):
    assert validate_delivery_address(addr) is expected
```

- [ ] **Step 2: Run to verify it fails on import**

Run: `python -m pytest tests/test_validation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.orders.validation'`.

- [ ] **Step 3: Implement the validator**

Create `app/orders/validation.py` with this content:

```python
"""Server-side validators for order field shapes (Sprint 2.2 #105).

Pure functions: input → bool. Orchestration (rejecting payloads,
shaping tool_result feedback) lives in the LLM client, not here.
"""

from __future__ import annotations


def validate_delivery_address(addr: str | None) -> bool:
    """A delivery address is acceptable iff it is non-empty after
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

- [ ] **Step 4: Run to verify all 12 cases pass**

Run: `python -m pytest tests/test_validation.py -v`
Expected: 12 PASSED.

- [ ] **Step 5: Commit**

```bash
git add app/orders/validation.py tests/test_validation.py
git commit -m "Add validate_delivery_address validator (#105)

Pure function: non-empty stripped + at least one digit. Server-side
filter for clearly-broken delivery addresses captured from noisy voice
transcription. Doesn't try to be a geocoder; just the minimum bar to
reject 'uhh' / '' / 'Main Street' without rejecting '14 Main' or
'Apartment 3'."
```

---

## Task 2: Schema — `Restaurant.offers_delivery`

**Files:**
- Modify: `app/restaurants/models.py:78-80` (insert new field after `forwarding_mode`)
- Modify: `tests/test_restaurants_storage.py` (append a small test at the end of the file)

- [ ] **Step 1: Write the failing test**

Append this function to the END of `tests/test_restaurants_storage.py`:

```python
def test_restaurant_offers_delivery_defaults_to_true():
    """Sprint 2.2 #105 — every restaurant offers delivery unless explicitly
    flagged off. Default True preserves current behavior for existing
    Firestore docs, no migration needed."""
    r = Restaurant(
        id="t",
        name="T",
        display_phone="+10000000000",
        twilio_phone="+10000000001",
        address="-",
        hours="-",
    )
    assert r.offers_delivery is True

    r_off = Restaurant(
        id="t",
        name="T",
        display_phone="+10000000000",
        twilio_phone="+10000000001",
        address="-",
        hours="-",
        offers_delivery=False,
    )
    assert r_off.offers_delivery is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_restaurants_storage.py::test_restaurant_offers_delivery_defaults_to_true -v`
Expected: FAIL with `AttributeError` on `r.offers_delivery` (or pydantic complains the kwarg is unknown).

- [ ] **Step 3: Add the field to `Restaurant`**

In `app/restaurants/models.py`, find this section (currently at lines ~76-80):

```python
    # Informational only — we don't enforce it. Tracks how the restaurant
    # configured their carrier-level forwarding so onboarding/support can
    # answer "why are calls landing here?".
    forwarding_mode: str = "always"
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)
```

Replace with (insert `offers_delivery` immediately after `forwarding_mode`):

```python
    # Informational only — we don't enforce it. Tracks how the restaurant
    # configured their carrier-level forwarding so onboarding/support can
    # answer "why are calls landing here?".
    forwarding_mode: str = "always"
    # Whether this tenant accepts delivery orders. Default True preserves
    # current behavior for existing Firestore docs (Niko Pizza Kitchen,
    # Twilight Family Restaurant). Flip to False in Firestore for
    # pickup-only restaurants — the system prompt branches accordingly.
    offers_delivery: bool = True
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)
```

- [ ] **Step 4: Verify the test passes + no regressions**

Run: `python -m pytest tests/test_restaurants_storage.py -v`
Expected: all tests PASS (the new test + every existing one).

Run: `python -m pytest tests/ -v --ignore=tests/test_llm_integration.py 2>&1 | tail -5`
Expected: full non-live suite green.

- [ ] **Step 5: Commit**

```bash
git add app/restaurants/models.py tests/test_restaurants_storage.py
git commit -m "Add Restaurant.offers_delivery flag (#105)

Default True preserves current behavior — no migration needed for
existing Firestore docs. Pickup-only tenants flip to False in
Firestore; the system prompt and address-validation flow will branch
on this in subsequent commits."
```

---

## Task 3: Prompt branching + address read-back

**Files:**
- Modify: `app/llm/prompts.py` (multiple lines in `_PREAMBLE` + render-time conditional)
- Modify: `tests/test_prompts.py` (append two tests at the end)

- [ ] **Step 1: Write the two failing rendering tests**

Append these two functions to the END of `tests/test_prompts.py`:

```python
def test_prompt_renders_delivery_offered_branch():
    """Sprint 2.2 #105 — when offers_delivery=True (default), the prompt
    presents both pickup and delivery as options and instructs Haiku to
    collect the address when delivery is chosen + read it back at
    confirmation."""
    restaurant = _demo()
    assert restaurant.offers_delivery is True
    prompt = build_system_prompt(restaurant)
    lower = prompt.lower()
    # Delivery is offered
    assert "pickup or delivery" in lower
    # Address is collected
    assert "if delivery, collect the caller's delivery address" in lower
    # Address is read back at confirmation
    assert "if order_type is delivery" in lower
    assert "read the delivery address back" in lower
    # Pickup-only language is NOT present
    assert "pickup-only" not in lower


def test_prompt_renders_pickup_only_branch():
    """Sprint 2.2 #105 — when offers_delivery=False, the prompt frames
    the restaurant as pickup-only and tells Haiku to soft-pivot when
    callers ask for delivery."""
    restaurant = Restaurant(
        id="t",
        name="Pickup-Only Place",
        display_phone="+10000000000",
        twilio_phone="+10000000001",
        address="1 Test St",
        hours="11am-9pm",
        menu={"mains": [{"name": "Burger", "price": 10.00}]},
        offers_delivery=False,
    )
    prompt = build_system_prompt(restaurant)
    lower = prompt.lower()
    # Pickup-only framing is present
    assert "pickup order" in lower or "pickup-only" in lower
    # Soft-pivot instruction
    assert "we're actually pickup-only" in lower
    assert "would pickup work for you" in lower
    # The "If delivery, collect the caller's delivery address" line is gone
    assert "if delivery, collect the caller's delivery address" not in lower
    # Haiku is told not to set delivery type
    assert "do not capture a delivery address" in lower
```

- [ ] **Step 2: Run to verify both fail**

Run: `python -m pytest tests/test_prompts.py::test_prompt_renders_delivery_offered_branch tests/test_prompts.py::test_prompt_renders_pickup_only_branch -v`
Expected: BOTH FAIL — the first because the address-readback string isn't in the prompt yet, the second because the pickup-only branch doesn't exist.

- [ ] **Step 3: Modify `_PREAMBLE` and `build_system_prompt`**

The strategy: keep `_PREAMBLE` as one f-string-style template with two placeholders (`{intro_line}` and `{delivery_handling}`) that vary by branch, plus an unconditional `{address_readback}` block that always renders. Render the right values in `build_system_prompt`.

In `app/llm/prompts.py`:

#### Step 3a — Replace `_PREAMBLE` definition

Find the existing `_PREAMBLE = dedent("""\\` block (starts at line 20). Replace the entire `_PREAMBLE` variable definition with:

```python
_PREAMBLE = dedent("""\
    You are niko, a friendly voice ordering agent answering the phone for {restaurant}.
    Your words are synthesized into audio, so:

    - Keep replies short — usually one or two sentences.
    - No markdown, lists, bullet points, or emojis.
    - Speak naturally, like a real person on the phone.
    - Read prices as words ("twelve ninety-nine"), not digits.

    Help callers with two things:
    1. {intro_line}
    2. Answer quick questions about hours, menu items, or location.

    Conversation flow:
    - Greet the caller briefly and ask how you can help.
    - Identify intent — ordering, question, or something else.
    - If ordering, walk through item, size, and quantity.
    {delivery_handling}

    Item customizations:
    - After the caller picks an item and size, ask once whether they have
      any customizations ("Any modifications — extra cheese, no onions?").
    - If they say no or give nothing, move on — do not ask again.
    - Accept any free-text customization; capture it exactly as stated.
      Do not validate against a fixed list and do not invent customizations
      the caller did not request.
    - Contradictory modifiers ("no cheese, extra cheese"): ask to clarify
      once before recording. Do not record both.
    - Mid-sentence mods ("...and make that one without onions"): capture
      them exactly as if stated separately.
    - If a requested modifier does not make sense for the item (e.g. "extra
      anchovies on a milkshake"), politely decline it once and ask if they
      meant something else. Do not record a nonsensical modifier.

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
    {order_type_swap_rule}
    - Delivery-address fix: send the full corrected address, not a partial.
    - After a correction, briefly acknowledge what changed in one short
      phrase ("Replaced with a large.", "Two now.") — do NOT re-read the
      whole order; that happens at the confirmation step.

    Order confirmation read-back:
    - Before asking for confirmation, read back every item with its
      quantity, size (if applicable), and any modifications. For example:
      "So that's one large Margherita with extra cheese and no basil, and
      one Coke — your total is twenty-one ninety-nine. Does that sound right?"
    - If order_type is delivery, also read the delivery address back as
      part of the summary. Example: "...for delivery to fourteen Main
      Street — your total is twenty-one ninety-nine. Does that sound right?"
    - Use the subtotal returned by the update_order tool — never compute
      it yourself from unit prices.
    - If an item has no modifications, omit the modifier clause entirely —
      do not say "no modifications."
    - If the caller corrects something mid-read-back, update via
      update_order and re-read the full corrected order before asking for
      confirmation again.
    - Only flip status="confirmed" and say the terminal goodbye after the
      caller explicitly confirms ("yes", "yep", "that's right", "sounds
      good") — not on a vague "uh huh" mid-conversation.

    Closing the call:
    - Once the caller has confirmed the summary (e.g. "yes that's right",
      "yep", "no that's it"), set the order's status to "confirmed" via
      update_order and say a brief, terminal goodbye like "Great, your
      order is in — see you soon!" or "Perfect, we'll have it ready —
      thanks for calling!"
    - CRITICAL: any time you say a wrap-up phrase like "your order is in",
      "we'll have it ready", "see you soon", or "thanks for calling", you
      MUST call update_order in the same turn with status="confirmed".
      Saying the goodbye without flipping status leaves the call hanging.
    - Do NOT ask another follow-up question after confirming. The call
      ends shortly after your goodbye.

    Restaurant address handling:
    - The "Address:" line in the menu is the restaurant's location. It's only
      for answering direct questions like "where are you?" or "what's your
      address?". Do NOT recite it during pickup wrap-ups — the caller knows
      which restaurant they called. End pickup confirmations with something
      generic like "we'll have it ready for you soon" instead.

    When you call the update_order tool:
    - Say a brief acknowledgement to the caller in plain text FIRST, then
      call the tool. For example: "One large Margherita coming up." then
      update_order(...). Never emit update_order before any spoken words —
      it delays audio and the caller thinks you stopped listening.

    If a caller asks for something off-menu, politely say you don't offer it and
    suggest a close alternative. If you're unsure what they said, ask them to
    repeat rather than guessing.

    When the caller hesitates or starts a sentence and trails off ("I'd like...",
    "uhhh", "I would also..."), DO NOT fill the silence with prompts like
    "take your time" or "I'm listening". Stay quiet and wait for them to finish
    their thought. Repeated reassurances on every micro-pause feel like the AI
    is rushing them. Only respond once they've actually finished speaking — a
    real sentence, not a fragment. The phrase you use when you do need to nudge
    is "take your time" — never "take your breath" or other variants.

    When you tell the caller their total, use the subtotal returned by the
    most recent update_order tool_result — never compute totals yourself from
    unit prices. The tool_result's "Subtotal: $X.XX" is the server-verified
    number; your math from memory will drift.
""")
```

(Three placeholders: `{restaurant}`, `{intro_line}`, `{delivery_handling}`, `{order_type_swap_rule}`. The address-readback paragraph is universal and is now baked in to the read-back block.)

#### Step 3b — Update `build_system_prompt` to fill the placeholders

Find the existing `build_system_prompt` function (currently at lines ~222-238). Replace it with:

```python
def build_system_prompt(restaurant: Restaurant) -> str:
    """Render the system prompt for one tenant.

    A ``greeting_addendum`` entry in ``restaurant.prompt_overrides`` is
    appended after the menu — used to inject restaurant-specific tone
    or quirks ("we're family-run since 1972", "ask about today's
    special") without forking the whole prompt.

    The intro / delivery-handling / corrections-block subsections branch
    on ``restaurant.offers_delivery``: pickup-only tenants get pickup-
    only framing and a soft-pivot rule when callers ask for delivery.
    """
    # Note: dedent() strips the common 4-space leading indent from the
    # _PREAMBLE template, so placeholder values must start at column 0
    # (the "- " bullet marker is at column 0 after dedent). Continuation
    # lines use 2-space indent to match the existing bullet style.
    if restaurant.offers_delivery:
        intro_line = "Place a pickup or delivery order from the menu below."
        delivery_handling = "- If delivery, collect the caller's delivery address."
        order_type_swap_rule = (
            "- Order-type swap to delivery: ask for the address before the next\n"
            "  read-back. Swap to pickup: clear delivery_address."
        )
    else:
        intro_line = "Place a pickup order from the menu below."
        delivery_handling = (
            "- If the caller asks for delivery, say something like\n"
            "  \"We're actually pickup-only — would pickup work for you?\"\n"
            "  and continue from there. Do not capture a delivery address;\n"
            "  do not set order_type to delivery."
        )
        order_type_swap_rule = (
            "- Order-type stays pickup. If the caller tries to switch to delivery,\n"
            "  decline politely (we're pickup-only)."
        )

    body = (
        _PREAMBLE.format(
            restaurant=restaurant.name,
            intro_line=intro_line,
            delivery_handling=delivery_handling,
            order_type_swap_rule=order_type_swap_rule,
        )
        + "\nMenu:\n"
        + _format_menu(restaurant)
    )
    addendum = restaurant.prompt_overrides.get("greeting_addendum")
    if addendum:
        body = f"{body}\n\n{addendum.strip()}"
    return body
```

- [ ] **Step 4: Run the new tests**

Run: `python -m pytest tests/test_prompts.py::test_prompt_renders_delivery_offered_branch tests/test_prompts.py::test_prompt_renders_pickup_only_branch -v`
Expected: BOTH PASS.

- [ ] **Step 5: Run the full prompts suite — no regressions**

Run: `python -m pytest tests/test_prompts.py -v`
Expected: all 16 tests PASS (14 pre-existing + 2 new).

If any pre-existing prompt test FAILS, investigate — the placeholder-substitution refactor may have changed the rendered text in a way that broke an existing assertion. Don't blindly update old tests; surface the failure.

- [ ] **Step 6: Commit**

```bash
git add app/llm/prompts.py tests/test_prompts.py
git commit -m "Branch system prompt on Restaurant.offers_delivery (#105)

Three rendering branches in build_system_prompt:
- intro line says 'pickup or delivery' vs 'pickup only'
- delivery handling line is the existing 'collect address' instruction
  for delivery-supporting tenants, replaced with a soft-pivot rule for
  pickup-only ones
- caller-corrections 'order-type swap' bullet adapts to whichever side
  the tenant supports

Universal addition (both branches): the order confirmation read-back
must include the delivery address verbatim when order_type is delivery.

Two rendering tests guard both branches against accidental regression."
```

---

## Task 4: Validator integration in `_apply_update`

**Files:**
- Modify: `app/llm/client.py` (new `_apply_validation` helper + thread it through `generate_reply` and `stream_reply`; tool_result construction grows a rejection branch)
- Modify: `tests/test_llm_client.py` (one new characterization test)

- [ ] **Step 1: Write the failing characterization test**

Append this function to the END of `tests/test_llm_client.py`:

```python
def test_correction_invalid_delivery_address_is_rejected_and_signaled():
    """Sprint 2.2 #105 — when Haiku ships an update_order patch whose
    delivery_address fails validation (non-empty + has a digit), the
    address is dropped from the patch (existing value stays) AND the
    tool_result string carries a rejection note so Haiku re-asks on
    the next turn."""
    order = Order(call_sid="CAtest")
    order = _apply_update(
        order,
        {
            "items": [
                {"name": "Margherita", "category": "pizza", "size": "large",
                 "quantity": 1, "unit_price": 19.99},
            ],
            "order_type": "delivery",
            "delivery_address": "14 Spadina Ave",
            "status": "in_progress",
        },
    )
    assert order.delivery_address == "14 Spadina Ave"

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        [
            FakeBlock(type="text", text="Got it, what's your address?"),
            FakeBlock(
                type="tool_use",
                id="toolu_bad_addr",
                name="update_order",
                input={
                    "items": [
                        {"name": "Margherita", "category": "pizza",
                         "size": "large", "quantity": 1, "unit_price": 19.99},
                    ],
                    "order_type": "delivery",
                    "delivery_address": "uhh",
                    "status": "in_progress",
                },
            ),
        ]
    )

    result = generate_reply(
        transcript="my address is uhh",
        history=[],
        order=order,
        system_prompt=_TEST_SYSTEM_PROMPT,
        client=fake_client,
    )

    # Bad address was REJECTED — previous good value stays.
    assert result.order.delivery_address == "14 Spadina Ave"
    # Tool_result that went back to Haiku carries the rejection note so
    # the model can re-ask on the next turn.
    last = result.history[-1]
    assert last["role"] == "user"
    assert last["content"][0]["type"] == "tool_result"
    assert "Delivery address incomplete" in last["content"][0]["content"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_llm_client.py::test_correction_invalid_delivery_address_is_rejected_and_signaled -v`
Expected: FAIL — the assertion `result.order.delivery_address == "14 Spadina Ave"` fails because today `_apply_update` accepts whatever Haiku ships (the address becomes `"uhh"`).

- [ ] **Step 3: Add `_apply_validation` and wire it into `generate_reply` and `stream_reply`**

In `app/llm/client.py`:

#### Step 3a — Add the import at top of file

Find this import block near the top:

```python
from app.config import settings
from app.orders.models import Order
```

Insert one line:

```python
from app.config import settings
from app.orders.models import Order
from app.orders.validation import validate_delivery_address
```

#### Step 3b — Add the `_apply_validation` helper

Find the `_apply_update` function (currently around line 222). Insert this NEW function immediately ABOVE `_apply_update`:

```python
_INVALID_ADDRESS_NOTE = (
    "Delivery address incomplete — please ask the caller for the full "
    "street address."
)


def _apply_validation(patch: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Filter an update_order patch through server-side validators.

    Returns a (cleaned_patch, rejection_notes) tuple:
    - cleaned_patch is a copy of patch with any field that failed
      validation removed (so the previous Order value stays put when
      the patch is applied).
    - rejection_notes is a list of human-readable strings to append to
      the tool_result so Haiku knows to re-ask the caller. Empty when
      every field passed validation.

    Today only delivery_address has a validator (Sprint 2.2 #105). New
    field validators slot in here so _apply_update stays a dumb
    dict-merger and orchestration stays in one place.
    """
    cleaned = dict(patch)
    notes: list[str] = []
    if "delivery_address" in cleaned:
        if not validate_delivery_address(cleaned["delivery_address"]):
            del cleaned["delivery_address"]
            notes.append(_INVALID_ADDRESS_NOTE)
    return cleaned, notes
```

#### Step 3c — Use it in `generate_reply`

Find this section in `generate_reply` (currently around line 282-288):

```python
    updated_order = order
    tool_results: list[dict[str, Any]] = []
    for tu in tool_uses:
        updated_order = _apply_update(updated_order, tu["input"])
        tool_results.append(
            _tool_result_block(tu["id"], _summarize_order(updated_order))
        )
```

Replace with:

```python
    updated_order = order
    tool_results: list[dict[str, Any]] = []
    for tu in tool_uses:
        cleaned_input, rejection_notes = _apply_validation(tu["input"])
        updated_order = _apply_update(updated_order, cleaned_input)
        summary = _summarize_order(updated_order)
        if rejection_notes:
            summary = summary + " " + " ".join(rejection_notes)
        tool_results.append(_tool_result_block(tu["id"], summary))
```

#### Step 3d — Use it in `stream_reply`

Find the analogous section in `stream_reply` (currently around line 372-378):

```python
    updated_order = order
    tool_results: list[dict[str, Any]] = []
    for tu in tool_uses:
        updated_order = _apply_update(updated_order, tu["input"])
        tool_results.append(
            _tool_result_block(tu["id"], _summarize_order(updated_order))
        )
```

Replace with:

```python
    updated_order = order
    tool_results: list[dict[str, Any]] = []
    for tu in tool_uses:
        cleaned_input, rejection_notes = _apply_validation(tu["input"])
        updated_order = _apply_update(updated_order, cleaned_input)
        summary = _summarize_order(updated_order)
        if rejection_notes:
            summary = summary + " " + " ".join(rejection_notes)
        tool_results.append(_tool_result_block(tu["id"], summary))
```

- [ ] **Step 4: Run the new test**

Run: `python -m pytest tests/test_llm_client.py::test_correction_invalid_delivery_address_is_rejected_and_signaled -v`
Expected: PASS.

- [ ] **Step 5: Run the full LLM client suite — no regressions**

Run: `python -m pytest tests/test_llm_client.py -v`
Expected: all 27 tests PASS (26 pre-existing + 1 new).

If any pre-existing test FAILS — particularly the 6 `test_correction_*` cases from #103 — the validation wire-through broke something. Investigate: is the validator wrongly rejecting an address that was always fine? Look at the tool_use payload in the failing test.

- [ ] **Step 6: Commit**

```bash
git add app/llm/client.py tests/test_llm_client.py
git commit -m "Reject invalid delivery addresses with tool_result feedback (#105)

New _apply_validation helper sits between Haiku's update_order payload
and _apply_update. Today it only checks delivery_address (via the
validator added in #105 task 1); fields that fail validation are
dropped from the patch, and a human-readable note is appended to the
tool_result so Haiku re-asks on the next turn. Same pattern as the
existing post-apply subtotal feedback.

_apply_update stays a dumb dict-merger; orchestration stays in the
LLM client.

Characterization test: bad address gets dropped, previous good value
stays, tool_result carries 'Delivery address incomplete'."
```

---

## Task 5: Live-Haiku regression catalog + parametrized test

**Files:**
- Create: `tests/fixtures/delivery_transcripts.py`
- Modify: `tests/test_llm_integration.py` (add `_DEMO_PICKUP_ONLY_RESTAURANT` fixture + a new parametrized live test)

- [ ] **Step 1: Create `tests/fixtures/delivery_transcripts.py`**

Create the file with this content. (Reuses `CorrectionScenario` from the sibling `correction_transcripts.py` module — same dataclass shape, no need to duplicate or rename.)

```python
"""Pickup vs delivery transcripts for the live-Haiku regression suite (#105).

Same scenario shape as tests/fixtures/correction_transcripts.py:
- ``initial_turns`` runs first to seed state.
- ``correction_transcript`` is the trigger turn (named for shape
  consistency with the sibling catalog; here it's the 'first delivery
  ask' or 'address attempt' turn).
- ``assert_end_state`` asserts the load-bearing fields on the final
  Order; pattern-specific, not full equality.

Three scenarios cover the three load-bearing behaviors:
1. delivery_address_complete — a valid address lands cleanly
2. delivery_address_uhh_then_real — invalid address is rejected, Haiku
   re-asks, valid address lands. Closes the validator-feedback loop.
3. pickup_only_soft_pivot — pickup-only tenant; caller asks for
   delivery; Haiku soft-pivots; final order is pickup with no address.
"""

from __future__ import annotations

from app.orders.models import Order, OrderType
from tests.fixtures.correction_transcripts import CorrectionScenario


def _assert_delivery_address_complete(final: Order) -> None:
    assert final.order_type is OrderType.DELIVERY, (
        f"Expected order_type=delivery; got {final.order_type}"
    )
    assert final.delivery_address is not None, "Expected an address"
    addr_lower = final.delivery_address.lower()
    assert "14" in addr_lower, (
        f"Expected captured address to contain '14'; got "
        f"{final.delivery_address!r}"
    )
    assert "spadina" in addr_lower, (
        f"Expected captured address to contain 'Spadina'; got "
        f"{final.delivery_address!r}"
    )


def _assert_uhh_then_real(final: Order) -> None:
    assert final.order_type is OrderType.DELIVERY, (
        f"Expected order_type=delivery; got {final.order_type}"
    )
    assert final.delivery_address is not None, (
        "Expected an address after the re-ask"
    )
    addr_lower = final.delivery_address.lower()
    assert "uhh" not in addr_lower, (
        f"'uhh' should have been rejected and replaced; got "
        f"{final.delivery_address!r}"
    )
    assert "14" in addr_lower, (
        f"Expected the corrected address to contain '14'; got "
        f"{final.delivery_address!r}"
    )


def _assert_pickup_only_soft_pivot(final: Order) -> None:
    assert final.order_type is OrderType.PICKUP, (
        f"Expected order_type=pickup; got {final.order_type}"
    )
    assert final.delivery_address in (None, ""), (
        f"Expected no delivery_address on pickup-only flow; got "
        f"{final.delivery_address!r}"
    )


# This catalog is consumed by the parametrized test in
# tests/test_llm_integration.py. Three scenarios ≈ ~10s each ≈ 30s total
# at live Haiku rates.
SCENARIOS: list[CorrectionScenario] = [
    CorrectionScenario(
        id="delivery_address_complete",
        initial_turns=[],
        correction_transcript=(
            "I'd like a large margherita for delivery to 14 Spadina Avenue."
        ),
        assert_end_state=_assert_delivery_address_complete,
    ),
    CorrectionScenario(
        id="delivery_address_uhh_then_real",
        initial_turns=[
            "Large margherita for delivery please.",
            "My address is uhh.",
        ],
        correction_transcript="14 Spadina Avenue.",
        assert_end_state=_assert_uhh_then_real,
    ),
    CorrectionScenario(
        id="pickup_only_soft_pivot",
        initial_turns=[],
        correction_transcript=(
            "Hi, can I get a large margherita for delivery please?"
        ),
        assert_end_state=_assert_pickup_only_soft_pivot,
    ),
]
```

- [ ] **Step 2: Verify the catalog imports cleanly**

Run: `python -c "from tests.fixtures.delivery_transcripts import SCENARIOS; print(len(SCENARIOS), [s.id for s in SCENARIOS])"`
Expected: prints `3 ['delivery_address_complete', 'delivery_address_uhh_then_real', 'pickup_only_soft_pivot']`.

DO NOT commit yet — Tasks 5 + 6 commit together.

- [ ] **Step 3: Add `_DEMO_PICKUP_ONLY_RESTAURANT` and the parametrized test to `tests/test_llm_integration.py`**

In `tests/test_llm_integration.py`:

#### Step 3a — Add the new fixture next to `_DEMO_RESTAURANT`

Find the existing `_DEMO_RESTAURANT = Restaurant(...)` definition (currently around line 30-72). Immediately AFTER its definition ends (after the closing parenthesis of the `Restaurant(...)` call), add:

```python
# Pickup-only variant: same menu, but offers_delivery=False so the
# system prompt branches into the soft-pivot flow. Used by the
# pickup_only_soft_pivot scenario in delivery_transcripts.py.
_DEMO_PICKUP_ONLY_RESTAURANT = _DEMO_RESTAURANT.model_copy(
    update={"offers_delivery": False}
)
_DEMO_PICKUP_ONLY_SYSTEM_PROMPT = build_system_prompt(_DEMO_PICKUP_ONLY_RESTAURANT)
```

#### Step 3b — Add the import for the new fixture

Find the existing top-of-file import line (added in #103/#104):

```python
from tests.fixtures.correction_transcripts import SCENARIOS, CorrectionScenario
```

Replace with (split into two imports for clarity, since the catalog names collide):

```python
from tests.fixtures.correction_transcripts import (
    SCENARIOS as CORRECTION_SCENARIOS,
    CorrectionScenario,
)
from tests.fixtures.delivery_transcripts import SCENARIOS as DELIVERY_SCENARIOS
```

Then update the existing parametrized test (`test_caller_correction_lands_in_final_order`) to use the renamed `CORRECTION_SCENARIOS`. Find this decorator/signature (currently around line 220):

```python
@pytest.mark.live_llm
@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_caller_correction_lands_in_final_order(scenario: CorrectionScenario):
```

Replace with:

```python
@pytest.mark.live_llm
@pytest.mark.parametrize(
    "scenario",
    CORRECTION_SCENARIOS,
    ids=[s.id for s in CORRECTION_SCENARIOS],
)
def test_caller_correction_lands_in_final_order(scenario: CorrectionScenario):
```

#### Step 3c — Add the new parametrized live test at the end of the file

Append at the very end of `tests/test_llm_integration.py`:

```python


# ---------------------------------------------------------------------------
# Pickup vs delivery live regression suite (Sprint 2.2 #105)
# ---------------------------------------------------------------------------
# Same shape as the caller-correction suite. Picks the right system prompt
# per scenario id (the pickup-only soft-pivot scenario uses the
# offers_delivery=False fixture; everything else uses the default).


def _system_prompt_for(scenario_id: str) -> str:
    if scenario_id == "pickup_only_soft_pivot":
        return _DEMO_PICKUP_ONLY_SYSTEM_PROMPT
    return _DEMO_SYSTEM_PROMPT


@pytest.mark.live_llm
@pytest.mark.parametrize(
    "scenario",
    DELIVERY_SCENARIOS,
    ids=[s.id for s in DELIVERY_SCENARIOS],
)
def test_pickup_delivery_flow(scenario: CorrectionScenario):
    """For each delivery scenario: seed via initial_turns, send the
    trigger transcript, assert the final Order matches the
    scenario-specific expectation."""

    order = Order(call_sid=f"CAlive-deliv-{scenario.id}")
    history: list[dict] = []
    system_prompt = _system_prompt_for(scenario.id)

    for turn in scenario.initial_turns:
        result = generate_reply(
            transcript=turn,
            history=history,
            order=order,
            system_prompt=system_prompt,
        )
        order = result.order
        history = result.history
        print(f"\n--- Seed turn ({scenario.id}) ---\nCaller: {turn}\n"
              f"Haiku: {result.reply_text}\n"
              f"Order: {order.model_dump_json(indent=2)}")

    trigger = scenario.correction_transcript
    result = generate_reply(
        transcript=trigger,
        history=history,
        order=order,
        system_prompt=system_prompt,
    )
    order = result.order

    print(f"\n--- Trigger ({scenario.id}) ---\nCaller: {trigger}\n"
          f"Haiku: {result.reply_text}\n"
          f"Final order: {order.model_dump_json(indent=2)}")

    scenario.assert_end_state(order)
```

- [ ] **Step 4: Verify collection**

Run: `python -m pytest tests/test_llm_integration.py --collect-only -m live_llm -q`
Expected: 9 tests listed total (6 from `test_caller_correction_lands_in_final_order` + 3 from `test_pickup_delivery_flow`).

- [ ] **Step 5: Run the live suite**

Run: `python -m pytest -m live_llm tests/test_llm_integration.py -v -s 2>&1 | tee /tmp/live-pickup-delivery-run.log`
Expected: 9 PASSED.

If `ANTHROPIC_API_KEY` is not set in the environment (and not in `.env`), STOP and report NEEDS_CONTEXT — the test is unverifiable without it.

If any of the 3 new scenarios FAIL:
- Capture the per-scenario assertion error and the printed transcript / order JSON.
- Hypothesize whether the issue is (a) the prompt branch is insufficient → tweak `app/llm/prompts.py`, (b) the validator is wrongly rejecting → tweak `app/orders/validation.py`, (c) the assertion is too strict → tweak the helper in `delivery_transcripts.py`. Report DONE_WITH_CONCERNS with hypothesis.
- Hold the commit until we agree on a fix path.

- [ ] **Step 6: Commit (only if all 9 PASS)**

```bash
git add tests/fixtures/delivery_transcripts.py tests/test_llm_integration.py
git commit -m "Add live-Haiku regression suite for pickup vs delivery (#105)

Three scripted scenarios exercise the validator-feedback loop and the
pickup-only prompt branch end-to-end:

- delivery_address_complete: clean delivery flow lands a valid address
- delivery_address_uhh_then_real: invalid address rejected, Haiku
  re-asks, valid address lands (closes the validator-feedback loop)
- pickup_only_soft_pivot: offers_delivery=False tenant; caller asks
  for delivery; Haiku soft-pivots; order persists as pickup

Catalog reuses CorrectionScenario from correction_transcripts.py.
Pickup-only fixture is a model_copy of _DEMO_RESTAURANT with
offers_delivery=False.

Run pre-merge with: pytest -m live_llm tests/test_llm_integration.py"
```

---

## Task 6: Manual e2e + push + PR

- [ ] **Step 1: Manual delivery call against the live deploy**

Call the Twilight Family Restaurant Twilio number. Verify Twilight currently has `offers_delivery=True` (or unset, which defaults to True): `gcloud firestore documents describe restaurants/twilight-family-restaurant` (or via the dashboard).

Build an order, ask for delivery, give a real-style address ("14 Main Street" or similar). Confirm the order. In the dashboard call view, verify:
- `order_type: delivery`
- `delivery_address` shows the captured value
- The address was read back during the confirmation summary (audible, also visible in transcript)

- [ ] **Step 2: Manual pickup-only call**

Toggle Twilight to `offers_delivery=False` in Firestore (via Firebase Console or `gcloud`). Place a call. Ask for delivery. Verify:
- Haiku soft-pivots ("we're pickup-only, would pickup work?")
- Caller continues with pickup; the order persists with `order_type=pickup` and `delivery_address=null` in the dashboard

After verifying, **revert Twilight to `offers_delivery=True`** in Firestore so subsequent real calls work correctly.

- [ ] **Step 3: Run the full non-live suite one last time**

Run: `python -m pytest tests/ -v 2>&1 | tail -10`
Expected: full suite green (or with only the live tests skipping if the env isn't set; that's fine).

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin feat/105-pickup-delivery
```

```bash
gh pr create --repo tsuki-works/niko --base master --head feat/105-pickup-delivery \
  --title "Pickup vs delivery flow (Sprint 2.2 #105)" \
  --body-file - <<'EOF'
## Summary
- Adds `Restaurant.offers_delivery: bool = True` flag. Pickup-only tenants flip to `False` in Firestore; the system prompt branches accordingly (soft-pivot when callers ask for delivery).
- New `app/orders/validation.py::validate_delivery_address` rejects clearly-broken delivery captures (empty / whitespace / no digit) before they land on the Order. `_apply_validation` in `app/llm/client.py` runs it on every `update_order` payload, drops the bad field, and appends a human-readable rejection note to the tool_result so Haiku re-asks on the next turn.
- Order confirmation read-back now requires the delivery address verbatim (universal — both prompt branches).
- Three live-Haiku scenarios in `tests/fixtures/delivery_transcripts.py` prove the loop closes end-to-end: clean address, invalid-then-corrected address, pickup-only soft-pivot.

## Linked issue
Closes #105. Closes the "Pickup vs. delivery flow" deliverable on Sprint 2.2 (#5).

## Spec & plan
- Spec: `docs/superpowers/specs/2026-04-28-pickup-delivery-design.md`
- Plan: `docs/superpowers/plans/2026-04-28-pickup-delivery.md`

## Test plan
- [x] Unit: `pytest tests/test_validation.py tests/test_restaurants_storage.py tests/test_prompts.py tests/test_llm_client.py` — green
- [x] Live-Haiku regression: `pytest -m live_llm tests/test_llm_integration.py` — paste output below
- [x] Manual e2e: delivery flow against Twilight (`offers_delivery=True`) — items + delivery + address roundtrip in dashboard
- [x] Manual e2e: pickup-only flow against Twilight (temporarily flipped to `offers_delivery=False`, then reverted) — Haiku soft-pivoted; order persisted as pickup

### Live regression suite output
<paste here>

## Notes
- **Out of scope** (per the spec): geocoding, delivery zones, dashboard UI for `offers_delivery`, `offers_pickup` flag, `/onboard-restaurant` skill update, alternate-platform suggestion ("try DoorDash"). Each is a one-PR follow-up if motivated by real-call signal.
- The validator is intentionally permissive (non-empty + ≥1 digit) — voice transcription is noisy and tighter rules cause more caller friction than they prevent. Real-call data can motivate stricter rules later.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

- [ ] **Step 5: Report PR URL back to the user**

Surface the PR URL in chat so the user can review.

---

## Self-review

**Spec coverage:**
- Schema: `Restaurant.offers_delivery` → Task 2 ✓
- Validator: `app/orders/validation.py` → Task 1 ✓
- `_apply_update` integration → Task 4 ✓
- Prompt branching → Task 3 ✓
- Address read-back rule → Task 3 (universal addition) ✓
- Layer 1 unit tests (validator + characterization + 2 prompt branches + schema default) → Tasks 1, 2, 3, 4 ✓
- Layer 2 live transcripts (3 scenarios) → Task 5 ✓
- Layer 3 manual e2e → Task 6 ✓

**Placeholder scan:** no TBDs. The PR-description "paste here" is intentional — filled in at PR creation, not at code time.

**Type consistency:** `validate_delivery_address` signature (`str | None -> bool`) matches across spec, validator, integration, and tests. `_apply_validation` returns `tuple[dict[str, Any], list[str]]` consistently in helper definition and call sites. `CorrectionScenario` is reused (not redefined) in `delivery_transcripts.py`. `Restaurant.offers_delivery: bool = True` matches across schema, prompt branch, and tests.

**Cross-task consistency check:**
- The `_INVALID_ADDRESS_NOTE` string `"Delivery address incomplete — please ask the caller for the full street address."` (defined in Task 4 Step 3b) is the substring asserted by the Task 4 characterization test (`"Delivery address incomplete"`). Match. ✓
- The pickup-only soft-pivot phrasing `"We're actually pickup-only — would pickup work for you?"` (in Task 3 Step 3b's `delivery_handling` for the False branch) matches the test assertions in Task 3 Step 1 (`"we're actually pickup-only"`, `"would pickup work for you"`). Lowercase comparison via `.lower()` makes this robust. ✓
- The address-readback rule text (in Task 3 Step 3a, inserted into the read-back block) contains `"if order_type is delivery"` and `"read the delivery address back"`, matching the assertions in Task 3 Step 1's first test. ✓
