"""Tests for the system prompt builder.

These guard the behavioural directives we tuned across #76, #78, and
#79: address handling, speak-before-tool-use, terminal goodbyes,
and the goodbye/status-flip coupling. Plus the multi-tenancy plumbing
from #79 — the builder accepts a ``Restaurant`` and reads from it
rather than a global menu.

If a future edit accidentally deletes any of these the tests fail
loudly rather than degrading the live caller experience silently.
"""

import re

from app.llm.prompts import build_system_prompt
from app.restaurants.models import Restaurant
from app.storage.restaurants import demo_restaurant_from_menu


def _demo() -> Restaurant:
    return demo_restaurant_from_menu()


def _collapse_ws(text: str) -> str:
    """Collapse runs of whitespace (including newlines) into a single
    space. The prompt wraps long sentences across lines for readability,
    so substring assertions that span a wrap point need a normalized
    view."""
    return re.sub(r"\s+", " ", text)


def test_prompt_includes_restaurant_name_and_menu_items():
    restaurant = _demo()
    prompt = build_system_prompt(restaurant)
    assert restaurant.name in prompt
    for pizza in restaurant.menu["pizzas"]:
        assert pizza["name"] in prompt


def test_prompt_describes_all_six_atomic_tools():
    """#305 Part B — the prompt must list each of the six atomic order
    tools so the model knows the full surface it has to work with.
    Missing a tool from the prompt would silently push the model to
    pick the wrong one (e.g., add_item for a quantity change because
    update_item was never introduced)."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    for tool_name in (
        "add_item",
        "remove_item",
        "update_item",
        "set_order_type",
        "set_delivery_address",
        "set_status",
    ):
        assert tool_name in lower, f"prompt is missing the {tool_name} tool description"


def test_prompt_enforces_per_turn_tool_calls_against_batching():
    """#305 Part B core invariant — the model must call the relevant
    tool the moment the order changes, in the SAME turn. Pre-Part-B
    diagnostic showed Haiku batching all update_order calls to the
    confirm turn (n_items=0 on adds, w=386 cache writes concentrated
    at confirm). With atomic tools batching defeats both the dashboard
    live view and the latency win — the prompt must explicitly forbid
    it."""
    prompt = build_system_prompt(_demo())
    flat = _collapse_ws(prompt.lower())
    # Same-turn rule must be present.
    assert "in the same turn" in flat
    # Explicit forbid against batching to confirm.
    assert "do not batch tool calls to the end" in flat


def test_prompt_warns_against_reciting_address_on_pickup_wrapup():
    """Regression for #76 — the placeholder address (or any address) must
    not be volunteered in pickup confirmations."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    assert "restaurant address handling" in lower
    assert "do not recite it during pickup wrap-ups" in lower or "do not recite" in lower
    assert "where are you" in lower  # the only time the address should come up


def test_prompt_requires_text_before_tool_use():
    """Regression for #76, #155, and #305 Part B — Haiku must speak first
    then call the tool, so audio starts streaming within the <1s budget on
    commit turns. In #155 the rule was strengthened from a soft bullet to a
    numbered CRITICAL block after Haiku was observed ignoring the soft form
    (1192ms tool_prefix on 18:33 call). #305 Part B replaced the single
    update_order tool with six atomic tools — the speak-first rule now
    applies to ALL of them."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    assert "when you call any of these tools" in lower
    assert "first" in lower
    # Updated for #155 — the rule was strengthened to a numbered CRITICAL block.
    # The "do not do this" string is the new equivalent assertion that the
    # rule still forbids tool-first turns.
    assert "do not do this" in lower


def test_prompt_speak_first_rule_is_critical_and_numbered():
    """Regression for #155 — the speak-first rule was strengthened
    from a soft bullet to a numbered CRITICAL section after Haiku
    was observed ignoring the soft form (1192ms tool_prefix on the
    18:33 test call). Don't soften this back without filing a fresh
    observability run that proves Haiku now obeys the soft form."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    # The block must read as a non-negotiable directive, not a hint.
    assert "ordering is critical" in lower
    assert "non-negotiable" in lower
    # Concrete WRONG example so the model has something to pattern-match against.
    assert "do not do this" in lower
    # Existing requirements still hold (regression for #76).
    assert "always speak a short acknowledgement first" in lower


def test_prompt_makes_confirmation_goodbyes_terminal():
    """Regression for #78 — once the caller confirms, the agent should
    say a brief terminal goodbye and NOT ask another question. Otherwise
    the auto-hangup would cut off whatever the bot asked next."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    assert "closing the call" in lower
    assert "do not ask another follow-up question after confirming" in lower
    # Spot-check that the directive references the confirmed status flow.
    # #260 simplified the wording from "set the order's status to confirmed"
    # to the literal tool-call form to keep the rule terse; #305 Part B
    # swapped update_order for the atomic set_status(confirmed) call.
    assert "set_status(confirmed)" in lower


def test_prompt_couples_goodbye_phrases_with_status_flip():
    """Regression for #79 — Haiku was saying 'your order is in' without
    calling the confirm tool, which left the auto-hangup inert. The
    prompt insists on the status flip in the same turn. #305 Part B
    swapped the snapshot tool for set_status(confirmed)."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    assert "critical" in lower
    assert "your order is in" in lower
    assert "set_status(confirmed)" in lower


def test_prompt_closing_uses_period_terminated_openers():
    """Regression for #186 (period-terminated openers for TTS flushing)
    and #260 (drop the enumerated four-ack list that was causing
    audible parroting on real calls).

    The period-terminated rule itself is load-bearing: TTS streams
    earlier when the opener ends in a period vs a comma. #260 kept the
    rule but removed the verbatim "Got it. / Perfect. / Alright. /
    Of course." enumeration because the model was rotating through
    that fixed list literally on every commit turn, leaking the
    prompt's structure to the caller. Don't restore the verbatim list
    without a fresh observability run showing the model still needs
    examples to obey the rule.
    """
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    flat = _collapse_ws(lower)
    # The period-vs-comma rule must remain explicit — it's the load-bearing
    # bit for TTS. The text wraps across lines, so check against the flat
    # form for substrings that cross a wrap point.
    assert "ending in a period" in flat
    assert "not a comma" in flat
    assert "periods let" in flat or "tts start speaking sooner" in flat
    # The wrap-up CRITICAL block is preserved — wrap-up phrases must
    # still couple to status="confirmed" in the same turn.
    assert "your order is in" in lower
    assert "we'll have it ready" in lower
    # Old comma-led forms must remain absent (regression for #186).
    assert "great, your order is in" not in lower
    assert "perfect, we'll have it ready" not in lower
    # #260 — the enumerated four-ack list must NOT appear, and the rule
    # should explicitly tell the model not to pick from a fixed rotation.
    assert '"got it.", "perfect.", "alright.", "of course."' not in lower
    assert "do not pick from a fixed rotation" in flat or "do not pick from a fixed list" in flat


def test_prompt_readback_uses_action_closer_not_price_validation():
    """Regression for #260 — the order read-back closes with a brief
    action/order-oriented turn-cue ("Is that okay?", "Ready to go?",
    "Should I send that through?"), NOT a yes/no question pinned to
    the price ("does that sound right?", "sound good?").

    The first attempt at #260 dropped the closer entirely and forced
    statement-form. The live call surfaced a 10-second silence-timeout
    regression because callers had no cue it was their turn. The fix
    keeps the price-validation prohibition but restores an explicit
    turn-cue with varied phrasing.

    Replaces the earlier #186 assertion that the read-back example led
    with "Perfect." — that example was dropped along with the four-ack
    enumeration (see test_prompt_closing_uses_period_terminated_openers).
    """
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    flat = _collapse_ws(lower)
    # The read-back example body is preserved (item + total form). Use
    # the flat form because the example wraps across lines.
    assert "so that's one large margherita" in flat
    # Price-validation closers remain banned — this is the core #260
    # protection (caller can't validate a number they don't know).
    # Both phrases appear in the *prohibition* list now, so check the
    # ban-rule context rather than absolute absence. The list wraps
    # across lines, so check against the flat form.
    assert '"does that sound right?"' in flat
    assert '"sound good?"' in flat
    assert "pinned to the price" in flat
    # The example must NOT use the banned phrasings as its closer —
    # check the example body specifically.
    assert "twenty-one ninety-nine. is that okay?" in flat
    # The example must end with an action-oriented closer, not a bare
    # statement. "Is that okay?" is the canonical example phrase.
    assert "is that okay?" in lower
    # Rule must explicitly tell the model to vary phrasing rather than
    # rotate a fixed list literally.
    assert "do not pick from a fixed rotation" in flat


def test_prompt_renders_per_tenant_name():
    """Multi-tenancy (#79): the same builder run against a different
    Restaurant produces a prompt with that restaurant's name — proves
    the prompt is no longer baked from a module-level singleton."""
    other = Restaurant(
        id="other-shop",
        name="Sandeep's Sandwich Hut",
        display_phone="+14160000000",
        twilio_phone="+14160000001",
        address="1 Spadina Ave",
        hours="11am-9pm",
        menu={"pizzas": [], "sides": [], "drinks": []},
    )
    prompt = build_system_prompt(other)
    assert "Sandeep's Sandwich Hut" in prompt
    assert "Niko's Pizza Kitchen" not in prompt


def test_prompt_appends_greeting_addendum_when_provided():
    """``prompt_overrides.greeting_addendum`` lets a tenant inject a
    short tone/quirk note without forking the whole prompt."""
    restaurant = _demo()
    restaurant.prompt_overrides = {
        "greeting_addendum": "We're family-run since 1972 — feel free to ask about today's special."
    }
    prompt = build_system_prompt(restaurant)
    assert "family-run since 1972" in prompt


def test_prompt_renders_arbitrary_menu_categories():
    """The menu renderer iterates whatever keys are present and title-
    cases them — no hardcoded ``pizzas``/``sides``/``drinks`` triple.
    A tenant with Caribbean-style categories should see them rendered
    under their own names, not collapsed into pizza terminology."""
    restaurant = Restaurant(
        id="twilight",
        name="Twilight Family Restaurant",
        display_phone="+14160000000",
        twilio_phone="+14160000001",
        address="55 Nugget Ave",
        hours="11am-10pm",
        menu={
            "appetizers": [{"name": "Vegetable Spring Roll", "price": 2.00}],
            "caribbean_appetizers": [{"name": "Jerk Chicken", "price": 14.75}],
            "fried_rice": [
                {
                    "name": "Twilight Fried Rice",
                    "description": "Chicken, beef, shrimp.",
                    "price": 15.75,
                }
            ],
        },
    )
    prompt = build_system_prompt(restaurant)
    # Category headers are title-cased, not literal snake_case
    assert "Appetizers:" in prompt
    assert "Caribbean Appetizers:" in prompt
    assert "Fried Rice:" in prompt
    # Items with single price render with parenthesized $ amount + description
    assert "Twilight Fried Rice" in prompt
    assert "$15.75" in prompt
    assert "Chicken, beef, shrimp." in prompt
    # No leakage from the hardcoded pizza-shop vocabulary
    assert "Pizzas:" not in prompt
    assert "Sides:" not in prompt


def test_prompt_respects_explicit_category_order():
    """``_category_order`` pins the prompt rendering order. Firestore
    scrambles dict insertion order on round-trip, so a tenant that
    cares about ordering uses this escape hatch. Categories listed in
    ``_category_order`` render first, in that order; anything else
    follows."""
    restaurant = Restaurant(
        id="t",
        name="T",
        display_phone="+10000000000",
        twilio_phone="+10000000001",
        address="-",
        hours="-",
        menu={
            # Dict order chosen to NOT match ``_category_order`` so the
            # test would fail if order came from dict iteration.
            "drinks": [{"name": "Coke", "price": 2.99}],
            "soups": [{"name": "Wonton", "price": 5.00}],
            "appetizers": [{"name": "Spring Roll", "price": 2.00}],
            "_category_order": ["appetizers", "soups", "drinks"],
        },
    )
    prompt = build_system_prompt(restaurant)
    apps_idx = prompt.index("Appetizers:")
    soups_idx = prompt.index("Soups:")
    drinks_idx = prompt.index("Drinks:")
    assert apps_idx < soups_idx < drinks_idx
    # The order key itself never renders as a category
    assert "Category Order:" not in prompt
    assert "_category_order" not in prompt


def test_prompt_category_order_lists_unknown_categories_are_ignored():
    """``_category_order`` referencing a category that doesn't exist
    in the menu shouldn't crash, and shouldn't fabricate a header for
    the missing category."""
    restaurant = Restaurant(
        id="t",
        name="T",
        display_phone="+10000000000",
        twilio_phone="+10000000001",
        address="-",
        hours="-",
        menu={
            "appetizers": [{"name": "Spring Roll", "price": 2.00}],
            "_category_order": ["mains", "appetizers", "desserts"],
        },
    )
    prompt = build_system_prompt(restaurant)
    assert "Appetizers:" in prompt
    assert "Mains:" not in prompt
    assert "Desserts:" not in prompt


def test_prompt_skips_empty_and_non_list_categories():
    """Empty categories shouldn't bloat the prompt with naked headers.
    Non-list values (Firestore can return scalars under unexpected
    keys) are silently dropped rather than crashing the call."""
    restaurant = Restaurant(
        id="x",
        name="X",
        display_phone="+10000000000",
        twilio_phone="+10000000001",
        address="-",
        hours="-",
        menu={
            "mains": [{"name": "Burger", "price": 10.00}],
            "sides": [],  # empty: skip header
            "promo_text": "Half off Tuesdays",  # scalar: skip silently
            "specials": None,  # falsy: skip
        },
    )
    prompt = build_system_prompt(restaurant)
    assert "Mains:" in prompt
    assert "Burger" in prompt
    # No empty headers
    assert "Sides:" not in prompt
    assert "Specials:" not in prompt
    # Scalar value not surfaced as if it were a category
    assert "Promo Text:" not in prompt
    assert "Half off Tuesdays" not in prompt


def test_prompt_includes_customization_guidance():
    """Sprint 2.2 #2 — prompt must instruct the agent to capture free-text
    modifications, not invent them, and to clarify contradictory or
    nonsensical ones."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    assert "customization" in lower
    assert "do not invent" in lower
    assert "clarify" in lower
    assert "does not make sense" in lower


def test_prompt_includes_readback_instruction():
    """Sprint 2.2 #3 — prompt must direct the agent to read back the full
    order using the server-verified subtotal returned in tool_result, and
    only confirm on an explicit caller yes.

    #260 (initial) tried statement-form read-backs to dodge price-
    validation framing; that produced a silence-timeout regression on
    live calls because callers had no turn-cue. #260 (revised) restores
    an explicit closer but keeps it order-oriented, never price-
    oriented. The "explicit confirmation" requirement still holds —
    the model must wait for a real "yes" before flipping status, not
    infer it from silence.

    #305 Part B replaced the single update_order tool with six atomic
    tools — the read-back rule now points the model at the latest
    tool_result for the subtotal (any of the six atomic tools surfaces it)
    instead of naming a specific tool.
    """
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    flat = _collapse_ws(lower)
    assert "read back" in lower
    # The subtotal comes from the latest tool_result regardless of which
    # atomic tool produced it.
    assert "tool_result" in lower
    # Price-validation framing remains banned (#260).
    assert "does that sound right" not in lower
    # An action-oriented turn-cue closer is required.
    assert "is that okay?" in lower
    # The explicit-confirmation requirement is still load-bearing.
    assert (
        "confirm explicitly" in flat
        or "explicitly confirms" in flat
        or "after explicit confirmation" in flat
    )


def test_prompt_pins_stt_uncertainty_on_bot_not_caller():
    """Regression for #260 — when the caller's transcript is unclear
    (typically STT noise like "Pepper Shrimp hypertension" on call
    CA2408cf afaf3f250c0bcf7cc2da2f9e19a1), the bot must own the
    uncertainty ("didn't catch that") rather than blame the caller
    ("I'm not sure what you mean by that"). Real STT misfires are on
    our pipeline, not the caller — framing them as caller error reads
    as blame and damages the call register."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    flat = _collapse_ws(lower)
    # The bot-owning frame must appear as the recommended phrasing.
    # The phrase wraps across lines, so check the flat form.
    assert "didn't catch that" in flat
    # The blame frame must be explicitly called out as wrong.
    assert "i'm not sure what you mean" in flat
    # The rule must explicitly tie the framing to the bot vs caller axis.
    assert "pin the uncertainty on yourself" in flat
    assert "never on the caller" in flat


def test_prompt_forbids_per_item_readback_and_running_total():
    """Regression for #260 — the read-back happens ONCE at the end,
    not after each item. Per-item summaries make multi-item orders
    feel like an interrogation; running-subtotal announcements are
    noise. The post-tool-result rule must explicitly forbid both
    so Haiku doesn't drift into chatty per-item recapping on long
    orders."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    flat = _collapse_ws(lower)
    # The mid-order branch must explicitly say "anything else?" and
    # must explicitly forbid recitation + running-total announcements.
    assert "anything else" in lower
    assert "do not recite" in flat
    assert "do not announce the running subtotal" in flat
    # Read-back rule must restate the once-at-end discipline so the
    # constraint is visible from both the read-back section and the
    # tool-ordering section.
    assert "happens once, at the end" in flat or "the read-back happens once" in flat


def test_prompt_includes_caller_corrections_block():
    """Sprint 2.2 #103 + #305 Part B — when a caller corrects something
    already in the order (remove, substitute, quantity, size, order-type
    swap, delivery address), the prompt must direct the model to the
    right atomic tool for each correction shape.

    Pre-Part-B this section told Haiku to emit one update_order with the
    FULL corrected state and explicitly "replace the wrong item" so the
    snapshot didn't drift into appending. Atomic tools make that
    impossible by construction (remove_item / update_item operate on
    specific item_ids), so the section now teaches per-correction tool
    selection instead."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    # Section header is present
    assert "caller corrections:" in lower
    # Each correction shape now maps to a specific atomic tool.
    assert "removals" in lower
    assert "call remove_item" in lower
    assert "substitutions" in lower
    assert "call remove_item for the old line, then" in lower
    assert "add_item for the new one" in lower
    assert "quantity changes" in lower
    assert "size changes" in lower
    assert "call update_item" in lower
    # Size + price coupling is the trickiest discrimination case — the
    # prompt must explicitly keep it on the same line rather than spawning
    # a new add_item (which would duplicate the line at the new size).
    assert "different size of the same item is still one line" in lower
    # Order-type and delivery-address shapes both still covered.
    assert "order-type swap to delivery" in lower
    assert "delivery-address fix" in lower
    assert "call set_delivery_address" in lower
    # Post-correction acknowledgement is short, not a full re-read
    assert "do not re-read" in lower
    assert "whole order" in lower
    # Caps preserve emphasis for Haiku — guard against silent downcasing.
    assert "do NOT re-read" in prompt
    assert "ONE line" in prompt


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
    # Address is read back at confirmation. #260 rephrased "read the
    # delivery address back" to "include the delivery address in the
    # read-back" — the rule is unchanged, just less verbose.
    assert "if order_type is delivery" in lower
    assert "include the delivery address" in lower
    # Pickup-only language is NOT present
    assert "pickup-only" not in lower


def test_format_menu_skips_unavailable_items():
    """Items with available=False must not appear in the LLM-readable
    menu — the dashboard's 'out of stock' toggle is the load-bearing
    feature that lets owners hide items from callers."""
    from app.llm.prompts import _format_menu

    restaurant = Restaurant(
        id="t",
        name="T",
        display_phone="+10000000000",
        twilio_phone="+10000000001",
        address="-",
        hours="-",
        menu={
            "pizzas": [
                {"name": "Margherita", "price": 12.99, "available": True},
                {"name": "Pepperoni", "price": 15.99, "available": False},
            ],
        },
    )
    rendered = _format_menu(restaurant)
    assert "Margherita" in rendered
    assert "Pepperoni" not in rendered


def test_format_menu_treats_missing_available_as_true():
    """Legacy items without an `available` field default to available
    (back-compat with pre-Sprint-2.4 menu docs)."""
    from app.llm.prompts import _format_menu

    restaurant = Restaurant(
        id="t",
        name="T",
        display_phone="+10000000000",
        twilio_phone="+10000000001",
        address="-",
        hours="-",
        menu={
            "pizzas": [
                {"name": "Margherita", "price": 12.99},  # no available field
            ],
        },
    )
    rendered = _format_menu(restaurant)
    assert "Margherita" in rendered


def test_format_menu_skips_category_when_all_items_unavailable():
    """A category whose every item is unavailable should not appear as
    a naked header in the prompt."""
    from app.llm.prompts import _format_menu

    restaurant = Restaurant(
        id="t",
        name="T",
        display_phone="+10000000000",
        twilio_phone="+10000000001",
        address="-",
        hours="-",
        menu={
            "pizzas": [
                {"name": "Pepperoni", "price": 15.99, "available": False},
            ],
        },
    )
    rendered = _format_menu(restaurant)
    assert "Pizzas:" not in rendered
    assert "Pepperoni" not in rendered


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
