"""Service boundaries with explicit deterministic test stubs, not BGE inference."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from trader_v2.embedding import EmbeddingInputError
from trader_v2.knowledge_service import KnowledgeService, _validated_document
from trader_v2.settings import KnowledgeSettings


class StubTokenizer:
    is_fast = True
    model_max_length = 512

    def num_special_tokens_to_add(self, pair=False):
        return 2

    def __call__(self, text, *, add_special_tokens, truncation, return_offsets_mapping=False):
        offsets = [(index, index + 1) for index, value in enumerate(text) if not value.isspace()]
        result = {"input_ids": list(range(len(offsets) + (2 if add_special_tokens else 0)))}
        if return_offsets_mapping:
            result["offset_mapping"] = offsets
        return result


class StubEmbedder:
    """Vectors deliberately carry no semantic meaning."""

    tokenizer = StubTokenizer()

    def __init__(self):
        self.documents = []
        self.queries = []

    def encode_documents(self, texts):
        self.documents.extend(texts)
        return [[1.0] + [0.0] * 511 for _ in texts]

    def encode_query(self, query):
        self.queries.append(query)
        if len(query) > 500:
            raise EmbeddingInputError("测试 stub 模拟编码器 token 超限")
        return [1.0] + [0.0] * 511

    def status(self):
        return {"downloaded": True, "loaded": True, "test_stub": True}


def document(**overrides):
    return {
        "scope_id": "local", "source_key": "test.source", "title": "测试资料",
        "body": "应收账款增加，需要核实期后收款。", "symbol": "601138",
        "kind": "note", "mode": "imported", "source_name": "用户测试输入",
        "source_url": "https://example.com/source",
        "available_at": datetime(2026, 10, 1, 8, tzinfo=timezone.utc),
        **overrides,
    }


def service_with_stub():
    embedder = StubEmbedder()
    service = KnowledgeService(Mock(), embedder=embedder, settings=KnowledgeSettings(model_path=Path("unused-test-model")))
    service.repository = Mock()
    service.repository.find_existing.return_value = None
    return service, embedder


def test_content_hash_normalizes_equivalent_timezone_instants():
    utc = _validated_document(document())
    shanghai = _validated_document(document(available_at=datetime(2026, 10, 1, 16, tzinfo=timezone(timedelta(hours=8)))))
    assert utc["content_hash"] == shanghai["content_hash"]
    assert shanghai["available_at"] == utc["available_at"]
    assert _validated_document(document(body="已补充收款明细。"))["content_hash"] != utc["content_hash"]
    assert _validated_document(document(symbol="600398"))["content_hash"] != utc["content_hash"]


def test_reimport_of_indexed_content_does_not_encode_again():
    service, embedder = service_with_stub()
    previous = {"id": "stored-id", "reused": True, "chunk_count": 1}
    service.repository.find_existing.return_value = previous
    assert service.ingest(document()) == previous
    assert embedder.documents == []
    service.repository.save_document.assert_not_called()


def test_ingestion_preserves_source_offsets_and_passes_profile():
    service, embedder = service_with_stub()
    body = "  " + "应收账款与实际收款之间存在时间差。" * 40 + "\r\n"
    service.repository.save_document.return_value = {"id": "new-id", "reused": False}
    saved = service.ingest(document(body=body))
    assert saved["id"] == "new-id"
    args, profile = service.repository.save_document.call_args
    metadata, chunks = args
    assert metadata["body"] == body
    assert len(chunks) > 1 and len(chunks) == len(embedder.documents)
    assert all(chunk["text"] == body[chunk["start_char"]:chunk["end_char"]] for chunk in chunks)
    assert all(len(chunk["embedding"]) == 512 and chunk["token_count"] <= 320 for chunk in chunks)
    assert profile["model_revision"] and profile["chunking_version"]


def test_empty_retrieval_remains_empty_without_a_fabricated_answer():
    service, embedder = service_with_stub()
    service.repository.search.return_value = []
    response = service.search("没有证据的问题", symbol="601138", mode="imported")
    assert response["results"] == []
    assert "answer" not in response
    _, options = service.repository.search.call_args
    assert options["symbol"] == "601138" and options["mode"] == "imported"
    assert options["as_of"].utcoffset() is not None
    assert embedder.queries == ["没有证据的问题"]


@pytest.mark.parametrize("query", ["", "   ", "甲" * 2001])
def test_invalid_query_rejected_before_embedding(query):
    service, embedder = service_with_stub()
    with pytest.raises(ValueError):
        service.search(query)
    assert embedder.queries == []
    service.repository.search.assert_not_called()


def test_encoder_token_limit_failure_is_not_silently_truncated():
    service, embedder = service_with_stub()
    query = "甲" * 501
    with pytest.raises(EmbeddingInputError):
        service.search(query)
    assert embedder.queries == [query]
    service.repository.search.assert_not_called()


@pytest.mark.parametrize("overrides", [
    {"body": "   "}, {"scope_id": "../other"}, {"symbol": "300001"},
    {"source_url": "javascript:alert(1)"}, {"source_url": "https://name:secret@example.com"},
    {"available_at": datetime(2026, 10, 1)},
])
def test_invalid_document_metadata_is_rejected(overrides):
    service, embedder = service_with_stub()
    with pytest.raises(ValueError):
        service.ingest(document(**overrides))
    assert embedder.documents == []
    service.repository.find_existing.assert_not_called()


@pytest.mark.parametrize("field", ["source_key", "title", "body", "source_name", "source_url"])
def test_nul_text_is_rejected_before_database_or_encoding(field):
    service, embedder = service_with_stub()
    data = document()
    data[field] = str(data[field]) + "\x00"
    with pytest.raises(ValueError):
        service.ingest(data)
    assert embedder.documents == []
    service.repository.find_existing.assert_not_called()
