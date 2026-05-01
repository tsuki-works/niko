"""Integration tests for the dashboard-facing restaurants endpoints
(``GET /restaurants/me`` already exists; this file covers the new
``PATCH /restaurants/me``)."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth.dependency import Tenant, current_tenant
from app.main import app
from app.storage import restaurants as r_storage


@pytest.fixture
def fake_tenant():
    return Tenant(
        uid="user-1",
        email="owner@niko.test",
        restaurant_id="niko-pizza-kitchen",
        role="owner",
    )


@pytest.fixture
def client(fake_tenant: Tenant):
    app.dependency_overrides[current_tenant] = lambda: fake_tenant
    yield TestClient(app)
    app.dependency_overrides.pop(current_tenant, None)


@pytest.fixture(autouse=True)
def reset_storage():
    yield
    r_storage.set_client(None)
    r_storage.clear_cache()


def _existing_doc() -> dict:
    return {
        "id": "niko-pizza-kitchen",
        "name": "Niko Pizza Kitchen",
        "display_phone": "+15551234567",
        "twilio_phone": "+16479058093",
        "address": "123 Main",
        "hours": "Mon-Sun 11-22",
        "menu": {},
    }


def _wire_storage(existing: dict) -> MagicMock:
    fs = MagicMock()
    r_storage.set_client(fs)
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = existing
    fs.collection.return_value.document.return_value.get.return_value = snap
    return fs


def test_patch_restaurant_updates_name_and_address(client: TestClient):
    fs = _wire_storage(_existing_doc())

    resp = client.patch(
        "/restaurants/me",
        json={"name": "Niko Pizza Kitchen 2.0", "address": "456 New Street"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Niko Pizza Kitchen 2.0"
    assert body["address"] == "456 New Street"
    fs.collection.return_value.document.return_value.set.assert_called_once()


def test_patch_restaurant_regenerates_hours_text_when_structured_changes(
    client: TestClient,
):
    _wire_storage(_existing_doc())

    structured = {
        "mon": {"open": "11:00", "close": "22:00", "closed": False},
        "tue": {"open": "11:00", "close": "22:00", "closed": False},
        "wed": {"open": "11:00", "close": "22:00", "closed": False},
        "thu": {"open": "11:00", "close": "22:00", "closed": False},
        "fri": {"open": "11:00", "close": "23:00", "closed": False},
        "sat": {"open": "11:00", "close": "23:00", "closed": False},
        "sun": {"open": "00:00", "close": "00:00", "closed": True},
    }
    resp = client.patch(
        "/restaurants/me",
        json={"hours_structured": structured},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["hours_structured"] == structured
    # Regenerated ``hours`` text should reflect the structured input
    assert "Mon-Thu 11:00-22:00" in body["hours"]
    assert "Sun: closed" in body["hours"]


def test_patch_restaurant_rejects_unknown_fields(client: TestClient):
    _wire_storage(_existing_doc())

    resp = client.patch(
        "/restaurants/me",
        json={"id": "different-id", "twilio_phone": "+15550000000"},
    )

    # Pydantic strict-extra → 422
    assert resp.status_code == 422


def test_patch_restaurant_404_when_doc_missing(client: TestClient):
    fs = MagicMock()
    r_storage.set_client(fs)
    snap = MagicMock()
    snap.exists = False
    fs.collection.return_value.document.return_value.get.return_value = snap

    resp = client.patch("/restaurants/me", json={"name": "X"})
    assert resp.status_code == 404


def test_patch_restaurant_validates_fallback_phone_format(client: TestClient):
    _wire_storage(_existing_doc())

    # Loose validation: any non-empty E.164-like string is fine; "abc"
    # rejected.
    resp = client.patch("/restaurants/me", json={"fallback_phone": "abc"})
    assert resp.status_code == 422
