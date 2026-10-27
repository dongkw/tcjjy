"""Real pgvector tests with synthetic vectors, isolated from the user's DB."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

from trader_v2.database import Database
from trader_v2.embedding import MODEL_REVISION
from trader_v2.knowledge_service import KnowledgeService
from trader_v2.memory_service import MemoryConflictError, MemoryService
from trader_v2.settings import KnowledgeSettings, Settings

from test_knowledge_service import StubEmbedder
from test_memory_service import memory


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def memory_database():
    if os.environ.get("V2_RUN_DB_TESTS") != "1":
        pytest.skip("set V2_RUN_DB_TESTS=1 to test PostgreSQL")
    admin_dsn = Settings.from_env().database_url
    name = "trader_v2_test_memory_" + uuid4().hex
    with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(admin_dsn)
    params["dbname"] = name
    dsn = make_conninfo(**params)
    try:
        database = Database(dsn)
        database.initialize()
        knowledge = KnowledgeService(database, embedder=StubEmbedder(), settings=KnowledgeSettings(model_path=Path("unused")))
        yield MemoryService(database, knowledge), database
    finally:
        assert name.startswith("trader_v2_test_memory_")
        with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def test_recall_uses_current_revision_and_preserves_history(memory_database):
    service, _ = memory_database
    scope = uuid4().hex
    saved = service.save(memory(scope_id=scope))
    assert saved["revision"] == 1 and saved["epistemic_status"] == "user_asserted"
    updated = service.update(saved["id"], memory(content="研究时先看利润再看现金流。"), scope_id=scope, expected_revision=1)
    assert updated["revision"] == 2
    hits = service.recall("研究偏好", scope_id=scope)["results"]
    assert len(hits) == 1 and hits[0]["content"] == updated["content"]
    assert hits[0]["score"] == pytest.approx(1)
    history = service.history(saved["id"], scope)
    assert [item["revision"] for item in history] == [2, 1]
    assert history[1]["content"] == saved["content"]
    with pytest.raises(MemoryConflictError):
        service.update(saved["id"], memory(), scope_id=scope, expected_revision=1)
    assert service.deactivate(saved["id"], scope)
    assert not service.deactivate(saved["id"], scope)
    assert service.recall("研究偏好", scope_id=scope)["results"] == []
    assert service.list(scope_id=scope) == []
    assert service.list(scope_id=scope, include_inactive=True)[0]["status"] == "deactivated"
    assert [item["revision"] for item in service.history(saved["id"], scope)] == [3, 2, 1]
    with pytest.raises(MemoryConflictError):
        service.update(saved["id"], memory(), scope_id=scope, expected_revision=3)


def test_company_scope_kind_expiry_and_profile_filter_before_ranking(memory_database):
    service, database = memory_database
    scope = uuid4().hex
    general = service.save(memory(scope_id=scope))
    wanted = service.save(memory(scope_id=scope, symbol="601138"))
    service.save(memory(scope_id=scope, symbol="600398"))
    service.save(memory(scope_id="elsewhere", symbol="601138"))
    service.save(memory(scope_id=scope, kind="pending", symbol="601138"))
    expired = service.save(memory(scope_id=scope, symbol="601138"))
    wrong_profile = service.save(memory(scope_id=scope, symbol="601138"))
    unrelated = service.save(memory(scope_id=scope, symbol="601138"))
    with database._connect() as conn:
        conn.execute("UPDATE agent_memory SET created_at=now()-interval '2 days', expires_at=now()-interval '1 day' WHERE id=%s", (expired["id"],))
        conn.execute("UPDATE agent_memory SET embedding_revision='wrong-test-profile' WHERE id=%s", (wrong_profile["id"],))
        conn.execute("UPDATE agent_memory SET embedding=%s::vector WHERE id=%s", ("[0,1," + ",".join(["0"] * 510) + "]", unrelated["id"]))
    hits = service.recall("偏好", scope_id=scope, symbol="601138", kind="preference", min_score=0.9)["results"]
    assert {item["id"] for item in hits} == {wanted["id"], general["id"]}
    assert service.get(wanted["id"], "another-scope") is None
    assert service.history(wanted["id"], "another-scope") == []
    assert not service.deactivate(wanted["id"], "another-scope")
    assert service.update(wanted["id"], memory(), scope_id="another-scope", expected_revision=1) is None


def test_report_lesson_cannot_invent_or_cross_scope_company(memory_database):
    service, database = memory_database
    scope = uuid4().hex
    data = memory(scope_id=scope, kind="lesson", source_type="research_report",
                  source_reference=str(uuid4()), symbol="601138")
    # A nonexistent report must fail even if all UUID and text shapes are valid.
    with pytest.raises(ValueError, match="来源报告不存在"):
        service.save(data)
    assert service.list(scope_id=scope, include_inactive=True) == []
    session_id, report_id = str(uuid4()), str(uuid4())
    with database._connect() as conn:
        conn.execute("""INSERT INTO research_sessions (id,scope_id,symbol,question,mode,as_of)
            VALUES (%s,%s,'601138','memory provenance test','fixture',now())""", (session_id, scope))
        # This fixture targets memory/report provenance only. Research tests
        # separately exercise search receipts and citation validation.
        conn.execute("""INSERT INTO research_reports (
            id,session_id,scope_id,symbol,mode,as_of,title,summary,facts,inferences,missing_information
            ) VALUES (%s,%s,%s,'601138','fixture',now(),'合成报告','测试出处','[]'::jsonb,'{}','{}')""",
            (report_id, session_id, scope))
    data["source_reference"] = report_id
    with pytest.raises(ValueError, match="来源报告不存在"):
        service.save({**data, "scope_id": "another-scope"})
    with pytest.raises(ValueError, match="经验股票必须"):
        service.save({**data, "symbol": "600398"})
    with pytest.raises(ValueError, match="经验股票必须"):
        service.save({**data, "symbol": None})
    saved = service.save(data)
    assert saved["epistemic_status"] == "provisional_lesson"
    assert saved["source_reference"] == report_id and saved["symbol"] == "601138"
    assert saved["expires_at"] - saved["created_at"] == timedelta(days=90)
