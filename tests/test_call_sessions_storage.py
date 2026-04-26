"""Unit tests for app.storage.call_sessions.

Uses a tiny in-memory Firestore fake — just enough surface to exercise
the storage module's reads and writes. No emulator, no network.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.storage import call_sessions


# ---------------------------------------------------------------------------
# Fake Firestore — just the surface we use
# ---------------------------------------------------------------------------


class _Snap:
    def __init__(self, data: dict | None):
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict:
        return dict(self._data or {})


class _IncrementSentinel:
    def __init__(self, amount: int):
        self.amount = amount


class _FakeFirestoreModule:
    """Stand-in for the symbols the storage module imports from
    ``google.cloud.firestore``."""

    Increment = _IncrementSentinel

    class Query:
        DESCENDING = "DESCENDING"


class _Query:
    def __init__(self, rows: list[dict]):
        self._rows = list(rows)
        self._order_field: str | None = None
        self._reverse = False
        self._limit: int | None = None

    def order_by(self, field, direction=None):
        q = _Query(self._rows)
        q._order_field = field
        q._reverse = direction == "DESCENDING"
        q._limit = self._limit
        return q

    def limit(self, n: int):
        q = _Query(self._rows)
        q._order_field = self._order_field
        q._reverse = self._reverse
        q._limit = n
        return q

    def stream(self):
        rows = list(self._rows)
        if self._order_field:
            rows.sort(
                key=lambda r: r.get(self._order_field) or datetime.min.replace(tzinfo=timezone.utc),
                reverse=self._reverse,
            )
        if self._limit is not None:
            rows = rows[: self._limit]
        for r in rows:
            yield _Snap(r)


class _DocRef:
    def __init__(self, client: "FakeClient", call_sid: str):
        self._client = client
        self._call_sid = call_sid

    def set(self, payload: dict) -> None:
        self._client.parents[self._call_sid] = dict(payload)
        self._client.events.setdefault(self._call_sid, [])

    def update(self, patch: dict) -> None:
        existing = self._client.parents.setdefault(self._call_sid, {})
        for key, val in patch.items():
            if isinstance(val, _IncrementSentinel):
                existing[key] = existing.get(key, 0) + val.amount
            else:
                existing[key] = val

    def get(self) -> _Snap:
        return _Snap(self._client.parents.get(self._call_sid))

    def collection(self, name: str) -> "_EventsCollectionRef":
        assert name == "events"
        return _EventsCollectionRef(self._client, self._call_sid)


class _EventsCollectionRef:
    def __init__(self, client: "FakeClient", call_sid: str):
        self._client = client
        self._call_sid = call_sid

    def add(self, payload: dict):
        self._client.events.setdefault(self._call_sid, []).append(dict(payload))
        return (0.0, None)

    def order_by(self, field, direction=None):
        rows = list(self._client.events.get(self._call_sid, []))
        return _Query(rows).order_by(field, direction)


class _ParentCollectionRef:
    def __init__(self, client: "FakeClient"):
        self._client = client

    def document(self, call_sid: str) -> _DocRef:
        return _DocRef(self._client, call_sid)

    def order_by(self, field, direction=None):
        rows = [
            {**doc, "_id": sid} for sid, doc in self._client.parents.items()
        ]
        return _Query(rows).order_by(field, direction)


class FakeClient:
    def __init__(self):
        self.parents: dict[str, dict] = {}
        self.events: dict[str, list[dict]] = {}

    def collection(self, name: str) -> _ParentCollectionRef:
        assert name == "call_sessions"
        return _ParentCollectionRef(self)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_firestore(monkeypatch):
    """Swap the firestore module symbols used by the storage module."""
    monkeypatch.setattr(call_sessions, "firestore", _FakeFirestoreModule)


@pytest.fixture()
def fake_client():
    client = FakeClient()
    call_sessions.set_client(client)
    yield client
    call_sessions.set_client(None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_init_creates_parent_doc_in_progress(fake_client):
    started = datetime(2026, 4, 25, 22, 0, tzinfo=timezone.utc)
    call_sessions.init_call_session("CAtest", started_at=started)

    snap = fake_client.collection("call_sessions").document("CAtest").get()
    assert snap.exists
    doc = snap.to_dict()
    assert doc["call_sid"] == "CAtest"
    assert doc["status"] == "in_progress"
    assert doc["started_at"] == started
    assert doc["ended_at"] is None
    assert doc["transcript_count"] == 0
    assert doc["has_error"] is False


def test_record_event_appends_to_subcollection_and_stamps_parent(fake_client):
    call_sessions.init_call_session("CAtest")
    call_sessions.record_event(
        "CAtest", kind="transcript_final", text="hello", detail={"text": "hello"}
    )
    call_sessions.record_event(
        "CAtest", kind="transcript_final", text="goodbye", detail={"text": "goodbye"}
    )

    snap = fake_client.collection("call_sessions").document("CAtest").get()
    assert snap.to_dict()["transcript_count"] == 2

    rows = list(
        fake_client.collection("call_sessions")
        .document("CAtest")
        .collection("events")
        .order_by("timestamp")
        .stream()
    )
    events = [s.to_dict() for s in rows]
    assert [e["kind"] for e in events] == ["transcript_final", "transcript_final"]
    assert events[0]["text"] == "hello"


def test_record_event_error_kind_flips_has_error(fake_client):
    call_sessions.init_call_session("CAtest")
    call_sessions.record_event("CAtest", kind="error", text="500 from anthropic")

    snap = fake_client.collection("call_sessions").document("CAtest").get()
    assert snap.to_dict()["has_error"] is True


def test_mark_call_ended_confirmed_status(fake_client):
    call_sessions.init_call_session("CAconfirmed")
    end = datetime(2026, 4, 25, 22, 5, tzinfo=timezone.utc)
    call_sessions.mark_call_ended("CAconfirmed", confirmed=True, ended_at=end)

    doc = fake_client.collection("call_sessions").document("CAconfirmed").get().to_dict()
    assert doc["status"] == "confirmed"
    assert doc["ended_at"] == end


def test_mark_call_ended_unconfirmed_becomes_ended(fake_client):
    call_sessions.init_call_session("CAdrop")
    call_sessions.mark_call_ended("CAdrop", confirmed=False)

    doc = fake_client.collection("call_sessions").document("CAdrop").get().to_dict()
    assert doc["status"] == "ended"


def test_list_recent_sessions_orders_by_started_at_desc(fake_client):
    early = datetime(2026, 4, 25, 22, 0, tzinfo=timezone.utc)
    late = early + timedelta(minutes=15)
    call_sessions.init_call_session("CAearly", started_at=early)
    call_sessions.init_call_session("CAlate", started_at=late)

    sessions = call_sessions.list_recent_sessions(limit=10)
    sids = [s["call_sid"] for s in sessions]
    assert sids == ["CAlate", "CAearly"]


def test_get_session_events_returns_events_for_known_call(fake_client):
    call_sessions.init_call_session("CAknown")
    call_sessions.record_event("CAknown", kind="start")
    call_sessions.record_event(
        "CAknown", kind="transcript_final", text="hi", detail={"text": "hi"}
    )

    events = call_sessions.get_session_events("CAknown")
    assert events is not None
    assert [e["kind"] for e in events] == ["start", "transcript_final"]


def test_get_session_events_returns_none_for_unknown_call(fake_client):
    assert call_sessions.get_session_events("CAmissing") is None


def test_record_event_swallows_firestore_exceptions(fake_client):
    """Critical contract: a Firestore failure mid-call must NOT propagate
    out of record_event(). The audio loop is more important than the
    dev dashboard."""

    class BoomClient:
        def collection(self, *_a, **_k):
            raise RuntimeError("firestore exploded")

    call_sessions.set_client(BoomClient())
    # No exception escaping is the assertion.
    call_sessions.record_event("CAtest", kind="transcript_final", text="hi")
