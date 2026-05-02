"""Tests for jarvis.memory.ThreadMemory.

Mocks the firestore.AsyncClient surface — no live Firestore.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.memory import ThreadMemory, MAX_TURNS


def _make_doc_ref_with_snapshot(snapshot_data: dict | None):
    """Wire up an AsyncMock chain: client.collection().document() -> doc_ref
    where doc_ref.get() returns a snapshot whose .exists and .to_dict()
    are driven by `snapshot_data`."""
    snapshot = MagicMock()
    snapshot.exists = snapshot_data is not None
    snapshot.to_dict = MagicMock(return_value=snapshot_data or {})

    doc_ref = MagicMock()
    doc_ref.get = AsyncMock(return_value=snapshot)
    doc_ref.set = AsyncMock()
    doc_ref.update = AsyncMock()

    coll = MagicMock()
    coll.document = MagicMock(return_value=doc_ref)

    client = MagicMock()
    client.collection = MagicMock(return_value=coll)

    return client, doc_ref


async def test_thread_exists_returns_false_for_unknown_thread():
    client, _doc = _make_doc_ref_with_snapshot(None)
    mem = ThreadMemory(client)
    assert await mem.thread_exists("999") is False


async def test_thread_exists_returns_true_for_known_thread():
    client, _doc = _make_doc_ref_with_snapshot({"thread_id": "999", "turns": []})
    mem = ThreadMemory(client)
    assert await mem.thread_exists("999") is True


async def test_record_thread_writes_seed_doc():
    client, doc_ref = _make_doc_ref_with_snapshot(None)
    mem = ThreadMemory(client)
    await mem.record_thread(
        thread_id="123",
        parent_channel_id="456",
        guild_id="789",
    )
    doc_ref.set.assert_awaited_once()
    payload = doc_ref.set.await_args.args[0]
    assert payload["thread_id"] == "123"
    assert payload["parent_channel_id"] == "456"
    assert payload["guild_id"] == "789"
    assert payload["turns"] == []
    # created_at / updated_at are sentinel values; just check presence.
    assert "created_at" in payload
    assert "updated_at" in payload


async def test_get_turns_returns_empty_for_unknown_thread():
    client, _doc = _make_doc_ref_with_snapshot(None)
    mem = ThreadMemory(client)
    turns = await mem.get_turns("nope")
    assert turns == []


async def test_get_turns_returns_recorded_turns():
    stored = {
        "thread_id": "123",
        "turns": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    }
    client, _doc = _make_doc_ref_with_snapshot(stored)
    mem = ThreadMemory(client)
    turns = await mem.get_turns("123")
    assert turns == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


async def test_append_turn_persists_via_update():
    client, doc_ref = _make_doc_ref_with_snapshot(
        {"thread_id": "123", "turns": [{"role": "user", "content": "hi"}]}
    )
    mem = ThreadMemory(client)
    await mem.append_turn(
        thread_id="123",
        role="assistant",
        content="hello",
    )
    doc_ref.update.assert_awaited_once()
    payload = doc_ref.update.await_args.args[0]
    assert "turns" in payload
    assert "updated_at" in payload
    new_turns = payload["turns"]
    assert new_turns[-1]["role"] == "assistant"
    assert new_turns[-1]["content"] == "hello"
    assert new_turns[-2]["role"] == "user"
    assert new_turns[-2]["content"] == "hi"


async def test_append_turn_caps_at_max_turns():
    existing = [
        {"role": "user", "content": f"msg {i}"} for i in range(MAX_TURNS)
    ]
    client, doc_ref = _make_doc_ref_with_snapshot(
        {"thread_id": "123", "turns": existing}
    )
    mem = ThreadMemory(client)
    await mem.append_turn(thread_id="123", role="assistant", content="newest")
    payload = doc_ref.update.await_args.args[0]
    assert len(payload["turns"]) == MAX_TURNS
    assert payload["turns"][-1]["content"] == "newest"
    # Oldest was dropped.
    assert payload["turns"][0]["content"] != "msg 0"
