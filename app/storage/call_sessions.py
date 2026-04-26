"""Firestore persistence for live call sessions (#70 + #79 PR C).

Two paths during the multi-tenancy migration:

  Legacy (flat, deprecated, removed in PR F):
    call_sessions/{call_sid}                — parent doc
    call_sessions/{call_sid}/events/{auto}  — one doc per timeline event

  Nested (new canonical, source of truth for backend reads):
    restaurants/{rid}/call_sessions/{call_sid}
    restaurants/{rid}/call_sessions/{call_sid}/events/{auto}

Why dual-write:

The dashboard's live-transcript view subscribes to the legacy flat
``call_sessions`` collection via Firestore ``onSnapshot``. PR D will
switch that subscription to the nested path; until then we keep both
paths in sync so live calls keep streaming to the dashboard. The
extra Firestore writes are negligible at our scale.

Field names are snake_case to mirror the Pydantic models on the
Python side and the Zod schemas on the dashboard side. Timestamps
are written as Firestore native ``Timestamp`` (via ``datetime``) —
the dashboard converter unwraps them to ``Date``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from google.cloud import firestore

logger = logging.getLogger(__name__)

# Legacy flat collection — kept in sync via dual-write so the
# dashboard's onSnapshot subscription doesn't break. Removed in PR F.
_LEGACY_COLLECTION = "call_sessions"
_EVENTS_SUBCOLLECTION = "events"

# Nested canonical path, parented under restaurants/{rid}.
_RESTAURANTS_COLLECTION = "restaurants"
_CALL_SESSIONS_SUBCOLLECTION = "call_sessions"

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


def _legacy_parent(client: firestore.Client, call_sid: str):
    return client.collection(_LEGACY_COLLECTION).document(call_sid)


def _nested_parent(
    client: firestore.Client, restaurant_id: str, call_sid: str
):
    return (
        client.collection(_RESTAURANTS_COLLECTION)
        .document(restaurant_id)
        .collection(_CALL_SESSIONS_SUBCOLLECTION)
        .document(call_sid)
    )


def init_call_session(
    call_sid: str,
    restaurant_id: str,
    *,
    started_at: Optional[datetime] = None,
) -> None:
    """Create or update the parent doc for a fresh call.

    Writes to both the legacy flat path (so the dashboard's onSnapshot
    keeps working) and the nested ``restaurants/{rid}/call_sessions/{sid}``
    path. Idempotent: re-calling for the same ``call_sid`` resets
    ``started_at`` and ``status`` to a fresh in-progress state.

    The nested doc carries ``restaurant_id`` so collectionGroup queries
    can filter without an extra lookup.
    """
    started = started_at or _now()
    legacy_doc = {
        "call_sid": call_sid,
        "started_at": started,
        "ended_at": None,
        "status": "in_progress",
        "transcript_count": 0,
        "has_error": False,
        "last_event_at": started,
    }
    nested_doc = {**legacy_doc, "restaurant_id": restaurant_id}

    try:
        client = _get_client()
        _legacy_parent(client, call_sid).set(legacy_doc)
        _nested_parent(client, restaurant_id, call_sid).set(nested_doc)
    except Exception:
        logger.exception("call_sessions: init failed call_sid=%s", call_sid)


def record_event(
    call_sid: str,
    restaurant_id: str,
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
    aggregate per-event subcollections to render badges. Mirrored to
    both legacy and nested paths.
    """
    ts = timestamp or _now()
    payload = {
        "timestamp": ts,
        "kind": kind,
        "text": text,
        "detail": detail or {},
    }
    update: dict[str, Any] = {"last_event_at": ts}
    if kind == "transcript_final":
        update["transcript_count"] = firestore.Increment(1)
    if kind == "error":
        update["has_error"] = True

    try:
        client = _get_client()

        legacy = _legacy_parent(client, call_sid)
        legacy.collection(_EVENTS_SUBCOLLECTION).add(payload)
        legacy.update(update)

        nested = _nested_parent(client, restaurant_id, call_sid)
        nested.collection(_EVENTS_SUBCOLLECTION).add(payload)
        nested.update(update)
    except Exception:
        logger.exception(
            "call_sessions: record_event failed call_sid=%s kind=%s",
            call_sid,
            kind,
        )


def list_recent_sessions(
    restaurant_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    """Return one restaurant's parent docs ordered by ``started_at`` desc.

    Reads from the nested canonical path. The legacy flat collection is
    no longer authoritative for backend reads.
    """
    client = _get_client()
    query = (
        client.collection(_RESTAURANTS_COLLECTION)
        .document(restaurant_id)
        .collection(_CALL_SESSIONS_SUBCOLLECTION)
        .order_by("started_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [snap.to_dict() for snap in query.stream()]


def get_session_events(
    call_sid: str, restaurant_id: str
) -> Optional[list[dict[str, Any]]]:
    """Return the timeline of events for one call_sid, oldest-first.

    ``None`` when the parent doc doesn't exist (call_sid never tracked).
    Empty list when the parent exists but no events were written yet.
    Reads from the nested canonical path.
    """
    client = _get_client()
    parent = _nested_parent(client, restaurant_id, call_sid).get()
    if not parent.exists:
        return None
    events_query = (
        _nested_parent(client, restaurant_id, call_sid)
        .collection(_EVENTS_SUBCOLLECTION)
        .order_by("timestamp")
    )
    return [snap.to_dict() for snap in events_query.stream()]


def mark_call_ended(
    call_sid: str,
    restaurant_id: str,
    *,
    confirmed: bool,
    ended_at: Optional[datetime] = None,
) -> None:
    """Stamp the parent doc(s) with the terminal state.

    ``status`` flips to ``confirmed`` if the order persisted, otherwise
    ``ended``. Mirrors to both legacy and nested paths.
    """
    end = ended_at or _now()
    patch = {
        "ended_at": end,
        "last_event_at": end,
        "status": "confirmed" if confirmed else "ended",
    }
    try:
        client = _get_client()
        _legacy_parent(client, call_sid).update(patch)
        _nested_parent(client, restaurant_id, call_sid).update(patch)
    except Exception:
        logger.exception(
            "call_sessions: mark_call_ended failed call_sid=%s", call_sid
        )
