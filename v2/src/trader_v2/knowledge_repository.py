"""Knowledge documents and exact pgvector search in the existing PostgreSQL DB.

The embeddings used by repository tests are deterministic fixtures, not a
substitute for the separate real-model retrieval evaluation.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg.errors import UniqueViolation

from .database import Database
from .models import validate_symbol


VECTOR_DIMENSION = 512
_DOCUMENT_COLUMNS = """
    d.id::text AS id, d.scope_id, d.source_key, d.version, d.content_hash,
    d.title, d.body, d.symbol, d.kind, d.mode, d.source_name, d.source_url,
    d.available_at, d.ingested_at, d.deleted_at
"""
_CHUNK_COLUMNS = """
    c.id::text AS chunk_id, c.document_id::text AS document_id,
    c.chunk_no, c.start_char, c.end_char, c.text, c.token_count,
    c.embedding_model, c.embedding_revision, c.chunking_version,
    d.scope_id, d.source_key, d.title, d.symbol, d.kind, d.mode,
    d.source_name, d.source_url, d.available_at, d.ingested_at, d.version
"""


class KnowledgeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def find_existing(
        self, scope_id: str, source_key: str, content_hash: str, *,
        model_id: str, model_revision: str, chunking_version: str,
    ) -> dict[str, Any] | None:
        """Find content already indexed with the requested embedding profile."""
        with self.database._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {_DOCUMENT_COLUMNS}, count(c.id)::integer AS chunk_count
                FROM documents d JOIN document_chunks c ON c.document_id = d.id
                WHERE d.scope_id = %s AND d.source_key = %s AND d.content_hash = %s
                    AND d.deleted_at IS NULL AND c.embedding_model = %s
                    AND c.embedding_revision = %s AND c.chunking_version = %s
                GROUP BY d.id
                """,
                (scope_id, source_key, content_hash, model_id, model_revision, chunking_version),
            ).fetchone()
        if row is not None:
            row["reused"] = True
        return row

    def save_document(
        self, metadata: dict[str, Any], chunks: list[dict[str, Any]], *,
        model_id: str, model_revision: str, chunking_version: str,
    ) -> dict[str, Any]:
        """Save one source version and its chunks, without business JSON files.

        A content/version uniqueness collision caused by concurrent imports is
        retried against the committed row rather than generating another copy.
        """
        if not chunks:
            raise ValueError("资料没有可保存的切块")
        prepared = [
            (
                chunk["chunk_no"], chunk["start_char"], chunk["end_char"], chunk["text"],
                chunk["token_count"], _vector_literal(chunk["embedding"]),
            )
            for chunk in chunks
        ]
        for attempt in range(3):
            try:
                return self._save_document_once(
                    metadata, prepared, model_id=model_id,
                    model_revision=model_revision, chunking_version=chunking_version,
                )
            except UniqueViolation as exc:
                if attempt == 2 or exc.diag.constraint_name not in {
                    "documents_source_version", "documents_source_hash",
                }:
                    raise
        raise AssertionError("document import retry loop did not finish")

    def _save_document_once(
        self, metadata: dict[str, Any], chunks: list[tuple], *,
        model_id: str, model_revision: str, chunking_version: str,
    ) -> dict[str, Any]:
        scope_id = metadata.get("scope_id", "local")
        with self.database._connect() as conn:
            existing = conn.execute(
                """SELECT id, deleted_at FROM documents
                   WHERE scope_id = %s AND source_key = %s AND content_hash = %s""",
                (scope_id, metadata["source_key"], metadata["content_hash"]),
            ).fetchone()
            created, restored = existing is None, False
            if existing is None:
                document_id = uuid4()
                conn.execute(
                    """
                    INSERT INTO documents (
                        id, scope_id, source_key, version, content_hash,
                        title, body, symbol, kind, mode, source_name, source_url, available_at
                    ) VALUES (
                        %s, %s, %s,
                        (SELECT coalesce(max(version), 0) + 1 FROM documents
                         WHERE scope_id = %s AND source_key = %s),
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        document_id, scope_id, metadata["source_key"], scope_id, metadata["source_key"],
                        metadata["content_hash"], metadata["title"], metadata["body"],
                        metadata.get("symbol"), metadata["kind"], metadata["mode"],
                        metadata["source_name"], metadata.get("source_url"), metadata["available_at"],
                    ),
                )
            else:
                document_id = existing["id"]
                if existing["deleted_at"] is not None:
                    # An explicit reimport can restore this exact version only.
                    conn.execute("UPDATE documents SET deleted_at = NULL WHERE id = %s", (document_id,))
                    restored = True
            inserted = 0
            for number, start, end, text, tokens, embedding in chunks:
                result = conn.execute(
                    """
                    INSERT INTO document_chunks (
                        id, document_id, chunk_no, start_char, end_char, text,
                        token_count, embedding, embedding_model, embedding_revision, chunking_version
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
                    ON CONFLICT (document_id, embedding_model, embedding_revision, chunking_version, chunk_no)
                    DO NOTHING
                    """,
                    (
                        uuid4(), document_id, number, start, end, text, tokens,
                        embedding, model_id, model_revision, chunking_version,
                    ),
                )
                inserted += result.rowcount
            saved = conn.execute(
                f"""
                SELECT {_DOCUMENT_COLUMNS}, count(c.id)::integer AS chunk_count
                FROM documents d JOIN document_chunks c ON c.document_id = d.id
                WHERE d.id = %s AND c.embedding_model = %s AND c.embedding_revision = %s
                    AND c.chunking_version = %s
                GROUP BY d.id
                """,
                (document_id, model_id, model_revision, chunking_version),
            ).fetchone()
            assert saved is not None
            saved["reused"] = not created and not restored and inserted == 0
        return saved

    def get_document(self, document_id: str, scope_id: str = "local") -> dict[str, Any] | None:
        with self.database._connect() as conn:
            return conn.execute(
                f"""
                SELECT {_DOCUMENT_COLUMNS},
                    (SELECT count(*)::integer FROM document_chunks c WHERE c.document_id = d.id) AS chunk_count
                FROM documents d
                WHERE d.id = %s AND d.scope_id = %s AND d.deleted_at IS NULL
                """,
                (UUID(document_id), scope_id),
            ).fetchone()

    def list_documents(
        self, scope_id: str = "local", symbol: str | None = None,
        mode: str | None = None, limit: int = 20,
    ) -> list[dict[str, Any]]:
        _validate_limit(limit, maximum=100)
        conditions, params = [], [scope_id]
        if symbol is not None:
            conditions.append("d.symbol = %s")
            params.append(validate_symbol(symbol))
        if mode is not None:
            if mode not in {"fixture", "imported"}:
                raise ValueError("资料 mode 必须是 fixture 或 imported")
            conditions.append("d.mode = %s")
            params.append(mode)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        with self.database._connect() as conn:
            return conn.execute(
                f"""
                WITH latest AS (
                    SELECT DISTINCT ON (source_key) * FROM documents
                    WHERE scope_id = %s AND deleted_at IS NULL
                    ORDER BY source_key, available_at DESC, version DESC
                )
                SELECT {_DOCUMENT_COLUMNS},
                    (SELECT count(*)::integer FROM document_chunks c WHERE c.document_id = d.id) AS chunk_count
                FROM latest d {where}
                ORDER BY d.ingested_at DESC, d.id DESC LIMIT %s
                """,
                params,
            ).fetchall()

    def read_chunk(self, chunk_id: str, scope_id: str = "local") -> dict[str, Any] | None:
        with self.database._connect() as conn:
            return conn.execute(
                f"""
                SELECT {_CHUNK_COLUMNS}
                FROM document_chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.id = %s AND d.scope_id = %s AND d.deleted_at IS NULL
                """,
                (UUID(chunk_id), scope_id),
            ).fetchone()

    def delete_source(self, document_id: str, scope_id: str = "local") -> bool:
        """Hide the selected source and all its versions from normal retrieval."""
        with self.database._connect() as conn:
            selected = conn.execute(
                "SELECT source_key FROM documents WHERE id = %s AND scope_id = %s",
                (UUID(document_id), scope_id),
            ).fetchone()
            if selected is None:
                return False
            changed = conn.execute(
                """UPDATE documents SET deleted_at = now()
                   WHERE scope_id = %s AND source_key = %s AND deleted_at IS NULL""",
                (scope_id, selected["source_key"]),
            )
            return changed.rowcount > 0

    def search(
        self, query_vector: list[float], *, scope_id: str = "local",
        symbol: str | None = None, kind: str | None = None, mode: str | None = None,
        as_of: datetime, top_k: int = 5, min_score: float = 0.55,
        model_id: str, model_revision: str, chunking_version: str,
    ) -> list[dict[str, Any]]:
        _validate_limit(top_k, maximum=50)
        if not isinstance(as_of, datetime) or as_of.utcoffset() is None:
            raise ValueError("as_of 必须是带时区的日期时间")
        if isinstance(min_score, bool) or not math.isfinite(min_score) or not -1 <= min_score <= 1:
            raise ValueError("min_score 必须是 -1～1 的有限数字")
        vector = _vector_literal(query_vector)
        filters = ["c.embedding_model = %s", "c.embedding_revision = %s", "c.chunking_version = %s"]
        params: list[Any] = [scope_id, as_of, vector, model_id, model_revision, chunking_version]
        if symbol is not None:
            filters.append("d.symbol = %s")
            params.append(validate_symbol(symbol))
        if kind is not None:
            if kind not in {"announcement", "research", "note"}:
                raise ValueError("不支持的资料类型")
            filters.append("d.kind = %s")
            params.append(kind)
        if mode is not None:
            if mode not in {"fixture", "imported"}:
                raise ValueError("资料 mode 必须是 fixture 或 imported")
            filters.append("d.mode = %s")
            params.append(mode)
        params.extend([min_score, top_k])
        with self.database._connect() as conn:
            return conn.execute(
                f"""
                WITH visible AS (
                    SELECT DISTINCT ON (source_key) * FROM documents
                    WHERE scope_id = %s AND available_at <= %s AND deleted_at IS NULL
                    ORDER BY source_key, available_at DESC, version DESC
                ), scored AS (
                    SELECT {_CHUNK_COLUMNS},
                        least(1.0, greatest(-1.0, 1 - (c.embedding <=> %s::vector))) AS score
                    FROM document_chunks c JOIN visible d ON d.id = c.document_id
                    WHERE {" AND ".join(filters)}
                )
                SELECT * FROM scored WHERE score >= %s
                ORDER BY score DESC, chunk_id LIMIT %s
                """,
                params,
            ).fetchall()


def _vector_literal(values: list[float]) -> str:
    if len(values) != VECTOR_DIMENSION:
        raise ValueError(f"向量必须是 {VECTOR_DIMENSION} 维")
    if any(isinstance(value, bool) for value in values):
        raise ValueError("向量不能包含布尔值")
    numeric = [float(value) for value in values]
    if any(not math.isfinite(value) for value in numeric) or not any(numeric):
        raise ValueError("向量必须是有限且非零的数字")
    return json.dumps(numeric, allow_nan=False, separators=(",", ":"))


def _validate_limit(value: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"查询数量必须是 1～{maximum} 的整数")
