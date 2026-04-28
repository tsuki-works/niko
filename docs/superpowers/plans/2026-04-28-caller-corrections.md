# Caller Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach niko to correctly handle six in-call correction patterns (remove item, substitute, quantity change, size change, order-type swap, delivery-address fix) by extending the system prompt — no new tools, no schema changes.

**Architecture:** Pure prompt extension. Add a `Caller corrections:` block to `_PREAMBLE` in `app/llm/prompts.py` so Haiku emits a single `update_order` carrying the corrected full state. The existing `_apply_update` does a full overwrite and already supports every correction shape — these tests lock in that behavior so future tool refactors can't regress it. Validate with deterministic unit tests + a marker-gated live-Haiku transcript regression suite.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, Anthropic SDK, pytest, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-04-28-error-recovery-design.md`
**Tracking issue:** [#103](https://github.com/tsuki-works/niko/issues/103)
**Branch:** `feat/103-caller-corrections` (already created; spec already committed)

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `pytest.ini` | Modify | Register the `live_llm` marker so opt-in live-API tests are explicit and CI doesn't burn credits |
| `app/llm/prompts.py` | Modify | Insert new `Caller corrections:` block into `_PREAMBLE` between `Item customizations:` and `Order confirmation read-back:` |
| `tests/test_prompts.py` | Modify | One rendering test asserting the new block appears in `build_system_prompt` output |
| `tests/test_llm_client.py` | Modify | Six unit tests against `_apply_update` covering the six correction shapes |
| `tests/fixtures/__init__.py` | Create | Empty file — makes `tests.fixtures` an importable package |
| `tests/fixtures/correction_transcripts.py` | Create | Catalog of 6 scripted caller turns, each paired with an initial `Order` and an expected end-state. Single source of truth for Layer 2 regression suite |
| `tests/test_llm_integration.py` | Modify | One new parametrized test that loads the catalog and asserts end-state for each pattern, gated on `@pytest.mark.live_llm` AND the existing module-level `skipif(not anthropic_api_key)` |

Files chosen by responsibility, not technical layer: prompt content + its rendering test live near each other; correction transcript fixtures are isolated so future bug-driven additions are mechanical.

---

## Task 1: Register the `live_llm` pytest marker

**Why first:** Later tasks reference `@pytest.mark.live_llm`. Marker must be registered before it's used or pytest emits warnings (and could fail with `--strict-markers`).

**Files:**
- Modify: `pytest.ini`

- [ ] **Step 1: Edit `pytest.ini`**

Replace the entire file with:

```ini
[pytest]
asyncio_mode = auto
markers =
    live_llm: hits the live Anthropic API; opt-in via `pytest -m live_llm`. Costs credits.
```

- [ ] **Step 2: Verify the marker is registered**

Run: `pytest --markers | grep live_llm`
Expected: a line like `@pytest.mark.live_llm: hits the live Anthropic API; ...`

- [ ] **Step 3: Commit**

```bash
git add pytest.ini
git commit -m "Register live_llm pytest marker (#103)

Opt-in marker for tests that hit the live Anthropic API. Used by the
caller-correction transcript regression suite added in this branch."
```

---

## Task 2: Add prompt rendering test (TDD red step)

**Why now:** Per TDD, write the failing test before the prompt change so we prove the test actually catches the absence of the new block.

**Files:**
- Modify: `tests/test_prompts.py:245` (append at end)

- [ ] **Step 1: Append the failing test to `tests/test_prompts.py`**

Add this function at the very end of the file:

```python
def test_prompt_includes_caller_corrections_block():
    """Sprint 2.2 #103 — when a caller corrects something already in the
    order (remove, substitute, quantity, size, order-type swap, delivery
    address), Haiku must emit a single update_order carrying the FULL
    corrected state. The prompt must explicitly tell it to replace the
    wrong item, not add the new one alongside it."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    # Section header is present
    assert "caller corrections:" in lower
    # Core "replace, don't add" rule
    assert "emit one update_order with the full corrected state" in lower
    assert "replace the wrong item" in lower
    # Coverage of each correction shape (one anchor per pattern)
    assert "removals" in lower
    assert "substitutions" in lower
    assert "quantity or size changes" in lower
    assert "order-type swap to delivery" in lower
    assert "delivery-address fix" in lower
    # Post-correction acknowledgement is short, not a full re-read
    assert "do not re-read the whole order" in lower
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_prompts.py::test_prompt_includes_caller_corrections_block -v`
Expected: FAIL with `AssertionError` on `assert "caller corrections:" in lower` (or the first missing string).

- [ ] **Step 3: DO NOT commit yet**

The next task adds the prompt block; both go in one commit.

---

## Task 3: Add the `Caller corrections:` block to `_PREAMBLE`

**Files:**
- Modify: `app/llm/prompts.py:53` (insert new block after the closing line of `Item customizations:` and before `Order confirmation read-back:`)

- [ ] **Step 1: Edit `app/llm/prompts.py`**

Find this block (lines 39-53 in the current file):

```python
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

    Order confirmation read-back:
```

Replace with (note the new `Caller corrections:` block inserted between the two existing blocks; everything else identical):

```python
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
    - Order-type swap to delivery: ask for the address before the next
      read-back. Swap to pickup: clear delivery_address.
    - Delivery-address fix: send the full corrected address, not a partial.
    - After a correction, briefly acknowledge what changed in one short
      phrase ("Replaced with a large.", "Two now.") — do NOT re-read the
      whole order; that happens at the confirmation step.

    Order confirmation read-back:
```

- [ ] **Step 2: Run the rendering test to verify it now passes**

Run: `pytest tests/test_prompts.py::test_prompt_includes_caller_corrections_block -v`
Expected: PASS.

- [ ] **Step 3: Run the full prompts test file to ensure no regressions**

Run: `pytest tests/test_prompts.py -v`
Expected: all tests PASS (existing `customization`/`readback` tests still match because their assertions are still present in the prompt).

- [ ] **Step 4: Commit**

```bash
git add app/llm/prompts.py tests/test_prompts.py
git commit -m "Add 'Caller corrections:' block to system prompt (#103)

Six in-scope correction patterns: remove, substitute, quantity, size,
order-type swap, delivery-address fix. The block tells Haiku to emit a
single update_order with the FULL corrected state — replacing the wrong
item, not adding the new one alongside it.

Placed between 'Item customizations:' and 'Order confirmation read-back:'
since corrections happen mid-order, before the final summary.

Rendering test in tests/test_prompts.py guards the section's presence
and the core rules against accidental deletion."
```

---

## Task 4: Lock in `_apply_update` correction behavior with unit tests

**Why:** `_apply_update` does a full-state overwrite and already handles every correction shape. These six tests are **characterization tests** — they assert current behavior so future refactors (e.g. introducing the `remove_item` tool from Approach C) cannot regress it.

**Files:**
- Modify: `tests/test_llm_client.py:863` (append at end, before any final blank line)

- [ ] **Step 1: Append the six tests to `tests/test_llm_client.py`**

Add this block at the end of the file:

```python
# ---------------------------------------------------------------------------
# Caller-correction characterization tests (Sprint 2.2 #103)
# ---------------------------------------------------------------------------
# These assert that _apply_update — which already does full-state overwrite —
# correctly handles every correction shape the new prompt block instructs
# Haiku to emit. They lock in current behavior; if a future refactor
# introduces a remove_item / change_item tool, these MUST still pass against
# the equivalent payload shape.


def _seed_order_with(items: list[dict[str, Any]], **extra: Any) -> Order:
    """Helper: build an Order with the given items and apply once."""
    base = Order(call_sid="CAtest")
    return _apply_update(base, {"items": items, "status": "in_progress", **extra})


def test_correction_remove_item_drops_it_from_order():
    """Caller: 'take off the Coke.' Payload omits the Coke entirely;
    only the Margherita remains."""
    order = _seed_order_with(
        [
            {"name": "Margherita", "category": "pizza", "size": "large",
             "quantity": 1, "unit_price": 19.99},
            {"name": "Coke", "category": "drinks", "size": None,
             "quantity": 1, "unit_price": 2.99},
        ],
        order_type="pickup",
    )

    corrected = _apply_update(
        order,
        {"items": [
            {"name": "Margherita", "category": "pizza", "size": "large",
             "quantity": 1, "unit_price": 19.99},
        ], "order_type": "pickup", "status": "in_progress"},
    )

    assert [i.name for i in corrected.items] == ["Margherita"]
    assert corrected.subtotal == 19.99


def test_correction_substitute_item_replaces_not_appends():
    """Caller: 'change the Margherita to a calzone.' Payload swaps the
    item; quantity carries through. Crucially the resulting order has
    ONE item, not two."""
    order = _seed_order_with(
        [
            {"name": "Margherita", "category": "pizza", "size": "large",
             "quantity": 1, "unit_price": 19.99},
        ],
        order_type="pickup",
    )

    corrected = _apply_update(
        order,
        {"items": [
            {"name": "Calzone", "category": "pizza", "size": "large",
             "quantity": 1, "unit_price": 16.99},
        ], "order_type": "pickup", "status": "in_progress"},
    )

    assert len(corrected.items) == 1
    assert corrected.items[0].name == "Calzone"
    assert corrected.items[0].unit_price == 16.99


def test_correction_quantity_change_does_not_duplicate_line():
    """Caller: 'make that 2 not 1.' Same line item with quantity bumped;
    never two lines for the same item."""
    order = _seed_order_with(
        [
            {"name": "Margherita", "category": "pizza", "size": "large",
             "quantity": 1, "unit_price": 19.99},
        ],
        order_type="pickup",
    )

    corrected = _apply_update(
        order,
        {"items": [
            {"name": "Margherita", "category": "pizza", "size": "large",
             "quantity": 2, "unit_price": 19.99},
        ], "order_type": "pickup", "status": "in_progress"},
    )

    assert len(corrected.items) == 1
    assert corrected.items[0].quantity == 2
    assert corrected.subtotal == 39.98


def test_correction_size_change_swaps_size_and_unit_price():
    """Caller: 'I said large not medium.' Same item with new size +
    new unit_price (the menu's price for the new size)."""
    order = _seed_order_with(
        [
            {"name": "Margherita", "category": "pizza", "size": "medium",
             "quantity": 1, "unit_price": 14.99},
        ],
        order_type="pickup",
    )

    corrected = _apply_update(
        order,
        {"items": [
            {"name": "Margherita", "category": "pizza", "size": "large",
             "quantity": 1, "unit_price": 19.99},
        ], "order_type": "pickup", "status": "in_progress"},
    )

    assert len(corrected.items) == 1
    assert corrected.items[0].size == "large"
    assert corrected.items[0].unit_price == 19.99


def test_correction_order_type_swap_to_pickup_clears_delivery_address():
    """Caller: 'switch back to pickup.' order_type flips and
    delivery_address goes back to None — otherwise the dashboard
    would show a stale address on a pickup order."""
    order = _seed_order_with(
        [
            {"name": "Margherita", "category": "pizza", "size": "large",
             "quantity": 1, "unit_price": 19.99},
        ],
        order_type="delivery",
        delivery_address="14 Spadina Ave",
    )
    assert order.order_type is OrderType.DELIVERY
    assert order.delivery_address == "14 Spadina Ave"

    corrected = _apply_update(
        order,
        {"items": [
            {"name": "Margherita", "category": "pizza", "size": "large",
             "quantity": 1, "unit_price": 19.99},
        ], "order_type": "pickup", "delivery_address": None,
         "status": "in_progress"},
    )

    assert corrected.order_type is OrderType.PICKUP
    assert corrected.delivery_address is None


def test_correction_delivery_address_fix_overwrites_full_value():
    """Caller: 'no, my address is 14 not 40.' Payload contains the
    fully-corrected address — not a partial / diff."""
    order = _seed_order_with(
        [
            {"name": "Margherita", "category": "pizza", "size": "large",
             "quantity": 1, "unit_price": 19.99},
        ],
        order_type="delivery",
        delivery_address="40 Main St",
    )

    corrected = _apply_update(
        order,
        {"items": [
            {"name": "Margherita", "category": "pizza", "size": "large",
             "quantity": 1, "unit_price": 19.99},
        ], "order_type": "delivery",
         "delivery_address": "14 Main St",
         "status": "in_progress"},
    )

    assert corrected.delivery_address == "14 Main St"
    assert corrected.order_type is OrderType.DELIVERY
```

- [ ] **Step 2: Run the new tests**

Run: `pytest tests/test_llm_client.py -v -k correction`
Expected: all 6 PASS. (`_apply_update`'s full-overwrite already covers each shape — these are characterization tests.)

If any FAIL: that's a real bug in `_apply_update`. Stop and surface the failure rather than papering over it; the spec assumes full-overwrite semantics.

- [ ] **Step 3: Run the full LLM client test file to ensure no regressions**

Run: `pytest tests/test_llm_client.py -v`
Expected: every test PASSES.

- [ ] **Step 4: Commit**

```bash
git add tests/test_llm_client.py
git commit -m "Lock in _apply_update correction behavior (#103)

Six characterization tests covering the correction shapes Haiku is now
prompted to emit: remove, substitute, quantity change, size change,
order-type swap (with delivery_address clear), delivery-address fix.

These pass against the current full-overwrite implementation; their
purpose is to prevent regression if a future refactor introduces tool
variants like remove_item / change_item."
```

---

## Task 5: Create the live-Haiku transcript regression catalog

**Files:**
- Create: `tests/fixtures/__init__.py`
- Create: `tests/fixtures/correction_transcripts.py`

- [ ] **Step 1: Create `tests/fixtures/__init__.py`**

Empty file — just makes `tests.fixtures` an importable package.

```python
```

- [ ] **Step 2: Create `tests/fixtures/correction_transcripts.py`**

```python
"""Caller-correction transcripts for the live-Haiku regression suite (#103).

Each entry is a multi-turn scenario:
- ``initial_turns`` runs first (no assertions) to seed the order state
  the way it would look in a real call right before the correction.
- ``correction_transcript`` is the caller's correction utterance.
- ``assert_end_state`` runs against the final ``Order`` and raises
  ``AssertionError`` with a human-readable message on mismatch — used
  instead of equality on a full Order because Haiku reasonably varies
  on incidentals (extra modifications, exact unit_price for a size we
  don't enumerate, etc.) and we only want to assert the load-bearing
  fields per pattern.

Add a row whenever a real correction bug is found in production. Pair
the row with a backstop in ``tests/test_llm_client.py`` that exercises
the same shape against ``_apply_update`` deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.orders.models import Order, OrderType


@dataclass
class CorrectionScenario:
    id: str
    initial_turns: list[str]
    correction_transcript: str
    assert_end_state: Callable[[Order], None]


def _assert_remove_item(final: Order) -> None:
    names = [i.name.lower() for i in final.items]
    assert not any("coke" in n for n in names), (
        f"Coke should be removed; items were {names}"
    )
    assert any("margherita" in n or "pepperoni" in n or "veggie" in n
               for n in names), (
        f"At least one pizza should remain; items were {names}"
    )


def _assert_substitute_item(final: Order) -> None:
    names = [i.name.lower() for i in final.items]
    # The substitute landed (calzone present)
    assert any("calzone" in n for n in names), (
        f"Calzone should be present; items were {names}"
    )
    # The replaced item is gone
    assert not any("margherita" in n for n in names), (
        f"Margherita should be replaced; items were {names}"
    )
    # No accidental duplication
    assert len(final.items) == 1, (
        f"Expected exactly one item after substitution; got {len(final.items)}"
    )


def _assert_quantity_change(final: Order) -> None:
    assert len(final.items) == 1, (
        f"Quantity change must not duplicate the line; got {len(final.items)} items"
    )
    assert final.items[0].quantity == 2, (
        f"Expected quantity=2; got {final.items[0].quantity}"
    )


def _assert_size_change(final: Order) -> None:
    assert len(final.items) == 1, (
        f"Size change must not duplicate the line; got {len(final.items)} items"
    )
    size = (final.items[0].size or "").lower()
    assert "large" in size, f"Expected size=large; got {final.items[0].size!r}"
    # unit_price should reflect the large price (>medium); we don't pin to
    # an exact value because the demo menu may shift, but it must be
    # strictly greater than a typical medium price (~$14).
    assert final.items[0].unit_price >= 16.00, (
        f"Expected unit_price >= 16.00 for large; got {final.items[0].unit_price}"
    )


def _assert_swap_to_pickup(final: Order) -> None:
    assert final.order_type is OrderType.PICKUP, (
        f"Expected order_type=pickup; got {final.order_type}"
    )
    assert final.delivery_address in (None, ""), (
        f"delivery_address should be cleared on swap-to-pickup; got "
        f"{final.delivery_address!r}"
    )


def _assert_address_fix(final: Order) -> None:
    assert final.order_type is OrderType.DELIVERY, (
        f"Expected order_type=delivery; got {final.order_type}"
    )
    assert final.delivery_address is not None, "Expected an address"
    assert "14" in final.delivery_address, (
        f"Expected corrected address to contain '14'; got "
        f"{final.delivery_address!r}"
    )
    assert "40" not in final.delivery_address, (
        f"Old address number '40' should be gone; got "
        f"{final.delivery_address!r}"
    )


SCENARIOS: list[CorrectionScenario] = [
    CorrectionScenario(
        id="remove_item",
        initial_turns=[
            "I'd like a large margherita and a Coke for pickup, please.",
        ],
        correction_transcript="Actually, take off the Coke.",
        assert_end_state=_assert_remove_item,
    ),
    CorrectionScenario(
        id="substitute_item",
        initial_turns=[
            "Can I get a large margherita for pickup?",
        ],
        correction_transcript="Wait, change the margherita to a calzone instead.",
        assert_end_state=_assert_substitute_item,
    ),
    CorrectionScenario(
        id="quantity_change",
        initial_turns=[
            "One large margherita for pickup, please.",
        ],
        correction_transcript="Actually, make that two — not one.",
        assert_end_state=_assert_quantity_change,
    ),
    CorrectionScenario(
        id="size_change",
        initial_turns=[
            "Can I get a medium margherita for pickup?",
        ],
        correction_transcript="Sorry, I meant large, not medium.",
        assert_end_state=_assert_size_change,
    ),
    CorrectionScenario(
        id="swap_to_pickup",
        initial_turns=[
            "I'd like a large margherita for delivery to 14 Spadina Avenue.",
        ],
        correction_transcript="Actually, switch it back to pickup.",
        assert_end_state=_assert_swap_to_pickup,
    ),
    CorrectionScenario(
        id="address_fix",
        initial_turns=[
            "Large margherita for delivery to 40 Main Street, please.",
        ],
        correction_transcript="Sorry, I meant 14 Main Street, not 40.",
        assert_end_state=_assert_address_fix,
    ),
]
```

- [ ] **Step 3: Verify the catalog imports cleanly**

Run: `python -c "from tests.fixtures.correction_transcripts import SCENARIOS; print(len(SCENARIOS))"`
Expected: prints `6`.

- [ ] **Step 4: DO NOT commit yet**

The next task wires the catalog into `test_llm_integration.py`; both go in one commit so the catalog isn't sitting unused.

---

## Task 6: Wire the catalog into a marker-gated live-Haiku test

**Files:**
- Modify: `tests/test_llm_integration.py:143` (append at end of file)

- [ ] **Step 1: Append the parametrized live test to `tests/test_llm_integration.py`**

```python
# ---------------------------------------------------------------------------
# Caller-correction live regression suite (Sprint 2.2 #103)
# ---------------------------------------------------------------------------
# Marker-gated so it only runs on `pytest -m live_llm`. Unlike the rest of
# this file (which auto-runs whenever ANTHROPIC_API_KEY is set), this suite
# costs ~6× a normal call and is meant to be run pre-merge, not on every
# `pytest` invocation. The module-level skipif still applies — without the
# API key we skip even when -m live_llm is passed.

from tests.fixtures.correction_transcripts import SCENARIOS, CorrectionScenario


@pytest.mark.live_llm
@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_caller_correction_lands_in_final_order(scenario: CorrectionScenario):
    """For each scenario: seed the order via initial turns, then send the
    correction utterance, then assert the final Order matches the
    pattern-specific expectation."""

    order = Order(call_sid=f"CAlive-corr-{scenario.id}")
    history: list[dict] = []

    for turn in scenario.initial_turns:
        result = generate_reply(transcript=turn, history=history, order=order)
        order = result.order
        history = result.history
        print(f"\n--- Seed turn ({scenario.id}) ---\nCaller: {turn}\n"
              f"Haiku: {result.reply_text}\n"
              f"Order: {order.model_dump_json(indent=2)}")

    correction = scenario.correction_transcript
    result = generate_reply(transcript=correction, history=history, order=order)
    order = result.order

    print(f"\n--- Correction ({scenario.id}) ---\nCaller: {correction}\n"
          f"Haiku: {result.reply_text}\n"
          f"Final order: {order.model_dump_json(indent=2)}")

    scenario.assert_end_state(order)
```

- [ ] **Step 2: Verify the test is collected under the marker**

Run: `pytest tests/test_llm_integration.py --collect-only -m live_llm -q`
Expected: 6 tests listed (one per scenario id), no other tests collected.

- [ ] **Step 3: Run the live suite (requires `ANTHROPIC_API_KEY`)**

Run: `ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY pytest -m live_llm tests/test_llm_integration.py -v -s`
Expected: all 6 scenarios PASS. Capture the full stdout in the PR description.

If `ANTHROPIC_API_KEY` is not set locally, the implementing engineer should fetch it via `/shared-creds` (Anthropic key from the Discord `#shared-creds` channel — never commit it).

If any scenario FAILS: this is signal that the prompt is insufficient for that pattern. Don't paper over it — refine the prompt block in `app/llm/prompts.py` and re-run. If a single scenario keeps failing after two prompt iterations, document it in the PR description as a known gap and decide with the user whether to escalate to Approach B (server-side guardrails) before merge.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/__init__.py tests/fixtures/correction_transcripts.py tests/test_llm_integration.py
git commit -m "Add live-Haiku regression suite for caller corrections (#103)

Six scripted scenarios — one per correction pattern — that seed an order
via initial turns, send the correction utterance, and assert the final
Order reflects the correction. Gated on @pytest.mark.live_llm AND the
existing module-level ANTHROPIC_API_KEY skipif.

Run pre-merge with: pytest -m live_llm tests/test_llm_integration.py

Catalog lives in tests/fixtures/correction_transcripts.py so adding a
new pattern (or a new variant of an existing one when a real-call bug
surfaces) is a one-row diff."
```

---

## Task 7: End-to-end manual verification + PR

- [ ] **Step 1: Place a manual test call against the live deploy**

Call the niko-pizza-kitchen Twilio number. Build an order with at least one item, then exercise:
- A substitution mid-order ("change my X to Y")
- An order-type swap to delivery, then provide an address

Verify in the dashboard call view that:
- Final order shows ONLY the substituted item (not both)
- order_type=delivery, delivery_address present and correct
- Subtotal matches expected

- [ ] **Step 2: Run the full test suite one last time**

Run: `pytest -v` (the non-live default — does NOT include `-m live_llm`)
Expected: all tests PASS (including the existing live integration tests if `ANTHROPIC_API_KEY` is set, which auto-run via module-level skipif).

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin feat/103-caller-corrections
```

```bash
gh pr create --repo tsuki-works/niko --base master --head feat/103-caller-corrections \
  --title "Caller corrections (Sprint 2.2 closeout — error recovery, #103)" \
  --body-file - <<'EOF'
## Summary
- Adds a "Caller corrections:" block to the system prompt covering six in-call correction patterns: remove item, substitute, quantity change, size change, order-type swap (with delivery_address clear), delivery-address fix.
- Pure prompt extension — no new tools, no schema changes. Existing `update_order` already takes the FULL current order state each turn; the new prompt rules tell Haiku to use that to *replace* the wrong item rather than add the new one alongside it.
- Six unit tests against `_apply_update` lock in current full-overwrite behavior so future refactors can't regress it.
- Six live-Haiku transcripts in `tests/fixtures/correction_transcripts.py` form an opt-in regression suite (`@pytest.mark.live_llm`) — runnable pre-merge with `pytest -m live_llm`.

## Linked issue
Closes #103. Closes the "Basic error recovery" deliverable on Sprint 2.2 (#5).

## Spec
`docs/superpowers/specs/2026-04-28-error-recovery-design.md`

## Test plan
- [x] Unit tests: `pytest tests/test_llm_client.py tests/test_prompts.py` — green
- [x] Live-Haiku regression suite: `pytest -m live_llm tests/test_llm_integration.py` — paste output below
- [x] Manual end-to-end call against the live deploy: substitution + swap-to-delivery flow reflected correctly in dashboard

### Live regression suite output
<paste here>

## Notes
- "Out of scope" per the spec: full reset ("cancel everything, start over"), misheard-item recovery (Kailash/Sandeep call-quality work), new tool affordances (`remove_item` etc.), server-side validation. All can be revisited as follow-ups.
- The "caller asks to remove an item not in the order" case is intentionally not covered yet — wait for real-call signal before specifying behavior.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

- [ ] **Step 4: Report PR URL back to user**

The `gh pr create` output is the PR URL. Surface it in the chat so the user can review.

---

## Self-review

**Spec coverage:**
- Six correction patterns → covered by Tasks 3 (prompt), 4 (unit tests), 5+6 (live tests). ✓
- "Pure prompt extension" approach → Task 3 only edits `_PREAMBLE`; no new tools/schema. ✓
- Layer 1 unit tests → Task 4. ✓
- Layer 2 live-Haiku regression suite → Tasks 5+6. ✓
- Layer 3 prompt rendering test → Task 2. ✓
- Done criteria (unit green, 6 live transcripts pass, manual call) → Task 7. ✓
- niko-reviewer sign-off → handled by PR review (Task 7 step 3). ✓

**Placeholder scan:** no TBDs. Every code step has full code. Every command has expected output. The PR-description "paste here" placeholder is intentional (filled in at PR time, not at code time).

**Type consistency:** `CorrectionScenario` defined in Task 5, imported in Task 6 — names match. `SCENARIOS` list name consistent. `_apply_update`, `Order`, `OrderType`, `OrderStatus`, `LineItem` references match `app/orders/models.py` and `app/llm/client.py`.

**One small deviation from spec:** spec said "Layer 3 — prompt rendering test". Plan implements this in Task 2/3 by adding the test in `tests/test_prompts.py` (matching the existing pattern of behavioral prompt assertions). That matches the spec's wording.
