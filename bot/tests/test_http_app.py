"""Tests for jarvis.http.app — the FastAPI /healthz surface."""

from __future__ import annotations

from fastapi.testclient import TestClient

from jarvis.http.app import build_app


def test_healthz_returns_ok():
    app = build_app(commit_sha="abc1234")
    client = TestClient(app)
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["commit_sha"] == "abc1234"
    assert isinstance(body["started_at"], str)
    assert len(body["started_at"]) > 0


def test_healthz_unknown_route_404():
    app = build_app(commit_sha="")
    client = TestClient(app)
    r = client.get("/does-not-exist")
    assert r.status_code == 404
