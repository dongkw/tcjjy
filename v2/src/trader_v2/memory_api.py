"""HTTP boundary for explicit memory writing and bounded semantic recall."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .memory_service import MemoryConflictError, MemoryService


class MemoryFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["preference", "pending", "lesson"]
    content: str = Field(min_length=1, max_length=1200, description="简短完整记忆；最多400个本地模型token，超限会拒绝保存")
    symbol: str | None = None
    source_type: Literal["user_statement", "research_report"]
    source_reference: str = Field(min_length=1, max_length=200, description="明确用户原话，或已保存报告UUID")
    expires_at: AwareDatetime | None = None


class SaveMemoryRequest(MemoryFields):
    scope_id: str = "local"


class UpdateMemoryRequest(MemoryFields):
    expected_revision: int = Field(ge=1)


class RecallMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    scope_id: str = "local"
    symbol: str | None = None
    kind: Literal["preference", "pending", "lesson"] | None = None
    mode: Literal["fixture", "imported"] | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float | None = Field(default=None, ge=0, le=1)


def memory_router(service: MemoryService) -> APIRouter:
    router = APIRouter(prefix="/api/memory", tags=["长期记忆"])

    @router.post("", summary="保存明确用户偏好、待办或有报告出处的待验证经验")
    def save(body: SaveMemoryRequest) -> dict:
        return service.save(body.model_dump())

    @router.post("/recall", summary="先限定范围、股票和有效期，再语义召回少量记忆")
    def recall(body: RecallMemoryRequest) -> dict:
        return service.recall(**body.model_dump())

    @router.get("", summary="列出当前记忆，可显式查看失效或停用记录")
    def memories(scope_id: str = "local", symbol: str | None = None,
                 kind: Literal["preference", "pending", "lesson"] | None = None,
                 mode: Literal["fixture", "imported"] | None = None,
                 include_inactive: bool = False, limit: int = Query(default=20, ge=1, le=100)) -> list[dict]:
        return service.list(scope_id=scope_id, symbol=symbol, kind=kind, mode=mode,
                            include_inactive=include_inactive, limit=limit)

    @router.get("/{memory_id}", summary="读取当前记忆及其revision")
    def get(memory_id: UUID, scope_id: str = "local") -> dict:
        row = service.get(str(memory_id), scope_id)
        if row is None:
            raise HTTPException(status_code=404, detail="未找到记忆")
        return row

    @router.put("/{memory_id}", summary="替换记忆并保留历史；需提交读到的revision")
    def update(memory_id: UUID, body: UpdateMemoryRequest, scope_id: str = "local") -> dict:
        data = body.model_dump()
        expected = data.pop("expected_revision")
        try:
            row = service.update(str(memory_id), data, expected_revision=expected, scope_id=scope_id)
        except MemoryConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if row is None:
            raise HTTPException(status_code=404, detail="未找到记忆")
        return row

    @router.delete("/{memory_id}", summary="停用记忆，立即退出召回，保留修改历史")
    def deactivate(memory_id: UUID, scope_id: str = "local") -> dict:
        if not service.deactivate(str(memory_id), scope_id):
            raise HTTPException(status_code=404, detail="记忆不存在或已经停用")
        return {"id": str(memory_id), "deactivated": True}

    @router.get("/{memory_id}/history", summary="查看记忆的每次修订和停用记录")
    def history(memory_id: UUID, scope_id: str = "local") -> list[dict]:
        rows = service.history(str(memory_id), scope_id)
        if not rows:
            raise HTTPException(status_code=404, detail="未找到记忆")
        return rows

    return router
