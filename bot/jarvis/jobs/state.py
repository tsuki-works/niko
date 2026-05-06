"""Firestore-backed per-job state + dedup.

Two collections:
  job_state/{job_name}                       — last_run_at, last_status, kind-merged fields
  job_dedup/{job_name}/keys/{dedup_key}      — seen_at, expires_at

is_dedup_seen reads the doc and returns True only if expires_at > now.
We chose read-time expiry (vs Firestore native TTL) for explicitness and
dev-environment friendliness — local emulators may not have TTL set up.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

_STATE_COLLECTION = "job_state"
_DEDUP_COLLECTION = "job_dedup"


class FirestoreJobState:
    def __init__(self, client: Any, job_name: str) -> None:
        self._client = client
        self._job_name = job_name

    def _state_doc(self):
        return self._client.collection(_STATE_COLLECTION).document(self._job_name)

    def _dedup_keys(self):
        return (
            self._client.collection(_DEDUP_COLLECTION)
            .document(self._job_name)
            .collection("keys")
        )

    async def merge_state(self, fields: dict[str, Any]) -> None:
        await self._state_doc().set(fields, merge=True)

    async def get_state(self) -> dict[str, Any]:
        snap = await self._state_doc().get()
        if not snap.exists:
            return {}
        return snap.to_dict() or {}

    async def is_dedup_seen(self, key: str) -> bool:
        snap = await self._dedup_keys().document(key).get()
        if not snap.exists:
            return False
        data = snap.to_dict() or {}
        expires_at = data.get("expires_at")
        if expires_at is None:
            return False
        return expires_at > datetime.now(timezone.utc)

    async def mark_dedup_seen(self, key: str, *, ttl: timedelta) -> None:
        now = datetime.now(timezone.utc)
        await self._dedup_keys().document(key).set(
            {"seen_at": now, "expires_at": now + ttl}
        )
