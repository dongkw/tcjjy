"""The knowledge HTTP endpoints do not download models or fetch arbitrary URLs."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .knowledge_service import KnowledgeService, validate_scope


class DocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_id: str = "local"
    source_key: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=200000)
    symbol: str | None = None
    kind: Literal["announcement", "research", "note"]
    mode: Literal["fixture", "imported"] = "imported"
    source_name: str = Field(min_length=1, max_length=200)
    source_url: str | None = None
    available_at: AwareDatetime


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    scope_id: str = "local"
    symbol: str | None = None
    kind: Literal["announcement", "research", "note"] | None = None
    mode: Literal["fixture", "imported"] | None = None
    as_of: AwareDatetime | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float | None = Field(default=None, ge=0, le=1)


def knowledge_router(service: KnowledgeService) -> APIRouter:
    router = APIRouter(prefix="/api/knowledge", tags=["资料与向量检索"])

    @router.get("/status", summary="查看本地模型文件与加载状态")
    def status() -> dict:
        return service.embedder.status()

    @router.post("/documents", summary="导入资料正文，切块并生成向量")
    def ingest(body: DocumentRequest) -> dict:
        return service.ingest(body.model_dump())

    @router.get("/documents", summary="列出资料的最新版本")
    def documents(
        scope_id: str = "local", symbol: str | None = None,
        mode: Literal["fixture", "imported"] | None = None, limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict]:
        validate_scope(scope_id)
        return [
            {key: value for key, value in row.items() if key != "body"}
            for row in service.repository.list_documents(scope_id=scope_id, symbol=symbol, mode=mode, limit=limit)
        ]

    @router.get("/documents/{document_id}", summary="读取资料正文和来源")
    def document(document_id: UUID, scope_id: str = "local") -> dict:
        validate_scope(scope_id)
        row = service.repository.get_document(str(document_id), scope_id)
        if row is None:
            raise HTTPException(status_code=404, detail="未找到资料")
        return row

    @router.delete("/documents/{document_id}", summary="删除整份来源及其全部版本，不再参与检索")
    def delete_document(document_id: UUID, scope_id: str = "local") -> dict:
        validate_scope(scope_id)
        changed = service.repository.delete_source(str(document_id), scope_id)
        if not changed:
            raise HTTPException(status_code=404, detail="资料不存在或已经删除")
        return {"deleted": True, "document_id": str(document_id)}

    @router.get("/chunks/{chunk_id}", summary="通过片段ID回查原文与准确字符位置")
    def chunk(chunk_id: UUID, scope_id: str = "local") -> dict:
        validate_scope(scope_id)
        row = service.repository.read_chunk(str(chunk_id), scope_id)
        if row is None:
            raise HTTPException(status_code=404, detail="未找到原文片段")
        return row

    @router.post("/search", summary="将问题向量化并按相似度检索，返回原文及出处")
    def search(body: SearchRequest) -> dict:
        return service.search(**body.model_dump())

    @router.post("/demo", summary="导入明确标识为合成的学习资料，可重复执行")
    def demo() -> dict:
        rows = service.seed_demo()
        return {"mode": "fixture", "documents": [
            {key: row[key] for key in ("id", "source_key", "title", "version", "chunk_count", "reused")}
            for row in rows
        ]}

    return router
