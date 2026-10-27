"""Knowledge HTTP boundary tests with explicit stubs and no model download."""

from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from trader_v2.app import create_app
from trader_v2.embedding import LocalBgeEmbedder
from trader_v2.knowledge_service import KnowledgeService
from trader_v2.settings import KnowledgeSettings

from test_knowledge_service import StubEmbedder


def api_service(embedder=None):
    database = Mock()
    database.health.return_value = {"database": "test", "pgvector_version": "test", "schema_version": 4}
    service = KnowledgeService(
        database, embedder=embedder or StubEmbedder(),
        settings=KnowledgeSettings(model_path=Path("unused-api-test-model")),
    )
    service.repository = Mock()
    service.repository.find_existing.return_value = None
    service.repository.search.return_value = []
    return TestClient(create_app(database, knowledge_service=service)), service


def input_document(**overrides):
    return {
        "source_key": "api.source", "title": "API测试资料", "body": "需要核实公司收款情况。",
        "symbol": "601138", "kind": "note", "source_name": "HTTP测试输入",
        "available_at": "2026-10-01T08:00:00Z", **overrides,
    }


def test_stage_three_health_and_no_evidence_response():
    client, _ = api_service()
    with client:
        health = client.get("/health").json()
        assert health["stage"] == 3 and health["schema_version"] == 4
        response = client.post("/api/knowledge/search", json={"query": "没有资料的问题"})
        assert response.status_code == 200
        assert response.json()["results"] == []


def test_missing_local_model_is_503_not_fake_vectors(tmp_path):
    client, service = api_service(LocalBgeEmbedder(tmp_path / "missing-model"))
    with client:
        status = client.get("/api/knowledge/status")
        assert status.status_code == 200 and not status.json()["downloaded"]
        response = client.post("/api/knowledge/search", json={"query": "资金回收风险"})
        assert response.status_code == 503
        assert client.post("/api/knowledge/documents", json=input_document()).status_code == 503
    service.repository.search.assert_not_called()
    service.repository.save_document.assert_not_called()


@pytest.mark.parametrize("overrides", [
    {"scope_id": "../escape"}, {"symbol": "300001"}, {"body": "   "},
    {"available_at": "2026-10-01T08:00:00"}, {"mode": "live"},
    {"source_url": "file:///private"}, {"source_url": "https://name:password@example.com"},
    {"unknown_field": "not-allowed"}, {"title": "invalid\x00title"},
])
def test_invalid_document_is_http_422(overrides):
    client, service = api_service()
    with client:
        assert client.post("/api/knowledge/documents", json=input_document(**overrides)).status_code == 422
    service.repository.save_document.assert_not_called()


@pytest.mark.parametrize("body", [
    {"query": "   "}, {"query": "甲" * 2001}, {"query": "x", "top_k": 0},
    {"query": "x", "min_score": 1.1}, {"query": "x", "as_of": "2026-10-01T08:00:00"},
    {"query": "x", "scope_id": "../escape"}, {"query": "x", "extra": True},
    {"query": "甲" * 501},
])
def test_invalid_search_does_not_query_database(body):
    client, service = api_service()
    with client:
        response = client.post("/api/knowledge/search", json=body)
        assert response.status_code == 422
    service.repository.search.assert_not_called()


def test_document_list_excludes_full_body_and_missing_evidence_is_404():
    client, service = api_service()
    service.repository.list_documents.return_value = [{"id": str(uuid4()), "title": "标题", "body": "完整正文"}]
    service.repository.get_document.return_value = None
    service.repository.read_chunk.return_value = None
    service.repository.delete_source.return_value = False
    missing = str(uuid4())
    with client:
        response = client.get("/api/knowledge/documents")
        assert "body" not in response.json()[0]
        assert client.get(f"/api/knowledge/documents/{missing}").status_code == 404
        assert client.get(f"/api/knowledge/chunks/{missing}").status_code == 404
        assert client.delete(f"/api/knowledge/documents/{missing}").status_code == 404
        assert client.get("/api/knowledge/chunks/not-a-uuid").status_code == 422
