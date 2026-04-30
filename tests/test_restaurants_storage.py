"""Unit tests for the restaurants storage module (#79).

Mocks the Firestore client so the suite stays offline. Covers:

- ``get_restaurant`` happy path + missing doc + cache hit
- ``get_restaurant_by_twilio_phone`` happy path + no match
- ``demo_restaurant_from_menu`` mirrors the legacy ``app.menu.MENU`` shape
- ``load_or_fallback_demo`` falls back to the menu when Firestore is empty
- ``save_restaurant`` populates the cache so a same-process read after
  write doesn't go back to Firestore
"""

from unittest.mock import MagicMock

import pytest

from app.restaurants.models import Restaurant
from app.storage import restaurants as storage


@pytest.fixture(autouse=True)
def _reset_module():
    """Each test starts with a fresh client + empty cache."""
    yield
    storage.set_client(None)
    storage.clear_cache()


def _fake_client() -> MagicMock:
    client = MagicMock()
    storage.set_client(client)
    return client


def _fake_doc(data: dict) -> MagicMock:
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = data
    return snap


def _restaurant_payload(rid: str = "niko-pizza-kitchen") -> dict:
    return {
        "id": rid,
        "name": "Niko's Pizza Kitchen",
        "display_phone": "+16475550100",
        "twilio_phone": "+16479058093",
        "address": "123 Main Street",
        "hours": "11am-10pm",
        "menu": {"pizzas": [], "sides": [], "drinks": []},
        "prompt_overrides": {},
        "forwarding_mode": "always",
    }


def test_get_restaurant_returns_none_when_doc_missing():
    client = _fake_client()
    client.collection.return_value.document.return_value.get.return_value.exists = False

    assert storage.get_restaurant("niko-pizza-kitchen") is None


def test_get_restaurant_hydrates_pydantic_model():
    client = _fake_client()
    snap = _fake_doc(_restaurant_payload())
    client.collection.return_value.document.return_value.get.return_value = snap

    result = storage.get_restaurant("niko-pizza-kitchen")

    assert result is not None
    assert isinstance(result, Restaurant)
    assert result.id == "niko-pizza-kitchen"
    assert result.twilio_phone == "+16479058093"


def test_get_restaurant_caches_within_ttl():
    """Second lookup with the same id must not hit Firestore again."""
    client = _fake_client()
    snap = _fake_doc(_restaurant_payload())
    client.collection.return_value.document.return_value.get.return_value = snap

    storage.get_restaurant("niko-pizza-kitchen")
    storage.get_restaurant("niko-pizza-kitchen")

    # ``.get()`` should only have been called once across the two reads.
    get_calls = client.collection.return_value.document.return_value.get.call_count
    assert get_calls == 1


def test_get_restaurant_by_twilio_phone_returns_doc():
    client = _fake_client()
    snap = _fake_doc(_restaurant_payload())
    query = (
        client.collection.return_value
        .where.return_value
        .limit.return_value
    )
    query.stream.return_value = iter([snap])

    result = storage.get_restaurant_by_twilio_phone("+16479058093")

    assert result is not None
    assert result.id == "niko-pizza-kitchen"
    client.collection.return_value.where.assert_called_with(
        "twilio_phone", "==", "+16479058093"
    )


def test_get_restaurant_by_twilio_phone_returns_none_when_no_match():
    client = _fake_client()
    query = (
        client.collection.return_value
        .where.return_value
        .limit.return_value
    )
    query.stream.return_value = iter([])

    assert storage.get_restaurant_by_twilio_phone("+19990000000") is None


def test_save_restaurant_populates_cache():
    """Caches by both id and twilio_phone — a save followed by either
    lookup avoids a Firestore round-trip."""
    client = _fake_client()
    restaurant = Restaurant.model_validate(_restaurant_payload())

    storage.save_restaurant(restaurant)

    # Reset get-calls so we can assert no Firestore reads happen below.
    client.collection.return_value.document.return_value.get.reset_mock()

    by_id = storage.get_restaurant("niko-pizza-kitchen")
    by_phone = storage.get_restaurant_by_twilio_phone("+16479058093")

    assert by_id is not None and by_id.id == "niko-pizza-kitchen"
    assert by_phone is not None and by_phone.id == "niko-pizza-kitchen"
    client.collection.return_value.document.return_value.get.assert_not_called()
    client.collection.return_value.where.assert_not_called()


def test_demo_restaurant_from_menu_mirrors_legacy_menu():
    from app.menu import MENU

    restaurant = storage.demo_restaurant_from_menu()

    assert restaurant.id == "niko-pizza-kitchen"
    assert restaurant.name == MENU["restaurant"]
    assert restaurant.address == MENU["address"]
    assert restaurant.hours == MENU["hours"]
    assert restaurant.menu["pizzas"] == MENU["pizzas"]
    assert restaurant.menu["sides"] == MENU["sides"]
    assert restaurant.menu["drinks"] == MENU["drinks"]


def test_load_or_fallback_demo_uses_firestore_when_present():
    client = _fake_client()
    snap = _fake_doc(_restaurant_payload())
    client.collection.return_value.document.return_value.get.return_value = snap

    result = storage.load_or_fallback_demo()
    assert result.name == "Niko's Pizza Kitchen"


def test_load_or_fallback_demo_falls_back_when_doc_missing(caplog):
    client = _fake_client()
    client.collection.return_value.document.return_value.get.return_value.exists = False

    with caplog.at_level("WARNING"):
        result = storage.load_or_fallback_demo()

    assert result.id == "niko-pizza-kitchen"
    assert any("falling back" in rec.message for rec in caplog.records)


def test_get_restaurant_returns_none_when_firestore_raises(caplog):
    """A transient Firestore error must not crash the call flow — the
    router treats ``None`` as a fallback signal."""
    client = _fake_client()
    client.collection.return_value.document.return_value.get.side_effect = (
        RuntimeError("firestore unavailable")
    )

    with caplog.at_level("ERROR"):
        result = storage.get_restaurant("niko-pizza-kitchen")

    assert result is None


def test_restaurant_offers_delivery_defaults_to_true():
    """Sprint 2.2 #105 — every restaurant offers delivery unless explicitly
    flagged off. Default True preserves current behavior for existing
    Firestore docs, no migration needed."""
    r = Restaurant(
        id="t",
        name="T",
        display_phone="+10000000000",
        twilio_phone="+10000000001",
        address="-",
        hours="-",
    )
    assert r.offers_delivery is True

    r_off = Restaurant(
        id="t",
        name="T",
        display_phone="+10000000000",
        twilio_phone="+10000000001",
        address="-",
        hours="-",
        offers_delivery=False,
    )
    assert r_off.offers_delivery is False


def test_restaurant_recording_retention_default_is_90():
    from app.restaurants.models import Restaurant

    r = Restaurant(
        id="x", name="X", display_phone="+1", twilio_phone="+1",
        address="a", hours="h", menu={"pizzas": [], "sides": [], "drinks": []},
    )
    assert r.recording_retention_days == 90


def test_restaurant_recording_retention_accepts_override():
    from app.restaurants.models import Restaurant

    r = Restaurant(
        id="x", name="X", display_phone="+1", twilio_phone="+1",
        address="a", hours="h",
        menu={"pizzas": [], "sides": [], "drinks": []},
        recording_retention_days=30,
    )
    assert r.recording_retention_days == 30


def test_restaurant_recording_retention_rejects_zero_or_negative():
    import pytest
    from pydantic import ValidationError
    from app.restaurants.models import Restaurant

    with pytest.raises(ValidationError):
        Restaurant(
            id="x", name="X", display_phone="+1", twilio_phone="+1",
            address="a", hours="h",
            menu={"pizzas": [], "sides": [], "drinks": []},
            recording_retention_days=0,
        )
