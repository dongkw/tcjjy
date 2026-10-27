"""Measure real retrieval on explicitly synthetic learning passages."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from .chunking import CHUNKING_VERSION
from .embedding import MODEL_ID, MODEL_REVISION
from .knowledge_fixtures import retrieval_cases
from .knowledge_service import KnowledgeService


def evaluate_retrieval(service: KnowledgeService, *, top_k: int = 5, min_score: float | None = None) -> dict[str, Any]:
    rows = []
    for case in retrieval_cases():
        found = service.search(
            case["query"], symbol=case["symbol"], as_of=case["as_of"],
            mode="fixture", top_k=top_k, min_score=min_score,
        )
        sources = [item["source_key"] for item in found["results"]]
        expected = case["expected_source_keys"]
        passed = not sources if case["should_be_empty"] else bool(set(expected) & set(sources))
        rows.append({
            **case, "as_of": case["as_of"].isoformat(), "passed": passed,
            "returned_source_keys": sources,
            "top_score": found["results"][0]["score"] if found["results"] else None,
        })
    report = {
        "id": str(uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus": "synthetic-learning-v1", "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION, "chunking_version": CHUNKING_VERSION,
        "top_k": top_k, "min_score": service.settings.min_score if min_score is None else min_score,
        "total": len(rows), "passed": sum(row["passed"] for row in rows), "cases": rows,
        "note": "合成学习语料的检索演示，不是金融事实验证或通用检索基准。",
    }
    with service.repository.database._connect() as conn:
        conn.execute(
            "INSERT INTO retrieval_evaluations (id, scope_id, result) VALUES (%s, %s, %s)",
            (report["id"], "local", Jsonb(report)),
        )
    return report
