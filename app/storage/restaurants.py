"""Firestore persistence for the ``restaurants`` collection (#79).

PR A wiring:

- ``get_restaurant(rid)`` — load by document id.
- ``get_restaurant_by_twilio_phone(e164)`` — load by Twilio number;
  used by PR B to route inbound calls to the right tenant.
- ``demo_restaurant_from_menu()`` — build a ``Restaurant`` from
  ``app.menu.MENU``. Lets the demo call flow keep working before
  ``scripts/seed_demo_restaurant.py`` has been run.

Reads are cached in-process for ``CACHE_TTL_SECONDS`` so we don't hit
Firestore on every LLM turn. The cache is keyed by both id and
twilio_phone — looking a restaurant up by either resolves to the same
cached object. Cloud Run instances are short-lived (~15 minutes idle),
so a stale cache self-corrects without an explicit invalidation.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from google.cloud import firestore

from app.restaurants.models import Restaurant

logger = logging.getLogger(__name__)

_COLLECTION = "restaurants"

# Demo restaurant id — must match ``Order.restaurant_id`` default in
# ``app/orders/models.py`` so existing flat-collection orders still
# attribute back to this tenant after the PR C migration.
DEMO_RID = "niko-pizza-kitchen"

CACHE_TTL_SECONDS = 60.0

_client: Optional[firestore.Client] = None
_cache: dict[str, tuple[float, Restaurant]] = {}


def _get_client() -> firestore.Client:
    global _client
    if _client is None:
        _client = firestore.Client()
    return _client


def set_client(client: Optional[firestore.Client]) -> None:
    """Override the module-level Firestore client (tests + emulator)."""
    global _client
    _client = client


def clear_cache() -> None:
    """Drop all cached restaurants. Used by tests; rarely needed in prod."""
    _cache.clear()


def _cache_get(key: str) -> Optional[Restaurant]:
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, restaurant = entry
    if time.monotonic() > expires_at:
        _cache.pop(key, None)
        return None
    return restaurant


def _cache_put(restaurant: Restaurant) -> None:
    expires_at = time.monotonic() + CACHE_TTL_SECONDS
    _cache[f"id:{restaurant.id}"] = (expires_at, restaurant)
    _cache[f"twilio:{restaurant.twilio_phone}"] = (expires_at, restaurant)


def get_restaurant(rid: str) -> Optional[Restaurant]:
    """Load a restaurant by its Firestore document id.

    Returns ``None`` when the doc doesn't exist (caller decides
    whether to fall back, 404, or raise).
    """
    cached = _cache_get(f"id:{rid}")
    if cached is not None:
        return cached
    try:
        snap = _get_client().collection(_COLLECTION).document(rid).get()
    except Exception:
        logger.exception("restaurants: load failed rid=%s", rid)
        return None
    if not snap.exists:
        return None
    restaurant = Restaurant.model_validate(snap.to_dict())
    _cache_put(restaurant)
    return restaurant


def get_restaurant_by_twilio_phone(e164: str) -> Optional[Restaurant]:
    """Load a restaurant by the Twilio number it answers on.

    Used by the inbound-call routing path in PR B — Twilio passes the
    dialed number as ``To`` on every webhook. ``e164`` is the E.164
    string (e.g. ``+16479058093``).
    """
    cached = _cache_get(f"twilio:{e164}")
    if cached is not None:
        return cached
    try:
        query = (
            _get_client()
            .collection(_COLLECTION)
            .where("twilio_phone", "==", e164)
            .limit(1)
        )
        docs = list(query.stream())
    except Exception:
        logger.exception("restaurants: phone lookup failed phone=%s", e164)
        return None
    if not docs:
        return None
    restaurant = Restaurant.model_validate(docs[0].to_dict())
    _cache_put(restaurant)
    return restaurant


def save_restaurant(restaurant: Restaurant) -> str:
    """Upsert a restaurant doc keyed by ``restaurant.id``. Used by
    ``scripts/seed_demo_restaurant.py`` and ``scripts/provision_restaurant.py``."""
    payload = restaurant.model_dump(mode="python")
    _get_client().collection(_COLLECTION).document(restaurant.id).set(payload)
    _cache_put(restaurant)
    return restaurant.id


def demo_restaurant_from_menu() -> Restaurant:
    """Build a ``Restaurant`` from the legacy ``app.menu.MENU`` dict.

    Bridges the gap between PR A (this PR) and the seeding step. The
    router prefers a Firestore lookup; if that returns ``None`` because
    the seed hasn't run yet, this fallback keeps the demo call flow
    working. Removed in PR F when ``app/menu.py`` itself goes away.
    """
    from app.menu import MENU

    return Restaurant(
        id=DEMO_RID,
        name=MENU["restaurant"],
        display_phone=MENU["phone"],
        twilio_phone="+16479058093",
        address=MENU["address"],
        hours=MENU["hours"],
        menu={
            "pizzas": MENU["pizzas"],
            "sides": MENU["sides"],
            "drinks": MENU["drinks"],
        },
    )


def load_or_fallback_demo(rid: str = DEMO_RID) -> Restaurant:
    """Load ``rid`` from Firestore, or fall back to the menu-based demo.

    The single chokepoint the call-flow code uses during PR A. Logs a
    one-line warning when falling back so misconfigured tenants are
    visible in Cloud Run logs.
    """
    restaurant = get_restaurant(rid)
    if restaurant is not None:
        return restaurant
    logger.warning(
        "restaurants: %s not in Firestore — falling back to app.menu (demo)",
        rid,
    )
    return demo_restaurant_from_menu()
