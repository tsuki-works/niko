"""Is-the-restaurant-open-right-now check.

Phase 1 hardcodes the timezone to America/Toronto (matches the
dashboard's <LocalTime /> default and ``app.storage.analytics``).
Multi-tz support arrives with multi-location, deferred per
``dashboard/CLAUDE.md``.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from app.restaurants.models import DayHours, HoursStructured, Restaurant

_TZ = ZoneInfo("America/Toronto")
_DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _day_for(dt_local: datetime) -> str:
    # Python: Monday == 0, Sunday == 6. Map to our day keys.
    return _DAY_KEYS[dt_local.weekday()]


def is_open_now(
    restaurant: Restaurant,
    now_utc: Optional[datetime] = None,
) -> bool:
    """Return True if the restaurant is currently open in its local
    timezone. Falls back to True when ``hours_structured`` is None —
    don't silently route callers to voicemail just because hours
    haven't been configured yet."""
    if restaurant.hours_structured is None:
        return True

    now = now_utc or datetime.now(_TZ)
    local = now.astimezone(_TZ)
    day_key = _day_for(local)
    day: DayHours = getattr(restaurant.hours_structured, day_key)

    if day.closed:
        return False

    open_t = _parse_hhmm(day.open)
    close_t = _parse_hhmm(day.close)
    current = local.time()
    return open_t <= current < close_t
