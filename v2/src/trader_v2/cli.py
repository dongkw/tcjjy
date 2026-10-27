"""Local data, rule, model preparation, and semantic-retrieval commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import uvicorn

from .database import Database
from .market import MarketDataError
from .service import ResearchService
from .settings import KnowledgeSettings, Settings


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("时间必须使用 ISO 格式，例如 2026-10-20T16:00:00+08:00") from exc
    if parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("时间必须包含时区，例如 +08:00 或 Z")
    return parsed


def _model_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise argparse.ArgumentTypeError("模型下载端点必须是不含凭据的 HTTP/HTTPS 地址")
    return value.rstrip("/")


def main() -> int:
    # Keep Chinese output readable in Windows terminals and redirected logs.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="天才交易员 V2：数据、规则与向量检索")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="启用 pgvector 并初始化业务表")
    commands.add_parser("health", help="检查 PostgreSQL 和 pgvector")
    serve = commands.add_parser("serve", help="启动本地接口及 /docs")
    serve.add_argument("--port", type=int)
    analyze = commands.add_parser("analyze", help="获取数据、计算趋势规则并保存结果")
    analyze.add_argument("symbol")
    analyze.add_argument("--mode", required=True, choices=["fixture", "live"])
    analyze.add_argument("--limit", type=int, default=120, choices=range(20, 641), metavar="20..640")
    analyze.add_argument("--end-date", type=date.fromisoformat)

    prepare = commands.add_parser("prepare-model", help="显式下载固定版本的本地 Embedding 模型，不需要数据库")
    prepare.add_argument("--endpoint", type=_model_endpoint, help="显式指定下载端点；省略时使用官方端点，不自动切换镜像")

    ingest = commands.add_parser("ingest", help="把本地 UTF-8 文本或 Markdown 切块、向量化并入库")
    ingest.add_argument("--file", required=True, type=Path)
    ingest.add_argument("--title", required=True)
    ingest.add_argument("--source-key", required=True)
    ingest.add_argument("--symbol")
    ingest.add_argument("--kind", choices=["announcement", "research", "note"], default="note")
    ingest.add_argument("--source-name", default="用户导入")
    ingest.add_argument("--source-url", help="只保存来源元数据，不访问这个地址")
    ingest.add_argument("--available-at", required=True, type=_aware_datetime)
    ingest.add_argument("--scope-id", default="local")

    commands.add_parser("knowledge-demo", help="将明确标记为合成的学习资料向量化并入库")
    search = commands.add_parser("search", help="按问题语义检索原文片段与来源")
    search.add_argument("query")
    search.add_argument("--symbol")
    search.add_argument("--scope-id", default="local")
    search.add_argument("--kind", choices=["announcement", "research", "note"])
    search.add_argument("--mode", choices=["fixture", "imported"])
    search.add_argument("--as-of", type=_aware_datetime)
    search.add_argument("--top-k", type=int, default=5, choices=range(1, 21), metavar="1..20")
    search.add_argument("--min-score", type=float)
    evaluate = commands.add_parser("evaluate-retrieval", help="运行真实模型检索评测并将报告存入数据库")
    evaluate.add_argument("--top-k", type=int, default=5, choices=range(1, 21), metavar="1..20")
    evaluate.add_argument("--min-score", type=float)

    args = parser.parse_args()
    if args.command == "serve" and args.port is not None and not 1 <= args.port <= 65535:
        parser.error("--port 必须是 1～65535")
    try:
        if args.command == "prepare-model":
            # The Hub reads HF_ENDPOINT when first imported by download_model.
            if args.endpoint is not None:
                os.environ["HF_ENDPOINT"] = args.endpoint
            from .embedding import download_model

            output = download_model(KnowledgeSettings.from_env().model_path)
            print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
            return 0

        settings = Settings.from_env()
        db = Database(settings.database_url)
        if args.command == "init-db":
            db.initialize()
            output = {"message": "数据库初始化完成", **db.health()}
        elif args.command == "health":
            output = db.health()
        elif args.command == "analyze":
            output = ResearchService(db).analyze(
                args.symbol, mode=args.mode, limit=args.limit, end_date=args.end_date,
            )
        elif args.command == "serve":
            db.health()
            port = args.port if args.port is not None else settings.port
            uvicorn.run("trader_v2.app:create_app", factory=True, host="127.0.0.1", port=port)
            return 0
        else:
            from .knowledge_service import KnowledgeService

            knowledge = KnowledgeService(db)
            if args.command == "ingest":
                output = knowledge.ingest({
                    "scope_id": args.scope_id,
                    "source_key": args.source_key,
                    "title": args.title,
                    "body": args.file.read_text(encoding="utf-8-sig"),
                    "symbol": args.symbol,
                    "kind": args.kind,
                    "mode": "imported",
                    "source_name": args.source_name,
                    "source_url": args.source_url,
                    "available_at": args.available_at,
                })
            elif args.command == "knowledge-demo":
                documents = knowledge.seed_demo()
                output = {
                    "mode": "fixture",
                    "document_count": len(documents),
                    "chunk_count": sum(item["chunk_count"] for item in documents),
                    "reused_count": sum(bool(item.get("reused")) for item in documents),
                    "documents": [
                        {key: item[key] for key in ("id", "source_key", "title", "version", "chunk_count", "reused")}
                        for item in documents
                    ],
                }
            elif args.command == "search":
                output = knowledge.search(
                    args.query, scope_id=args.scope_id, symbol=args.symbol,
                    kind=args.kind, mode=args.mode, as_of=args.as_of,
                    top_k=args.top_k, min_score=args.min_score,
                )
            else:
                from .knowledge_eval import evaluate_retrieval

                output = evaluate_retrieval(knowledge, top_k=args.top_k, min_score=args.min_score)
        # JSON is stdout/API serialization only; business records stay in PostgreSQL.
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        if args.command == "evaluate-retrieval" and output["passed"] != output["total"]:
            return 1
        return 0
    except psycopg.Error:
        print("数据库不可用，请先启动数据库并运行 trader-v2 init-db。", file=sys.stderr)
    except (MarketDataError, ValueError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
