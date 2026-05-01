"""Unit tests for app.restaurants.hours.render_hours_text."""

from app.restaurants.hours import render_hours_text
from app.restaurants.models import DayHours, HoursStructured


def _all_days(open_t: str, close_t: str, closed: bool = False) -> HoursStructured:
    payload = DayHours(open=open_t, close=close_t, closed=closed)
    return HoursStructured(
        mon=payload,
        tue=payload,
        wed=payload,
        thu=payload,
        fri=payload,
        sat=payload,
        sun=payload,
    )


def test_render_hours_text_collapses_uniform_week():
    """All seven days identical → "Mon-Sun 11:00-22:00"."""
    text = render_hours_text(_all_days("11:00", "22:00"))
    assert text == "Mon-Sun 11:00-22:00"


def test_render_hours_text_handles_per_day_when_mixed():
    h = HoursStructured(
        mon=DayHours(open="11:00", close="22:00", closed=False),
        tue=DayHours(open="11:00", close="22:00", closed=False),
        wed=DayHours(open="11:00", close="22:00", closed=False),
        thu=DayHours(open="11:00", close="22:00", closed=False),
        fri=DayHours(open="11:00", close="23:00", closed=False),
        sat=DayHours(open="11:00", close="23:00", closed=False),
        sun=DayHours(open="00:00", close="00:00", closed=True),
    )
    text = render_hours_text(h)
    assert "Mon" in text and "11:00-22:00" in text
    assert "Fri" in text and "11:00-23:00" in text
    assert "Sun: closed" in text


def test_render_hours_text_marks_all_closed_day_as_closed():
    h = HoursStructured(
        mon=DayHours(open="00:00", close="00:00", closed=True),
        tue=DayHours(open="11:00", close="22:00", closed=False),
        wed=DayHours(open="11:00", close="22:00", closed=False),
        thu=DayHours(open="11:00", close="22:00", closed=False),
        fri=DayHours(open="11:00", close="22:00", closed=False),
        sat=DayHours(open="11:00", close="22:00", closed=False),
        sun=DayHours(open="11:00", close="22:00", closed=False),
    )
    text = render_hours_text(h)
    assert "Mon: closed" in text
    assert "Tue-Sun 11:00-22:00" in text
