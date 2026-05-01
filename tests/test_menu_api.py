"""Integration tests for the granular menu endpoints."""

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
        restaurant_id="r1",
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


def _wire(menu: dict) -> MagicMock:
    fs = MagicMock()
    r_storage.set_client(fs)
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {
        "id": "r1",
        "name": "R",
        "display_phone": "+15551234567",
        "twilio_phone": "+15551234567",
        "address": "1 Main",
        "hours": "11-22",
        "menu": menu,
    }
    fs.collection.return_value.document.return_value.get.return_value = snap
    return fs


def test_post_menu_item_appends(client: TestClient):
    fs = _wire({"pizzas": [{"name": "Margherita", "price": 12.99, "available": True}]})
    resp = client.post(
        "/restaurants/me/menu/items",
        json={"category": "pizzas", "name": "Pepperoni", "price": 15.99},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert any(i["name"] == "Pepperoni" for i in body["menu"]["pizzas"])
    fs.collection.return_value.document.return_value.set.assert_called_once()


def test_post_menu_item_409_on_duplicate(client: TestClient):
    _wire({"pizzas": [{"name": "Margherita", "price": 12.99, "available": True}]})
    resp = client.post(
        "/restaurants/me/menu/items",
        json={"category": "pizzas", "name": "Margherita", "price": 99.00},
    )
    assert resp.status_code == 409


def test_patch_menu_item_updates_price(client: TestClient):
    _wire({"pizzas": [{"name": "Margherita", "price": 12.99, "available": True}]})
    resp = client.patch(
        "/restaurants/me/menu/items/pizzas/Margherita",
        json={"price": 14.99},
    )
    assert resp.status_code == 200
    body = resp.json()
    item = body["menu"]["pizzas"][0]
    assert item["price"] == 14.99


def test_patch_menu_item_404_when_not_found(client: TestClient):
    _wire({"pizzas": []})
    resp = client.patch(
        "/restaurants/me/menu/items/pizzas/NotThere",
        json={"price": 10.00},
    )
    assert resp.status_code == 404


def test_delete_menu_item_removes(client: TestClient):
    _wire({"pizzas": [{"name": "Margherita", "price": 12.99}]})
    resp = client.delete(
        "/restaurants/me/menu/items/pizzas/Margherita",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["menu"]["pizzas"] == []


def test_post_category_creates_empty(client: TestClient):
    _wire({"pizzas": []})
    resp = client.post(
        "/restaurants/me/menu/categories",
        json={"key": "drinks"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["menu"]["drinks"] == []


def test_post_category_409_on_duplicate(client: TestClient):
    _wire({"pizzas": []})
    resp = client.post(
        "/restaurants/me/menu/categories",
        json={"key": "pizzas"},
    )
    assert resp.status_code == 409


def test_post_category_rejects_underscore_prefix(client: TestClient):
    _wire({"pizzas": []})
    resp = client.post(
        "/restaurants/me/menu/categories",
        json={"key": "_secret"},
    )
    # Underscore prefix violates the regex pattern
    assert resp.status_code == 422


def test_post_menu_item_403_for_non_owner(client: TestClient, fake_tenant: Tenant):
    """Staff cannot add menu items — owner-only."""
    import dataclasses
    from app.auth.dependency import current_tenant
    staff = dataclasses.replace(fake_tenant, role="staff")
    app.dependency_overrides[current_tenant] = lambda: staff

    _wire({"pizzas": []})
    resp = client.post(
        "/restaurants/me/menu/items",
        json={"category": "pizzas", "name": "X", "price": 10.00},
    )
    assert resp.status_code == 403
