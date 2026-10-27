"""HTTP boundary checks that do not require a database server."""

from datetime import date
from unittest.mock import Mock

import psycopg
from fastapi.testclient import TestClient

from trader_v2.app import create_app
from trader_v2.database import DatabaseNotReadyError
from trader_v2.market import MarketDataError, TencentDailyProvider


def test_database_failure_is_503_without_connection_details():
    database = Mock()
    database.health.side_effect = psycopg.OperationalError("postgresql://private-password@host")
    with TestClient(create_app(database)) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert "private-password" not in response.text


def test_unready_database_is_not_reported_healthy():
    database = Mock()
    database.health.side_effect = DatabaseNotReadyError("pgvector 未就绪")
    with TestClient(create_app(database)) as client:
        assert client.get("/health").status_code == 503


def test_source_failure_does_not_save_fixture(monkeypatch):
    database = Mock()

    def unavailable(*args, **kwargs):
        raise MarketDataError("测试数据源不可用")

    monkeypatch.setattr(TencentDailyProvider, "fetch", unavailable)
    with TestClient(create_app(database)) as client:
        response = client.post("/api/stocks/601138/analyze", json={"mode": "live"})
    assert response.status_code == 502
    database.save_analysis.assert_not_called()


def test_invalid_symbol_and_mode_never_touch_database():
    database = Mock()
    with TestClient(create_app(database)) as client:
        assert client.post("/api/stocks/300001/analyze", json={"mode": "fixture"}).status_code == 422
        assert client.post("/api/stocks/601138/analyze", json={"mode": "anything"}).status_code == 422
        assert client.post("/api/stocks/601138/analyze", json={}).status_code == 422
        assert client.get("/api/analyses/not-a-uuid").status_code == 422
    database.save_analysis.assert_not_called()


def test_future_live_cutoff_is_rejected_before_network():
    database = Mock()
    with TestClient(create_app(database)) as client:
        response = client.post(
            "/api/stocks/601138/analyze", json={"mode": "live", "end_date": date.max.isoformat()},
        )
    assert response.status_code == 422
    database.save_analysis.assert_not_called()
