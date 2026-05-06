from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.jobs.state import FirestoreJobState


def _fake_firestore_with(state_doc: dict | None, dedup_doc: dict | None):
    client = MagicMock()

    state_snap = MagicMock()
    state_snap.exists = state_doc is not None
    state_snap.to_dict = MagicMock(return_value=state_doc or {})
    state_ref = MagicMock()
    state_ref.get = AsyncMock(return_value=state_snap)
    state_ref.set = AsyncMock()
    state_ref.update = AsyncMock()

    dedup_snap = MagicMock()
    dedup_snap.exists = dedup_doc is not None
    dedup_snap.to_dict = MagicMock(return_value=dedup_doc or {})
    dedup_ref = MagicMock()
    dedup_ref.get = AsyncMock(return_value=dedup_snap)
    dedup_ref.set = AsyncMock()

    state_collection = MagicMock()
    state_collection.document = MagicMock(return_value=state_ref)

    dedup_keys = MagicMock()
    dedup_keys.document = MagicMock(return_value=dedup_ref)
    dedup_doc_ref = MagicMock()
    dedup_doc_ref.collection = MagicMock(return_value=dedup_keys)
    dedup_collection = MagicMock()
    dedup_collection.document = MagicMock(return_value=dedup_doc_ref)

    def _collection(name):
        return state_collection if name == "job_state" else dedup_collection

    client.collection = MagicMock(side_effect=_collection)
    return client, state_ref, dedup_ref


@pytest.mark.asyncio
async def test_merge_state_calls_set_with_merge():
    client, state_ref, _ = _fake_firestore_with(None, None)
    state = FirestoreJobState(client, "morning_brief")
    await state.merge_state({"last_run_at": "now", "last_status": "ok"})
    state_ref.set.assert_awaited_once()
    args, kwargs = state_ref.set.call_args
    assert args[0]["last_status"] == "ok"
    assert kwargs.get("merge") is True


@pytest.mark.asyncio
async def test_is_dedup_seen_false_when_no_doc():
    client, _, _ = _fake_firestore_with(None, None)
    state = FirestoreJobState(client, "j")
    assert (await state.is_dedup_seen("k")) is False


@pytest.mark.asyncio
async def test_is_dedup_seen_false_when_expired():
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    client, _, _ = _fake_firestore_with(None, {"expires_at": past, "seen_at": past})
    state = FirestoreJobState(client, "j")
    assert (await state.is_dedup_seen("k")) is False


@pytest.mark.asyncio
async def test_is_dedup_seen_true_when_unexpired():
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    client, _, _ = _fake_firestore_with(None, {"expires_at": future, "seen_at": future})
    state = FirestoreJobState(client, "j")
    assert (await state.is_dedup_seen("k")) is True


@pytest.mark.asyncio
async def test_mark_dedup_seen_writes_expires_at():
    client, _, dedup_ref = _fake_firestore_with(None, None)
    state = FirestoreJobState(client, "j")
    await state.mark_dedup_seen("k", ttl=timedelta(hours=2))
    dedup_ref.set.assert_awaited_once()
    payload = dedup_ref.set.call_args.args[0]
    assert "seen_at" in payload
    assert "expires_at" in payload
    delta = payload["expires_at"] - payload["seen_at"]
    assert timedelta(hours=1, minutes=59) <= delta <= timedelta(hours=2, minutes=1)
