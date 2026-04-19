"""Haiku 4.5 system prompt for the POC voice agent.

Built at import time from ``app.menu.MENU``. The prompt is tuned for
voice output: short replies, natural phrasing, no markdown or lists
(all of which sound wrong through TTS).
"""

from textwrap import dedent

from app.menu import MENU

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
    - If delivery, collect the address.

    If a caller asks for something off-menu, politely say you don't offer it and
    suggest a close alternative. If you're unsure what they said, ask them to
    repeat rather than guessing.
""")


def _format_menu() -> str:
    lines = [MENU["restaurant"], ""]

    lines.append("Pizzas:")
    for item in MENU["pizzas"]:
        sizes = ", ".join(
            f"{size} ${price:.2f}" for size, price in item["sizes"].items()
        )
        lines.append(f"  - {item['name']} — {item['description']} ({sizes})")
    lines.append("")

    lines.append("Sides:")
    for item in MENU["sides"]:
        lines.append(f"  - {item['name']} — ${item['price']:.2f}")
    lines.append("")

    lines.append("Drinks:")
    for item in MENU["drinks"]:
        lines.append(f"  - {item['name']} — ${item['price']:.2f}")
    lines.append("")

    lines.append(f"Hours: {MENU['hours']}")
    lines.append(f"Address: {MENU['address']}")

    return "\n".join(lines)


def build_system_prompt() -> str:
    return (
        _PREAMBLE.format(restaurant=MENU["restaurant"])
        + "\nMenu:\n"
        + _format_menu()
    )


SYSTEM_PROMPT = build_system_prompt()
