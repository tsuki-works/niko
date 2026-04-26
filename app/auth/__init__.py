"""Firebase Auth integration for tenant-scoped API access (PR D of #79/#81).

Two entrypoints:

- ``current_tenant`` — FastAPI dependency. Reads the ``Authorization``
  header (or session cookie), verifies via firebase-admin, returns a
  ``Tenant`` describing who's calling and which restaurant they may
  access.
- ``Tenant`` — the verified caller's identity. Routes that need
  tenant scoping declare ``tenant: Tenant = Depends(current_tenant)``
  and read ``tenant.restaurant_id``.

The dashboard sets a Firebase session cookie after a successful
sign-in; FastAPI prefers that cookie when present and falls back to
a raw ``Bearer`` ID token for direct API consumers (curl, scripts,
the admin CLI).
"""

from app.auth.dependency import (
    Tenant,
    current_tenant,
    optional_tenant,
    require_role,
)

__all__ = [
    "Tenant",
    "current_tenant",
    "optional_tenant",
    "require_role",
]
