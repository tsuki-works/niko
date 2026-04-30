"""Tests for /calls/{call_sid}/recording — playback redirect + delete.

The auth boundary is checked through FastAPI's dep override pattern,
matching ``test_orders_route.py``. GCS and Firestore are stubbed at the
module level so no network call escapes.
"""

import pytest
from fastapi.testclient import TestClient

from app.auth.dependency import Tenant, current_tenant
from app.main import app

client = TestClient(app)

_RID = "niko-pizza-kitchen"
_OWNER = Tenant(uid="u-owner", email="o@x.com", restaurant_id=_RID, role="owner")
_STAFF = Tenant(uid="u-staff", email="s@x.com", restaurant_id=_RID, role="staff")


@pytest.fixture
def override_owner():
    app.dependency_overrides[current_tenant] = lambda: _OWNER
    yield
    app.dependency_overrides.pop(current_tenant, None)


@pytest.fixture
def override_staff():
    app.dependency_overrides[current_tenant] = lambda: _STAFF
    yield
    app.dependency_overrides.pop(current_tenant, None)


# ---------------------------------------------------------------------------
# GET /calls/{sid}/recording — 302 to signed URL
# ---------------------------------------------------------------------------


def test_get_call_recording_returns_302_to_signed_url(override_owner, monkeypatch):
    from app.storage import call_sessions, recordings

    monkeypatch.setattr(
        call_sessions, "get_session",
        lambda call_sid, rid: {"recording_url": f"gs://niko-recordings/{rid}/CAt.mp3"},
    )
    monkeypatch.setattr(
        recordings, "generate_signed_url",
        lambda *, call_sid, restaurant_id: "https://signed.example/?sig=fake",
    )

    r = client.get("/calls/CAt/recording", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"] == "https://signed.example/?sig=fake"


def test_get_call_recording_404_when_url_missing(override_owner, monkeypatch):
    from app.storage import call_sessions

    monkeypatch.setattr(
        call_sessions, "get_session",
        lambda call_sid, rid: {"recording_url": None},
    )
    r = client.get("/calls/CAt/recording")
    assert r.status_code == 404


def test_get_call_recording_502_when_url_not_gs(override_owner, monkeypatch):
    """Legacy Firestore docs that still carry a Twilio URL would have
    been served via the old proxy. Refuse them now — only ``gs://``."""
    from app.storage import call_sessions

    monkeypatch.setattr(
        call_sessions, "get_session",
        lambda call_sid, rid: {"recording_url": "https://api.twilio.com/legacy.mp3"},
    )
    r = client.get("/calls/CAt/recording", follow_redirects=False)
    assert r.status_code == 502


# ---------------------------------------------------------------------------
# DELETE /calls/{sid}/recording — owner only
# ---------------------------------------------------------------------------


def test_delete_call_recording_owner_returns_204(override_owner, monkeypatch):
    from app.storage import call_sessions, recordings

    monkeypatch.setattr(
        call_sessions, "get_session",
        lambda call_sid, rid: {"recording_url": f"gs://niko-recordings/{rid}/CAt.mp3"},
    )
    deleted: list[dict] = []
    cleared: list[dict] = []
    monkeypatch.setattr(
        recordings, "delete_recording",
        lambda *, call_sid, restaurant_id: deleted.append({"sid": call_sid, "rid": restaurant_id}),
    )
    monkeypatch.setattr(
        call_sessions, "mark_recording_deleted",
        lambda call_sid, rid: cleared.append({"sid": call_sid, "rid": rid}),
    )

    r = client.delete("/calls/CAt/recording")
    assert r.status_code == 204
    assert deleted == [{"sid": "CAt", "rid": _RID}]
    assert cleared == [{"sid": "CAt", "rid": _RID}]


def test_delete_call_recording_non_owner_returns_403(override_staff):
    r = client.delete("/calls/CAt/recording")
    assert r.status_code == 403


def test_delete_call_recording_404_when_call_missing(override_owner, monkeypatch):
    from app.storage import call_sessions

    monkeypatch.setattr(
        call_sessions, "get_session", lambda call_sid, rid: None
    )
    r = client.delete("/calls/CAt/recording")
    assert r.status_code == 404


def test_delete_call_recording_idempotent_on_no_recording(override_owner, monkeypatch):
    """Call exists but has no recording. The endpoint still returns 204
    — both ``delete_recording`` (idempotent on missing blob) and
    ``mark_recording_deleted`` (idempotent on already-cleared doc)
    handle this gracefully."""
    from app.storage import call_sessions, recordings

    monkeypatch.setattr(
        call_sessions, "get_session",
        lambda call_sid, rid: {"recording_url": None},
    )
    monkeypatch.setattr(recordings, "delete_recording", lambda **kw: None)
    monkeypatch.setattr(call_sessions, "mark_recording_deleted", lambda *a, **kw: None)

    r = client.delete("/calls/CAt/recording")
    assert r.status_code == 204
