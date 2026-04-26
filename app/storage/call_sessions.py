"""Firestore persistence for live call sessions.

Two collections:

  call_sessions/{call_sid}                — parent doc with summary fields
  call_sessions/{call_sid}/events/{auto}  — one doc per timeline event

The dashboard subscribes to both via ``onSnapshot`` so transcripts appear
in real time as the caller speaks. The Cloud-Logging-backed surface from
#68 is kept around as a pure parser library for backfill but the live
read path is here.

Field names are snake_case to mirror the Pydantic models on the Python
side and the Zod schemas on the dashboard side. Timestamps are written
as Firestore native ``Timestamp`` (via ``datetime``) — the dashboard
converter unwraps them to ``Date``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from google.cloud import firestore

logger = logging.getLogger(__name__)

_COLLECTION = "call_sessions"
_EVENTS_SUBCOLLECTION = "events"

_client: Optional[firestore.Client] = None


def _get_client() -> firestore.Client:
    global _client
    if _client is None:
        _client = firestore.Client()
    return _client


def set_client(client: Optional[firestore.Client]) -> None:
    """Override the module-level Firestore client (for tests + emulator)."""
    global _client
    _client = client


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def init_call_session(call_sid: str, *, started_at: Optional[datetime] = None) -> None:
    """Create or update the parent doc for a fresh call.

    Idempotent: re-calling for the same call_sid resets ``started_at``
    and ``status`` to a fresh in-progress state. Called from
    ``media-stream start``.
    """
    started = started_at or _now()
    doc = {
        "call_sid": call_sid,
        "started_at": started,
        "ended_at": None,
        "status": "in_progress",
        "transcript_count": 0,
        "has_error": False,
        "last_event_at": started,
    }
    try:
        _get_client().collection(_COLLECTION).document(call_sid).set(doc)
    except Exception:
        logger.exception("call_sessions: init failed call_sid=%s", call_sid)


def record_event(
    call_sid: str,
    *,
    kind: str,
    text: str = "",
    detail: Optional[dict[str, Any]] = None,
    timestamp: Optional[datetime] = None,
) -> None:
    """Append one event to the call's events subcollection.

    All known kinds (mirror ``app/dev/calls.py``):
      start | transcript_final | transcript_interim | llm_turn_start |
      first_audio | barge_in | silence_timeout | stop | order_confirmed |
      error | log

    The parent doc's ``transcript_count``, ``has_error``, and
    ``last_event_at`` are kept in sync so the list view doesn't need to
    aggregate per-event subcollections to render badges.
    """
    ts = timestamp or _now()
    payload = {
        "timestamp": ts,
        "kind": kind,
        "text": text,
        "detail": detail or {},
    }
    try:
        client = _get_client()
        parent = client.collection(_COLLECTION).document(call_sid)
        parent.collection(_EVENTS_SUBCOLLECTION).add(payload)

        update: dict[str, Any] = {"last_event_at": ts}
        if kind == "transcript_final":
            update["transcript_count"] = firestore.Increment(1)
        if kind == "error":
            update["has_error"] = True
        parent.update(update)
    except Exception:
        logger.exception(
            "call_sessions: record_event failed call_sid=%s kind=%s",
            call_sid,
            kind,
        )


def list_recent_sessions(limit: int = 50) -> list[dict[str, Any]]:
    """Return parent docs ordered by ``started_at`` desc, newest-first."""
    client = _get_client()
    query = (
        client.collection(_COLLECTION)
        .order_by("started_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [snap.to_dict() for snap in query.stream()]


def get_session_events(call_sid: str) -> Optional[list[dict[str, Any]]]:
    """Return the timeline of events for one call_sid, oldest-first.

    ``None`` when the parent doc doesn't exist (call_sid never tracked).
    Empty list when the parent exists but no events were written yet.
    """
    client = _get_client()
    parent = client.collection(_COLLECTION).document(call_sid).get()
    if not parent.exists:
        return None
    events_query = (
        client.collection(_COLLECTION)
        .document(call_sid)
        .collection(_EVENTS_SUBCOLLECTION)
        .order_by("timestamp")
    )
    return [snap.to_dict() for snap in events_query.stream()]


def mark_call_ended(
    call_sid: str,
    *,
    confirmed: bool,
    ended_at: Optional[datetime] = None,
) -> None:
    """Stamp the parent doc with the terminal state.

    ``status`` flips to ``confirmed`` if the order persisted, otherwise
    ``ended``. Called from the ``finally`` block of ``/media-stream``.
    """
    end = ended_at or _now()
    try:
        _get_client().collection(_COLLECTION).document(call_sid).update(
            {
                "ended_at": end,
                "last_event_at": end,
                "status": "confirmed" if confirmed else "ended",
            }
        )
    except Exception:
        logger.exception(
            "call_sessions: mark_call_ended failed call_sid=%s", call_sid
        )
