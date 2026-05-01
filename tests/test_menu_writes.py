"""Unit tests for app.restaurants.menu_writes — pure-function menu
mutations on a Restaurant.menu dict."""

import pytest

from app.restaurants.menu_writes import (
    DuplicateMenuItem,
    MenuItemNotFound,
    add_category,
    add_menu_item,
    delete_menu_item,
    update_menu_item,
)
from app.restaurants.models import (
    CategoryCreate,
    MenuItemCreate,
    MenuItemUpdate,
    Restaurant,
)


def _r() -> Restaurant:
    return Restaurant(
        id="r1",
        name="R",
        display_phone="+15551234567",
        twilio_phone="+15551234567",
        address="1 Main",
        hours="11-22",
        menu={
            "pizzas": [
                {"name": "Margherita", "price": 12.99, "available": True},
            ],
            "sides": [],
        },
    )


def test_add_menu_item_appends_to_existing_category():
    r = _r()
    out = add_menu_item(
        r,
        MenuItemCreate(category="pizzas", name="Pepperoni", price=15.99),
    )
    items = out.menu["pizzas"]
    assert len(items) == 2
    assert items[1]["name"] == "Pepperoni"
    assert items[1]["available"] is True


def test_add_menu_item_creates_category_if_missing():
    r = _r()
    out = add_menu_item(
        r,
        MenuItemCreate(category="drinks", name="Coke", price=2.50),
    )
    assert out.menu["drinks"][0]["name"] == "Coke"


def test_add_menu_item_rejects_duplicate_name_in_category():
    r = _r()
    with pytest.raises(DuplicateMenuItem):
        add_menu_item(
            r,
            MenuItemCreate(category="pizzas", name="Margherita", price=10.00),
        )


def test_update_menu_item_modifies_price_in_place():
    r = _r()
    out = update_menu_item(
        r,
        category="pizzas",
        name="Margherita",
        update=MenuItemUpdate(price=14.99),
    )
    assert out.menu["pizzas"][0]["price"] == 14.99


def test_update_menu_item_renames_when_new_name_set():
    r = _r()
    out = update_menu_item(
        r,
        category="pizzas",
        name="Margherita",
        update=MenuItemUpdate(new_name="Margherita DOP"),
    )
    assert out.menu["pizzas"][0]["name"] == "Margherita DOP"


def test_update_menu_item_moves_category_when_new_category_set():
    r = _r()
    out = update_menu_item(
        r,
        category="pizzas",
        name="Margherita",
        update=MenuItemUpdate(new_category="sides"),
    )
    assert out.menu["pizzas"] == []
    assert any(i["name"] == "Margherita" for i in out.menu["sides"])


def test_update_menu_item_swaps_price_for_sizes():
    r = _r()
    out = update_menu_item(
        r,
        category="pizzas",
        name="Margherita",
        update=MenuItemUpdate(sizes={"small": 10.00, "large": 16.00}),
    )
    item = out.menu["pizzas"][0]
    assert "price" not in item
    assert item["sizes"] == {"small": 10.00, "large": 16.00}


def test_update_menu_item_404_when_not_found():
    r = _r()
    with pytest.raises(MenuItemNotFound):
        update_menu_item(
            r,
            category="pizzas",
            name="NonExistent",
            update=MenuItemUpdate(price=10.00),
        )


def test_delete_menu_item_removes_from_category():
    r = _r()
    out = delete_menu_item(r, category="pizzas", name="Margherita")
    assert out.menu["pizzas"] == []


def test_delete_menu_item_404_when_not_found():
    r = _r()
    with pytest.raises(MenuItemNotFound):
        delete_menu_item(r, category="pizzas", name="NonExistent")


def test_add_category_creates_empty_array():
    r = _r()
    out = add_category(r, CategoryCreate(key="drinks"))
    assert out.menu["drinks"] == []


def test_add_category_rejects_duplicate():
    r = _r()
    with pytest.raises(DuplicateMenuItem):
        add_category(r, CategoryCreate(key="pizzas"))


def test_update_menu_item_rename_to_same_name_is_noop():
    """Renaming Margherita → Margherita should NOT raise — the skip-self
    check in update_menu_item must allow the no-op."""
    r = _r()
    out = update_menu_item(
        r,
        category="pizzas",
        name="Margherita",
        update=MenuItemUpdate(new_name="Margherita"),
    )
    assert out.menu["pizzas"][0]["name"] == "Margherita"


def test_update_menu_item_rename_within_category_409_on_collision():
    """Renaming Margherita → Pepperoni when both exist in pizzas should
    raise DuplicateMenuItem."""
    r = _r()
    r = add_menu_item(
        r,
        MenuItemCreate(category="pizzas", name="Pepperoni", price=15.99),
    )
    with pytest.raises(DuplicateMenuItem):
        update_menu_item(
            r,
            category="pizzas",
            name="Margherita",
            update=MenuItemUpdate(new_name="Pepperoni"),
        )


def test_update_menu_item_move_to_category_with_existing_name_409():
    """Moving Margherita to sides where a 'Margherita' already exists
    should raise DuplicateMenuItem."""
    r = _r()
    r = add_menu_item(
        r,
        MenuItemCreate(category="sides", name="Margherita", price=5.00),
    )
    with pytest.raises(DuplicateMenuItem):
        update_menu_item(
            r,
            category="pizzas",
            name="Margherita",
            update=MenuItemUpdate(new_category="sides"),
        )
