"""Local FastAPI surface; Swagger is the first-stage interactive entry point."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from .database import Database, DatabaseNotReadyError
from .embedding import EmbeddingUnavailableError
from .knowledge_api import knowledge_router
from .knowledge_service import KnowledgeService
from .market import MarketDataError
from .models import validate_symbol
from .memory_api import memory_router
from .memory_service import MemoryService
from .research_api import research_router
from .research_workflow import ResearchWorkflow
from .service import ResearchService
from .settings import Settings


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["fixture", "live"] = Field(description="fixture 为合成样例；live 为腾讯真实日线")
    limit: int = Field(default=120, ge=20, le=640, description="请求日线数量，完整规则至少需要61根")
    end_date: date | None = Field(default=None, description="日线截止日期，不能作为可成交报价使用")


def create_app(database: Database | None = None, knowledge_service: KnowledgeService | None = None) -> FastAPI:
    db = database or Database(Settings.from_env().database_url)
    service = ResearchService(db)
    knowledge = knowledge_service or KnowledgeService(db)
    api = FastAPI(
        title="天才交易员 V2 · Agent研究与长期记忆",
        version="0.3.0",
        description=("查日线、运行趋势规则、导入文本、切块和本地向量检索。"
                     "fixture 明确为合成样例，live 才访问真实来源。"
                     "知识库 imported 表示用户导入，不代表来源已经核实。"
                     "dsh 插件负责研究循环，后端保存带引用报告和长期记忆。本阶段没有交易能力。"),
    )
    api.state.database = db
    api.include_router(knowledge_router(knowledge))
    api.include_router(memory_router(MemoryService(db, knowledge)))
    api.include_router(research_router(ResearchWorkflow(db, knowledge)))

    @api.exception_handler(EmbeddingUnavailableError)
    def embedding_unavailable(_request: Request, exc: EmbeddingUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @api.exception_handler(ValueError)
    def invalid_business_input(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @api.exception_handler(DatabaseNotReadyError)
    def database_not_ready(_request: Request, exc: DatabaseNotReadyError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @api.exception_handler(psycopg.Error)
    def database_error(_request: Request, _exc: psycopg.Error) -> JSONResponse:
        return JSONResponse(status_code=503, content={
            "detail": "数据库暂不可用，请检查 PostgreSQL 并运行 trader-v2 init-db。",
        })

    @api.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/docs")

    @api.get("/health", tags=["运行状态"])
    def health() -> dict:
        return {"status": "ok", "stage": 3, **db.health()}

    @api.get("/api/watchlist", tags=["数据与规则"], summary="查看当前自选股")
    def watchlist() -> list[dict]:
        return db.get_watchlist()

    @api.post("/api/stocks/{symbol}/analyze", tags=["数据与规则"], summary="获取日线并计算规则，保存到数据库")
    def analyze(symbol: str, body: AnalyzeRequest) -> dict:
        try:
            return service.analyze(symbol, mode=body.mode, limit=body.limit, end_date=body.end_date)
        except MarketDataError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.get("/api/analyses", tags=["历史结果"], summary="查询已保存结果，可分开查看样例和真实数据")
    def analyses(
        symbol: str | None = None, mode: Literal["fixture", "live"] | None = None,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict]:
        if symbol is not None:
            try:
                validate_symbol(symbol)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return db.list_analyses(symbol=symbol, mode=mode, limit=limit)

    @api.get("/api/analyses/{run_id}", tags=["历史结果"], summary="通过记录ID回查结果")
    def analysis(run_id: UUID) -> dict:
        saved = db.get_analysis(str(run_id))
        if saved is None:
            raise HTTPException(status_code=404, detail="没有找到该研究记录")
        return saved

    return api
