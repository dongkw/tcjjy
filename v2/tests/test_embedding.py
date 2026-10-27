"""Mock-runtime checks; actual semantic quality is evaluated separately."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import sys
from unittest.mock import Mock

import pytest

from trader_v2.embedding import (
    DIMENSION, MODEL_ID, MODEL_REVISION, QUERY_PREFIX,
    EmbeddingInputError, EmbeddingUnavailableError, LocalBgeEmbedder,
)


class Tokenizer:
    is_fast = True
    model_max_length = 512

    def __call__(self, text, *, add_special_tokens, truncation):
        assert truncation is False
        return {"input_ids": list(range(len(text) + (2 if add_special_tokens else 0)))}


def fake_embedder(tmp_path):
    embedder = LocalBgeEmbedder(tmp_path)
    model = Mock()
    model.tokenizer = Tokenizer()
    model.max_seq_length = 512
    model.encode.side_effect = lambda texts, **kwargs: [[1.0] + [0.0] * (DIMENSION - 1) for _ in texts]
    embedder._model = model
    return embedder, model


def test_documents_do_not_receive_query_instruction(tmp_path):
    embedder, model = fake_embedder(tmp_path)
    documents = ["应收账款增长，回款周期延长。", "现金流改善。"]
    vectors = embedder.encode_documents(documents)
    assert len(vectors) == 2 and len(vectors[0]) == 512
    assert model.encode.call_args.args[0] == documents
    assert model.encode.call_args.kwargs["normalize_embeddings"] is True
    assert model.encode.call_args.kwargs["convert_to_numpy"] is True


def test_query_receives_instruction_and_rejects_silent_truncation(tmp_path):
    embedder, model = fake_embedder(tmp_path)
    query = "公司的资金回收有没有风险？"
    assert len(embedder.encode_query(query)) == 512
    assert model.encode.call_args.args[0] == [QUERY_PREFIX + query]
    model.encode.reset_mock()
    with pytest.raises(EmbeddingInputError, match="超过"):
        embedder.encode_query("甲" * 510)
    model.encode.assert_not_called()


@pytest.mark.parametrize("texts", [[], [""], [" \n"], [None], "单个字符串"])
def test_invalid_document_inputs_are_rejected_before_loading(tmp_path, texts):
    with pytest.raises(EmbeddingInputError):
        LocalBgeEmbedder(tmp_path).encode_documents(texts)


@pytest.mark.parametrize("query", ["", " \n", None])
def test_empty_queries_are_rejected_before_loading(tmp_path, query):
    with pytest.raises(EmbeddingInputError):
        LocalBgeEmbedder(tmp_path).encode_query(query)


@pytest.mark.parametrize("vector", [
    [1.0], [0.0] * DIMENSION, [float("nan")] + [0.0] * (DIMENSION - 1),
    [float("inf")] + [0.0] * (DIMENSION - 1), [2.0] + [0.0] * (DIMENSION - 1),
])
def test_invalid_runtime_vectors_are_rejected(tmp_path, vector):
    embedder, model = fake_embedder(tmp_path)
    model.encode.side_effect = None
    model.encode.return_value = [vector]
    with pytest.raises(EmbeddingUnavailableError):
        embedder.encode_documents(["正文"])


def test_status_does_not_load_or_create_model(tmp_path):
    missing = tmp_path / "not-downloaded"
    embedder = LocalBgeEmbedder(missing)
    status = embedder.status()
    assert status["downloaded"] is False and status["loaded"] is False
    assert status["dimension"] == 512
    assert not missing.exists()
    with pytest.raises(EmbeddingUnavailableError, match="下载"):
        embedder.encode_query("现金流风险")
    assert not missing.exists()


@pytest.mark.parametrize("threads", [0, -1, 33, True, "4"])
def test_invalid_thread_count_is_rejected(tmp_path, threads):
    with pytest.raises(ValueError):
        LocalBgeEmbedder(tmp_path, threads=threads)


def test_pinned_model_loads_once_and_without_network_or_auth(monkeypatch, tmp_path):
    from trader_v2 import embedding

    for name in embedding._REQUIRED_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("model test fixture", encoding="utf-8")
    (tmp_path / embedding._MANIFEST).write_text(f"{MODEL_ID}\n{MODEL_REVISION}\n", encoding="utf-8")
    model = Mock()
    model.tokenizer = Tokenizer()
    model.get_sentence_embedding_dimension.return_value = DIMENSION
    loader = Mock(return_value=model)
    thread_setter = Mock()
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=thread_setter))
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=loader))
    embedder = LocalBgeEmbedder(tmp_path, threads=2)

    with ThreadPoolExecutor(max_workers=4) as executor:
        tokenizers = list(executor.map(lambda _: embedder.tokenizer, range(4)))
    assert all(tokenizer is model.tokenizer for tokenizer in tokenizers)
    loader.assert_called_once()
    assert loader.call_args.kwargs["local_files_only"] is True
    assert loader.call_args.kwargs["trust_remote_code"] is False
    assert loader.call_args.kwargs["token"] is False
    assert loader.call_args.kwargs["device"] == "cpu"
    thread_setter.assert_called_once_with(2)
    assert embedder.status()["loaded"] is True


def test_wrong_revision_marker_is_not_loaded(tmp_path):
    from trader_v2 import embedding

    for name in embedding._REQUIRED_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("model test fixture", encoding="utf-8")
    (tmp_path / embedding._MANIFEST).write_text(f"{MODEL_ID}\nwrong-revision\n", encoding="utf-8")
    embedder = LocalBgeEmbedder(tmp_path)
    assert embedder.status()["downloaded"] is False
    with pytest.raises(EmbeddingUnavailableError):
        embedder.encode_query("应收账款")


def test_prepare_complete_local_model_reuses_files_without_download(monkeypatch, tmp_path):
    from trader_v2 import embedding

    for name in embedding._REQUIRED_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("model test fixture", encoding="utf-8")
    (tmp_path / embedding._MANIFEST).write_text(f"{MODEL_ID}\n{MODEL_REVISION}\n", encoding="utf-8")
    snapshot = Mock(side_effect=AssertionError("must not download a complete local model"))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot))
    assert embedding.download_model(tmp_path)["downloaded"] is True
    snapshot.assert_not_called()
