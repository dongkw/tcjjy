"""HTTP adapter for the Agent's bounded, citation-aware research workflow."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .research_workflow import ResearchConflictError, ResearchNotFoundError, ResearchWorkflow


class BeginResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_id: str = "local"
    symbol: str
    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["fixture", "imported"]
    as_of: AwareDatetime | None = None


class ResearchSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_id: str = "local"
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    min_score: float | None = Field(default=None, ge=0, le=1)


class ResearchFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[UUID] = Field(min_length=1, max_length=10)


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_id: str = "local"
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4000)
    facts: list[ResearchFact] = Field(default_factory=list, max_length=20)
    inferences: list[str] = Field(default_factory=list, max_length=20)
    missing_information: list[str] = Field(default_factory=list, max_length=20)


def research_router(service: ResearchWorkflow) -> APIRouter:
    router = APIRouter(prefix="/api/research", tags=["Agent研究与引用"])

    def call(method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except ResearchNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ResearchConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/sessions", summary="开始一次限定股票、来源模式和截止时间的研究")
    def begin(body: BeginResearchRequest) -> dict:
        return call(service.begin, **body.model_dump())

    @router.get("/sessions/{session_id}", summary="查看本次研究检索、已读证据和报告进度")
    def session(session_id: UUID, scope_id: str = "local") -> dict:
        return call(service.get_session, str(session_id), scope_id)

    @router.post("/sessions/{session_id}/search", summary="检索并记录本次研究可引用的候选证据")
    def search(session_id: UUID, body: ResearchSearchRequest) -> dict:
        return call(service.search, str(session_id), **body.model_dump())

    @router.get("/sessions/{session_id}/evidence/{evidence_id}", summary="读取候选来源，建立已读证据记录")
    def evidence(session_id: UUID, evidence_id: UUID, scope_id: str = "local") -> dict:
        return call(service.read_evidence, str(session_id), str(evidence_id), scope_id)

    @router.post("/sessions/{session_id}/reports", summary="区分事实、推断和缺口，校验引用后保存报告")
    def report(session_id: UUID, body: ReportRequest) -> dict:
        payload = body.model_dump()
        for fact in payload["facts"]:
            fact["evidence_ids"] = [str(value) for value in fact["evidence_ids"]]
        return call(service.save_report, str(session_id), **payload)

    @router.get("/reports", summary="查询已保存的研究报告")
    def reports(scope_id: str = "local", symbol: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> list[dict]:
        return call(service.list_reports, scope_id=scope_id, symbol=symbol, limit=limit)

    @router.get("/reports/{report_id}", summary="读取报告、原文引用快照和当前来源有效性")
    def saved_report(report_id: UUID, scope_id: str = "local") -> dict:
        return call(service.get_report, str(report_id), scope_id)

    return router
