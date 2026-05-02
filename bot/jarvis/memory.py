"""Firestore-backed per-thread conversation memory.

Each Discord thread the bot has joined gets a doc at
`jarvis_threads/<thread_id>`. The doc carries the rolling conversation
history (capped at MAX_TURNS) plus enough metadata to answer "is this
thread mine?" without an extra channel-level query.

Why a class with an injected client:
  Module-singleton accessors (the pattern in app/storage/firestore.py)
  make tests rely on monkeypatching imports. PR 2 has more moving
  pieces; constructor-injected dependencies keep the test surface small
  (mock one client, pass it in) and let main.py wire production
  dependencies once at startup.
"""

from __future__ import annotations

from typing import Any, Optional

from google.cloud import firestore

COLLECTION = "jarvis_threads"
MAX_TURNS = 20


class ThreadMemory:
    """Async Firestore wrapper for per-thread conversation history."""

    def __init__(self, client: firestore.AsyncClient) -> None:
        self._client = client

    def _doc(self, thread_id: str):
        return self._client.collection(COLLECTION).document(thread_id)

    async def thread_exists(self, thread_id: str) -> bool:
        snap = await self._doc(thread_id).get()
        return bool(snap.exists)

    async def record_thread(
        self,
        *,
        thread_id: str,
        parent_channel_id: str,
        guild_id: str,
    ) -> None:
        """Seed a fresh thread doc. Idempotent: re-recording resets the doc."""
        await self._doc(thread_id).set(
            {
                "thread_id": thread_id,
                "parent_channel_id": parent_channel_id,
                "guild_id": guild_id,
                "created_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP,
                "turns": [],
            }
        )

    async def get_turns(self, thread_id: str) -> list[dict[str, Any]]:
        """Return turns in chronological order. Empty list if no doc yet."""
        snap = await self._doc(thread_id).get()
        if not snap.exists:
            return []
        data = snap.to_dict() or {}
        turns = data.get("turns", [])
        # Strip Firestore-internal fields the model doesn't need.
        return [
            {"role": t["role"], "content": t["content"]} for t in turns
        ]

    async def append_turn(
        self,
        *,
        thread_id: str,
        role: str,
        content: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Append a turn. Caps total turns at MAX_TURNS (oldest dropped first)."""
        snap = await self._doc(thread_id).get()
        existing = (snap.to_dict() or {}).get("turns", []) if snap.exists else []
        new_turn: dict[str, Any] = {"role": role, "content": content}
        if user_id is not None:
            new_turn["user_id"] = user_id
        combined = list(existing) + [new_turn]
        if len(combined) > MAX_TURNS:
            combined = combined[-MAX_TURNS:]
        await self._doc(thread_id).update(
            {
                "turns": combined,
                "updated_at": firestore.SERVER_TIMESTAMP,
            }
        )
