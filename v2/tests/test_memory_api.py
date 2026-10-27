"""HTTP contract tests for explicit memory control."""

from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from trader_v2.memory_api import memory_router
from trader_v2.memory_service import MemoryConflictError


def client_service():
    service = Mock()
    app = FastAPI()
    app.include_router(memory_router(service))

    @app.exception_handler(ValueError)
    def invalid(_request: Request, exc: ValueError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    return TestClient(app), service


def body(**overrides):
    return {"kind": "preference", "content": "先核对现金流。", "source_type": "user_statement",
            "source_reference": "以后先看现金流", **overrides}


def test_save_and_recall_contract_preserves_provenance():
    client, service = client_service()
    service.save.return_value = {"id": str(uuid4()), "revision": 1}
    service.recall.return_value = {"results": []}
    with client:
        assert client.post("/api/memory", json=body()).status_code == 200
        assert client.post("/api/memory/recall", json={"query": "研究偏好"}).json() == {"results": []}
    data = service.save.call_args.args[0]
    assert data["scope_id"] == "local" and data["source_type"] == "user_statement"
    assert data["source_reference"] == "以后先看现金流" and data["expires_at"] is None


def test_unknown_fields_naive_expiry_and_invalid_uuid_rejected():
    client, service = client_service()
    with client:
        assert client.post("/api/memory", json=body(extra="no")).status_code == 422
        assert client.post("/api/memory", json=body(expires_at="2026-12-01T00:00:00")).status_code == 422
        assert client.post("/api/memory/recall", json={"query": "x", "top_k": 21}).status_code == 422
        assert client.get("/api/memory/not-a-uuid").status_code == 422
    service.save.assert_not_called()
    service.recall.assert_not_called()


def test_stale_revision_is_409_and_missing_scope_is_404():
    client, service = client_service()
    memory_id = str(uuid4())
    service.update.side_effect = MemoryConflictError("记忆已被修改")
    service.get.return_value = None
    service.history.return_value = []
    service.deactivate.return_value = False
    with client:
        assert client.put(f"/api/memory/{memory_id}", json=body(expected_revision=1)).status_code == 409
        assert client.get(f"/api/memory/{memory_id}?scope_id=elsewhere").status_code == 404
        assert client.get(f"/api/memory/{memory_id}/history?scope_id=elsewhere").status_code == 404
        assert client.delete(f"/api/memory/{memory_id}?scope_id=elsewhere").status_code == 404
    assert service.get.call_args.args == (memory_id, "elsewhere")
