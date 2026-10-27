"""Real PostgreSQL/pgvector boundary tests with explicit synthetic vectors.

These verify storage and filters, not the quality of a text embedding model.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from importlib.resources import files
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from trader_v2.database import Database
from trader_v2.knowledge_repository import KnowledgeRepository
from trader_v2.settings import Settings


pytestmark = pytest.mark.integration
PROFILE = {"model_id": "synthetic-test", "model_revision": "test-r1", "chunking_version": "test-chunks-v1"}
OCTOBER = datetime(2026, 10, 1, tzinfo=timezone.utc)
DECEMBER = datetime(2026, 12, 1, tzinfo=timezone.utc)


def vector(axis: int = 0, sign: float = 1.0) -> list[float]:
    values = [0.0] * 512
    values[axis] = sign
    return values


@pytest.fixture(scope="module")
def knowledge_database():
    if os.environ.get("V2_RUN_DB_TESTS") != "1":
        pytest.skip("set V2_RUN_DB_TESTS=1 to test PostgreSQL")
    admin_dsn = Settings.from_env().database_url
    name = "trader_v2_test_knowledge_" + uuid4().hex
    with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(admin_dsn)
    params["dbname"] = name
    dsn = make_conninfo(**params)
    try:
        database = Database(dsn)
        database.initialize()
        # This also allows the focused test to run before the root upgrades its
        # migration runner; execution is idempotent once migration 2 is wired.
        with database._connect() as conn:
            conn.execute(files("trader_v2").joinpath("sql", "002_knowledge.sql").read_text(encoding="utf-8"), prepare=False)
        yield KnowledgeRepository(database), dsn
    finally:
        assert name.startswith("trader_v2_test_knowledge_")
        with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def save(repository, scope, key, *, text="应收账款增长，回款周期延长。", symbol="601138",
         kind="announcement", mode="fixture", available=OCTOBER, embedding=None, profile=None):
    metadata = {
        "scope_id": scope, "source_key": key, "title": "合成测试资料",
        "body": text, "symbol": symbol, "kind": kind, "mode": mode,
        "source_name": "synthetic-test", "source_url": None, "available_at": available,
        "content_hash": hashlib.sha256(f"{text}|{symbol}|{kind}|{mode}|{available}".encode()).hexdigest(),
    }
    chunks = [{
        "chunk_no": 0, "start_char": 0, "end_char": len(text), "text": text,
        "token_count": len(text), "embedding": embedding or vector(),
    }]
    return repository.save_document(metadata, chunks, **(profile or PROFILE)), metadata, chunks


def search(repository, scope, **kwargs):
    return repository.search(vector(), scope_id=scope, as_of=kwargs.pop("as_of", DECEMBER), **PROFILE, **kwargs)


def test_duplicate_import_and_original_offsets(knowledge_database):
    repository, dsn = knowledge_database
    scope = uuid4().hex
    saved, metadata, chunks = save(repository, scope, "same-source")
    again = repository.save_document(metadata, chunks, **PROFILE)
    assert not saved["reused"] and again["reused"]
    assert saved["id"] == again["id"] and again["version"] == 1
    assert again["chunk_count"] == 1
    found = repository.find_existing(scope, "same-source", metadata["content_hash"], **PROFILE)
    assert found["id"] == saved["id"] and found["reused"]
    hits = search(repository, scope)
    assert hits[0]["score"] == pytest.approx(1)
    evidence = repository.read_chunk(hits[0]["chunk_id"], scope)
    document = repository.get_document(saved["id"], scope)
    assert document["body"][evidence["start_char"]:evidence["end_char"]] == evidence["text"]
    assert repository.get_document(saved["id"], "another-scope") is None
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT count(*) FROM documents WHERE scope_id = %s", (scope,)).fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM document_chunks WHERE document_id = %s", (saved["id"],)).fetchone()[0] == 1


def test_scope_company_type_mode_and_threshold_filters(knowledge_database):
    repository, _ = knowledge_database
    scope = uuid4().hex
    wanted, _, _ = save(repository, scope, "wanted")
    save(repository, "elsewhere", "other-account")
    save(repository, scope, "another-company", symbol="600398")
    save(repository, scope, "another-kind", kind="research")
    save(repository, scope, "another-mode", mode="imported")
    save(repository, scope, "unrelated", embedding=vector(1))
    hits = search(repository, scope, symbol="601138", kind="announcement", mode="fixture", min_score=0.7)
    assert [hit["document_id"] for hit in hits] == [wanted["id"]]
    assert search(repository, scope, symbol="000969") == []
    assert repository.list_documents(scope_id=scope, symbol="601138", mode="imported")[0]["source_key"] == "another-mode"


def test_visible_version_is_chosen_before_metadata_filter(knowledge_database):
    repository, _ = knowledge_database
    scope = uuid4().hex
    old, _, _ = save(repository, scope, "revision", text="旧版风险提示。")
    new, _, _ = save(
        repository, scope, "revision", text="新版资料修订了公司归属。", symbol="600398",
        available=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    assert new["version"] == 2
    historical = search(repository, scope, as_of=datetime(2026, 10, 15, tzinfo=timezone.utc), symbol="601138")
    assert historical[0]["document_id"] == old["id"]
    assert search(repository, scope, symbol="601138") == []
    assert search(repository, scope, symbol="600398")[0]["document_id"] == new["id"]
    assert search(repository, scope, as_of=datetime(2026, 9, 1, tzinfo=timezone.utc)) == []


def test_deleting_a_source_hides_all_versions_and_chunks(knowledge_database):
    repository, _ = knowledge_database
    scope = uuid4().hex
    old, _, _ = save(repository, scope, "delete-me", text="第一版。")
    evidence_id = search(repository, scope)[0]["chunk_id"]
    save(repository, scope, "delete-me", text="第二版。")
    assert not repository.delete_source(old["id"], "another-scope")
    assert repository.delete_source(old["id"], scope)
    assert not repository.delete_source(old["id"], scope)
    assert search(repository, scope) == []
    assert repository.list_documents(scope) == []
    assert repository.read_chunk(evidence_id, scope) is None


def test_embedding_profile_is_not_mixed(knowledge_database):
    repository, _ = knowledge_database
    scope = uuid4().hex
    saved, metadata, chunks = save(repository, scope, "profiles")
    revised = {**PROFILE, "model_revision": "test-r2"}
    assert repository.find_existing(scope, "profiles", metadata["content_hash"], **revised) is None
    chunks[0]["embedding"] = vector(0, -1)
    another = repository.save_document(metadata, chunks, **revised)
    assert another["id"] == saved["id"] and another["chunk_count"] == 1
    assert search(repository, scope)[0]["score"] == pytest.approx(1)
    assert repository.search(vector(), scope_id=scope, as_of=DECEMBER, **revised) == []
    assert repository.search(vector(), scope_id=scope, as_of=DECEMBER, **{**PROFILE, "chunking_version": "unknown"}) == []


@pytest.mark.parametrize("bad_vector", [[0.0] * 512, [1.0], [float("nan")] + [0.0] * 511])
def test_invalid_vectors_never_reach_postgres(knowledge_database, bad_vector):
    repository, _ = knowledge_database
    with pytest.raises(ValueError):
        repository.search(bad_vector, scope_id=uuid4().hex, as_of=DECEMBER, **PROFILE)
