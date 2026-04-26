"""List candidate Twilio phone numbers in an area code.

Used by the ``/onboard-restaurant`` skill: present a few options to
the user before purchasing, instead of buying the first available.
Read-only — never purchases anything.

Searches Canada first, falls back to US (matches the order in
``scripts/provision_restaurant.py::_purchase_number``).

Usage:
    python -m scripts.list_twilio_numbers --area-code 416
    python -m scripts.list_twilio_numbers --area-code 416 --limit 10

Required env: ``TWILIO_ACCOUNT_SID``, ``TWILIO_AUTH_TOKEN``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from twilio.rest import Client as TwilioClient

from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--area-code", required=True, help="3-digit NANP area code")
    parser.add_argument(
        "--limit", type=int, default=5, help="How many candidates to return (default 5)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a human table",
    )
    return parser.parse_args()


def _twilio_client() -> TwilioClient:
    sid = settings.twilio_account_sid or os.environ.get("TWILIO_ACCOUNT_SID")
    token = settings.twilio_auth_token or os.environ.get("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        raise SystemExit("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are required")
    return TwilioClient(sid, token)


def _search(twilio: TwilioClient, area_code: str, limit: int) -> tuple[str, list]:
    """Return (country, numbers). Try CA first, fall back to US."""
    available = twilio.available_phone_numbers("CA").local.list(
        area_code=area_code, limit=limit
    )
    if available:
        return "CA", available
    available = twilio.available_phone_numbers("US").local.list(
        area_code=area_code, limit=limit
    )
    return "US", available


def main() -> int:
    args = _parse_args()
    twilio = _twilio_client()
    country, numbers = _search(twilio, args.area_code, args.limit)

    if not numbers:
        msg = f"No numbers available in area code {args.area_code} (CA or US)"
        if args.json:
            print(json.dumps({"country": None, "numbers": [], "error": msg}))
        else:
            logger.info(msg)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "country": country,
                    "numbers": [
                        {
                            "phone_number": n.phone_number,
                            "friendly_name": n.friendly_name,
                            "locality": getattr(n, "locality", None),
                            "region": getattr(n, "region", None),
                        }
                        for n in numbers
                    ],
                },
                indent=2,
            )
        )
        return 0

    logger.info(
        "Available numbers in area code %s (%s) — %d shown:",
        args.area_code,
        country,
        len(numbers),
    )
    for idx, n in enumerate(numbers, start=1):
        locality = getattr(n, "locality", None) or ""
        region = getattr(n, "region", None) or ""
        loc = f" ({locality}, {region})" if locality or region else ""
        logger.info("  %d. %s — %s%s", idx, n.phone_number, n.friendly_name, loc)
    logger.info(
        "\nTo provision with a specific number, pass it to provision_restaurant:"
    )
    logger.info(
        "  python -m scripts.provision_restaurant ... --phone-number <E.164>"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
