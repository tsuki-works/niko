"""Tests for the atomic order-update tools (Issue #305 Part B).

Replaces the snapshot ``update_order`` tool with 6 atomic operations:
``add_item``, ``remove_item``, ``update_item``, ``set_order_type``,
``set_delivery_address``, ``set_status``. Each operation has a single
dispatch entry point ``apply_tool_call`` in ``app.llm.orchestration``.

Item identity uses server-assigned IDs (``i_<6hex>``) returned in
``tool_result`` summaries so the model can reference items in subsequent
``remove_item`` / ``update_item`` calls.
"""

from __future__ import annotations

import pytest

from app.llm.orchestration import apply_tool_call, summarize_order_for_tool_result
from app.orders.models import LineItem, Order


def _order(items: list[LineItem] | None = None) -> Order:
    return Order(call_sid="CAtest", items=items or [])


def test_line_item_has_auto_generated_item_id():
    """Every LineItem gets a unique ``item_id`` at construction so the
    LLM can reference it from later ``remove_item`` / ``update_item``
    tool calls (the model reads IDs out of prior ``tool_result`` blocks
    in its message history)."""
    item_a = LineItem(name="Pepperoni", category="pizza", quantity=1, unit_price=12.99)
    item_b = LineItem(name="Coke", category="drink", quantity=1, unit_price=2.99)

    assert item_a.item_id.startswith("i_")
    assert item_b.item_id.startswith("i_")
    assert item_a.item_id != item_b.item_id


# ---------------------------------------------------------------------------
# Dispatch + add_item
# ---------------------------------------------------------------------------


def test_apply_tool_call_unknown_tool_returns_rejection_note():
    order = _order()
    new_order, notes = apply_tool_call(order, "frobnicate", {})

    assert new_order == order  # no mutation
    assert notes and "unknown" in notes[0].lower()


def test_add_item_to_empty_order_appends_with_generated_id():
    order = _order()
    new_order, notes = apply_tool_call(
        order,
        "add_item",
        {"name": "Pad Thai", "category": "main", "quantity": 1, "unit_price": 12.0},
    )

    assert notes == []
    assert len(new_order.items) == 1
    assert new_order.items[0].name == "Pad Thai"
    assert new_order.items[0].item_id.startswith("i_")
    assert new_order.subtotal == 12.0


def test_add_item_appends_to_existing_order_preserving_ids():
    first = LineItem(name="Pepperoni", category="pizza", quantity=1, unit_price=10.0)
    order = _order([first])

    new_order, notes = apply_tool_call(
        order,
        "add_item",
        {"name": "Coke", "category": "drink", "quantity": 2, "unit_price": 3.0},
    )

    assert notes == []
    assert len(new_order.items) == 2
    assert new_order.items[0].item_id == first.item_id  # preserved
    assert new_order.items[1].name == "Coke"
    assert new_order.items[1].quantity == 2
    assert new_order.subtotal == pytest.approx(16.0)


def test_add_item_captures_size_and_modifications():
    order = _order()
    new_order, _ = apply_tool_call(
        order,
        "add_item",
        {
            "name": "Margherita",
            "category": "pizza",
            "size": "large",
            "quantity": 1,
            "unit_price": 20.0,
            "modifications": ["extra cheese", "no basil"],
        },
    )

    item = new_order.items[0]
    assert item.size == "large"
    assert item.modifications == ["extra cheese", "no basil"]


def test_add_item_rejects_missing_required_fields():
    order = _order()
    new_order, notes = apply_tool_call(
        order,
        "add_item",
        {"name": "Pad Thai"},  # missing category, quantity, unit_price
    )

    assert new_order == order
    assert notes and "add_item" in notes[0]


def test_add_item_rejects_zero_quantity():
    order = _order()
    new_order, notes = apply_tool_call(
        order,
        "add_item",
        {"name": "Coke", "category": "drink", "quantity": 0, "unit_price": 2.0},
    )

    assert new_order == order
    assert notes


# ---------------------------------------------------------------------------
# remove_item
# ---------------------------------------------------------------------------


def test_remove_item_by_id_drops_matching_line():
    a = LineItem(name="Pepperoni", category="pizza", quantity=1, unit_price=10.0)
    b = LineItem(name="Coke", category="drink", quantity=2, unit_price=3.0)
    order = _order([a, b])

    new_order, notes = apply_tool_call(order, "remove_item", {"item_id": a.item_id})

    assert notes == []
    assert [i.item_id for i in new_order.items] == [b.item_id]
    assert new_order.subtotal == pytest.approx(6.0)


def test_remove_item_unknown_id_returns_rejection_note():
    a = LineItem(name="Pepperoni", category="pizza", quantity=1, unit_price=10.0)
    order = _order([a])

    new_order, notes = apply_tool_call(order, "remove_item", {"item_id": "i_nope"})

    assert new_order == order
    assert notes and "i_nope" in notes[0]


def test_remove_item_missing_item_id_returns_rejection_note():
    order = _order([LineItem(name="X", category="y", quantity=1, unit_price=1.0)])

    new_order, notes = apply_tool_call(order, "remove_item", {})

    assert new_order == order
    assert notes


# ---------------------------------------------------------------------------
# update_item
# ---------------------------------------------------------------------------


def test_update_item_changes_quantity_only():
    a = LineItem(name="Pepperoni", category="pizza", quantity=1, unit_price=10.0)
    order = _order([a])

    new_order, notes = apply_tool_call(order, "update_item", {"item_id": a.item_id, "quantity": 3})

    assert notes == []
    item = new_order.items[0]
    assert item.item_id == a.item_id  # ID preserved
    assert item.quantity == 3
    assert item.name == "Pepperoni"  # other fields untouched
    assert item.unit_price == 10.0


def test_update_item_changes_size_and_unit_price():
    a = LineItem(name="Margherita", category="pizza", size="small", quantity=1, unit_price=12.0)
    order = _order([a])

    new_order, _ = apply_tool_call(
        order,
        "update_item",
        {"item_id": a.item_id, "size": "large", "unit_price": 20.0},
    )

    item = new_order.items[0]
    assert item.size == "large"
    assert item.unit_price == 20.0
    assert item.quantity == 1  # not provided -> unchanged


def test_update_item_replaces_modifications():
    a = LineItem(
        name="Margherita",
        category="pizza",
        quantity=1,
        unit_price=12.0,
        modifications=["extra cheese"],
    )
    order = _order([a])

    new_order, _ = apply_tool_call(
        order,
        "update_item",
        {"item_id": a.item_id, "modifications": ["no basil"]},
    )

    assert new_order.items[0].modifications == ["no basil"]


def test_update_item_unknown_id_returns_rejection_note():
    order = _order([LineItem(name="X", category="y", quantity=1, unit_price=1.0)])

    new_order, notes = apply_tool_call(order, "update_item", {"item_id": "i_nope", "quantity": 5})

    assert new_order == order
    assert notes and "i_nope" in notes[0]


# ---------------------------------------------------------------------------
# set_order_type
# ---------------------------------------------------------------------------


def test_set_order_type_pickup():
    order = _order()
    new_order, notes = apply_tool_call(order, "set_order_type", {"order_type": "pickup"})

    assert notes == []
    assert new_order.order_type.value == "pickup"


def test_set_order_type_delivery():
    order = _order()
    new_order, notes = apply_tool_call(order, "set_order_type", {"order_type": "delivery"})

    assert notes == []
    assert new_order.order_type.value == "delivery"


def test_set_order_type_pickup_clears_existing_delivery_address():
    """Switching pickup wipes any address captured during the prior
    delivery flow — matches the _CORRECTIONS prompt rule from the
    snapshot era."""
    order = Order(
        call_sid="CAtest",
        order_type="delivery",
        delivery_address="14 Main St",
    )

    new_order, _ = apply_tool_call(order, "set_order_type", {"order_type": "pickup"})

    assert new_order.order_type.value == "pickup"
    assert new_order.delivery_address is None


def test_set_order_type_rejects_invalid_value():
    order = _order()
    new_order, notes = apply_tool_call(order, "set_order_type", {"order_type": "carrier-pigeon"})

    assert new_order == order
    assert notes


# ---------------------------------------------------------------------------
# set_delivery_address
# ---------------------------------------------------------------------------


def test_set_delivery_address_valid():
    order = _order()
    new_order, notes = apply_tool_call(
        order, "set_delivery_address", {"delivery_address": "14 Main St"}
    )

    assert notes == []
    assert new_order.delivery_address == "14 Main St"


def test_set_delivery_address_invalid_returns_rejection_note():
    order = _order()
    new_order, notes = apply_tool_call(
        order, "set_delivery_address", {"delivery_address": "garbled"}
    )

    assert new_order == order
    assert notes and "address" in notes[0].lower()


def test_set_delivery_address_none_clears():
    order = Order(call_sid="CAtest", delivery_address="14 Main St")

    new_order, notes = apply_tool_call(order, "set_delivery_address", {"delivery_address": None})

    assert notes == []
    assert new_order.delivery_address is None


# ---------------------------------------------------------------------------
# set_status
# ---------------------------------------------------------------------------


def test_set_status_confirmed():
    order = _order()
    new_order, notes = apply_tool_call(order, "set_status", {"status": "confirmed"})

    assert notes == []
    assert new_order.status.value == "confirmed"


def test_set_status_cancelled():
    order = _order()
    new_order, notes = apply_tool_call(order, "set_status", {"status": "cancelled"})

    assert notes == []
    assert new_order.status.value == "cancelled"


def test_set_status_rejects_other_values():
    """Only ``confirmed`` and ``cancelled`` are valid for the LLM tool
    surface — kitchen-workflow states (preparing/ready/completed) are
    set by the dashboard, not the model."""
    order = _order()
    new_order, notes = apply_tool_call(order, "set_status", {"status": "preparing"})

    assert new_order == order
    assert notes


# ---------------------------------------------------------------------------
# tool_result summary surfaces item_ids
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ToolSpec declarations in app/llm/base.py (#305 Part B)
# ---------------------------------------------------------------------------


def test_atomic_tool_specs_cover_all_six_operations():
    """Six atomic tool specs replace the single snapshot ``update_order``
    spec. Names map 1:1 to the dispatch table in ``orchestration.py``."""
    from app.llm.base import ATOMIC_TOOL_SPECS

    names = {spec.name for spec in ATOMIC_TOOL_SPECS}
    assert names == {
        "add_item",
        "remove_item",
        "update_item",
        "set_order_type",
        "set_delivery_address",
        "set_status",
    }


def test_add_item_spec_required_fields_match_handler():
    """add_item's JSON schema must require exactly the fields the handler
    enforces — drift here would let the model emit a payload the schema
    accepts but the handler rejects."""
    from app.llm.base import ATOMIC_TOOL_SPECS

    spec = next(s for s in ATOMIC_TOOL_SPECS if s.name == "add_item")
    required = set(spec.parameters["required"])
    assert required == {"name", "category", "quantity", "unit_price"}


def test_add_item_description_calls_out_size_as_separate_line():
    """Discrimination from update_item depends on the model knowing that
    ordering a different size = new line, not an in-place size change.
    Without that signal the model misroutes 'add a large pad thai' to
    update_item when a small pad thai already exists."""
    from app.llm.base import ATOMIC_TOOL_SPECS

    spec = next(s for s in ATOMIC_TOOL_SPECS if s.name == "add_item")
    assert "size" in spec.description.lower()
    assert "separate" in spec.description.lower() or "new line" in spec.description.lower()


def test_remove_and_update_item_specs_reference_item_id():
    """Both must require ``item_id`` and steer the model toward reading
    it from prior tool_result blocks (otherwise the model invents IDs
    that don't exist in the order)."""
    from app.llm.base import ATOMIC_TOOL_SPECS

    for name in ("remove_item", "update_item"):
        spec = next(s for s in ATOMIC_TOOL_SPECS if s.name == name)
        assert "item_id" in spec.parameters["required"]
        assert "tool_result" in spec.description.lower()


def test_set_status_spec_restricts_to_confirmed_or_cancelled():
    """Kitchen states are dashboard-only — the LLM tool surface must
    not advertise them."""
    from app.llm.base import ATOMIC_TOOL_SPECS

    spec = next(s for s in ATOMIC_TOOL_SPECS if s.name == "set_status")
    enum = spec.parameters["properties"]["status"]["enum"]
    assert set(enum) == {"confirmed", "cancelled"}


def test_summary_includes_item_ids_so_model_can_reference_them():
    """The tool_result summary must surface each line's item_id so the
    model can call ``remove_item``/``update_item`` against it on the
    next turn. Without this, the IDs exist only inside the Order
    object — invisible to the model."""
    a = LineItem(name="Pepperoni", category="pizza", quantity=2, unit_price=10.0)
    b = LineItem(name="Coke", category="drink", quantity=1, unit_price=3.0)
    order = _order([a, b])

    summary = summarize_order_for_tool_result(order)

    assert a.item_id in summary
    assert b.item_id in summary
    assert "Pepperoni" in summary
    assert "Subtotal: $23.00" in summary
