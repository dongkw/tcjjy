"""Token-bounded text windows with pointers into the unchanged source body."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Any


CHUNKING_VERSION = "token-window-v1:320:40"


@dataclass(frozen=True)
class TextChunk:
    chunk_no: int
    start_char: int
    end_char: int
    text: str
    token_count: int


def chunk_text(
    body: str, tokenizer: Any, max_tokens: int = 320, overlap_tokens: int = 40,
) -> list[TextChunk]:
    if not isinstance(body, str) or not body.strip():
        raise ValueError("资料正文不能为空")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (max_tokens, overlap_tokens)):
        raise ValueError("切块大小和重叠必须是整数")
    if not 0 <= overlap_tokens < max_tokens:
        raise ValueError("重叠 token 必须非负且小于切块大小")
    if not getattr(tokenizer, "is_fast", False):
        raise ValueError("切块需要支持 offsets_mapping 的 fast tokenizer")
    special_tokens = tokenizer.num_special_tokens_to_add(pair=False)
    model_limit = min(512, int(getattr(tokenizer, "model_max_length", 512)))
    if max_tokens + special_tokens > model_limit:
        raise ValueError("切块大小加特殊 token 超过模型输入上限")

    encoded = tokenizer(body, add_special_tokens=False, truncation=False, return_offsets_mapping=True)
    offsets = [(int(start), int(end)) for start, end in encoded["offset_mapping"] if int(end) > int(start)]
    if not offsets:
        raise ValueError("资料正文没有可向量化的 token")
    if any(start < 0 or end > len(body) or start >= end for start, end in offsets):
        raise ValueError("tokenizer 返回了无效原文位置")
    starts = [start for start, _ in offsets]
    if starts != sorted(starts):
        raise ValueError("tokenizer 原文位置必须递增")

    chunks: list[TextChunk] = []
    start_index = 0
    while start_index < len(offsets):
        end_index = min(start_index + max_tokens, len(offsets))
        start_char = 0 if start_index == 0 else offsets[start_index][0]
        end_char = len(body) if end_index == len(offsets) else offsets[end_index][0]

        if end_index < len(offsets):
            paragraph_end = body.rfind("\n\n", offsets[start_index + max_tokens // 2][0], end_char)
            if paragraph_end >= 0:
                paragraph_index = bisect_right(starts, paragraph_end + 1)
                if start_index + overlap_tokens < paragraph_index < end_index:
                    end_index = paragraph_index

        # WordPiece tokens can change when a window starts in the middle of a word.
        # Count each actual slice and shorten it rather than letting encode truncate.
        while end_index > start_index:
            end_char = len(body) if end_index == len(offsets) else offsets[end_index][0]
            text = body[start_char:end_char]
            token_count = len(tokenizer(text, add_special_tokens=False, truncation=False)["input_ids"])
            if text.strip() and token_count <= max_tokens:
                break
            end_index -= 1
        else:
            raise ValueError("单个原文片段超过切块上限，无法在保留原文位置时编码")

        chunks.append(TextChunk(len(chunks), start_char, end_char, text, token_count))
        if end_index == len(offsets):
            break
        start_index = max(start_index + 1, end_index - overlap_tokens)
    return chunks
