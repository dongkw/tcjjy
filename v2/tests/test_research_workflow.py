"""Real DB provenance boundaries using explicitly synthetic embedding vectors."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from trader_v2.chunking import CHUNKING_VERSION
from trader_v2.database import Database
from trader_v2.embedding import MODEL_ID, MODEL_REVISION
from trader_v2.knowledge_service import KnowledgeService
from trader_v2.research_workflow import ResearchConflictError, ResearchNotFoundError, ResearchWorkflow
from trader_v2.settings import KnowledgeSettings, Settings


OCTOBER = datetime(2026, 10, 1, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 10, 15, tzinfo=timezone.utc)
PROFILE = {"model_id": MODEL_ID, "model_revision": MODEL_REVISION, "chunking_version": CHUNKING_VERSION}


class SyntheticEmbedder:
    def encode_query(self, _query):
        return [1.0] + [0.0] * 511


@pytest.fixture(scope="module")
def workflow_database():
    if os.environ.get("V2_RUN_DB_TESTS") != "1":
        pytest.skip("set V2_RUN_DB_TESTS=1 to test PostgreSQL")
    admin_dsn = Settings.from_env().database_url
    name = "trader_v2_test_research_" + uuid4().hex
    with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(admin_dsn)
    params["dbname"] = name
    try:
        database = Database(make_conninfo(**params))
        database.initialize()
        knowledge = KnowledgeService(database, embedder=SyntheticEmbedder(), settings=KnowledgeSettings(model_path=Path("synthetic-test")))
        yield ResearchWorkflow(database, knowledge), knowledge.repository
    finally:
        assert name.startswith("trader_v2_test_research_")
        with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def source(repository, scope, key="test.cashflow", *, symbol="601138", mode="fixture", available=OCTOBER, text="经营现金流减少，应收账款增加。"):
    metadata = {
        "scope_id": scope, "source_key": key, "content_hash": hashlib.sha256(f"{text}{symbol}{mode}{available}".encode()).hexdigest(),
        "title": "合成现金流公告", "body": text, "symbol": symbol, "kind": "announcement", "mode": mode,
        "source_name": "synthetic research test", "source_url": "https://example.com/synthetic", "available_at": available,
    }
    return repository.save_document(metadata, [{"chunk_no": 0, "start_char": 0, "end_char": len(text), "text": text,
        "token_count": len(text), "embedding": [1.0] + [0.0] * 511}], **PROFILE)


def begin(workflow, scope):
    return workflow.begin(scope_id=scope, symbol="601138", question="现金回款存在什么问题？", mode="fixture", as_of=CUTOFF)


def search(workflow, session, scope):
    return workflow.search(session["id"], query="客户回款", scope_id=scope)


def report(workflow, session, scope, evidence_ids):
    return workflow.save_report(session["id"], scope_id=scope, title="现金回款研究", summary="需继续核实回款压力。",
        facts=[{"text": "合成公告披露经营现金流减少。", "evidence_ids": evidence_ids}],
        inferences=["应收账款增加可能影响未来现金回收。"], missing_information=["缺少应收账款账龄明细。"])


@pytest.mark.integration
def test_search_read_report_and_persistent_citation_snapshot(workflow_database):
    workflow, repository = workflow_database
    scope = uuid4().hex
    document = source(repository, scope)
    session = begin(workflow, scope)
    result = search(workflow, session, scope)
    assert result["searches_remaining"] == 11
    evidence_id = result["results"][0]["evidence_id"]
    with pytest.raises(ValueError, match="已读取"):
        report(workflow, session, scope, [evidence_id])
    read = workflow.read_evidence(session["id"], evidence_id, scope)
    assert read["read_at"] and read["text"] == document["body"]
    saved = report(workflow, session, scope, [evidence_id])
    assert saved["facts"][0]["evidence_ids"] == [evidence_id]
    assert saved["citations"][0]["currently_visible"]
    assert saved["citations"][0]["text"] == document["body"]
    assert workflow.get_session(session["id"], scope)["status"] == "completed"
    assert workflow.list_reports(scope_id=scope, symbol="601138")[0]["id"] == saved["id"]
    with pytest.raises(ResearchConflictError, match="已完成"):
        search(workflow, session, scope)
    with pytest.raises(ResearchConflictError):
        report(workflow, session, scope, [evidence_id])
    repository.delete_source(document["id"], scope)
    history = workflow.get_report(saved["id"], scope)
    assert not history["citations"][0]["currently_visible"]
    assert history["citations"][0]["text"] == document["body"]
    with pytest.raises(ResearchNotFoundError):
        workflow.get_report(saved["id"], "another-scope")


@pytest.mark.integration
def test_cross_session_and_unretrieved_citations_rejected(workflow_database):
    workflow, repository = workflow_database
    scope = uuid4().hex
    source(repository, scope)
    first, second = begin(workflow, scope), begin(workflow, scope)
    evidence_id = search(workflow, first, scope)["results"][0]["evidence_id"]
    workflow.read_evidence(first["id"], evidence_id, scope)
    with pytest.raises(ResearchNotFoundError):
        workflow.read_evidence(second["id"], evidence_id, scope)
    with pytest.raises(ResearchNotFoundError):
        workflow.read_evidence(first["id"], evidence_id, "other-account")
    with pytest.raises(ValueError):
        report(workflow, second, scope, [evidence_id])
    with pytest.raises(ValueError):
        report(workflow, second, scope, [str(uuid4())])


@pytest.mark.integration
def test_scope_company_mode_cutoff_and_latest_revision_filters(workflow_database):
    workflow, repository = workflow_database
    scope = uuid4().hex
    wanted = source(repository, scope)
    source(repository, scope, "wrong-company", symbol="600398")
    source(repository, scope, "wrong-mode", mode="imported")
    source(repository, scope, "future", available=datetime(2026, 10, 20, tzinfo=timezone.utc))
    source(repository, "another-account", "wrong-scope")
    session = begin(workflow, scope)
    found = search(workflow, session, scope)
    assert [row["document_id"] for row in found["results"]] == [wanted["id"]]
    evidence_id = found["results"][0]["evidence_id"]
    workflow.read_evidence(session["id"], evidence_id, scope)
    source(repository, scope, available=datetime(2026, 10, 10, tzinfo=timezone.utc), text="修订公告明确回款已改善。")
    with pytest.raises(ResearchConflictError, match="新版"):
        report(workflow, session, scope, [evidence_id])
    with pytest.raises(ResearchConflictError):
        workflow.read_evidence(session["id"], evidence_id, scope)
    revised = search(workflow, session, scope)["results"][0]
    assert revised["version"] == 2
    workflow.read_evidence(session["id"], revised["evidence_id"], scope)
    saved = report(workflow, session, scope, [revised["evidence_id"]])
    assert saved["citations"][0]["source_version"] == 2


@pytest.mark.integration
def test_deleted_source_blocks_report_and_empty_research_records_gap(workflow_database):
    workflow, repository = workflow_database
    scope = uuid4().hex
    document = source(repository, scope)
    session = begin(workflow, scope)
    evidence_id = search(workflow, session, scope)["results"][0]["evidence_id"]
    workflow.read_evidence(session["id"], evidence_id, scope)
    repository.delete_source(document["id"], scope)
    with pytest.raises(ResearchConflictError):
        report(workflow, session, scope, [evidence_id])
    assert search(workflow, session, scope)["results"] == []
    saved = workflow.save_report(session["id"], scope_id=scope, title="资料不足", summary="当前无法判断。",
        facts=[], inferences=[], missing_information=["缺少有效公司公告。"])
    assert saved["citations"] == [] and saved["missing_information"]


@pytest.mark.integration
def test_search_budget_is_persisted_and_bounded(workflow_database):
    workflow, _ = workflow_database
    scope = uuid4().hex
    session = begin(workflow, scope)
    for _ in range(workflow.MAX_SEARCHES):
        search(workflow, session, scope)
    with pytest.raises(ResearchConflictError, match="上限"):
        search(workflow, session, scope)
    assert len(workflow.get_session(session["id"], scope)["searches"]) == 12


@pytest.mark.parametrize("kwargs", [
    {"scope_id": "../escape"}, {"symbol": "300001"}, {"question": "   "},
    {"mode": "live"}, {"as_of": datetime(2026, 10, 1)},
    {"as_of": datetime.now(timezone.utc) + timedelta(days=1)},
])
def test_invalid_session_rejected_before_connect(kwargs):
    from unittest.mock import Mock
    database = Mock()
    workflow = ResearchWorkflow(database, Mock())
    with pytest.raises(ValueError):
        workflow.begin(**{"scope_id": "local", "symbol": "601138", "question": "风险", "mode": "fixture", **kwargs})
    database._connect.assert_not_called()


@pytest.mark.parametrize("overrides", [
    {"facts": [{"text": "无引用的断言", "evidence_ids": []}]},
    {"facts": [{"text": "伪造结构", "evidence_ids": [str(uuid4())], "extra": "x"}]},
    {"facts": [], "missing_information": []}, {"inferences": ["\x00"]},
    {"missing_information": ["x"] * 21}, {"summary": " "},
])
def test_invalid_report_rejected_before_connect(overrides):
    from unittest.mock import Mock
    database = Mock()
    workflow = ResearchWorkflow(database, Mock())
    payload = {"title": "资料不足", "summary": "未知", "facts": [], "inferences": [], "missing_information": ["缺少资料"], **overrides}
    with pytest.raises(ValueError):
        workflow.save_report(str(uuid4()), **payload)
    database._connect.assert_not_called()
