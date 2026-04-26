"""Seed the demo restaurant doc into Firestore (PR A of #79).

Idempotent: re-running upserts the same id (``niko-pizza-kitchen``).
Reads menu + business info from ``app.menu.MENU`` so the seed always
matches the current hardcoded source of truth, and bumps
``updated_at`` to ``now``.

Usage:
    python -m scripts.seed_demo_restaurant

Auth: same as the rest of the backend — Cloud Run service account in
prod, ``gcloud auth application-default login`` locally. Set
``GOOGLE_CLOUD_PROJECT=niko-tsuki`` if running outside GCP.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from app.storage import restaurants as restaurants_storage

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    restaurant = restaurants_storage.demo_restaurant_from_menu()
    restaurant.updated_at = datetime.now(timezone.utc)

    rid = restaurants_storage.save_restaurant(restaurant)
    logger.info("seeded restaurants/%s", rid)
    logger.info("  name           = %s", restaurant.name)
    logger.info("  display_phone  = %s", restaurant.display_phone)
    logger.info("  twilio_phone   = %s", restaurant.twilio_phone)
    logger.info(
        "  menu items     = %d pizzas, %d sides, %d drinks",
        len(restaurant.menu.get("pizzas", [])),
        len(restaurant.menu.get("sides", [])),
        len(restaurant.menu.get("drinks", [])),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
