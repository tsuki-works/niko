"""Unit tests for ``app.auth.dependency`` (PR D of #81).

The dep is called from FastAPI routes that need a tenant. We mock
firebase-admin's verification functions directly so the suite stays
offline.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.auth.dependency import (
    Tenant,
    current_tenant,
    optional_tenant,
    require_role,
)


def _claims(**overrides):
    base = {
        "uid": "uid-test",
        "email": "owner@restaurant.com",
        "restaurant_id": "niko-pizza-kitchen",
        "role": "owner",
    }
    base.update(overrides)
    return base


def test_returns_tenant_from_session_cookie():
    with patch(
        "app.auth.dependency.firebase_auth.verify_session_cookie",
        return_value=_claims(),
    ) as mock:
        tenant = current_tenant(__session="cookie-value", authorization=None)

    mock.assert_called_once_with("cookie-value")
    assert isinstance(tenant, Tenant)
    assert tenant.uid == "uid-test"
    assert tenant.email == "owner@restaurant.com"
    assert tenant.restaurant_id == "niko-pizza-kitchen"
    assert tenant.role == "owner"
    assert tenant.is_admin is False


def test_returns_tenant_from_bearer_token_when_no_cookie():
    with patch(
        "app.auth.dependency.firebase_auth.verify_id_token",
        return_value=_claims(role="tsuki_admin"),
    ) as mock:
        tenant = current_tenant(
            __session=None, authorization="Bearer raw-id-token"
        )

    mock.assert_called_once_with("raw-id-token")
    assert tenant.is_admin is True


def test_prefers_cookie_over_bearer_when_both_present():
    """Cookie wins so the dashboard's session lifetime governs."""
    with patch(
        "app.auth.dependency.firebase_auth.verify_session_cookie",
        return_value=_claims(),
    ) as cookie_mock, patch(
        "app.auth.dependency.firebase_auth.verify_id_token"
    ) as token_mock:
        current_tenant(__session="cookie", authorization="Bearer raw")

    cookie_mock.assert_called_once()
    token_mock.assert_not_called()


def test_raises_401_when_neither_credential_present():
    with pytest.raises(HTTPException) as exc:
        current_tenant(__session=None, authorization=None)
    assert exc.value.status_code == 401


def test_raises_401_when_authorization_header_isnt_bearer():
    """Basic auth, malformed scheme, missing token — all 401."""
    with pytest.raises(HTTPException) as exc:
        current_tenant(__session=None, authorization="Basic abc")
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:
        current_tenant(__session=None, authorization="Bearer ")
    assert exc.value.status_code == 401


def test_raises_401_when_session_cookie_invalid():
    with patch(
        "app.auth.dependency.firebase_auth.verify_session_cookie",
        side_effect=ValueError("invalid signature"),
    ):
        with pytest.raises(HTTPException) as exc:
            current_tenant(__session="bad", authorization=None)
    assert exc.value.status_code == 401


def test_raises_403_when_user_lacks_restaurant_id_claim():
    """Authenticated but unprovisioned: 403 so ops can tell the
    difference from a missing/invalid credential (401)."""
    with patch(
        "app.auth.dependency.firebase_auth.verify_session_cookie",
        return_value=_claims(restaurant_id=None),
    ):
        with pytest.raises(HTTPException) as exc:
            current_tenant(__session="cookie", authorization=None)
    assert exc.value.status_code == 403


def test_default_role_is_owner_when_claim_missing():
    with patch(
        "app.auth.dependency.firebase_auth.verify_session_cookie",
        return_value=_claims(role=None),
    ):
        tenant = current_tenant(__session="cookie", authorization=None)
    assert tenant.role == "owner"


def test_optional_tenant_returns_none_for_no_credentials():
    assert optional_tenant(__session=None, authorization=None) is None


def test_optional_tenant_swallows_invalid_credentials():
    with patch(
        "app.auth.dependency.firebase_auth.verify_session_cookie",
        side_effect=ValueError("invalid"),
    ):
        assert optional_tenant(__session="bad", authorization=None) is None


def test_optional_tenant_returns_tenant_when_credentials_valid():
    with patch(
        "app.auth.dependency.firebase_auth.verify_session_cookie",
        return_value=_claims(),
    ):
        tenant = optional_tenant(__session="cookie", authorization=None)
    assert tenant is not None
    assert tenant.restaurant_id == "niko-pizza-kitchen"


def test_require_role_allows_listed_role():
    admin_only = require_role("tsuki_admin")
    tenant = Tenant(
        uid="u",
        email="x@y.com",
        restaurant_id="*",
        role="tsuki_admin",
    )
    # The dep returns a callable that takes ``tenant`` (resolved by
    # ``current_tenant``) and returns it through if the role matches.
    assert admin_only(tenant=tenant) is tenant


def test_require_role_rejects_other_roles():
    admin_only = require_role("tsuki_admin")
    owner = Tenant(
        uid="u",
        email="x@y.com",
        restaurant_id="niko-pizza-kitchen",
        role="owner",
    )
    with pytest.raises(HTTPException) as exc:
        admin_only(tenant=owner)
    assert exc.value.status_code == 403
