"""Session-bound research receipts and reports, stored in PostgreSQL.

Citation checks prove provenance and visibility, not whether a model's sentence
is entailed by its source. Imported sources remain unverified input.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from .database import Database
from .knowledge_service import KnowledgeService, validate_scope
from .models import validate_symbol


class ResearchNotFoundError(LookupError):
    """A research object is absent from the caller's scope."""


class ResearchConflictError(RuntimeError):
    """The session or evidence can no longer be used as requested."""


def _text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{name} 需为1～{maximum}个字符的非空文本")
    return value.strip()


def _strings(values: Any, name: str) -> list[str]:
    if not isinstance(values, list) or len(values) > 20:
        raise ValueError(f"{name} 最多20条")
    return [_text(value, name, 2000) for value in values]


class ResearchWorkflow:
    MAX_SEARCHES = 12

    def __init__(self, database: Database, knowledge_service: KnowledgeService) -> None:
        self.database = database
        self.knowledge = knowledge_service

    def begin(
        self, *, symbol: str, question: str, mode: str, scope_id: str = "local",
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        validate_scope(scope_id)
        validate_symbol(symbol)
        question = _text(question, "question", 2000)
        if mode not in {"fixture", "imported"}:
            raise ValueError("mode 仅支持 fixture 或 imported")
        cutoff = as_of or datetime.now(timezone.utc)
        if not isinstance(cutoff, datetime) or cutoff.utcoffset() is None:
            raise ValueError("as_of 必须包含时区")
        if cutoff > datetime.now(timezone.utc):
            raise ValueError("研究截止时间不能晚于当前时间")
        with self.database._connect() as conn:
            row = conn.execute(
                """INSERT INTO research_sessions(id, scope_id, symbol, question, mode, as_of)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
                (uuid4(), scope_id, symbol, question, mode, cutoff),
            ).fetchone()
        return _ids(row)

    def _session(self, conn, session_id: str, scope_id: str, *, open_only=False) -> dict:
        validate_scope(scope_id)
        row = conn.execute(
            "SELECT * FROM research_sessions WHERE id = %s AND scope_id = %s FOR UPDATE",
            (UUID(session_id), scope_id),
        ).fetchone()
        if row is None:
            raise ResearchNotFoundError("未找到本范围内的研究会话")
        if open_only and row["status"] != "open":
            raise ResearchConflictError("研究会话已完成，请新建会话继续研究")
        return row

    def get_session(self, session_id: str, scope_id: str = "local") -> dict:
        with self.database._connect() as conn:
            session = self._session(conn, session_id, scope_id)
            searches = conn.execute(
                "SELECT * FROM research_searches WHERE session_id = %s ORDER BY created_at, id",
                (session["id"],),
            ).fetchall()
            evidence = conn.execute(
                """SELECT id AS evidence_id, search_id, chunk_id, score, read_at
                   FROM research_evidence WHERE session_id = %s ORDER BY id""", (session["id"],),
            ).fetchall()
            report = conn.execute("SELECT id FROM research_reports WHERE session_id = %s", (session["id"],)).fetchone()
        return {**_ids(session), "searches": [_ids(row) for row in searches],
                "evidence": [_ids(row) for row in evidence], "report_id": str(report["id"]) if report else None,
                "search_budget": self.MAX_SEARCHES}

    def search(
        self, session_id: str, *, query: str, scope_id: str = "local",
        top_k: int = 5, min_score: float | None = None,
    ) -> dict:
        # Keep the session row locked so concurrent calls share the same budget.
        with self.database._connect() as conn:
            session = self._session(conn, session_id, scope_id, open_only=True)
            count = conn.execute("SELECT count(*) AS n FROM research_searches WHERE session_id = %s", (session["id"],)).fetchone()["n"]
            if count >= self.MAX_SEARCHES:
                raise ResearchConflictError("本次研究已达到12次检索上限，请整理已有证据或记录缺口")
            result = self.knowledge.search(
                query, scope_id=scope_id, symbol=session["symbol"], mode=session["mode"],
                as_of=session["as_of"], top_k=top_k, min_score=min_score,
            )
            search_id = uuid4()
            conn.execute(
                """INSERT INTO research_searches(id, session_id, query, top_k, min_score,
                   model_id, model_revision, chunking_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (search_id, session["id"], query, top_k, result["min_score"], result["model_id"],
                 result["model_revision"], result["chunking_version"]),
            )
            hits = []
            for hit in result["results"]:
                current = self._visible_chunk(conn, UUID(hit["chunk_id"]), session)
                if current is None:
                    continue
                evidence_id = uuid4()
                conn.execute(
                    """INSERT INTO research_evidence(id, session_id, search_id, chunk_id, score)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (evidence_id, session["id"], search_id, UUID(hit["chunk_id"]), hit["score"]),
                )
                hits.append({**hit, "evidence_id": str(evidence_id), "read_at": None})
        return {**result, "results": hits, "session_id": str(session["id"]), "search_id": str(search_id),
                "searches_remaining": self.MAX_SEARCHES - count - 1,
                "next_step": "通过 evidence_id 读取原文后，才能将它用于报告的事实引用。"}

    def _visible_chunk(self, conn, chunk_id: UUID, session: dict) -> dict | None:
        return conn.execute(
            """WITH latest AS (
                SELECT DISTINCT ON (source_key) * FROM documents
                WHERE scope_id = %s AND available_at <= %s AND deleted_at IS NULL
                ORDER BY source_key, available_at DESC, version DESC
            )
            SELECT c.id::text AS chunk_id, c.document_id::text AS document_id,
                c.text, c.start_char, c.end_char, c.chunk_no, d.scope_id, d.symbol,
                d.source_key, d.version, d.title, d.mode, d.kind, d.source_name,
                d.source_url, d.available_at
            FROM document_chunks c JOIN latest d ON d.id = c.document_id
            WHERE c.id = %s AND d.symbol = %s AND d.mode = %s""",
            (session["scope_id"], session["as_of"], chunk_id, session["symbol"], session["mode"]),
        ).fetchone()

    def read_evidence(self, session_id: str, evidence_id: str, scope_id: str = "local") -> dict:
        with self.database._connect() as conn:
            session = self._session(conn, session_id, scope_id, open_only=True)
            receipt = conn.execute(
                "SELECT * FROM research_evidence WHERE id = %s AND session_id = %s",
                (UUID(evidence_id), session["id"]),
            ).fetchone()
            if receipt is None:
                raise ResearchNotFoundError("该证据不属于本次研究检索")
            chunk = self._visible_chunk(conn, receipt["chunk_id"], session)
            if chunk is None:
                raise ResearchConflictError("来源已删除或在研究截止时间内被新版替代，请重新检索")
            row = conn.execute("UPDATE research_evidence SET read_at = now() WHERE id = %s RETURNING read_at", (receipt["id"],)).fetchone()
        return {**chunk, "evidence_id": str(receipt["id"]), "session_id": str(session["id"]),
                "read_at": row["read_at"], "source_warning": "合成样例" if session["mode"] == "fixture" else "用户导入资料，来源真实性尚未核实"}

    def save_report(
        self, session_id: str, *, title: str, summary: str, facts: list[dict],
        inferences: list[str], missing_information: list[str], scope_id: str = "local",
    ) -> dict:
        title, summary = _text(title, "title", 200), _text(summary, "summary", 4000)
        inferences = _strings(inferences, "inferences")
        missing_information = _strings(missing_information, "missing_information")
        if not isinstance(facts, list) or len(facts) > 20:
            raise ValueError("facts 最多20条")
        prepared = []
        evidence_ids = set()
        for fact in facts:
            if not isinstance(fact, dict) or set(fact) != {"text", "evidence_ids"}:
                raise ValueError("每条事实只能含 text 与 evidence_ids")
            refs = fact["evidence_ids"]
            if not isinstance(refs, list) or not 1 <= len(refs) <= 10:
                raise ValueError("每条事实必须引用1～10个证据ID")
            refs = list(dict.fromkeys(str(UUID(value)) for value in refs))
            prepared.append({"text": _text(fact["text"], "fact.text", 2000), "evidence_ids": refs})
            evidence_ids.update(refs)
        if not prepared and not missing_information:
            raise ValueError("没有事实证据时必须明确记录缺失信息")
        report_id = uuid4()
        with self.database._connect() as conn:
            session = self._session(conn, session_id, scope_id, open_only=True)
            sources = []
            for evidence_id in sorted(evidence_ids):
                receipt = conn.execute(
                    "SELECT * FROM research_evidence WHERE id = %s AND session_id = %s",
                    (UUID(evidence_id), session["id"]),
                ).fetchone()
                if receipt is None or receipt["read_at"] is None:
                    raise ValueError("引用必须是本次研究实际检索且已读取的证据ID")
                source = self._visible_chunk(conn, receipt["chunk_id"], session)
                if source is None:
                    raise ResearchConflictError("引用来源已删除或被新版替代，请补查后再保存")
                sources.append((evidence_id, source))
            conn.execute(
                """INSERT INTO research_reports(id, session_id, scope_id, symbol, mode, as_of,
                   title, summary, facts, inferences, missing_information)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (report_id, session["id"], scope_id, session["symbol"], session["mode"], session["as_of"],
                 title, summary, Jsonb(prepared), inferences, missing_information),
            )
            for evidence_id, source in sources:
                conn.execute(
                    """INSERT INTO research_citations(report_id, evidence_id, chunk_id, document_id,
                       source_key, source_version, title, source_name, source_url, available_at,
                       start_char, end_char, text) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (report_id, UUID(evidence_id), UUID(source["chunk_id"]), UUID(source["document_id"]),
                     source["source_key"], source["version"], source["title"], source["source_name"],
                     source["source_url"], source["available_at"], source["start_char"], source["end_char"], source["text"]),
                )
            conn.execute("UPDATE research_sessions SET status = 'completed' WHERE id = %s", (session["id"],))
        return self.get_report(str(report_id), scope_id)

    def get_report(self, report_id: str, scope_id: str = "local") -> dict:
        validate_scope(scope_id)
        with self.database._connect() as conn:
            report = conn.execute("SELECT * FROM research_reports WHERE id = %s AND scope_id = %s", (UUID(report_id), scope_id)).fetchone()
            if report is None:
                raise ResearchNotFoundError("未找到本范围内的研究报告")
            citations = conn.execute("SELECT * FROM research_citations WHERE report_id = %s ORDER BY evidence_id", (report["id"],)).fetchall()
            for citation in citations:
                citation["currently_visible"] = self._visible_chunk(conn, citation["chunk_id"], report) is not None
        return {**_ids(report), "citations": [_ids(row) for row in citations],
                "provenance_note": "引用检查证明本次研究读取过该来源；不证明结论正确或来源真实。",
                "source_warning": "合成学习样例" if report["mode"] == "fixture" else "用户导入资料，来源真实性尚未核实"}

    def list_reports(self, *, scope_id: str = "local", symbol: str | None = None, limit: int = 20) -> list[dict]:
        validate_scope(scope_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit 必须是1～100的整数")
        if symbol is not None:
            validate_symbol(symbol)
        with self.database._connect() as conn:
            rows = conn.execute(
                """SELECT id, session_id, scope_id, symbol, mode, as_of, title, summary, created_at
                   FROM research_reports WHERE scope_id = %s AND (%s::text IS NULL OR symbol = %s)
                   ORDER BY created_at DESC, id LIMIT %s""", (scope_id, symbol, symbol, limit),
            ).fetchall()
        return [_ids(row) for row in rows]


def _ids(row: dict) -> dict:
    return {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}
