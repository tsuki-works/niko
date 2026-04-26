"""Tests for the system prompt builder.

These guard the two behavioural directives we tuned in #76:

1. The address from app/menu.py must NOT be recited during pickup
   wrap-ups — only used for direct location questions.
2. The agent must speak before calling update_order, never the other
   way around (latency).

Both rules live in `app/llm/prompts.py`. If a future edit accidentally
deletes them the tests fail loudly rather than degrading the live
caller experience silently.
"""
from app.llm.prompts import SYSTEM_PROMPT, build_system_prompt
from app.menu import MENU


def test_prompt_includes_restaurant_name_and_menu_items():
    prompt = build_system_prompt()
    assert MENU["restaurant"] in prompt
    for pizza in MENU["pizzas"]:
        assert pizza["name"] in prompt


def test_prompt_warns_against_reciting_address_on_pickup_wrapup():
    """Regression for #76 — the placeholder address (or any address) must
    not be volunteered in pickup confirmations."""
    prompt = build_system_prompt()
    lower = prompt.lower()
    assert "restaurant address handling" in lower
    assert "do not recite it during pickup wrap-ups" in lower or "do not recite" in lower
    assert "where are you" in lower  # the only time the address should come up


def test_prompt_requires_text_before_tool_use():
    """Regression for #76 — Haiku must speak first then call update_order,
    so audio starts streaming within the <1s budget on commit turns."""
    prompt = build_system_prompt()
    lower = prompt.lower()
    assert "when you call the update_order tool" in lower
    assert "first" in lower
    assert "never emit update_order before any spoken words" in lower


def test_prompt_makes_confirmation_goodbyes_terminal():
    """Regression for #78 — once the caller confirms, the agent should
    say a brief terminal goodbye and NOT ask another question. Otherwise
    the auto-hangup would cut off whatever the bot asked next."""
    prompt = build_system_prompt()
    lower = prompt.lower()
    assert "closing the call" in lower
    assert "do not ask another follow-up question after confirming" in lower
    # Spot-check that the directive references the confirmed status flow.
    assert 'set the order\'s status to "confirmed"' in lower or "status to confirmed" in lower


def test_prompt_couples_goodbye_phrases_with_status_flip():
    """Regression for #79 — Haiku was saying 'your order is in' without
    calling update_order(status='confirmed'), which left the auto-hangup
    inert. The prompt now insists on the status flip in the same turn."""
    prompt = build_system_prompt()
    lower = prompt.lower()
    assert "critical" in lower
    assert "your order is in" in lower
    assert 'status="confirmed"' in lower


def test_module_level_system_prompt_matches_builder():
    """The cached SYSTEM_PROMPT must equal a fresh build — catches the
    case where someone edits build_system_prompt() but forgets that
    SYSTEM_PROMPT is computed at import time."""
    assert SYSTEM_PROMPT == build_system_prompt()
