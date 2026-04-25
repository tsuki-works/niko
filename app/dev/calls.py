"""Dev-only call-log surface backed by Cloud Logging.

Reads structured telephony log lines from Cloud Logging, groups them by
``call_sid``, and exposes:

- ``list_recent_calls`` — summary per call_sid (start/end, transcript
  count, error flag, terminal status).
- ``get_call_timeline`` — full ordered event timeline for one call_sid.

Authoritative event source is the same Cloud Run service that generated
the logs. The Cloud Run service account needs ``roles/logging.viewer``.

This module is consumed by the ``/dev/calls`` and ``/dev/calls/{call_sid}``
routes, both gated on ``NIKO_DEV_ENDPOINTS=true``. It is **not** a Phase 2
product feature — it's a debug surface for the team.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

# google-cloud-logging is an optional runtime dependency; importing lazily
# keeps unit tests independent of the SDK and lets the routes raise a clear
# error if the deploy environment is missing the package.
try:
    from google.cloud import logging as gcp_logging
except ImportError:  # pragma: no cover - exercised only when SDK absent
    gcp_logging = None  # type: ignore[assignment]


_CALL_SID_RE = re.compile(r"call_sid=(CA\w+)")
_TEXT_RE = re.compile(r"text='([^']*)'")
_TRANSCRIPT_RE = re.compile(r"transcript=('([^']*)'|\"([^\"]*)\")")
_LATENCY_RE = re.compile(r"latency=([0-9.]+)s")

_SERVICE_NAME = os.environ.get("K_SERVICE") or "niko"


@dataclass
class CallEvent:
    timestamp: datetime
    kind: str  # "start" | "transcript_final" | "transcript_interim" | "llm_turn_start" | "first_audio" | "barge_in" | "silence_timeout" | "stop" | "order_confirmed" | "error" | "log"
    text: str  # original log payload (or extracted detail)
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class CallSummary:
    call_sid: str
    started_at: datetime
    ended_at: datetime
    transcript_count: int
    has_error: bool
    status: str  # "confirmed" | "ended" | "in_progress"


def _classify(payload: str) -> tuple[str, dict[str, Any]]:
    """Map a raw log payload into an event kind + extracted details.

    Recognises the lines emitted by ``app.telephony.router`` and falls back
    to ``log`` for everything else (so the timeline still shows context like
    Anthropic / Deepgram HTTP responses or asyncio errors).
    """
    detail: dict[str, Any] = {}
    if "transcript [final]" in payload:
        match = _TEXT_RE.search(payload)
        if match:
            detail["text"] = match.group(1)
        return "transcript_final", detail
    if "transcript [interim]" in payload:
        match = _TEXT_RE.search(payload)
        if match:
            detail["text"] = match.group(1)
        return "transcript_interim", detail
    if "media-stream start" in payload:
        return "start", detail
    if "media-stream stop" in payload:
        return "stop", detail
    if "order confirmed" in payload:
        return "order_confirmed", detail
    if "first_audio" in payload:
        match = _LATENCY_RE.search(payload)
        if match:
            detail["latency_seconds"] = float(match.group(1))
        return "first_audio", detail
    if "llm_turn cancelled (barge-in)" in payload:
        return "barge_in", detail
    if "llm_turn start" in payload:
        match = _TRANSCRIPT_RE.search(payload)
        if match:
            detail["transcript"] = match.group(2) or match.group(3) or ""
        return "llm_turn_start", detail
    if "silence timeout" in payload:
        return "silence_timeout", detail
    if "ERROR" in payload or "Task exception" in payload or "Traceback" in payload:
        return "error", detail
    return "log", detail


def _extract_call_sid(payload: str) -> Optional[str]:
    match = _CALL_SID_RE.search(payload)
    return match.group(1) if match else None


def _entry_payload(entry: Any) -> str:
    """Pull the textual payload out of a Cloud Logging entry.

    Cloud Logging exposes either ``payload`` (text logs) or
    ``json_payload`` (structured). Cloud Run forwards stdout as text by
    default, so most entries land in ``payload``. Be defensive against
    structured payloads that contain a ``message`` field.
    """
    payload = getattr(entry, "payload", None)
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return str(payload.get("message") or payload)
    return str(payload or "")


def _entry_timestamp(entry: Any) -> datetime:
    ts = getattr(entry, "timestamp", None)
    if isinstance(ts, datetime):
        return ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return datetime.now(tz=timezone.utc)


def parse_events(entries: Iterable[Any]) -> dict[str, list[CallEvent]]:
    """Group raw log entries by call_sid and turn each into a CallEvent.

    Entries without a recognisable call_sid are skipped — they're not
    associated with any call. Output is ordered chronologically per call.
    """
    grouped: dict[str, list[CallEvent]] = {}
    for entry in entries:
        payload = _entry_payload(entry)
        call_sid = _extract_call_sid(payload)
        if not call_sid:
            continue
        kind, detail = _classify(payload)
        event = CallEvent(
            timestamp=_entry_timestamp(entry),
            kind=kind,
            text=payload,
            detail=detail,
        )
        grouped.setdefault(call_sid, []).append(event)
    for events in grouped.values():
        events.sort(key=lambda e: e.timestamp)
    return grouped


def summarize(call_sid: str, events: list[CallEvent]) -> CallSummary:
    started = events[0].timestamp
    ended = events[-1].timestamp
    transcript_count = sum(1 for e in events if e.kind == "transcript_final")
    has_error = any(e.kind == "error" for e in events)
    if any(e.kind == "order_confirmed" for e in events):
        status = "confirmed"
    elif any(e.kind == "stop" for e in events):
        status = "ended"
    else:
        status = "in_progress"
    return CallSummary(
        call_sid=call_sid,
        started_at=started,
        ended_at=ended,
        transcript_count=transcript_count,
        has_error=has_error,
        status=status,
    )


def _logging_client():
    if gcp_logging is None:
        raise RuntimeError(
            "google-cloud-logging is not installed. "
            "Add it to requirements.txt and redeploy."
        )
    return gcp_logging.Client()


def _build_filter(hours: int) -> str:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    return (
        f'resource.type="cloud_run_revision" '
        f'resource.labels.service_name="{_SERVICE_NAME}" '
        f'timestamp>="{cutoff.isoformat()}" '
        f'textPayload:"call_sid=CA"'
    )


def fetch_entries(
    *, hours: int, page_size: int = 1000, client: Any = None
) -> Iterable[Any]:
    """Pull recent niko service log entries that mention a call_sid.

    ``client`` is injectable for tests — pass any object with a
    ``list_entries`` method that yields entry-like objects.
    """
    log_client = client or _logging_client()
    filter_str = _build_filter(hours)
    descending = (
        gcp_logging.DESCENDING if gcp_logging is not None else "timestamp desc"
    )
    return log_client.list_entries(
        filter_=filter_str,
        order_by=descending,
        page_size=page_size,
    )


def list_recent_calls(*, hours: int = 24, client: Any = None) -> list[CallSummary]:
    """Return one summary per call_sid seen in the last ``hours``, newest first."""
    grouped = parse_events(fetch_entries(hours=hours, client=client))
    summaries = [summarize(sid, events) for sid, events in grouped.items()]
    summaries.sort(key=lambda s: s.started_at, reverse=True)
    return summaries


def get_call_timeline(
    call_sid: str, *, hours: int = 168, client: Any = None
) -> Optional[list[CallEvent]]:
    """Return the ordered event timeline for a single call_sid, or ``None``
    if no logs exist for it within the lookback window."""
    grouped = parse_events(fetch_entries(hours=hours, client=client))
    return grouped.get(call_sid)
