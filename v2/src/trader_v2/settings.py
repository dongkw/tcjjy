"""Load only the V2 process configuration, never the old JSON account files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_url: str
    port: int = 8012

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env", override=False, encoding="utf-8-sig")
        url = os.environ.get("V2_DATABASE_URL", "")
        if not url:
            raise RuntimeError("缺少 V2_DATABASE_URL，请先运行 .\\scripts\\setup.ps1")
        port = int(os.environ.get("V2_API_PORT", "8012"))
        if not 1 <= port <= 65535:
            raise ValueError("V2_API_PORT 必须是 1～65535")
        return cls(database_url=url, port=port)


@dataclass(frozen=True)
class KnowledgeSettings:
    model_path: Path = PROJECT_ROOT / ".runtime" / "models" / "bge-small-zh-v1.5"
    threads: int = 4
    min_score: float = 0.55

    @classmethod
    def from_env(cls) -> "KnowledgeSettings":
        load_dotenv(PROJECT_ROOT / ".env", override=False, encoding="utf-8-sig")
        model_path = Path(os.environ.get("V2_MODEL_PATH", str(cls.model_path))).expanduser().resolve()
        threads = int(os.environ.get("V2_EMBEDDING_THREADS", "4"))
        min_score = float(os.environ.get("V2_RETRIEVAL_MIN_SCORE", "0.55"))
        if not 1 <= threads <= 32 or not 0 <= min_score <= 1:
            raise ValueError("Embedding 线程需为1～32，检索阈值需为0～1")
        return cls(model_path=model_path, threads=threads, min_score=min_score)
