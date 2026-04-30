"""Unit tests for app.storage.call_sessions.

Uses a tiny in-memory Firestore fake — just enough surface to exercise
the storage module's reads and writes. No emulator, no network.

Post-#79 PR C, the storage module dual-writes: every parent and event
write hits BOTH the legacy ``call_sessions/{sid}`` and the nested
``restaurants/{rid}/call_sessions/{sid}`` paths. The fake here tracks
arbitrary path segments so tests can assert both writes landed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.storage import call_sessions

_DEMO_RID = "niko-pizza-kitchen"


# ---------------------------------------------------------------------------
# Fake Firestore — in-memory, path-tuple-keyed
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
    def __init__(self, client: "FakeClient", path: tuple[str, ...]):
        self._client = client
        self._path = path

    def set(self, payload: dict) -> None:
        self._client.docs[self._path] = dict(payload)
        # Ensure subcollections (events) exist as buckets even if empty
        # so iteration tests don't KeyError before any add().
        self._client.events.setdefault(self._path, [])

    def update(self, patch: dict) -> None:
        existing = self._client.docs.setdefault(self._path, {})
        for key, val in patch.items():
            if isinstance(val, _IncrementSentinel):
                existing[key] = existing.get(key, 0) + val.amount
            else:
                existing[key] = val

    def get(self) -> _Snap:
        return _Snap(self._client.docs.get(self._path))

    def collection(self, name: str) -> "_CollectionRef":
        return _CollectionRef(self._client, self._path + (name,))


class _CollectionRef:
    def __init__(self, client: "FakeClient", path: tuple[str, ...]):
        self._client = client
        self._path = path

    def document(self, doc_id: str) -> _DocRef:
        return _DocRef(self._client, self._path + (doc_id,))

    def add(self, payload: dict):
        # Events live under their parent doc's path. We key the bucket
        # by the parent doc path (everything except the trailing
        # collection name).
        bucket_key = self._path[:-1]
        self._client.events.setdefault(bucket_key, []).append(dict(payload))
        return (0.0, None)

    def order_by(self, field, direction=None):
        # Two cases:
        #  - ``call_sessions`` (top-level legacy) → list parent docs
        #  - ``restaurants/{rid}/call_sessions`` → list parent docs
        #  - ``.../events`` → list events for one parent doc
        if self._path[-1] == "events":
            bucket_key = self._path[:-1]
            rows = list(self._client.events.get(bucket_key, []))
        else:
            # Walk all docs whose path is exactly self._path + (doc_id,).
            depth = len(self._path) + 1
            rows = [
                doc
                for path, doc in self._client.docs.items()
                if len(path) == depth and path[: len(self._path)] == self._path
            ]
        return _Query(rows).order_by(field, direction)


class FakeClient:
    def __init__(self):
        # Path tuple → doc dict
        self.docs: dict[tuple[str, ...], dict] = {}
        # Parent path tuple → list of event payload dicts (flat list)
        self.events: dict[tuple[str, ...], list[dict]] = {}

    def collection(self, name: str) -> _CollectionRef:
        return _CollectionRef(self, (name,))


_LEGACY = ("call_sessions",)


def _legacy_parent(call_sid: str) -> tuple[str, ...]:
    return _LEGACY + (call_sid,)


def _nested_parent(rid: str, call_sid: str) -> tuple[str, ...]:
    return ("restaurants", rid, "call_sessions", call_sid)


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
    call_sessions.init_call_session("CAtest", _DEMO_RID, started_at=started)

    legacy = fake_client.docs[_legacy_parent("CAtest")]
    nested = fake_client.docs[_nested_parent(_DEMO_RID, "CAtest")]

    for doc in (legacy, nested):
        assert doc["call_sid"] == "CAtest"
        assert doc["status"] == "in_progress"
        assert doc["started_at"] == started
        assert doc["ended_at"] is None
        assert doc["transcript_count"] == 0
        assert doc["has_error"] is False

    # Only the nested doc carries restaurant_id; legacy stays minimal so
    # the dashboard's existing schema doesn't break before PR D.
    assert nested["restaurant_id"] == _DEMO_RID
    assert "restaurant_id" not in legacy


def test_record_event_appends_to_both_paths(fake_client):
    """Every event lands in BOTH legacy and nested events buckets."""
    call_sessions.init_call_session("CAtest", _DEMO_RID)
    call_sessions.record_event(
        "CAtest",
        _DEMO_RID,
        kind="transcript_final",
        text="hello",
        detail={"text": "hello"},
    )
    call_sessions.record_event(
        "CAtest",
        _DEMO_RID,
        kind="transcript_final",
        text="goodbye",
        detail={"text": "goodbye"},
    )

    legacy_events = fake_client.events[_legacy_parent("CAtest")]
    nested_events = fake_client.events[_nested_parent(_DEMO_RID, "CAtest")]
    assert [e["kind"] for e in legacy_events] == ["transcript_final", "transcript_final"]
    assert [e["kind"] for e in nested_events] == ["transcript_final", "transcript_final"]
    assert legacy_events[0]["text"] == "hello"

    # transcript_count incremented on both parents.
    assert fake_client.docs[_legacy_parent("CAtest")]["transcript_count"] == 2
    assert fake_client.docs[_nested_parent(_DEMO_RID, "CAtest")]["transcript_count"] == 2


def test_record_event_error_kind_flips_has_error(fake_client):
    call_sessions.init_call_session("CAtest", _DEMO_RID)
    call_sessions.record_event(
        "CAtest", _DEMO_RID, kind="error", text="500 from anthropic"
    )

    assert fake_client.docs[_legacy_parent("CAtest")]["has_error"] is True
    assert fake_client.docs[_nested_parent(_DEMO_RID, "CAtest")]["has_error"] is True


def test_mark_call_ended_confirmed_status(fake_client):
    call_sessions.init_call_session("CAconfirmed", _DEMO_RID)
    end = datetime(2026, 4, 25, 22, 5, tzinfo=timezone.utc)
    call_sessions.mark_call_ended(
        "CAconfirmed", _DEMO_RID, confirmed=True, ended_at=end
    )

    for path in (_legacy_parent("CAconfirmed"), _nested_parent(_DEMO_RID, "CAconfirmed")):
        doc = fake_client.docs[path]
        assert doc["status"] == "confirmed"
        assert doc["ended_at"] == end


def test_mark_call_ended_unconfirmed_becomes_ended(fake_client):
    call_sessions.init_call_session("CAdrop", _DEMO_RID)
    call_sessions.mark_call_ended("CAdrop", _DEMO_RID, confirmed=False)

    for path in (_legacy_parent("CAdrop"), _nested_parent(_DEMO_RID, "CAdrop")):
        assert fake_client.docs[path]["status"] == "ended"


def test_list_recent_sessions_reads_from_nested_path(fake_client):
    early = datetime(2026, 4, 25, 22, 0, tzinfo=timezone.utc)
    late = early + timedelta(minutes=15)
    call_sessions.init_call_session("CAearly", _DEMO_RID, started_at=early)
    call_sessions.init_call_session("CAlate", _DEMO_RID, started_at=late)

    sessions = call_sessions.list_recent_sessions(_DEMO_RID, limit=10)
    sids = [s["call_sid"] for s in sessions]
    assert sids == ["CAlate", "CAearly"]


def test_list_recent_sessions_scopes_by_restaurant(fake_client):
    """A different tenant's sessions don't leak into the result."""
    call_sessions.init_call_session("CAfor-niko", _DEMO_RID)
    call_sessions.init_call_session("CAfor-palace", "pizza-palace")

    niko_sessions = call_sessions.list_recent_sessions(_DEMO_RID, limit=10)
    assert [s["call_sid"] for s in niko_sessions] == ["CAfor-niko"]

    palace_sessions = call_sessions.list_recent_sessions("pizza-palace", limit=10)
    assert [s["call_sid"] for s in palace_sessions] == ["CAfor-palace"]


def test_get_session_events_returns_events_for_known_call(fake_client):
    call_sessions.init_call_session("CAknown", _DEMO_RID)
    call_sessions.record_event("CAknown", _DEMO_RID, kind="start")
    call_sessions.record_event(
        "CAknown",
        _DEMO_RID,
        kind="transcript_final",
        text="hi",
        detail={"text": "hi"},
    )

    events = call_sessions.get_session_events("CAknown", _DEMO_RID)
    assert events is not None
    assert [e["kind"] for e in events] == ["start", "transcript_final"]


def test_get_session_events_returns_none_for_unknown_call(fake_client):
    assert call_sessions.get_session_events("CAmissing", _DEMO_RID) is None


def test_record_event_swallows_firestore_exceptions(fake_client):
    """Critical contract: a Firestore failure mid-call must NOT propagate
    out of record_event(). The audio loop is more important than the
    dev dashboard."""

    class BoomClient:
        def collection(self, *_a, **_k):
            raise RuntimeError("firestore exploded")

    call_sessions.set_client(BoomClient())
    # No exception escaping is the assertion.
    call_sessions.record_event(
        "CAtest", _DEMO_RID, kind="transcript_final", text="hi"
    )


def test_mark_recording_deleted_clears_url_and_emits_event(monkeypatch):
    from app.storage import call_sessions

    patches: list[dict] = []
    events: list[dict] = []

    class FakeDoc:
        def __init__(self):
            self._collection = FakeCollection(events)
        def update(self, patch):
            patches.append(patch)
        def collection(self, _name):
            return self._collection

    class FakeCollection:
        def __init__(self, events):
            self._events = events
        def add(self, payload):
            self._events.append(payload)

    fake_legacy = FakeDoc()
    fake_nested = FakeDoc()

    monkeypatch.setattr(call_sessions, "_get_client", lambda: object())
    monkeypatch.setattr(call_sessions, "_legacy_parent", lambda _c, _sid: fake_legacy)
    monkeypatch.setattr(call_sessions, "_nested_parent", lambda _c, _rid, _sid: fake_nested)

    call_sessions.mark_recording_deleted("CAtest", "rid1")

    # Both parents are cleared
    assert len(patches) == 2
    for p in patches:
        assert p.get("recording_url") is None
        assert p.get("recording_sid") is None
        assert p.get("recording_duration_seconds") is None

    # An event was appended on each side
    assert len(events) == 2
    for ev in events:
        assert ev["kind"] == "recording_deleted"
