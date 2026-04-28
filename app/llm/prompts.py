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
    - If ordering, walk through item, size, and quantity.
    - If delivery, collect the caller's delivery address.

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
    - When the caller corrects something already in the order, emit one update_order with the full corrected state. Replace the wrong item —
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
    - After a correction, briefly acknowledge what changed in one short phrase ("Replaced with a large.", "Two now.") — do NOT re-read the whole order; that happens at the confirmation step.

    Order confirmation read-back:
    - Before asking for confirmation, read back every item with its
      quantity, size (if applicable), and any modifications. For example:
      "So that's one large Margherita with extra cheese and no basil, and
      one Coke — your total is twenty-one ninety-nine. Does that sound right?"
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


def _humanize_category(key: str) -> str:
    """``caribbean_appetizers`` → ``Caribbean Appetizers``. Tenants pick
    their own category keys (``mains``/``soups``/``chow_mein``/...);
    the renderer just title-cases whatever they wrote."""
    return key.replace("_", " ").replace("-", " ").strip().title()


def _format_item_price(item: dict[str, Any]) -> str:
    """Render the price portion of a menu item line.

    Two shapes are supported, mirroring how restaurants actually price:

    - ``sizes: {"small": 12.99, "large": 20.99}`` — multi-size item.
      Renders as ``small $12.99, large $20.99``. Use this when the
      caller has to pick a size as part of the order.
    - ``price: 8.99`` — single-price item. Renders as ``$8.99``.

    If both are present, ``sizes`` wins (it carries more information).
    Returns an empty string when neither is set, so menu items without
    a price (e.g. seasonal "market price") still render cleanly.
    """
    sizes = item.get("sizes") or {}
    if sizes:
        return ", ".join(f"{name} ${price:.2f}" for name, price in sizes.items())
    price = item.get("price")
    if price is not None:
        return f"${price:.2f}"
    return ""


def _ordered_category_keys(menu: dict[str, Any]) -> list[str]:
    """Decide what order to render menu categories in.

    Firestore doesn't preserve dict insertion order on round-trip
    (maps are stored unordered server-side; the SDK returns them in
    protobuf order, which is essentially random). So a tenant's menu
    JSON ordered "appetizers, soups, mains, drinks" can come back as
    "mains, drinks, soups, appetizers" — the AI still understands it,
    but the prompt log reads weird and any "first item I'll mention"
    heuristic gets coin-flipped.

    A tenant can pin the order with an ``_category_order`` list in the
    menu dict (a list IS preserved by Firestore). Categories listed
    there render first, in that order; any remaining categories follow
    in whatever order the dict yields. Categories named in
    ``_category_order`` that don't actually exist in the menu are
    silently skipped.
    """
    explicit = menu.get("_category_order")
    if not isinstance(explicit, list) or not explicit:
        return [k for k in menu.keys() if k != "_category_order"]
    ordered: list[str] = []
    seen: set[str] = set()
    for key in explicit:
        if isinstance(key, str) and key in menu and key not in seen and key != "_category_order":
            ordered.append(key)
            seen.add(key)
    for key in menu.keys():
        if key == "_category_order" or key in seen:
            continue
        ordered.append(key)
    return ordered


def _format_menu(restaurant: Restaurant) -> str:
    """Render every populated category in ``restaurant.menu`` as a
    section in the system prompt.

    The shape is intentionally tenant-agnostic: a pizza place writes
    ``pizzas``/``sides``/``drinks``, a Caribbean place writes
    ``appetizers``/``soups``/``fried_rice``/``chow_mein``/....

    Order is controlled by the optional ``_category_order`` key (see
    ``_ordered_category_keys``). Empty categories are skipped so
    unfinished menus don't bloat the prompt with empty headers.
    Non-list values are skipped defensively — Firestore can return
    scalars under unexpected keys, and we'd rather drop them than
    crash the call.
    """
    menu = restaurant.menu
    lines: list[str] = [restaurant.name, ""]

    for category in _ordered_category_keys(menu):
        items = menu.get(category)
        if not isinstance(items, list) or not items:
            continue
        lines.append(f"{_humanize_category(category)}:")
        for item in items:
            name = item.get("name", "")
            if not name:
                continue
            description = (item.get("description") or "").strip()
            price = _format_item_price(item)
            parts = [f"  - {name}"]
            if description:
                parts.append(f" — {description}")
            if price:
                parts.append(f" ({price})")
            lines.append("".join(parts))
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
