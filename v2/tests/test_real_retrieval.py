"""Opt-in tests with the real pinned model and a real temporary PostgreSQL DB."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from trader_v2.database import Database
from trader_v2.knowledge_service import KnowledgeService
from trader_v2.settings import Settings


pytestmark = [pytest.mark.integration, pytest.mark.embedding]


@pytest.fixture(scope="module")
def real_knowledge():
    if os.environ.get("V2_RUN_DB_TESTS") != "1" or os.environ.get("V2_RUN_EMBEDDING_TESTS") != "1":
        pytest.skip("enable both V2_RUN_DB_TESTS=1 and V2_RUN_EMBEDDING_TESTS=1")
    admin_dsn = Settings.from_env().database_url
    name = "trader_v2_test_semantic_" + uuid4().hex
    with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(admin_dsn)
    params["dbname"] = name
    try:
        database = Database(make_conninfo(**params))
        database.initialize()
        service = KnowledgeService(database)
        for key, symbol, body, year in (
            ("cash", "601138", "客户欠款回收缓慢，应收账款增长快于收入，经营现金流低于净利润。", 2026),
            ("cake", "601138", "戚风蛋糕出炉后倒扣冷却，避免蛋糕塌陷。", 2026),
            ("other-company", "600398", "客户欠款回收缓慢，应收账款增长快于收入，经营现金流低于净利润。", 2026),
            ("future", "601138", "未来资料：客户欠款回收缓慢，现金回款不足，需要核实收款。", 2027),
        ):
            service.ingest({
                "scope_id": "local", "source_key": key, "title": "合成检索测试资料：" + key,
                "body": body, "symbol": symbol, "kind": "note", "mode": "fixture",
                "source_name": "synthetic semantic test",
                "available_at": datetime(year, 10, 1, tzinfo=timezone.utc),
            })
        yield service
    finally:
        assert name.startswith("trader_v2_test_semantic_")
        with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3) as conn:
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def test_real_model_ranks_related_evidence_above_unrelated_text(real_knowledge):
    result = real_knowledge.search(
        "账面赚了钱，为什么实际没收到货款？", symbol="601138", mode="fixture",
        as_of=datetime(2026, 10, 26, tzinfo=timezone.utc), min_score=0, top_k=5,
    )
    rows = result["results"]
    assert rows[0]["source_key"] == "cash"
    scores = {row["source_key"]: row["score"] for row in rows}
    assert scores["cash"] > scores["cake"]
    assert set(scores) == {"cash", "cake"}
    assert real_knowledge.embedder.status()["loaded"] is True


def test_real_retrieved_chunk_points_to_exact_original_body(real_knowledge):
    result = real_knowledge.search("回款风险", symbol="601138", min_score=0, top_k=1)
    row = result["results"][0]
    evidence = real_knowledge.repository.read_chunk(row["chunk_id"])
    original = real_knowledge.repository.get_document(row["document_id"])
    assert original["body"][evidence["start_char"]:evidence["end_char"]] == evidence["text"]


def test_real_embedding_still_obeys_no_visible_data_cutoff(real_knowledge):
    result = real_knowledge.search(
        "现金回款", symbol="601138", as_of=datetime(2025, 1, 1, tzinfo=timezone.utc), min_score=0,
    )
    assert result["results"] == []
