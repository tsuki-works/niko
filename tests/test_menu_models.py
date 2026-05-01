"""Unit tests for the granular-menu request bodies."""

import pytest

from app.restaurants.models import MenuItemCreate, MenuItemUpdate


def test_menu_item_create_accepts_single_price():
    item = MenuItemCreate(category="pizzas", name="Margherita", price=12.99)
    assert item.available is True
    assert item.sizes is None
    assert item.price == 12.99


def test_menu_item_create_accepts_sizes():
    item = MenuItemCreate(
        category="pizzas",
        name="Pepperoni",
        sizes={"small": 12.99, "large": 18.99},
    )
    assert item.price is None
    assert item.sizes == {"small": 12.99, "large": 18.99}


def test_menu_item_create_rejects_both_price_and_sizes():
    with pytest.raises(ValueError):
        MenuItemCreate(
            category="pizzas",
            name="X",
            price=10.00,
            sizes={"small": 8.00},
        )


def test_menu_item_create_rejects_neither_price_nor_sizes():
    with pytest.raises(ValueError):
        MenuItemCreate(category="pizzas", name="X")


def test_menu_item_create_rejects_negative_price():
    with pytest.raises(ValueError):
        MenuItemCreate(category="pizzas", name="X", price=-1.00)


def test_menu_item_update_allows_partial_fields():
    upd = MenuItemUpdate(price=14.99)
    assert upd.model_dump(exclude_unset=True) == {"price": 14.99}


def test_menu_item_update_rejects_both_price_and_sizes_together():
    with pytest.raises(ValueError):
        MenuItemUpdate(price=10.00, sizes={"small": 8.00})
