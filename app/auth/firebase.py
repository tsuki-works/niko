"""Firebase Admin SDK initialization (PR D of #81).

In Cloud Run, the service account attached to the service auto-auths
via the metadata server — no explicit credential needed. Locally, set
``GOOGLE_APPLICATION_CREDENTIALS`` to a service-account JSON path
(same one used for Firestore via ADC).

The admin app is initialized lazily on first use so module import
stays fast and tests can patch ``firebase_admin`` before any real
verification happens.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import firebase_admin
from firebase_admin import auth as firebase_auth

logger = logging.getLogger(__name__)

_app: Optional[firebase_admin.App] = None


def _get_app() -> firebase_admin.App:
    global _app
    if _app is None:
        if firebase_admin._apps:
            _app = firebase_admin.get_app()
        else:
            _app = firebase_admin.initialize_app()
    return _app


def verify_session_cookie(cookie: str) -> dict[str, Any]:
    """Verify a Firebase session cookie. Raises on failure.

    Session cookies are issued by ``auth.create_session_cookie`` and
    have a longer lifetime than ID tokens (up to 14 days). They're set
    HTTP-only by the dashboard's ``/api/auth/session`` route after a
    successful sign-in.
    """
    _get_app()
    return firebase_auth.verify_session_cookie(cookie, check_revoked=False)


def verify_id_token(token: str) -> dict[str, Any]:
    """Verify a raw Firebase ID token. Raises on failure.

    Used for direct API consumers (curl, ops scripts) that don't go
    through the dashboard's session-cookie flow. The ID token expires
    after one hour by default — clients are responsible for refresh.
    """
    _get_app()
    return firebase_auth.verify_id_token(token, check_revoked=False)


def set_app(app: Optional[firebase_admin.App]) -> None:
    """Override the module-level Firebase Admin app. Used by tests
    that pre-initialize a stub app or want a clean slate."""
    global _app
    _app = app
