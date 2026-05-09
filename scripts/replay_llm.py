"""Local LLM replay tool — feed a transcript through the production
``generate_reply`` and observe the bot's text replies + tool calls.

Single-variant mode (default — runs against ``app.llm.prompts._PREAMBLE``)::

    python scripts/replay_llm.py dev_recordings/transcripts/foo.json

A/B mode — run the current preamble and a revised preamble side-by-side::

    python scripts/replay_llm.py dev_recordings/transcripts/foo.json \\
        --revised scripts/_preamble_revised.txt

Transcript JSON shape::

    {
      "restaurant": "twilight-family-restaurant",   # restaurants/<name>.json
      "restaurant_name": "Twilight Family Restaurant",
      "offers_delivery": false,
      "turns": [
        {"caller": "[call started — greet the caller]"},
        {"caller": "Can I place an order for pickup?"},
        {"caller": "I'll get one chicken fried rice."}
      ]
    }

The first turn is conventionally the literal greeting trigger
(``GREETING_TRANSCRIPT`` in ``app.telephony.session``); subsequent turns
are the caller's actual utterances.

Design notes
------------
- The harness deliberately does NOT modify ``app/llm/prompts.py``. The
  "revised" variant is built by reading a plain-text preamble template
  from disk and reusing the same ``{restaurant}`` / ``{intro_line}`` /
  ``{delivery_handling}`` / ``{order_type_swap_rule}`` placeholders the
  production builder uses. The menu rendering is delegated back to
  ``app.llm.prompts._format_menu`` so menu output stays identical
  across variants.
- The harness uses the synchronous ``generate_reply`` (not the streaming
  path). We're comparing reply *text* and tool calls; streaming adds
  telemetry noise that's not relevant to prompt-tuning.
- Restaurant fixture is built from the menu JSON in ``restaurants/``
  with dummy values for phone/address/hours so the harness runs offline
  with no Firestore. Real address/hours can come from a fuller fixture
  if that ever matters for prompt evaluation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Ensure ``app`` is importable when running from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from app.llm.client import generate_reply  # noqa: E402
from app.llm.prompts import _PREAMBLE, _format_menu  # noqa: E402, PLC2701
from app.orders.models import Order  # noqa: E402
from app.restaurants.models import Restaurant  # noqa: E402


@dataclass
class TurnOutcome:
    caller: str
    reply_text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    subtotal: float = 0.0
    item_summary: str = "(empty)"


@dataclass
class VariantResult:
    label: str
    system_prompt_chars: int
    turns: list[TurnOutcome] = field(default_factory=list)


def _restaurant_from_menu_file(
    menu_path: Path, *, offers_delivery: bool, name: Optional[str] = None
) -> Restaurant:
    """Build a Restaurant from a menu JSON file, filling the non-menu
    fields with offline-safe defaults. The harness only exercises the
    prompt builder + LLM, so phone/address/hours need to be present
    but don't need to be real."""
    menu = json.loads(menu_path.read_text(encoding="utf-8"))
    rid = menu_path.stem
    display_name = name or rid.replace("-", " ").title()
    return Restaurant(
        id=rid,
        name=display_name,
        display_phone="+10000000000",
        twilio_phone="+10000000000",
        address="123 Replay Street, Test City",
        hours="Open daily 10:00–22:00",
        menu=menu,
        offers_delivery=offers_delivery,
    )


def _build_system_prompt(restaurant: Restaurant, preamble_template: str) -> str:
    """Render a system prompt from a custom preamble, mirroring
    ``app.llm.prompts.build_system_prompt`` without modifying it.

    Kept in sync structurally with the production builder — if
    ``build_system_prompt`` grows new placeholders, this function needs
    the same additions."""
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
            '  "We\'re actually pickup-only — would pickup work for you?"\n'
            "  and continue from there. Do not capture a delivery address;\n"
            "  do not set order_type to delivery."
        )
        order_type_swap_rule = (
            "- Order-type stays pickup. If the caller tries to switch to delivery,\n"
            "  decline politely (we're pickup-only)."
        )

    body = (
        preamble_template.format(
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


def _run_variant(
    *,
    label: str,
    system_prompt: str,
    restaurant: Restaurant,
    turns: list[dict[str, Any]],
    max_turns: Optional[int] = None,
    progress: bool = True,
) -> VariantResult:
    """Replay every caller turn against the LLM with the given system
    prompt. Threads conversation history exactly the way the live
    router does, so multi-turn tool-use semantics match production."""
    order = Order(
        call_sid=f"replay-{restaurant.id}-{label}-{int(time.time())}",
        restaurant_id=restaurant.id,
    )
    history: list[dict[str, Any]] = []
    result = VariantResult(label=label, system_prompt_chars=len(system_prompt))

    iter_turns = turns if max_turns is None else turns[:max_turns]
    total = len(iter_turns)

    for i, turn in enumerate(iter_turns):
        caller_text = turn["caller"]
        if progress:
            print(f"# [{label}] turn {i + 1}/{total}", file=sys.stderr, flush=True)

        resp = generate_reply(
            transcript=caller_text,
            history=history,
            order=order,
            system_prompt=system_prompt,
        )

        # Extract tool_use blocks from any new assistant messages this turn
        # added to history. There can be 1 or 2 assistant messages depending
        # on whether the model called update_order.
        tool_calls: list[dict[str, Any]] = []
        for msg in resp.history[len(history):]:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls.append(
                        {"name": block.get("name"), "input": block.get("input")}
                    )

        items_summary = (
            ", ".join(
                f"{item.quantity}× {item.name}"
                + (f" [{', '.join(item.modifications)}]" if item.modifications else "")
                for item in resp.order.items
            )
            if resp.order.items
            else "(empty)"
        )

        result.turns.append(
            TurnOutcome(
                caller=caller_text,
                reply_text=resp.reply_text,
                tool_calls=tool_calls,
                subtotal=resp.order.subtotal,
                item_summary=items_summary,
            )
        )

        history = resp.history
        order = resp.order

    return result


def _print_pretty(variants: list[VariantResult]) -> None:
    if not variants:
        return
    n_turns = min(len(v.turns) for v in variants)
    label_w = max(len(v.label) for v in variants)
    sep = "-" * 78

    print(sep)
    for v in variants:
        print(f"# variant {v.label!r}: {v.system_prompt_chars} chars system prompt")
    print(sep)

    for i in range(n_turns):
        caller_text = variants[0].turns[i].caller
        print(f"T{i:02d}  CALLER: {caller_text}")
        for v in variants:
            outcome = v.turns[i]
            label = v.label.ljust(label_w)
            indent_first = f"  [{label}] BOT:    "
            indent_cont = " " * len(indent_first)
            wrapped = textwrap.fill(
                outcome.reply_text or "(no text)",
                width=110,
                initial_indent=indent_first,
                subsequent_indent=indent_cont,
                break_long_words=False,
                break_on_hyphens=False,
            )
            print(wrapped)
            for tc in outcome.tool_calls:
                input_repr = json.dumps(tc.get("input"), separators=(",", ":"))
                if len(input_repr) > 120:
                    input_repr = input_repr[:117] + "..."
                print(f"  [{label}] TOOL:   {tc.get('name')}({input_repr})")
            if outcome.tool_calls:
                print(
                    f"  [{label}] STATE:  subtotal=${outcome.subtotal:.2f}, "
                    f"items={outcome.item_summary}"
                )
        print(sep)


def _print_json(variants: list[VariantResult]) -> None:
    payload = [
        {
            "label": v.label,
            "system_prompt_chars": v.system_prompt_chars,
            "turns": [
                {
                    "caller": t.caller,
                    "reply_text": t.reply_text,
                    "tool_calls": t.tool_calls,
                    "subtotal": t.subtotal,
                    "item_summary": t.item_summary,
                }
                for t in v.turns
            ],
        }
        for v in variants
    ]
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Replay a transcript through the production LLM client.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("transcript", type=Path, help="Path to a transcript JSON file")
    p.add_argument(
        "--restaurant",
        type=Path,
        default=None,
        help="Path to restaurants/<rid>.json (default: derived from transcript.restaurant)",
    )
    delivery_grp = p.add_mutually_exclusive_group()
    delivery_grp.add_argument(
        "--offers-delivery",
        dest="offers_delivery",
        action="store_true",
        default=None,
        help="Configure fixture restaurant to accept delivery",
    )
    delivery_grp.add_argument(
        "--no-offers-delivery",
        dest="offers_delivery",
        action="store_false",
        help="Configure fixture restaurant as pickup-only",
    )
    p.add_argument(
        "--revised",
        type=Path,
        default=None,
        help=(
            "Path to a revised preamble template. When provided, runs A/B "
            "mode (current vs revised). When omitted, only the current "
            "preamble runs."
        ),
    )
    p.add_argument(
        "--only-revised",
        type=Path,
        default=None,
        help=(
            "Run ONLY the revised preamble at the given path (skip "
            "current). Mutually exclusive with --revised."
        ),
    )
    p.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Replay only the first N turns (cheap iteration during dev)",
    )
    p.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="Emit machine-readable JSON instead of the pretty side-by-side print",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-turn progress lines on stderr",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Build the system prompt(s) and print them, but do not call "
            "the LLM. Useful for sanity-checking template rendering "
            "without spending API credits."
        ),
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    # The system prompt contains em-dashes, arrows, and other non-ASCII
    # punctuation that Windows' default cp1252 stdout can't encode.
    # Force utf-8 on both streams so dry-run printing and pretty-print
    # both work on Windows. Linux/macOS already default to utf-8.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (AttributeError, OSError):
                pass

    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.revised is not None and args.only_revised is not None:
        sys.exit("--revised and --only-revised are mutually exclusive")

    if not args.dry_run and not os.getenv("ANTHROPIC_API_KEY", "").strip():
        sys.exit(
            "ANTHROPIC_API_KEY not set. Add it to .env (fetch via /shared-creds) "
            "before running the harness."
        )

    transcript = json.loads(args.transcript.read_text(encoding="utf-8"))
    turns = transcript.get("turns", [])
    if not turns:
        sys.exit("Transcript has no 'turns'")

    if args.restaurant is not None:
        menu_path = args.restaurant
    else:
        rid = transcript.get("restaurant")
        if not rid:
            sys.exit(
                "Transcript missing 'restaurant' and --restaurant not provided"
            )
        menu_path = Path("restaurants") / f"{rid}.json"

    if not menu_path.is_file():
        sys.exit(f"Menu file not found: {menu_path}")

    if args.offers_delivery is None:
        offers_delivery = bool(transcript.get("offers_delivery", False))
    else:
        offers_delivery = args.offers_delivery

    restaurant = _restaurant_from_menu_file(
        menu_path,
        offers_delivery=offers_delivery,
        name=transcript.get("restaurant_name"),
    )

    # Decide which variants to run.
    variants_to_run: list[tuple[str, str]] = []
    if args.only_revised is not None:
        if not args.only_revised.is_file():
            sys.exit(f"Revised preamble not found: {args.only_revised}")
        variants_to_run.append(
            ("revised", args.only_revised.read_text(encoding="utf-8"))
        )
    else:
        variants_to_run.append(("current", _PREAMBLE))
        if args.revised is not None:
            if not args.revised.is_file():
                sys.exit(f"Revised preamble not found: {args.revised}")
            variants_to_run.append(
                ("revised", args.revised.read_text(encoding="utf-8"))
            )

    if args.dry_run:
        for label, template in variants_to_run:
            system_prompt = _build_system_prompt(restaurant, template)
            sep = "=" * 78
            print(sep)
            print(f"# variant {label!r}: {len(system_prompt)} chars")
            print(sep)
            print(system_prompt)
            print()
        return 0

    results: list[VariantResult] = []
    for label, template in variants_to_run:
        system_prompt = _build_system_prompt(restaurant, template)
        result = _run_variant(
            label=label,
            system_prompt=system_prompt,
            restaurant=restaurant,
            turns=turns,
            max_turns=args.max_turns,
            progress=not args.quiet,
        )
        results.append(result)

    if args.emit_json:
        _print_json(results)
    else:
        _print_pretty(results)

    return 0


if __name__ == "__main__":
    sys.exit(main())
