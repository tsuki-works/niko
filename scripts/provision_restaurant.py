"""Provision a new restaurant tenant end-to-end (PR A of #79).

What it does, in order:

1. Buy a Twilio phone number in the requested area code.
2. Configure that number's voice webhook to point at our Cloud Run
   service (``{BACKEND_URL}/voice``).
3. Write a ``restaurants/{rid}`` doc to Firestore with name, address,
   hours, menu, and the new ``twilio_phone``.

After this script runs, the restaurant just needs to set up
forwarding from their existing line to the new Twilio number. See
``docs/onboarding-forwarding.md`` (TODO, PR B).

Usage:
    python -m scripts.provision_restaurant \\
        --rid pizza-palace \\
        --name "Pizza Palace" \\
        --display-phone +14165551234 \\
        --address "456 Queen St W, Toronto" \\
        --hours "Mon-Sun, 11am-11pm" \\
        --area-code 416 \\
        --menu-file restaurants/pizza-palace.json

``--menu-file`` is a JSON file in the shape ``{"pizzas":[...],
"sides":[...], "drinks":[...]}`` — same as ``app.menu.MENU`` minus
the top-level metadata fields.

Required env:
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN — buys + configures number
    BACKEND_URL — e.g. https://niko-ciyyvuq2pq-uc.a.run.app
                  Must be stable; if Cloud Run URL changes, re-run
                  this script's update step.
    GOOGLE_CLOUD_PROJECT, GOOGLE_APPLICATION_CREDENTIALS — Firestore
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

from twilio.rest import Client as TwilioClient

from app.config import settings
from app.restaurants.models import Restaurant
from app.storage import restaurants as restaurants_storage

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rid", required=True, help="Firestore document id (slug)")
    parser.add_argument("--name", required=True)
    parser.add_argument("--display-phone", required=True, help="E.164 customer-facing number")
    parser.add_argument("--address", required=True)
    parser.add_argument("--hours", required=True)
    parser.add_argument("--area-code", required=True, help="3-digit area code for Twilio search")
    parser.add_argument("--menu-file", required=True, help="Path to JSON menu file")
    parser.add_argument(
        "--forwarding-mode",
        default="always",
        choices=["always", "busy", "noanswer"],
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Twilio purchase + Firestore write; just log what would happen",
    )
    return parser.parse_args()


def _twilio_client() -> TwilioClient:
    sid = settings.twilio_account_sid or os.environ.get("TWILIO_ACCOUNT_SID")
    token = settings.twilio_auth_token or os.environ.get("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        raise SystemExit("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are required")
    return TwilioClient(sid, token)


def _backend_url() -> str:
    url = os.environ.get("BACKEND_URL", "").rstrip("/")
    if not url:
        raise SystemExit("BACKEND_URL env var is required (e.g. https://niko-xyz.run.app)")
    return url


def _purchase_number(twilio: TwilioClient, area_code: str) -> str:
    """Buy a US/CA local number in ``area_code``. Returns the E.164 string."""
    available = twilio.available_phone_numbers("CA").local.list(
        area_code=area_code, limit=1
    )
    if not available:
        # Fall back to US if the area code has no Canadian inventory.
        available = twilio.available_phone_numbers("US").local.list(
            area_code=area_code, limit=1
        )
    if not available:
        raise SystemExit(f"No numbers available in area code {area_code}")
    candidate = available[0].phone_number
    logger.info("twilio: purchasing %s (area code %s)", candidate, area_code)
    purchased = twilio.incoming_phone_numbers.create(phone_number=candidate)
    return purchased.phone_number


def _configure_voice_webhook(twilio: TwilioClient, e164: str, backend_url: str) -> None:
    voice_url = f"{backend_url}/voice"
    numbers = twilio.incoming_phone_numbers.list(phone_number=e164, limit=1)
    if not numbers:
        raise SystemExit(f"twilio: number {e164} not found on this account")
    twilio.incoming_phone_numbers(numbers[0].sid).update(
        voice_url=voice_url, voice_method="POST"
    )
    logger.info("twilio: %s voice webhook → %s", e164, voice_url)


def main() -> int:
    args = _parse_args()

    with open(args.menu_file, encoding="utf-8") as fh:
        menu = json.load(fh)

    if args.dry_run:
        twilio_phone = "+10000000000"
        logger.info("[dry-run] would purchase a number in area code %s", args.area_code)
    else:
        twilio = _twilio_client()
        backend_url = _backend_url()
        twilio_phone = _purchase_number(twilio, args.area_code)
        _configure_voice_webhook(twilio, twilio_phone, backend_url)

    restaurant = Restaurant(
        id=args.rid,
        name=args.name,
        display_phone=args.display_phone,
        twilio_phone=twilio_phone,
        address=args.address,
        hours=args.hours,
        menu=menu,
        forwarding_mode=args.forwarding_mode,
        updated_at=datetime.now(timezone.utc),
    )

    if args.dry_run:
        logger.info("[dry-run] would write restaurants/%s", args.rid)
        logger.info(restaurant.model_dump_json(indent=2))
        return 0

    rid = restaurants_storage.save_restaurant(restaurant)
    logger.info("firestore: wrote restaurants/%s", rid)
    logger.info("✔ provisioned %s — twilio_phone=%s", args.name, twilio_phone)
    logger.info(
        "next: configure %s to forward inbound calls to %s",
        args.display_phone,
        twilio_phone,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
