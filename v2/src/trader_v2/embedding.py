"""Pinned, local-only BGE embeddings; downloading is an explicit CLI action."""

from __future__ import annotations

import math
from pathlib import Path
from threading import Lock
from typing import Any


MODEL_ID = "BAAI/bge-small-zh-v1.5"
MODEL_REVISION = "7999e1d3359715c523056ef9478215996d62a620"
DIMENSION = 512
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
_MANIFEST = ".trader-model.txt"
_REQUIRED_FILES = (
    "config.json", "modules.json", "tokenizer.json", "vocab.txt",
    "model.safetensors", "1_Pooling/config.json",
)
_DOWNLOAD_PATTERNS = [
    "config.json", "config_sentence_transformers.json", "sentence_bert_config.json",
    "modules.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
    "vocab.txt", "1_Pooling/config.json", "model.safetensors",
]


class EmbeddingUnavailableError(RuntimeError):
    """The pinned local model or its runtime cannot serve embeddings."""


class EmbeddingInputError(ValueError):
    """Text cannot be encoded without dropping user-provided content."""


def _manifest_text() -> str:
    return f"{MODEL_ID}\n{MODEL_REVISION}\n"


def _downloaded(model_path: Path) -> bool:
    try:
        return (
            model_path.joinpath(_MANIFEST).read_text(encoding="utf-8") == _manifest_text()
            and all(model_path.joinpath(name).is_file() for name in _REQUIRED_FILES)
        )
    except OSError:
        return False


def download_model(model_path: Path) -> dict[str, Any]:
    """Download only this public model revision into the requested local path."""
    if MODEL_REVISION == "TBD":
        raise EmbeddingUnavailableError("尚未固定 Embedding 模型修订版本")
    target = Path(model_path).resolve()
    if _downloaded(target):
        return LocalBgeEmbedder(target).status()
    try:
        from huggingface_hub import snapshot_download

        target.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=MODEL_ID,
            revision=MODEL_REVISION,
            local_dir=target,
            cache_dir=target.parent / ".hub-cache",
            allow_patterns=_DOWNLOAD_PATTERNS,
            token=False,
        )
        if not all(target.joinpath(name).is_file() for name in _REQUIRED_FILES):
            raise EmbeddingUnavailableError("Embedding 模型文件下载不完整")
        target.joinpath(_MANIFEST).write_text(_manifest_text(), encoding="utf-8")
    except EmbeddingUnavailableError:
        raise
    except Exception as exc:
        raise EmbeddingUnavailableError("Embedding 模型下载失败，请检查网络并重试下载命令") from exc
    return LocalBgeEmbedder(target).status()


class LocalBgeEmbedder:
    def __init__(self, model_path: Path, threads: int = 4) -> None:
        if isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= 32:
            raise ValueError("Embedding threads 必须是 1～32 的整数")
        self.model_path = Path(model_path).resolve()
        self.threads = threads
        self._model: Any = None
        self._load_lock = Lock()
        self._encode_lock = Lock()

    def status(self) -> dict[str, Any]:
        """Inspect local files only, without loading weights or contacting a server."""
        return {
            "model_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "dimension": DIMENSION,
            "model_path": str(self.model_path),
            "downloaded": _downloaded(self.model_path),
            "loaded": self._model is not None,
        }

    @property
    def tokenizer(self) -> Any:
        return self._load().tokenizer

    def _load(self) -> Any:
        with self._load_lock:
            if self._model is not None:
                return self._model
            if not _downloaded(self.model_path):
                raise EmbeddingUnavailableError("固定版本的本地 Embedding 模型未就绪，请先运行模型下载命令")
            try:
                import torch
                from sentence_transformers import SentenceTransformer

                torch.set_num_threads(self.threads)
                model = SentenceTransformer(
                    str(self.model_path), device="cpu", local_files_only=True,
                    trust_remote_code=False, token=False,
                    cache_folder=str(self.model_path.parent / ".sentence-cache"),
                )
                if model.get_sentence_embedding_dimension() != DIMENSION:
                    raise EmbeddingUnavailableError("本地 Embedding 模型维度不匹配")
                if not getattr(model.tokenizer, "is_fast", False):
                    raise EmbeddingUnavailableError("本地 Embedding 模型需要支持原文位置的 fast tokenizer")
                self._model = model
            except EmbeddingUnavailableError:
                raise
            except Exception as exc:
                raise EmbeddingUnavailableError("本地 Embedding 模型加载失败，请检查依赖和模型文件") from exc
            return self._model

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def encode_query(self, query: str) -> list[float]:
        if not isinstance(query, str) or not query.strip():
            raise EmbeddingInputError("检索问题不能为空")
        return self._encode([QUERY_PREFIX + query])[0]

    def _encode(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(texts, list) or not texts:
            raise EmbeddingInputError("Embedding 输入不能为空")
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise EmbeddingInputError("Embedding 文本不能为空")
        model = self._load()
        tokenizer_limit = int(getattr(model.tokenizer, "model_max_length", 512))
        token_limit = min(512, int(model.max_seq_length), tokenizer_limit)
        for text in texts:
            tokens = model.tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"]
            if len(tokens) > token_limit:
                raise EmbeddingInputError(f"Embedding 输入超过 {token_limit} token，请先切块或缩短问题")
        try:
            with self._encode_lock:
                values = model.encode(
                    texts, normalize_embeddings=True, convert_to_numpy=True,
                    show_progress_bar=False, batch_size=16,
                )
            if len(values) != len(texts):
                raise EmbeddingUnavailableError("Embedding 返回数量不匹配")
            vectors = [_validate_vector(value) for value in values]
        except EmbeddingUnavailableError:
            raise
        except Exception as exc:
            raise EmbeddingUnavailableError("本地 Embedding 推理失败") from exc
        return vectors


def _validate_vector(raw: Any) -> list[float]:
    vector = [float(value) for value in raw]
    if len(vector) != DIMENSION or any(not math.isfinite(value) for value in vector):
        raise EmbeddingUnavailableError("Embedding 返回了无效维度或非有限数值")
    norm = math.sqrt(math.fsum(value * value for value in vector))
    if not math.isfinite(norm) or not math.isclose(norm, 1.0, abs_tol=0.001):
        raise EmbeddingUnavailableError("Embedding 返回了零向量或未归一化向量")
    return vector
