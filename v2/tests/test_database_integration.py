"""End-to-end stage-one checks against a separate, temporary PostgreSQL DB.

Opt in with V2_RUN_DB_TESTS=1. Only the test-created database is removed.
"""

import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from trader_v2.app import create_app
from trader_v2.database import Database
from trader_v2.settings import Settings


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def isolated_database():
    if os.environ.get("V2_RUN_DB_TESTS") != "1":
        pytest.skip("set V2_RUN_DB_TESTS=1 to test PostgreSQL")
    admin_dsn = Settings.from_env().database_url
    database_name = "trader_v2_test_" + uuid4().hex
    with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    params = conninfo_to_dict(admin_dsn)
    params["dbname"] = database_name
    test_dsn = make_conninfo(**params)
    database = Database(test_dsn)
    database.initialize()
    try:
        yield database, test_dsn
    finally:
        assert database_name.startswith("trader_v2_test_")
        with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


def test_pgvector_and_http_round_trip(isolated_database):
    database, dsn = isolated_database
    database.initialize()  # a second setup preserves existing data
    with TestClient(create_app(database)) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["pgvector_version"]
        assert len(client.get("/api/watchlist").json()) == 3
        response = client.post("/api/stocks/601138/analyze", json={"mode": "fixture", "limit": 90})
        assert response.status_code == 200
        saved = response.json()
        assert saved["mode"] == "fixture" and saved["source"] == "fixture"
        assert saved["bar_count"] == 90
        assert saved["status"] == "PASS"
        assert client.get(f"/api/analyses/{saved['id']}").json() == saved
        assert client.get("/api/analyses", params={"mode": "live"}).json() == []
        assert saved["id"] in [item["id"] for item in client.get("/api/analyses", params={"mode": "fixture"}).json()]
    with psycopg.connect(dsn) as conn:
        count = conn.execute("SELECT count(*) FROM daily_bars WHERE snapshot_id = %s", (saved["snapshot_id"],)).fetchone()[0]
        assert count == 90
        distance = conn.execute("SELECT '[1,0,0]'::vector <=> '[1,0,0]'::vector").fetchone()[0]
        assert distance == pytest.approx(0)


def test_insufficient_history_is_saved_as_blocked(isolated_database):
    database, _ = isolated_database
    with TestClient(create_app(database)) as client:
        response = client.post("/api/stocks/000969/analyze", json={"mode": "fixture", "limit": 20})
        saved = response.json()
        assert response.status_code == 200
        assert saved["status"] == "BLOCKED"
        assert saved["missing_fields"]
        assert client.get(f"/api/analyses/{saved['id']}").json()["status"] == "BLOCKED"
