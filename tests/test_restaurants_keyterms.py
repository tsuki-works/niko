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

from app.restaurants.keyterms import compute_keyterms


def _estimate_tokens(text: str) -> int:
    """Mirror of the production heuristic for budget assertions."""
    words = text.split()
    return max(1, ceil(len(words) * 1.3)) if words else 0


def test_includes_restaurant_name_first_with_empty_menu() -> None:
    assert compute_keyterms({}, "Twilight Family Restaurant") == ["Twilight Family Restaurant"]


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
    assert keyterms == ["Twilight", "Pepper Shrimp"]


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
