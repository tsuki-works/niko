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
  routing lookup off it. **Empty string is the explicit "awaiting
  Twilio number" state** — used between tenant creation and number
  provisioning (e.g. paid-account upgrade pending, manual carrier
  port). The routing lookup short-circuits on empty, the dashboard
  renders an "Awaiting Twilio number" pill, and the kitchen empty
  states fall back to "no number assigned yet" copy.

The customer's existing line is configured (carrier-side) to forward
inbound calls to ``twilio_phone``. Restaurant keeps their published
number; we sit behind it.

``menu`` is a free-form dict so each tenant can pick their own
category keys. A pizza place uses ``pizzas`` / ``sides`` / ``drinks``;
a Caribbean place uses ``appetizers`` / ``soups`` / ``fried_rice`` /
``chow_mein`` / ``drinks``. The prompt builder
(``app.llm.prompts._format_menu``) renders whatever keys are present
in insertion order, so ordering the JSON controls the order categories
appear in the system prompt.

Per-item shape is also flexible:

- ``{"name": ..., "price": 12.99}`` — single-priced items.
- ``{"name": ..., "sizes": {"small": 12.99, "large": 18.99}}`` —
  multi-size items where the caller has to pick a size.
- ``description`` is optional on either shape.

An optional ``_category_order`` list (e.g. ``["appetizers", "soups",
"mains", "drinks"]``) controls prompt rendering order — Firestore
doesn't preserve dict insertion order on round-trip, so a tenant who
cares about order must spell it out. Without ``_category_order``,
categories render in whatever order the deserialized dict yields.

A stricter ``MenuItem`` / ``Menu`` schema is a follow-up — Sprint 2.4
owns the menu CRUD UI and is the right time to tighten validation.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate_hhmm(value: str) -> str:
    if not _HHMM.match(value):
        raise ValueError(f"time must be HH:MM (24-hour), got {value!r}")
    return value


class DayHours(BaseModel):
    """Open/close pair for a single day. Times are local to the
    restaurant's timezone (Phase 1: America/Toronto for everyone;
    multi-tz arrives with multi-location, deferred per
    dashboard/CLAUDE.md)."""

    open: str = Field(description="Local opening time, HH:MM 24-hour")
    close: str = Field(description="Local closing time, HH:MM 24-hour")
    closed: bool = False

    @field_validator("open", "close")
    @classmethod
    def _check_format(cls, v: str) -> str:
        return _validate_hhmm(v)


class HoursStructured(BaseModel):
    """Per-day open/close ranges. The dashboard's hours editor writes
    this; the prompt builder reads ``Restaurant.hours`` (the str
    rendering) so changing this without regenerating ``hours`` would
    drift the LLM. ``RestaurantUpdate`` regenerates ``hours`` on save."""

    mon: DayHours
    tue: DayHours
    wed: DayHours
    thu: DayHours
    fri: DayHours
    sat: DayHours
    sun: DayHours


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
    # Whether this tenant accepts delivery orders. Default True preserves
    # current behavior for existing Firestore docs (Niko Pizza Kitchen,
    # Twilight Family Restaurant). Flip to False in Firestore for
    # pickup-only restaurants — the system prompt branches accordingly.
    offers_delivery: bool = True
    recording_retention_days: int = Field(default=90, ge=1, le=3650)
    hours_structured: Optional[HoursStructured] = None
    # Used by Sprint 2.4 Track 2 (call transfer). E.164. None means
    # the call falls through to voicemail without an attempted dial.
    fallback_phone: Optional[str] = None
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)
