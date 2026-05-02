"""FastAPI dependency for validating Twilio request signatures.

Applies to all POST webhook routes that Twilio calls (see router.py).
Rejects with 403 on missing or invalid X-Twilio-Signature.

Bypass: when settings.testing_mode is True or TWILIO_AUTH_TOKEN is unset
(local dev without a real Twilio number), validation is skipped with a
one-time log warning so tests don't need real signatures.
"""

from __future__ import annotations

import logging

from fastapi import Depends, Header, HTTPException, Request
from twilio.request_validator import RequestValidator

from app.config import settings

logger = logging.getLogger(__name__)
_bypass_warned = False


async def require_twilio_signature(
    request: Request,
    x_twilio_signature: str | None = Header(default=None),
) -> None:
    global _bypass_warned

    if settings.testing_mode or not settings.twilio_auth_token:
        if not _bypass_warned:
            logger.warning(
                "Twilio signature validation disabled (testing_mode=%s, "
                "auth_token_set=%s)",
                settings.testing_mode,
                bool(settings.twilio_auth_token),
            )
            _bypass_warned = True
        return

    if not x_twilio_signature:
        raise HTTPException(status_code=403, detail="Missing X-Twilio-Signature")

    if not settings.public_base_url:
        raise HTTPException(
            status_code=500,
            detail="PUBLIC_BASE_URL not configured — cannot validate Twilio signature",
        )

    # Reconstruct the canonical URL Twilio signed.
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    url = f"{settings.public_base_url.rstrip('/')}{path}"

    form = await request.form()
    params = dict(form)

    validator = RequestValidator(settings.twilio_auth_token)
    if not validator.validate(url, params, x_twilio_signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
