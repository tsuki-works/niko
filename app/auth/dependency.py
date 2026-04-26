"""FastAPI dependencies for tenant-scoped routes (PR D of #81).

Usage:

    from app.auth import Tenant, current_tenant
    from fastapi import Depends

    @app.get("/orders")
    def list_orders(tenant: Tenant = Depends(current_tenant)):
        return order_storage.list_recent_orders(tenant.restaurant_id)

The dependency:

1. Looks for a Firebase session cookie in the ``__session`` cookie
   (the convention the dashboard sets in ``/api/auth/session``).
2. Falls back to a ``Bearer <id_token>`` ``Authorization`` header for
   direct API consumers.
3. Verifies via firebase-admin; rejects with 401 on missing or
   invalid credentials.
4. Reads custom claims for ``restaurant_id`` and ``role``. A user
   without a ``restaurant_id`` claim gets a 403 — they're
   authenticated but not provisioned for any tenant yet.

Customize the role check with ``require_role(...)``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from fastapi import Cookie, Depends, Header, HTTPException, status

from app.auth import firebase as firebase_auth

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "__session"
DEFAULT_ROLE = "owner"


@dataclass(frozen=True)
class Tenant:
    """The verified identity of an inbound request.

    ``uid`` is Firebase Auth's stable user id. ``email`` is the user's
    email at the time of token issuance — convenient for logs but
    don't use it for authorization, use ``uid``. ``restaurant_id``
    comes from the user's custom claims; routes scope every read to
    this tenant unless the user has the ``tsuki_admin`` role.
    """

    uid: str
    email: Optional[str]
    restaurant_id: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "tsuki_admin"


def _extract_token(
    session_cookie: Optional[str],
    authorization: Optional[str],
) -> tuple[str, str]:
    """Return ``(kind, value)`` for the first credential we find.

    ``kind`` is ``"cookie"`` or ``"bearer"``; ``value`` is the raw
    string passed to firebase-admin. Raises 401 if neither is present.
    """
    if session_cookie:
        return "cookie", session_cookie
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            return "bearer", token
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing session cookie or Bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _claims_to_tenant(claims: dict[str, Any]) -> Tenant:
    rid = claims.get("restaurant_id")
    if not rid:
        # Authenticated but not provisioned. Tsuki ops needs to set
        # the custom claim via ``scripts/grant_tenant_claim.py``.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No restaurant_id claim on user — tenant not provisioned",
        )
    return Tenant(
        uid=claims.get("uid") or claims.get("user_id") or "",
        email=claims.get("email"),
        restaurant_id=rid,
        role=claims.get("role") or DEFAULT_ROLE,
    )


def _verify_credential(kind: str, value: str) -> dict:
    """Verify a Firebase credential. Tries the kind-specific path
    first; if Bearer fails an ID-token verify we retry as a session
    cookie so callers that forward a session cookie via Bearer (some
    server-to-server clients) still authenticate.

    Raises the underlying firebase-admin exception on failure so
    ``current_tenant`` can map it to a 401.
    """
    if kind == "cookie":
        return firebase_auth.verify_session_cookie(value)
    # Bearer path. Try ID token first — that's what
    # ``signInWithEmailAndPassword`` produces. Fall back to session
    # cookie verify when the issuer mismatches (the dashboard mints
    # session cookies and forwards them; both should be accepted).
    try:
        return firebase_auth.verify_id_token(value)
    except Exception as id_token_err:  # noqa: BLE001
        try:
            return firebase_auth.verify_session_cookie(value)
        except Exception:  # noqa: BLE001
            raise id_token_err


def current_tenant(
    __session: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
) -> Tenant:
    """Resolve the calling tenant from session cookie or Bearer token.

    Verifies via firebase-admin and parses custom claims. 401 if no
    credential, 401 if invalid credential, 403 if no ``restaurant_id``
    custom claim has been provisioned for the user.
    """
    kind, value = _extract_token(__session, authorization)
    try:
        claims = _verify_credential(kind, value)
    except Exception as exc:  # noqa: BLE001 — firebase-admin raises a family of errors
        logger.warning("auth: %s rejected: %s", kind, exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credential",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return _claims_to_tenant(claims)


def optional_tenant(
    __session: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
) -> Optional[Tenant]:
    """Like ``current_tenant`` but returns ``None`` instead of raising.

    Useful for endpoints that have a public fallback but customize
    behavior when authenticated (none today; reserved for future use).
    """
    if not __session and not authorization:
        return None
    try:
        return current_tenant(__session, authorization)
    except HTTPException:
        return None


def require_role(*allowed: str):
    """FastAPI dependency factory: gate a route on a specific role set.

    Example:
        admin_only = require_role("tsuki_admin")

        @app.post("/admin/whatever")
        def whatever(tenant: Tenant = Depends(admin_only)): ...
    """
    allowed_set = set(allowed)

    def _checker(tenant: Tenant = Depends(current_tenant)) -> Tenant:
        if tenant.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role in {sorted(allowed_set)}",
            )
        return tenant

    return _checker


def _bypass_for_tests(tenant: Tenant) -> Iterable[None]:
    """Convenience hook for tests that want to swap the dependency.

    Tests can do:
        app.dependency_overrides[current_tenant] = lambda: Tenant(...)
    directly — this helper is here as documentation for that pattern.
    """
    yield None
