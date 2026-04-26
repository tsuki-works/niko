"""Upsert a Firestore ``restaurants/{rid}`` doc without touching Twilio.

Use cases:

- **Reassigning a number** between tenants (e.g. moving the trial
  number from ``niko-pizza-kitchen`` to ``twilight-family-restaurant``).
  ``provision_restaurant.py`` always tries to *buy* a number; this
  script does the Firestore half on its own when the number already
  exists on our account.
- **Creating an "awaiting number" tenant** — pass ``--twilio-phone ""``
  (empty) to write a tenant doc with no Twilio number assigned. The
  dashboard renders the awaiting-number pill and the routing lookup
  short-circuits.
- **Editing one field** — re-running with the same ``--rid`` and the
  fields you want to change is a partial upsert; unspecified fields
  preserve their existing values from Firestore.

Usage:
    python -m scripts.upsert_restaurant \\
        --rid twilight-family-restaurant \\
        --name "Twilight Family Restaurant" \\
        --display-phone +14167546894 \\
        --twilio-phone +16479058093 \\
        --address "55 Nugget Ave., Unit 12, Scarborough, ON M1S 3L1" \\
        --hours "Mon-Wed 11am-10pm, Thu-Sat 11am-2am, Sun 12pm-10pm" \\
        --menu-file restaurants/twilight-family-restaurant.json

To clear a tenant's Twilio number (move it to "awaiting number"):
    python -m scripts.upsert_restaurant --rid niko-pizza-kitchen --twilio-phone ""

Required env (Firestore only — no Twilio):
    GOOGLE_CLOUD_PROJECT, GOOGLE_APPLICATION_CREDENTIALS
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from app.restaurants.models import Restaurant
from app.storage import restaurants as restaurants_storage

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


_SENTINEL = object()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rid", required=True, help="Firestore document id (slug)")
    parser.add_argument("--name", default=_SENTINEL)
    parser.add_argument("--display-phone", default=_SENTINEL)
    parser.add_argument(
        "--twilio-phone",
        default=_SENTINEL,
        help='E.164 number, or "" to clear (awaiting-number state)',
    )
    parser.add_argument("--address", default=_SENTINEL)
    parser.add_argument("--hours", default=_SENTINEL)
    parser.add_argument(
        "--menu-file",
        default=_SENTINEL,
        help="Path to JSON menu file. Replaces the menu wholesale.",
    )
    parser.add_argument(
        "--forwarding-mode",
        default=_SENTINEL,
        choices=["always", "busy", "noanswer"],
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the Firestore write; just print the merged doc.",
    )
    return parser.parse_args()


def _maybe(args: argparse.Namespace, attr: str):
    """Return the CLI value when supplied, otherwise the sentinel."""
    return getattr(args, attr.replace("-", "_"))


def main() -> int:
    args = _parse_args()

    existing = restaurants_storage.get_restaurant(args.rid)
    if existing is None:
        # New tenant — every field except optional ones must be supplied.
        required = ("name", "display_phone", "twilio_phone", "address", "hours", "menu_file")
        missing = [f for f in required if _maybe(args, f) is _SENTINEL]
        if missing:
            raise SystemExit(
                f"Tenant {args.rid!r} doesn't exist; --{', --'.join(m.replace('_', '-') for m in missing)} required"
            )
        merged = _build_new(args)
    else:
        merged = _merge_with_existing(existing, args)

    if args.dry_run:
        logger.info("[dry-run] would upsert restaurants/%s", merged.id)
        logger.info(merged.model_dump_json(indent=2))
        return 0

    restaurants_storage.save_restaurant(merged)
    logger.info("firestore: wrote restaurants/%s", merged.id)
    logger.info(
        "  twilio_phone   = %s",
        merged.twilio_phone or "(unassigned — awaiting number)",
    )
    return 0


def _load_menu(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _build_new(args: argparse.Namespace) -> Restaurant:
    menu = _load_menu(args.menu_file)
    return Restaurant(
        id=args.rid,
        name=args.name,
        display_phone=args.display_phone,
        twilio_phone=args.twilio_phone,
        address=args.address,
        hours=args.hours,
        menu=menu,
        forwarding_mode=(
            args.forwarding_mode if args.forwarding_mode is not _SENTINEL else "always"
        ),
        updated_at=datetime.now(timezone.utc),
    )


def _merge_with_existing(existing: Restaurant, args: argparse.Namespace) -> Restaurant:
    payload = existing.model_dump()
    if _maybe(args, "name") is not _SENTINEL:
        payload["name"] = args.name
    if _maybe(args, "display-phone") is not _SENTINEL:
        payload["display_phone"] = args.display_phone
    if _maybe(args, "twilio-phone") is not _SENTINEL:
        payload["twilio_phone"] = args.twilio_phone
    if _maybe(args, "address") is not _SENTINEL:
        payload["address"] = args.address
    if _maybe(args, "hours") is not _SENTINEL:
        payload["hours"] = args.hours
    if _maybe(args, "menu-file") is not _SENTINEL:
        payload["menu"] = _load_menu(args.menu_file)
    if _maybe(args, "forwarding-mode") is not _SENTINEL:
        payload["forwarding_mode"] = args.forwarding_mode
    payload["updated_at"] = datetime.now(timezone.utc)
    return Restaurant.model_validate(payload)


if __name__ == "__main__":
    sys.exit(main())
