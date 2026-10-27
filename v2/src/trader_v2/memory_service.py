"""Explicit, revisable long-term memory stored in PostgreSQL and pgvector.

These are user assertions and provisional sourced lessons. They never stand in
for account balances, holdings, market facts, or verified strategy performance.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from .database import Database
from .embedding import MODEL_ID, MODEL_REVISION
from .knowledge_repository import _vector_literal
from .knowledge_service import KnowledgeService, validate_scope
from .models import validate_symbol


KINDS = {"preference", "pending", "lesson"}
DEFAULT_TTL_DAYS = {"preference": 365, "pending": 30, "lesson": 90}
_FIELDS = """id::text AS id, scope_id, revision, kind, symbol, content,
    source_type, source_reference, source_mode, epistemic_status, status, created_at,
    updated_at, expires_at, embedding_model, embedding_revision"""
_SNAPSHOT_FIELDS = """id, revision, scope_id, kind, symbol, content,
    source_type, source_reference, source_mode, epistemic_status, status, created_at,
    updated_at, expires_at, embedding, embedding_model, embedding_revision"""


class MemoryConflictError(ValueError):
    """The caller attempted to replace a revision it has not read."""


def _text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{name} 需为1～{maximum}个字符的非空文本")
    return value


def _limit(value: int, maximum: int = 100) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"查询数量必须为1～{maximum}")
    return value


def _id(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("记忆编号必须是 UUID") from exc


def _filter(scope_id: str, symbol: str | None, kind: str | None,
            mode: str | None = None) -> tuple[list[str], list[Any]]:
    clauses, params = ["scope_id = %s"], [validate_scope(scope_id)]
    if symbol is not None:
        # General user preferences also apply when a stock is selected, while
        # a memory about another company must never leak into the result.
        clauses.append("(symbol = %s OR symbol IS NULL)")
        params.append(validate_symbol(symbol))
    if kind is not None:
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError("记忆类型仅支持 preference、pending、lesson")
        clauses.append("kind = %s")
        params.append(kind)
    if mode is not None:
        if mode not in {"fixture", "imported"}:
            raise ValueError("记忆来源模式仅支持 fixture 或 imported")
        clauses.append("(source_type = 'user_statement' OR source_mode = %s)")
        params.append(mode)
    return clauses, params


class MemoryService:
    def __init__(self, database: Database, knowledge_service: KnowledgeService) -> None:
        self.database = database
        self.embedder = knowledge_service.embedder
        self.min_score = knowledge_service.settings.min_score

    def _validated(self, data: dict[str, Any], now: datetime) -> dict[str, Any]:
        result = dict(data)
        result["scope_id"] = validate_scope(data.get("scope_id", "local"))
        kind = result.get("kind")
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError("记忆类型仅支持 preference、pending、lesson")
        result["symbol"] = validate_symbol(data["symbol"]) if data.get("symbol") is not None else None
        result["content"] = _text(data.get("content"), "content", 1200)
        result["source_reference"] = _text(data.get("source_reference"), "source_reference", 200)
        expected_source = "research_report" if kind == "lesson" else "user_statement"
        if data.get("source_type") != expected_source:
            raise ValueError("偏好和待办需引用用户明确陈述；经验需引用已保存研究报告")
        result["source_type"] = expected_source
        # Provenance mode is derived from the stored report, never from a
        # caller/model claim. Explicit user preferences are mode-independent.
        result["source_mode"] = None
        result["epistemic_status"] = "provisional_lesson" if kind == "lesson" else "user_asserted"
        if kind == "lesson":
            result["source_reference"] = _id(result["source_reference"])
        expires = data.get("expires_at") or now + timedelta(days=DEFAULT_TTL_DAYS[kind])
        if not isinstance(expires, datetime) or expires.utcoffset() is None:
            raise ValueError("expires_at 必须包含时区")
        expires = expires.astimezone(timezone.utc)
        if not now < expires <= now + timedelta(days=3660):
            raise ValueError("记忆失效时间必须晚于现在且不超过10年")
        result["expires_at"] = expires
        return result

    def _encode_memory(self, content: str) -> str:
        encoded = self.embedder.tokenizer(content, add_special_tokens=True, truncation=False)
        if len(encoded["input_ids"]) > 400:
            raise ValueError("记忆正文最多400个token，请拆成独立且完整的短记忆")
        return _vector_literal(self.embedder.encode_documents([content])[0])

    @staticmethod
    def _validate_report(conn: Any, data: dict[str, Any]) -> None:
        if data["kind"] != "lesson":
            return
        report = conn.execute(
            "SELECT id, symbol, mode FROM research_reports WHERE id = %s AND scope_id = %s",
            (data["source_reference"], data["scope_id"]),
        ).fetchone()
        if report is None:
            raise ValueError("经验来源报告不存在或不属于当前 scope")
        if report["symbol"] != data["symbol"]:
            raise ValueError("经验股票必须与来源报告一致")
        data["source_mode"] = report["mode"]

    @staticmethod
    def _snapshot(conn: Any, memory_id: str) -> None:
        conn.execute(
            f"""INSERT INTO agent_memory_versions (
                memory_id, revision, scope_id, kind, symbol, content,
                source_type, source_reference, source_mode, epistemic_status, status, created_at,
                updated_at, expires_at, embedding, embedding_model, embedding_revision
            ) SELECT {_SNAPSHOT_FIELDS} FROM agent_memory WHERE id = %s""", (memory_id,),
        )

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        value = self._validated(data, now)
        # Encoding rejects texts above the pinned model token limit; no hidden
        # truncation or fragmented memory that changes the intended assertion.
        embedding = self._encode_memory(value["content"])
        memory_id = str(uuid4())
        with self.database._connect() as conn:
            self._validate_report(conn, value)
            row = conn.execute(
                f"""INSERT INTO agent_memory (
                    id, scope_id, revision, kind, symbol, content, source_type,
                    source_reference, source_mode, epistemic_status, status, created_at,
                    updated_at, expires_at, embedding, embedding_model, embedding_revision
                ) VALUES (%s,%s,1,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,%s::vector,%s,%s)
                RETURNING {_FIELDS}""",
                (memory_id, value["scope_id"], value["kind"], value["symbol"], value["content"],
                 value["source_type"], value["source_reference"], value["source_mode"], value["epistemic_status"],
                 now, now, value["expires_at"], embedding, MODEL_ID, MODEL_REVISION),
            ).fetchone()
            self._snapshot(conn, memory_id)
        return dict(row)

    def update(self, memory_id: str, data: dict[str, Any], *, expected_revision: int,
               scope_id: str = "local") -> dict[str, Any] | None:
        memory_id = _id(memory_id)
        _limit(expected_revision, maximum=2_147_483_646)
        scope_id = validate_scope(scope_id)
        now = datetime.now(timezone.utc)
        value = self._validated({**data, "scope_id": scope_id}, now)
        with self.database._connect() as conn:
            old = conn.execute(
                "SELECT revision, status FROM agent_memory WHERE id = %s AND scope_id = %s FOR UPDATE",
                (memory_id, scope_id),
            ).fetchone()
            if old is None:
                return None
            if old["revision"] != expected_revision:
                raise MemoryConflictError("记忆已被修改，请重新读取后提交当前 revision")
            if old["status"] != "active":
                raise MemoryConflictError("记忆已经停用，请新建记忆而非恢复旧记忆")
            self._validate_report(conn, value)
            embedding = self._encode_memory(value["content"])
            row = conn.execute(
                f"""UPDATE agent_memory SET revision = revision + 1, kind = %s,
                    symbol = %s, content = %s, source_type = %s, source_reference = %s, source_mode = %s,
                    epistemic_status = %s, updated_at = %s, expires_at = %s,
                    embedding = %s::vector, embedding_model = %s, embedding_revision = %s
                    WHERE id = %s AND scope_id = %s RETURNING {_FIELDS}""",
                (value["kind"], value["symbol"], value["content"], value["source_type"],
                 value["source_reference"], value["source_mode"], value["epistemic_status"], now, value["expires_at"],
                 embedding, MODEL_ID, MODEL_REVISION, memory_id, scope_id),
            ).fetchone()
            self._snapshot(conn, memory_id)
        return dict(row)

    def get(self, memory_id: str, scope_id: str = "local") -> dict[str, Any] | None:
        with self.database._connect() as conn:
            return conn.execute(
                f"SELECT {_FIELDS}, expires_at <= now() AS expired FROM agent_memory WHERE id = %s AND scope_id = %s",
                (_id(memory_id), validate_scope(scope_id)),
            ).fetchone()

    def list(self, *, scope_id: str = "local", symbol: str | None = None,
             kind: str | None = None, mode: str | None = None,
             include_inactive: bool = False, limit: int = 20) -> list[dict[str, Any]]:
        clauses, params = _filter(scope_id, symbol, kind, mode)
        if not isinstance(include_inactive, bool):
            raise ValueError("include_inactive 必须为布尔值")
        if not include_inactive:
            clauses.extend(["status = 'active'", "expires_at > now()"])
        params.append(_limit(limit))
        with self.database._connect() as conn:
            return conn.execute(
                f"""SELECT {_FIELDS}, expires_at <= now() AS expired FROM agent_memory
                    WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC, id LIMIT %s""", params,
            ).fetchall()

    def recall(self, query: str, *, scope_id: str = "local", symbol: str | None = None,
               kind: str | None = None, mode: str | None = None,
               top_k: int = 5, min_score: float | None = None) -> dict[str, Any]:
        _text(query, "query", 2000)
        clauses, params = _filter(scope_id, symbol, kind, mode)
        score = self.min_score if min_score is None else min_score
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("min_score 必须为0～1的有限数字")
        _limit(top_k, 20)
        vector = _vector_literal(self.embedder.encode_query(query))
        clauses.extend(["status = 'active'", "expires_at > now()", "embedding_model = %s", "embedding_revision = %s"])
        params.extend([MODEL_ID, MODEL_REVISION])
        with self.database._connect() as conn:
            rows = conn.execute(
                f"""WITH eligible AS MATERIALIZED (
                    SELECT * FROM agent_memory WHERE {' AND '.join(clauses)}
                ), ranked AS (
                    SELECT {_FIELDS}, least(1.0, greatest(-1.0, 1 - (embedding <=> %s::vector))) AS score
                    FROM eligible
                ) SELECT * FROM ranked WHERE score >= %s ORDER BY score DESC, id LIMIT %s""",
                [*params, vector, score, top_k],
            ).fetchall()
        return {"query": query, "scope_id": scope_id, "symbol": symbol, "kind": kind, "mode": mode,
                "top_k": top_k, "min_score": score, "results": rows,
                "notice": "记忆是用户陈述或待验证经验，不能替代行情、账户数据或收益验证。"}

    def deactivate(self, memory_id: str, scope_id: str = "local") -> bool:
        with self.database._connect() as conn:
            row = conn.execute(
                """UPDATE agent_memory SET status = 'deactivated', revision = revision + 1,
                    updated_at = now() WHERE id = %s AND scope_id = %s AND status = 'active'
                    RETURNING id::text AS id""", (_id(memory_id), validate_scope(scope_id)),
            ).fetchone()
            if row is None:
                return False
            self._snapshot(conn, row["id"])
            return True

    def history(self, memory_id: str, scope_id: str = "local") -> list[dict[str, Any]]:
        with self.database._connect() as conn:
            return conn.execute(
                """SELECT memory_id::text AS id, revision, scope_id, kind, symbol, content,
                    source_type, source_reference, source_mode, epistemic_status, status, created_at,
                    updated_at, expires_at, embedding_model, embedding_revision
                    FROM agent_memory_versions WHERE memory_id = %s AND scope_id = %s
                    ORDER BY revision DESC""", (_id(memory_id), validate_scope(scope_id)),
            ).fetchall()
