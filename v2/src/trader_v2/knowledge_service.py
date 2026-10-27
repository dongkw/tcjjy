"""Turn source text into local embeddings, then retrieve cited source chunks."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from .chunking import CHUNKING_VERSION, chunk_text
from .database import Database
from .embedding import MODEL_ID, MODEL_REVISION, LocalBgeEmbedder
from .knowledge_repository import KnowledgeRepository
from .models import validate_symbol
from .settings import KnowledgeSettings


def validate_scope(scope_id: str) -> str:
    if not isinstance(scope_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", scope_id):
        raise ValueError("scope_id 必须是1～80位字母、数字或 _ . : -")
    return scope_id


class KnowledgeService:
    def __init__(
        self, database: Database, embedder: LocalBgeEmbedder | None = None,
        settings: KnowledgeSettings | None = None,
    ) -> None:
        self.settings = settings or KnowledgeSettings.from_env()
        self.embedder = embedder or LocalBgeEmbedder(self.settings.model_path, self.settings.threads)
        self.repository = KnowledgeRepository(database)

    def ingest(self, document: dict[str, Any]) -> dict[str, Any]:
        metadata = _validated_document(document)
        profile = {"model_id": MODEL_ID, "model_revision": MODEL_REVISION, "chunking_version": CHUNKING_VERSION}
        previous = self.repository.find_existing(
            metadata["scope_id"], metadata["source_key"], metadata["content_hash"], **profile,
        )
        if previous is not None:
            return previous
        pieces = chunk_text(metadata["body"], self.embedder.tokenizer)
        vectors = self.embedder.encode_documents([piece.text for piece in pieces])
        chunks = [{**asdict(piece), "embedding": vector} for piece, vector in zip(pieces, vectors, strict=True)]
        return self.repository.save_document(metadata, chunks, **profile)

    def search(
        self, query: str, *, scope_id: str = "local", symbol: str | None = None,
        kind: str | None = None, mode: str | None = None, as_of: datetime | None = None,
        top_k: int = 5, min_score: float | None = None,
    ) -> dict[str, Any]:
        validate_scope(scope_id)
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000:
            raise ValueError("检索问题需为1～2000个字符")
        if symbol is not None:
            validate_symbol(symbol)
        if kind is not None and kind not in {"announcement", "research", "note"}:
            raise ValueError("不支持的资料类型")
        if mode is not None and mode not in {"fixture", "imported"}:
            raise ValueError("资料模式仅支持 fixture 或 imported")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 20:
            raise ValueError("top_k 必须为1～20")
        cutoff = as_of or datetime.now(timezone.utc)
        if not isinstance(cutoff, datetime) or cutoff.utcoffset() is None:
            raise ValueError("信息截止时间必须包含时区")
        score = self.settings.min_score if min_score is None else min_score
        if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("min_score 必须为0～1的有限数字")
        vector = self.embedder.encode_query(query)
        results = self.repository.search(
            vector, scope_id=scope_id, symbol=symbol, kind=kind, mode=mode, as_of=cutoff,
            top_k=top_k, min_score=score, model_id=MODEL_ID,
            model_revision=MODEL_REVISION, chunking_version=CHUNKING_VERSION,
        )
        return {
            "query": query, "scope_id": scope_id, "symbol": symbol, "kind": kind,
            "mode": mode, "as_of": cutoff, "top_k": top_k, "min_score": score,
            "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
            "chunking_version": CHUNKING_VERSION, "results": results,
        }

    def seed_demo(self) -> list[dict[str, Any]]:
        from .knowledge_fixtures import demo_documents

        return [self.ingest(document) for document in demo_documents()]


def _validated_document(document: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(document)
    metadata["scope_id"] = validate_scope(metadata.get("scope_id", "local"))
    for field, maximum in (("source_key", 500), ("title", 200), ("source_name", 200), ("body", 200000)):
        value = metadata.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
            raise ValueError(f"{field} 需为1～{maximum}个字符的非空文本")
    if metadata.get("symbol") is not None:
        validate_symbol(metadata["symbol"])
    if metadata.get("kind") not in {"announcement", "research", "note"}:
        raise ValueError("kind 仅支持 announcement、research 或 note")
    if metadata.get("mode") not in {"fixture", "imported"}:
        raise ValueError("mode 仅支持 fixture 或 imported")
    available = metadata.get("available_at")
    if not isinstance(available, datetime) or available.utcoffset() is None:
        raise ValueError("available_at 必须包含公开可用时间及时区")
    metadata["available_at"] = available.astimezone(timezone.utc)
    url = metadata.get("source_url")
    if url is not None:
        if not isinstance(url, str) or len(url) > 2048 or "\x00" in url:
            raise ValueError("source_url 格式无效")
        parsed = urlsplit(url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("source_url 仅接受不含凭据的 HTTP/HTTPS 来源地址")
        metadata["source_url"] = parsed.geturl()
    metadata.setdefault("symbol", None)
    metadata.setdefault("source_url", None)
    canonical = {key: metadata[key] for key in (
        "title", "body", "symbol", "kind", "mode", "source_name", "source_url",
    )}
    canonical["available_at"] = metadata["available_at"].isoformat()
    metadata["content_hash"] = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
    ).hexdigest()
    return metadata
