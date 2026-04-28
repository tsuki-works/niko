"""Tests for the system prompt builder.

These guard the behavioural directives we tuned across #76, #78, and
#79: address handling, speak-before-tool-use, terminal goodbyes,
and the goodbye/status-flip coupling. Plus the multi-tenancy plumbing
from #79 — the builder accepts a ``Restaurant`` and reads from it
rather than a global menu.

If a future edit accidentally deletes any of these the tests fail
loudly rather than degrading the live caller experience silently.
"""

from app.llm.prompts import build_system_prompt
from app.restaurants.models import Restaurant
from app.storage.restaurants import demo_restaurant_from_menu


def _demo() -> Restaurant:
    return demo_restaurant_from_menu()


def test_prompt_includes_restaurant_name_and_menu_items():
    restaurant = _demo()
    prompt = build_system_prompt(restaurant)
    assert restaurant.name in prompt
    for pizza in restaurant.menu["pizzas"]:
        assert pizza["name"] in prompt


def test_prompt_warns_against_reciting_address_on_pickup_wrapup():
    """Regression for #76 — the placeholder address (or any address) must
    not be volunteered in pickup confirmations."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    assert "restaurant address handling" in lower
    assert "do not recite it during pickup wrap-ups" in lower or "do not recite" in lower
    assert "where are you" in lower  # the only time the address should come up


def test_prompt_requires_text_before_tool_use():
    """Regression for #76 — Haiku must speak first then call update_order,
    so audio starts streaming within the <1s budget on commit turns."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    assert "when you call the update_order tool" in lower
    assert "first" in lower
    assert "never emit update_order before any spoken words" in lower


def test_prompt_makes_confirmation_goodbyes_terminal():
    """Regression for #78 — once the caller confirms, the agent should
    say a brief terminal goodbye and NOT ask another question. Otherwise
    the auto-hangup would cut off whatever the bot asked next."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    assert "closing the call" in lower
    assert "do not ask another follow-up question after confirming" in lower
    # Spot-check that the directive references the confirmed status flow.
    assert 'set the order\'s status to "confirmed"' in lower or "status to confirmed" in lower


def test_prompt_couples_goodbye_phrases_with_status_flip():
    """Regression for #79 — Haiku was saying 'your order is in' without
    calling update_order(status='confirmed'), which left the auto-hangup
    inert. The prompt now insists on the status flip in the same turn."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    assert "critical" in lower
    assert "your order is in" in lower
    assert 'status="confirmed"' in lower


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
    order using the server-verified update_order subtotal, and only
    confirm on an explicit caller yes."""
    prompt = build_system_prompt(_demo())
    lower = prompt.lower()
    assert "read back" in lower
    assert "update_order" in lower
    assert "does that sound right" in lower
    assert "explicitly confirms" in lower


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
    assert "emit one" in lower
    assert "update_order with the full corrected state" in lower
    assert "replace the wrong item" in lower
    # Coverage of each correction shape (one anchor per pattern)
    assert "removals" in lower
    assert "substitutions" in lower
    assert "quantity or size changes" in lower
    assert "order-type swap to delivery" in lower
    assert "delivery-address fix" in lower
    # Post-correction acknowledgement is short, not a full re-read
    assert "do not re-read" in lower
    assert "whole order" in lower
    # Caps preserve emphasis for Haiku — guard against silent downcasing
    # (a3e8d5e had to restore these after the initial commit downcased them).
    assert "emit ONE" in prompt
    assert "FULL corrected state" in prompt
    assert "do NOT re-read" in prompt
