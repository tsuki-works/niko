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
