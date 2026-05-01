"""Pure-function menu mutations on a Restaurant.menu dict.

The dashboard's editor sends granular create/update/delete operations
against this module's functions; the FastAPI handler reads the
restaurant doc, calls the helper, writes the new doc back. Keeping the
logic free of Firestore I/O lets us unit-test mutations without mocks.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.restaurants.models import (
    CategoryCreate,
    MenuItemCreate,
    MenuItemUpdate,
    Restaurant,
)


class MenuItemNotFound(KeyError):
    """The (category, name) pair didn't match any item."""


class DuplicateMenuItem(ValueError):
    """An item with this name already exists in the target category,
    or the target category already exists."""


_RESERVED_KEYS = {"_category_order"}


def _menu_copy(r: Restaurant) -> dict[str, Any]:
    return deepcopy(r.menu)


def add_menu_item(r: Restaurant, item: MenuItemCreate) -> Restaurant:
    menu = _menu_copy(r)
    cat = menu.setdefault(item.category, [])
    if any(existing.get("name") == item.name for existing in cat):
        raise DuplicateMenuItem(
            f"item {item.name!r} already exists in category {item.category!r}"
        )

    payload: dict[str, Any] = {
        "name": item.name,
        "available": item.available,
    }
    if item.description:
        payload["description"] = item.description
    if item.price is not None:
        payload["price"] = item.price
    if item.sizes is not None:
        payload["sizes"] = dict(item.sizes)

    cat.append(payload)
    return r.model_copy(update={"menu": menu})


def _find_item(menu: dict[str, Any], category: str, name: str) -> int:
    items = menu.get(category)
    if not isinstance(items, list):
        raise MenuItemNotFound(f"category {category!r} not found")
    for idx, item in enumerate(items):
        if isinstance(item, dict) and item.get("name") == name:
            return idx
    raise MenuItemNotFound(
        f"item {name!r} not found in category {category!r}"
    )


def update_menu_item(
    r: Restaurant,
    *,
    category: str,
    name: str,
    update: MenuItemUpdate,
) -> Restaurant:
    menu = _menu_copy(r)
    idx = _find_item(menu, category, name)
    item = dict(menu[category][idx])

    if update.new_name is not None:
        target_cat = update.new_category or category
        target_items = (
            menu.get(target_cat, [])
            if target_cat != category
            else menu[category]
        )
        # Reject rename collision — but allow renaming to same value
        # (no-op) by skipping the index of the item being modified.
        for i_idx, i in enumerate(target_items):
            if not isinstance(i, dict):
                continue
            if i.get("name") != update.new_name:
                continue
            if target_cat == category and i_idx == idx:
                continue
            raise DuplicateMenuItem(
                f"item {update.new_name!r} already exists in {target_cat!r}"
            )
        item["name"] = update.new_name
    if update.description is not None:
        item["description"] = update.description
    if update.available is not None:
        item["available"] = update.available
    if update.price is not None:
        item["price"] = update.price
        item.pop("sizes", None)
    if update.sizes is not None:
        item["sizes"] = dict(update.sizes)
        item.pop("price", None)

    if update.new_category is not None and update.new_category != category:
        menu[category].pop(idx)
        menu.setdefault(update.new_category, []).append(item)
    else:
        menu[category][idx] = item

    return r.model_copy(update={"menu": menu})


def delete_menu_item(
    r: Restaurant, *, category: str, name: str
) -> Restaurant:
    menu = _menu_copy(r)
    idx = _find_item(menu, category, name)
    menu[category].pop(idx)
    return r.model_copy(update={"menu": menu})


def add_category(r: Restaurant, category: CategoryCreate) -> Restaurant:
    menu = _menu_copy(r)
    if category.key in _RESERVED_KEYS or category.key in menu:
        raise DuplicateMenuItem(
            f"category {category.key!r} already exists"
        )
    menu[category.key] = []
    return r.model_copy(update={"menu": menu})
