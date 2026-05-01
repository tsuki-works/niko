"""Render an ``HoursStructured`` value to the LLM-readable ``hours: str``
the prompt builder consumes. The renderer collapses contiguous runs of
identical days (Mon-Wed 11:00-22:00) and inlines closed-day notes
(Sun: closed) so the rendered text stays compact."""

from __future__ import annotations

from app.restaurants.models import DayHours, HoursStructured

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_LABELS = {
    "mon": "Mon",
    "tue": "Tue",
    "wed": "Wed",
    "thu": "Thu",
    "fri": "Fri",
    "sat": "Sat",
    "sun": "Sun",
}


def _key(d: DayHours) -> tuple[bool, str, str]:
    return (d.closed, d.open, d.close)


def render_hours_text(hours: HoursStructured) -> str:
    """Collapse contiguous runs of identical days into ranges; mark
    closed days inline. Returns a compact one-line description suitable
    for the system prompt."""
    days = [(d, getattr(hours, d)) for d in _DAYS]

    parts: list[str] = []
    i = 0
    while i < len(days):
        start_key = _key(days[i][1])
        j = i
        while j + 1 < len(days) and _key(days[j + 1][1]) == start_key:
            j += 1

        first_label = _LABELS[days[i][0]]
        last_label = _LABELS[days[j][0]]
        span = first_label if i == j else f"{first_label}-{last_label}"

        spec = days[i][1]
        if spec.closed:
            parts.append(f"{span}: closed")
        else:
            parts.append(f"{span} {spec.open}-{spec.close}")

        i = j + 1

    return ", ".join(parts)
