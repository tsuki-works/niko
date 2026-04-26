"""Backfill historical Firestore data into nested subcollections (#79 PR C).

Walks the legacy flat collections and copies each doc to the new
nested path under ``restaurants/{rid}/...``. Idempotent — re-running
upserts the same destination ids.

Source → destination map:

  orders/{call_sid}                     → restaurants/{order.restaurant_id}/orders/{call_sid}
  call_sessions/{call_sid}              → restaurants/niko-pizza-kitchen/call_sessions/{call_sid}
  call_sessions/{call_sid}/events/{eid} → restaurants/niko-pizza-kitchen/call_sessions/{call_sid}/events/{auto}

Why ``call_sessions`` lands under the demo tenant:
The legacy flat docs predate the multi-tenant schema, so they have no
``restaurant_id`` field. Only one tenant existed historically (the
demo), so we backfill them all under ``niko-pizza-kitchen``. New
calls written via the updated ``app/storage/call_sessions.py`` do
include ``restaurant_id`` on the parent doc.

The flat collections stay in place after this migration runs — they
remain the source for the dashboard's live ``onSnapshot`` until PR D
moves the subscription. PR F deletes them.

Usage:
    python -m scripts.migrate_to_nested_subcollections             # live
    python -m scripts.migrate_to_nested_subcollections --dry-run   # report only

Auth: ADC (``gcloud auth application-default login``) or service
account JSON via ``GOOGLE_APPLICATION_CREDENTIALS``. Set
``GOOGLE_CLOUD_PROJECT=niko-tsuki`` if outside Cloud Run.
"""

from __future__ import annotations

import argparse
import logging
import sys

from google.cloud import firestore

from app.storage.restaurants import DEMO_RID

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _migrate_orders(client: firestore.Client, dry_run: bool) -> int:
    """Copy ``orders/{call_sid}`` → ``restaurants/{rid}/orders/{call_sid}``."""
    moved = 0
    for snap in client.collection("orders").stream():
        data = snap.to_dict() or {}
        rid = data.get("restaurant_id") or DEMO_RID
        call_sid = data.get("call_sid") or snap.id
        target = (
            client.collection("restaurants")
            .document(rid)
            .collection("orders")
            .document(call_sid)
        )
        if dry_run:
            logger.info("[dry-run] orders/%s → restaurants/%s/orders/%s", snap.id, rid, call_sid)
        else:
            target.set(data)
        moved += 1
    return moved


def _migrate_call_sessions(client: firestore.Client, dry_run: bool) -> tuple[int, int]:
    """Copy ``call_sessions`` parents + events to nested under DEMO_RID."""
    parents_moved = 0
    events_moved = 0
    rid = DEMO_RID
    for parent_snap in client.collection("call_sessions").stream():
        parent_data = parent_snap.to_dict() or {}
        # Stamp restaurant_id on the nested parent so collectionGroup
        # queries can filter — the legacy flat docs lack it.
        parent_data.setdefault("restaurant_id", rid)
        call_sid = parent_data.get("call_sid") or parent_snap.id
        nested_parent = (
            client.collection("restaurants")
            .document(rid)
            .collection("call_sessions")
            .document(call_sid)
        )
        if dry_run:
            logger.info(
                "[dry-run] call_sessions/%s → restaurants/%s/call_sessions/%s",
                parent_snap.id,
                rid,
                call_sid,
            )
        else:
            nested_parent.set(parent_data)
        parents_moved += 1

        events_ref = (
            client.collection("call_sessions")
            .document(parent_snap.id)
            .collection("events")
        )
        for ev_snap in events_ref.stream():
            ev_data = ev_snap.to_dict() or {}
            if dry_run:
                logger.info(
                    "[dry-run]   event %s/%s",
                    parent_snap.id,
                    ev_snap.id,
                )
            else:
                # Use auto-id on the destination so re-runs append rather
                # than collide. Idempotency for events is best-effort —
                # exact-once would require event-level dedup which we
                # don't need given the dashboard recomputes counts from
                # the parent doc's ``transcript_count``.
                nested_parent.collection("events").add(ev_data)
            events_moved += 1
    return parents_moved, events_moved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the moves without writing anything",
    )
    args = parser.parse_args()

    client = firestore.Client()

    logger.info("=== migrate orders ===")
    orders_moved = _migrate_orders(client, args.dry_run)
    logger.info("orders: %d doc(s) %s", orders_moved, "would copy" if args.dry_run else "copied")

    logger.info("=== migrate call_sessions ===")
    parents, events = _migrate_call_sessions(client, args.dry_run)
    logger.info(
        "call_sessions: %d parent(s), %d event(s) %s",
        parents,
        events,
        "would copy" if args.dry_run else "copied",
    )

    if args.dry_run:
        logger.info("(dry-run — no writes performed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
