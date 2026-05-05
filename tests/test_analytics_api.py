"""Integration test for GET /analytics/summary."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth.dependency import Tenant, current_tenant
from app.main import app
from app.storage import analytics
from app.storage import firestore as order_storage


@pytest.fixture
def client():
    app.dependency_overrides[current_tenant] = lambda: Tenant(
        uid="u1",
        email="o@niko.test",
        restaurant_id="r1",
        role="owner",
    )
    yield TestClient(app)
    app.dependency_overrides.pop(current_tenant, None)


@pytest.fixture(autouse=True)
def reset_storage():
    yield
    order_storage.set_client(None)


def test_get_analytics_summary_returns_metrics(client: TestClient):
    fake = analytics.OrderSummary(
        today_count=3,
        seven_day_count=21,
        average_order_value_7d=24.50,
        completion_rate_7d=0.92,
    )
    with patch(
        "app.main.analytics.summarize_orders",
        return_value=fake,
    ):
        resp = client.get("/analytics/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["today_count"] == 3
    assert body["seven_day_count"] == 21
    assert body["average_order_value_7d"] == 24.50
    assert body["completion_rate_7d"] == 0.92


def test_get_analytics_summary_passes_tenant_id(client: TestClient):
    """Verify the handler scopes the aggregation to the calling tenant."""
    fake = analytics.OrderSummary(
        today_count=0,
        seven_day_count=0,
        average_order_value_7d=0.0,
        completion_rate_7d=0.0,
    )
    with patch(
        "app.main.analytics.summarize_orders",
        return_value=fake,
    ) as mock_fn:
        client.get("/analytics/summary")
    mock_fn.assert_called_once_with(restaurant_id="r1")
