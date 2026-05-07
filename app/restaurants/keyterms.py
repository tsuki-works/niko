"""Per-tenant keyterm computation for Deepgram Flux STT.

Flux exposes a ``keyterm`` parameter on its v2 connect API that biases
recognition toward menu-specific vocabulary. Without it, every call is
open-domain English and items like "Coke" or "Pepper Shrimp" lose to
acoustically-similar everyday phrases ("smoke", "pepper soup").

Deepgram caps the keyterm payload at 500 tokens across all terms per
request. Token here means a sub-word vocabulary unit; we approximate
it with ``ceil(word_count * 1.3)`` because the tokenizer is not
public. The 50-token safety margin under the 500 cap absorbs the
heuristic's slop.

This module is intentionally a pure function over a menu dict. No
Firestore reads, no settings reads, no logging — the caller owns
all of that. Keeps the heuristic deterministic and trivially testable.
"""

from __future__ import annotations

from math import ceil
from typing import Any

# Items the model recognizes reliably without keyterm bias. Lowercase
# substrings; if a menu item's name contains one of these, we skip it
# to save token budget for items that actually need biasing. The list
# is intentionally short — when in doubt, include the term and let
# Flux's tokenizer absorb a few wasted tokens.
_COMMON_SAFE_TERMS = frozenset(
    {
        "french fries",
        "chicken wings",
        "caesar salad",
        "garlic bread",
        "ice cream",
        "spring roll",
        "shrimp roll",
        "vegetable spring roll",
        "fried rice",
    }
)

# Conservative token estimate. Deepgram's tokenizer isn't public; a
# 1.3x word multiplier slightly overestimates so the safety margin
# accommodates terms with sub-word splits like "Bánh Mì".
_TOKENS_PER_WORD = 1.3

# Target budget. Flux's hard cap is 500 tokens; the 50-token margin
# protects against heuristic underestimation.
_TOKEN_BUDGET = 450


def _estimate_tokens(term: str) -> int:
    """Rough sub-word token count. Always returns at least 1."""
    words = term.split()
    if not words:
        return 0
    return max(1, ceil(len(words) * _TOKENS_PER_WORD))


def _is_common_safe_term(name: str) -> bool:
    """True iff the name contains a substring the model recognizes
    reliably without bias. Substring match avoids forcing the safe
    list to enumerate every variant ('Spicy French Fries' is also
    safe because it contains 'french fries')."""
    name_lower = name.lower()
    return any(safe in name_lower for safe in _COMMON_SAFE_TERMS)


def compute_keyterms(menu: dict[str, Any], restaurant_name: str) -> list[str]:
    """Build a Flux keyterm list for one restaurant.

    Returns ``restaurant_name`` first (always — the caller may say it
    when greeting), then menu item names in menu order, skipping items
    in the common-safe set and items that duplicate something already
    included (case-insensitive). Stops at the first item whose addition
    would push the running token estimate over the budget — remaining
    items get no bias on this call.

    Pathological input where ``restaurant_name`` alone exceeds budget:
    return only ``[restaurant_name]`` — the caller is responsible for
    deciding whether that's acceptable. Returning an empty list would
    mean *no* bias at all, which is worse.
    """
    name_tokens = _estimate_tokens(restaurant_name)
    if name_tokens >= _TOKEN_BUDGET:
        # Name alone exceeds the budget. Return as-is and let the
        # caller log/triage; producing an empty list would silently
        # drop biasing for the caller-spoken restaurant name.
        return [restaurant_name]

    terms: list[str] = [restaurant_name]
    used_tokens = name_tokens
    seen: set[str] = {restaurant_name.lower()}

    for category_key, items in menu.items():
        if isinstance(category_key, str) and category_key.startswith("_"):
            # Reserved keys like _category_order. Skip — they aren't
            # category lists and would crash isinstance(items, list).
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            if not name:
                continue
            name_lower = name.lower()
            if name_lower in seen:
                continue
            if _is_common_safe_term(name):
                continue
            cost = _estimate_tokens(name)
            if used_tokens + cost > _TOKEN_BUDGET:
                # We've hit the budget — stop emitting. Any items we
                # haven't reached yet simply don't get biased on this
                # call. The caller can decide whether to log this.
                return terms
            terms.append(name)
            used_tokens += cost
            seen.add(name_lower)

    return terms
