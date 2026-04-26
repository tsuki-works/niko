"""Grant Firebase Auth custom claims that scope a user to a tenant (#81).

PR D wires the dashboard + backend to read ``restaurant_id`` and
``role`` from Firebase Auth custom claims. New users created via the
Firebase Auth Console don't automatically get those claims — Tsuki
ops runs this script once per user/restaurant pair.

Usage:
    python -m scripts.grant_tenant_claim \\
        --email user@restaurant.com \\
        --rid niko-pizza-kitchen

    # Optional role (default: owner). Allowed values: owner, manager,
    # staff, tsuki_admin. Backend ``current_tenant`` reads this.
    python -m scripts.grant_tenant_claim \\
        --email admin@tsuki.works --rid '*' --role tsuki_admin

Auth: same as ``scripts/seed_demo_restaurant.py`` — ADC via
``gcloud auth application-default login`` locally, attached service
account in Cloud Run.

The user's ID token doesn't include the new claims until they
sign out + sign back in (or call ``getIdToken(true)`` to force
refresh) — Firebase's docs recommend forcing a refresh in the UI
right after a claim change.
"""

from __future__ import annotations

import argparse
import logging
import sys

import firebase_admin
from firebase_admin import auth as firebase_auth

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


_ALLOWED_ROLES = {"owner", "manager", "staff", "tsuki_admin"}


def _ensure_app() -> None:
    if not firebase_admin._apps:
        firebase_admin.initialize_app()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--email", required=True, help="Email of the existing Firebase Auth user"
    )
    parser.add_argument(
        "--rid",
        required=True,
        help=(
            "Restaurant id (Firestore doc id under ``restaurants/``). "
            "Use '*' with --role tsuki_admin for cross-tenant access."
        ),
    )
    parser.add_argument(
        "--role",
        default="owner",
        choices=sorted(_ALLOWED_ROLES),
        help="Role attached to the user. Default: owner.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _ensure_app()

    try:
        user = firebase_auth.get_user_by_email(args.email)
    except firebase_auth.UserNotFoundError:
        logger.error(
            "auth: no user found for email=%s. Create the user in the "
            "Firebase Auth Console first, then re-run.",
            args.email,
        )
        return 1

    # Preserve any existing claims the user already has — we only
    # touch restaurant_id and role.
    existing = dict(user.custom_claims or {})
    existing["restaurant_id"] = args.rid
    existing["role"] = args.role

    firebase_auth.set_custom_user_claims(user.uid, existing)
    logger.info(
        "✔ set claims on %s (uid=%s): restaurant_id=%s role=%s",
        args.email,
        user.uid,
        args.rid,
        args.role,
    )
    logger.info(
        "  next: have the user sign out + back in (or getIdToken(true)) "
        "to refresh the session token with the new claims."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
