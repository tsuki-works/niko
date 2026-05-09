"""Tests for compute_keyterms — the per-tenant Flux keyterm builder.

The function is a pure dict-in / list-out transform; tests cover the
contract from the spec: restaurant name always first, common-safe
items skipped, duplicates dropped, token budget honored, edge cases
on malformed input.
"""

from __future__ import annotations

import json
from math import ceil
from pathlib import Path

from app.restaurants.keyterms import _UNIVERSAL_MODIFIERS, compute_keyterms


def _estimate_tokens(text: str) -> int:
    """Mirror of the production heuristic for budget assertions."""
    words = text.split()
    return max(1, ceil(len(words) * 1.3)) if words else 0


def test_includes_restaurant_name_first_with_empty_menu() -> None:
    keyterms = compute_keyterms({}, "Twilight Family Restaurant")
    assert keyterms[0] == "Twilight Family Restaurant"
    # Universal modifiers are emitted even with an empty menu.
    assert "no" in keyterms
    assert "spicy" in keyterms
    assert "to go" in keyterms


def test_walks_menu_in_category_order() -> None:
    menu = {
        "appetizers": [
            {"name": "Pepper Shrimp", "price": 16.25},
            {"name": "Sweet Chilli Shrimp", "price": 16.25},
        ],
        "soups": [
            {"name": "Wonton Soup", "price": 8.0},
        ],
    }
    keyterms = compute_keyterms(menu, "Twilight")
    assert keyterms[0] == "Twilight"
    assert "Pepper Shrimp" in keyterms
    assert "Sweet Chilli Shrimp" in keyterms
    assert "Wonton Soup" in keyterms


def test_skips_common_safe_items() -> None:
    """French Fries is a model-cold-recognized item — wastes budget."""
    menu = {
        "appetizers": [
            {"name": "French Fries", "price": 7.25},
            {"name": "Spicy French Fries", "price": 7.50},
            {"name": "Pepper Shrimp", "price": 16.25},
        ],
    }
    keyterms = compute_keyterms(menu, "Twilight")
    assert "French Fries" not in keyterms
    assert "Spicy French Fries" not in keyterms
    assert "Pepper Shrimp" in keyterms


def test_skips_underscore_reserved_keys() -> None:
    """_category_order is a list of strings, not a category. Don't
    crash on it; don't include its strings as 'menu items'."""
    menu = {
        "_category_order": ["appetizers", "soups"],
        "appetizers": [{"name": "Pepper Shrimp", "price": 16.25}],
    }
    keyterms = compute_keyterms(menu, "Twilight")
    assert "Pepper Shrimp" in keyterms
    assert "appetizers" not in keyterms
    assert "soups" not in keyterms


def test_drops_duplicates_case_insensitive() -> None:
    """Same item appears in two categories or two casings — include once."""
    menu = {
        "category_a": [{"name": "Pepper Shrimp", "price": 16.25}],
        "category_b": [{"name": "pepper shrimp", "price": 16.25}],
    }
    keyterms = compute_keyterms(menu, "Twilight")
    pepper_count = sum(1 for k in keyterms if k.lower() == "pepper shrimp")
    assert pepper_count == 1


def test_skips_items_without_a_name() -> None:
    menu = {
        "appetizers": [
            {"price": 5.0},  # no name
            {"name": "", "price": 5.0},  # empty name
            {"name": "   ", "price": 5.0},  # whitespace name
            {"name": "Pepper Shrimp", "price": 16.25},
        ],
    }
    keyterms = compute_keyterms(menu, "Twilight")
    assert keyterms[0] == "Twilight"
    assert "Pepper Shrimp" in keyterms
    # Universal modifiers appear between the restaurant name and menu items.
    assert "no" in keyterms
    pepper_idx = keyterms.index("Pepper Shrimp")
    assert pepper_idx > keyterms.index("no")


def test_skips_non_dict_menu_items_and_non_list_categories() -> None:
    """Defensive: Firestore can return surprising shapes. Don't crash."""
    menu = {
        "appetizers": [
            "this is not a dict",
            {"name": "Pepper Shrimp", "price": 16.25},
            42,
        ],
        "garbage_category": "this is not a list",
        "another_garbage": 123,
    }
    keyterms = compute_keyterms(menu, "Twilight")
    assert "Pepper Shrimp" in keyterms
    # Non-dict items contribute nothing; the function does not crash.


def test_token_budget_honored_on_large_menu() -> None:
    """Build a menu wide enough to exceed the budget; verify the
    function returns early and stays under cap."""
    items = [
        {"name": f"Special Dish Number {i} With Extra Words", "price": 10.0} for i in range(200)
    ]
    menu = {"specials": items}
    keyterms = compute_keyterms(menu, "Big Place")

    total_tokens = sum(_estimate_tokens(t) for t in keyterms)
    assert total_tokens <= 450, f"keyterms exceed token budget: {total_tokens} > 450"
    # Should have stopped short of all 200 items.
    assert len(keyterms) < 201
    assert keyterms[0] == "Big Place"


def test_pathological_long_restaurant_name_returns_name_only() -> None:
    """If the restaurant name alone exceeds the budget, the menu items
    are skipped. Returning an empty list would silently drop biasing
    for the caller-spoken name."""
    long_name = " ".join(["Very"] * 400)
    menu = {"appetizers": [{"name": "Pepper Shrimp", "price": 16.25}]}
    keyterms = compute_keyterms(menu, long_name)
    assert keyterms == [long_name]


def test_twilight_real_menu_fits_under_budget() -> None:
    """Regression: the live tenant's menu must fit comfortably. If
    this fires, the heuristic needs tightening before the migration
    can ship."""
    menu_path = Path(__file__).parent.parent / "restaurants" / "twilight-family-restaurant.json"
    if not menu_path.exists():
        # Local dev environments may not have the tenant fixture.
        return
    with menu_path.open(encoding="utf-8") as f:
        menu = json.load(f)
    keyterms = compute_keyterms(menu, "Twilight Family Restaurant")
    total_tokens = sum(_estimate_tokens(t) for t in keyterms)
    assert keyterms[0] == "Twilight Family Restaurant"
    assert total_tokens <= 450
    # Sanity: we should be biasing dozens of items, not just the name.
    assert len(keyterms) > 5


def test_output_preserves_original_casing() -> None:
    """Don't lowercase or title-case names — they go on the wire as-is."""
    menu = {"appetizers": [{"name": "PePPer Shrimp"}]}
    keyterms = compute_keyterms(menu, "Twilight")
    assert "PePPer Shrimp" in keyterms


def test_universal_modifiers_emitted_after_restaurant_name() -> None:
    """With an empty menu the output is [restaurant_name] + modifiers in order."""
    keyterms = compute_keyterms({}, "Twilight")
    assert keyterms[0] == "Twilight"
    assert keyterms[1:] == list(_UNIVERSAL_MODIFIERS)


def test_universal_modifiers_emitted_before_menu_items() -> None:
    """Every modifier appears before any menu item in the result list."""
    menu = {"appetizers": [{"name": "Pepper Shrimp"}]}
    keyterms = compute_keyterms(menu, "Test")
    pepper_idx = keyterms.index("Pepper Shrimp")
    for modifier in _UNIVERSAL_MODIFIERS:
        if modifier in keyterms:
            assert keyterms.index(modifier) < pepper_idx, (
                f"modifier '{modifier}' appears after menu item 'Pepper Shrimp'"
            )


def test_modifier_dedups_against_menu_item() -> None:
    """A menu item named like a modifier is not emitted a second time."""
    menu = {"appetizers": [{"name": "spicy"}]}
    keyterms = compute_keyterms(menu, "Test")
    count = sum(1 for k in keyterms if k.lower() == "spicy")
    assert count == 1, f"'spicy' appeared {count} times; expected exactly 1"
    assert keyterms.index("spicy") < keyterms.index("Test") + len(keyterms)


def test_modifier_dedups_against_restaurant_name() -> None:
    """Restaurant name 'No' means the 'no' modifier must not appear again."""
    keyterms = compute_keyterms({}, "No")
    assert keyterms[0] == "No"
    count = sum(1 for k in keyterms if k.lower() == "no")
    assert count == 1, f"'no' appeared {count} times; expected exactly 1"


def test_token_budget_still_includes_full_menu_for_realistic_input() -> None:
    """A realistic ~30-item menu fits under budget alongside all modifiers."""
    short_items = [
        "Jerk Chicken",
        "Oxtail Stew",
        "Curry Goat",
        "Brown Stew Fish",
        "Ackee Saltfish",
        "Callaloo",
        "Bammy",
        "Festival",
        "Rice Peas",
        "Plantain",
        "Escovitch Fish",
        "Steamed Cabbage",
        "Breadfruit",
        "Roast Yam",
        "Peas Soup",
        "Beef Patty",
        "Coco Bread",
        "Mannish Water",
        "Tripe Beans",
        "Cow Foot",
        "Pelau",
        "Roti",
        "Doubles",
        "Bake Shark",
        "Sorrel Drink",
        "Ginger Beer",
        "Sea Moss",
        "Rum Punch",
        "Mango Juice",
        "Soursop",
    ]
    menu = {"entrees": [{"name": name} for name in short_items]}
    keyterms = compute_keyterms(menu, "Island Kitchen")

    # All modifiers must be present.
    for modifier in _UNIVERSAL_MODIFIERS:
        assert modifier in keyterms, f"modifier '{modifier}' missing from keyterms"

    # All menu items must be present (none dropped due to modifier-tax).
    for item in short_items:
        assert item in keyterms, f"menu item '{item}' was dropped from keyterms"

    total_tokens = sum(_estimate_tokens(t) for t in keyterms)
    assert total_tokens <= 450, f"keyterms exceed token budget: {total_tokens} > 450"
