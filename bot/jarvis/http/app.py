"""FastAPI surface co-located with the Discord gateway client.

Exposes /healthz for uptime checks. POST /post is added in PR 6 when
the custom MCP shim lands. build_app(commit_sha=...) is a factory so
tests can inject a known SHA without touching env vars.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI


def build_app(commit_sha: str) -> FastAPI:
    started_at = datetime.now(timezone.utc).isoformat()
    app = FastAPI(title="jarvis", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {
            "status": "ok",
            "commit_sha": commit_sha,
            "started_at": started_at,
        }

    return app
