"""Memory validation uses explicit stubs; it does not assess model relevance."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from trader_v2.knowledge_service import KnowledgeService
from trader_v2.memory_service import MemoryService
from trader_v2.settings import KnowledgeSettings

from test_knowledge_service import StubEmbedder


def make_memory_service():
    db = Mock()
    knowledge = KnowledgeService(db, embedder=StubEmbedder(), settings=KnowledgeSettings(model_path=Path("unused")))
    return MemoryService(db, knowledge), db, knowledge.embedder


def memory(**overrides):
    return {"kind": "preference", "content": "研究时先核对现金流。", "source_type": "user_statement",
            "source_reference": "以后研究时优先看现金流", **overrides}


@pytest.mark.parametrize("overrides", [
    {"kind": "fact"}, {"scope_id": "../other"}, {"content": "   "}, {"content": "a\x00b"},
    {"content": "甲" * 1201}, {"source_reference": ""}, {"source_reference": "x\x00"},
    {"symbol": "300001"}, {"source_type": "research_report"},
    {"kind": "lesson", "source_type": "user_statement"},
    {"kind": "lesson", "source_type": "research_report", "source_reference": "made-up-id"},
    {"expires_at": datetime.now()},
    {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
    {"expires_at": datetime.now(timezone.utc) + timedelta(days=4000)},
])
def test_invalid_memory_never_encodes_or_writes(overrides):
    service, db, embedder = make_memory_service()
    with pytest.raises(ValueError):
        service.save(memory(**overrides))
    assert embedder.documents == []
    db._connect.assert_not_called()


def test_default_lifetimes_and_epistemic_status_are_explicit():
    service, _, _ = make_memory_service()
    now = datetime.now(timezone.utc)
    preference = service._validated(memory(), now)
    pending = service._validated(memory(kind="pending"), now)
    assert preference["expires_at"] == now + timedelta(days=365)
    assert pending["expires_at"] == now + timedelta(days=30)
    assert preference["epistemic_status"] == "user_asserted"


def test_long_memory_is_rejected_without_truncating_or_splitting():
    service, db, embedder = make_memory_service()
    with pytest.raises(ValueError, match="最多400个token"):
        service.save(memory(content="甲" * 399))
    assert embedder.documents == []
    db._connect.assert_not_called()


@pytest.mark.parametrize("kwargs", [
    {"query": " "}, {"query": "x", "scope_id": "../other"},
    {"query": "x", "symbol": "300001"}, {"query": "x", "kind": "fact"},
    {"query": "x", "min_score": float("nan")}, {"query": "x", "min_score": True},
    {"query": "x", "top_k": 0}, {"query": "x", "top_k": True},
])
def test_invalid_recall_never_encodes_or_queries(kwargs):
    service, db, embedder = make_memory_service()
    with pytest.raises(ValueError):
        service.recall(**kwargs)
    assert embedder.queries == []
    db._connect.assert_not_called()


def test_scope_and_limits_checked_for_non_embedding_reads():
    service, db, _ = make_memory_service()
    with pytest.raises(ValueError):
        service.list(scope_id="../other")
    with pytest.raises(ValueError):
        service.list(limit=0)
    with pytest.raises(ValueError):
        service.list(include_inactive="yes")
    db._connect.assert_not_called()
