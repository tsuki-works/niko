"""Restaurant Pydantic model for multi-tenancy (#79).

One ``Restaurant`` doc per tenant in Firestore at ``restaurants/{id}``.
The ``id`` is the Firestore document key (e.g. ``niko-pizza-kitchen``).
Every field that drives runtime behavior — menu, address, prompt
overrides — is read fresh per call rather than baked at module import,
so an update in Firestore takes effect on the next call without a
redeploy.

Two phone fields, intentionally split:

- ``display_phone`` — what customers dial; on Google Maps, menus,
  signage. Never used for routing.
- ``twilio_phone`` — the number we provisioned for this restaurant.
  Twilio's ``To`` field on inbound calls equals this. PR B keys the
  routing lookup off it.

The customer's existing line is configured (carrier-side) to forward
inbound calls to ``twilio_phone``. Restaurant keeps their published
number; we sit behind it.

``menu`` stays a free-form dict to match the existing
``app.menu.MENU`` shape during the migration. A stricter
``MenuItem`` / ``Menu`` schema is a follow-up — Sprint 2.4 owns the
menu CRUD UI and is the right time to tighten validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Restaurant(BaseModel):
    id: str
    name: str
    display_phone: str
    twilio_phone: str
    address: str
    hours: str
    menu: dict[str, Any] = Field(default_factory=dict)
    # Free-form per-restaurant prompt nudges (e.g. ``greeting_addendum``,
    # ``tone``). Consumed by ``app.llm.prompts.build_system_prompt``.
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
    # Informational only — we don't enforce it. Tracks how the restaurant
    # configured their carrier-level forwarding so onboarding/support can
    # answer "why are calls landing here?".
    forwarding_mode: str = "always"
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)
