"""Unit tests for app.restaurants.open_check.is_open_now."""

from datetime import datetime, timezone

import pytest

from app.restaurants.models import DayHours, HoursStructured, Restaurant
from app.restaurants.open_check import is_open_now


def _r(hours: HoursStructured | None) -> Restaurant:
    return Restaurant(
        id="r1",
        name="R",
        display_phone="+15551234567",
        twilio_phone="+15551234567",
        address="1 Main",
        hours="11-22",
        hours_structured=hours,
    )


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Build a UTC datetime. Caller accounts for America/Toronto offset.
    May 2026 is EDT (UTC-4)."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_is_open_now_returns_true_when_hours_structured_is_none():
    """No configured hours → assume always open. Conservative default
    so existing tenants don't suddenly land in voicemail."""
    assert is_open_now(_r(None), _utc(2026, 5, 1, 18)) is True


def test_is_open_now_returns_true_within_open_window():
    day = DayHours(open="11:00", close="22:00", closed=False)
    h = HoursStructured(mon=day, tue=day, wed=day, thu=day, fri=day, sat=day, sun=day)
    # 2026-05-01 is a Friday. EDT = UTC-4.
    # 18:00 UTC = 14:00 local → within 11-22 window.
    assert is_open_now(_r(h), _utc(2026, 5, 1, 18)) is True


def test_is_open_now_returns_false_outside_open_window():
    day = DayHours(open="11:00", close="22:00", closed=False)
    h = HoursStructured(mon=day, tue=day, wed=day, thu=day, fri=day, sat=day, sun=day)
    # 06:00 UTC = 02:00 local Friday → closed.
    assert is_open_now(_r(h), _utc(2026, 5, 1, 6)) is False


def test_is_open_now_returns_false_on_closed_day():
    open_day = DayHours(open="11:00", close="22:00", closed=False)
    closed_day = DayHours(open="00:00", close="00:00", closed=True)
    h = HoursStructured(
        mon=open_day,
        tue=open_day,
        wed=open_day,
        thu=open_day,
        fri=open_day,
        sat=open_day,
        sun=closed_day,
    )
    # 2026-05-03 is a Sunday. 18:00 UTC = 14:00 local Sunday.
    assert is_open_now(_r(h), _utc(2026, 5, 3, 18)) is False


def test_is_open_now_handles_late_night_close():
    """A close time of 23:00 includes 22:59 local; excludes 23:01."""
    day = DayHours(open="11:00", close="23:00", closed=False)
    h = HoursStructured(mon=day, tue=day, wed=day, thu=day, fri=day, sat=day, sun=day)
    # 2026-05-02 03:00 UTC = 23:00 local Friday → at the close edge,
    # treat as closed.
    assert is_open_now(_r(h), _utc(2026, 5, 2, 3)) is False
    # 02:59 UTC = 22:59 local Friday → still open.
    assert is_open_now(_r(h), _utc(2026, 5, 2, 2, 59)) is True
