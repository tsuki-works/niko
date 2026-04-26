"""Haiku 4.5 system prompt builder for the voice agent.

Built per call from a ``Restaurant`` object (loaded by the call-flow
orchestrator in ``app/telephony/router.py``). Pre-#79 this module was
a singleton — ``SYSTEM_PROMPT`` baked from ``app.menu.MENU`` at import
time. Multi-tenancy means the prompt has to vary per call, so the
singleton is gone; build fresh on each ``media-stream start``.

The prompt is tuned for voice output: short replies, natural phrasing,
no markdown or lists (all of which sound wrong through TTS).
"""

from __future__ import annotations

from textwrap import dedent
from typing import Any

from app.restaurants.models import Restaurant

_PREAMBLE = dedent("""\
    You are niko, a friendly voice ordering agent answering the phone for {restaurant}.
    Your words are synthesized into audio, so:

    - Keep replies short — usually one or two sentences.
    - No markdown, lists, bullet points, or emojis.
    - Speak naturally, like a real person on the phone.
    - Read prices as words ("twelve ninety-nine"), not digits.

    Help callers with two things:
    1. Place a pickup or delivery order from the menu below.
    2. Answer quick questions about hours, menu items, or location.

    Conversation flow:
    - Greet the caller briefly and ask how you can help.
    - Identify intent — ordering, question, or something else.
    - If ordering, walk through item, size, quantity, and any modifications.
    - Confirm the full order (items plus total) before wrapping up.
    - If delivery, collect the caller's delivery address.

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
""")


def _format_menu(restaurant: Restaurant) -> str:
    menu = restaurant.menu
    lines: list[str] = [restaurant.name, ""]

    pizzas: list[dict[str, Any]] = menu.get("pizzas", []) or []
    if pizzas:
        lines.append("Pizzas:")
        for item in pizzas:
            sizes = ", ".join(
                f"{size} ${price:.2f}"
                for size, price in (item.get("sizes") or {}).items()
            )
            desc = item.get("description", "")
            lines.append(f"  - {item['name']} — {desc} ({sizes})")
        lines.append("")

    sides: list[dict[str, Any]] = menu.get("sides", []) or []
    if sides:
        lines.append("Sides:")
        for item in sides:
            lines.append(f"  - {item['name']} — ${item['price']:.2f}")
        lines.append("")

    drinks: list[dict[str, Any]] = menu.get("drinks", []) or []
    if drinks:
        lines.append("Drinks:")
        for item in drinks:
            lines.append(f"  - {item['name']} — ${item['price']:.2f}")
        lines.append("")

    lines.append(f"Hours: {restaurant.hours}")
    lines.append(f"Address: {restaurant.address}")

    return "\n".join(lines)


def build_system_prompt(restaurant: Restaurant) -> str:
    """Render the system prompt for one tenant.

    A ``greeting_addendum`` entry in ``restaurant.prompt_overrides`` is
    appended after the menu — used to inject restaurant-specific tone
    or quirks ("we're family-run since 1972", "ask about today's
    special") without forking the whole prompt.
    """
    body = (
        _PREAMBLE.format(restaurant=restaurant.name)
        + "\nMenu:\n"
        + _format_menu(restaurant)
    )
    addendum = restaurant.prompt_overrides.get("greeting_addendum")
    if addendum:
        body = f"{body}\n\n{addendum.strip()}"
    return body
