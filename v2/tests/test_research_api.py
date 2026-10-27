"""Research HTTP request shapes and error classifications without model calls."""

from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trader_v2.research_api import research_router
from trader_v2.research_workflow import ResearchConflictError, ResearchNotFoundError


def api():
    service = Mock()
    app = FastAPI()
    app.include_router(research_router(service))
    return TestClient(app), service


def test_begin_search_read_report_routes_forward_validated_values():
    client, service = api()
    session_id, evidence_id, report_id = str(uuid4()), str(uuid4()), str(uuid4())
    service.begin.return_value = {"id": session_id}
    service.search.return_value = {"results": [{"evidence_id": evidence_id}]}
    service.read_evidence.return_value = {"evidence_id": evidence_id, "text": "原文"}
    service.save_report.return_value = {"id": report_id}
    with client:
        assert client.post("/api/research/sessions", json={"symbol": "601138", "question": "回款风险", "mode": "fixture"}).json()["id"] == session_id
        assert client.post(f"/api/research/sessions/{session_id}/search", json={"query": "客户回款"}).status_code == 200
        assert client.get(f"/api/research/sessions/{session_id}/evidence/{evidence_id}").status_code == 200
        response = client.post(f"/api/research/sessions/{session_id}/reports", json={"title": "研究", "summary": "有待核实",
            "facts": [{"text": "公告披露", "evidence_ids": [evidence_id]}]})
        assert response.status_code == 200 and response.json()["id"] == report_id
    assert service.save_report.call_args.kwargs["facts"][0]["evidence_ids"] == [evidence_id]


@pytest.mark.parametrize("body", [
    {"symbol": "601138", "question": "x", "mode": "live"},
    {"symbol": "601138", "question": "x", "mode": "fixture", "as_of": "2026-10-01T00:00:00"},
    {"symbol": "601138", "question": "x", "mode": "fixture", "unknown": True},
])
def test_begin_rejects_invalid_http_shape(body):
    client, service = api()
    assert client.post("/api/research/sessions", json=body).status_code == 422
    service.begin.assert_not_called()


def test_missing_and_stale_evidence_are_distinct_http_errors():
    client, service = api()
    path = f"/api/research/sessions/{uuid4()}/evidence/{uuid4()}"
    service.read_evidence.side_effect = ResearchNotFoundError("不属于本范围")
    assert client.get(path).status_code == 404
    service.read_evidence.side_effect = ResearchConflictError("来源已更新")
    assert client.get(path).status_code == 409
