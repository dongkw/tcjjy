"""Chunk boundaries use a tiny offset tokenizer, not a semantic model evaluation."""

import pytest

from trader_v2.chunking import chunk_text


class CharacterTokenizer:
    is_fast = True
    model_max_length = 512

    def num_special_tokens_to_add(self, pair=False):
        return 2

    def __call__(self, text, *, add_special_tokens, truncation, return_offsets_mapping=False):
        assert truncation is False
        offsets = [(i, i + 1) for i, character in enumerate(text) if not character.isspace()]
        result = {"input_ids": list(range(len(offsets) + (2 if add_special_tokens else 0)))}
        if return_offsets_mapping:
            result["offset_mapping"] = offsets
        return result


def test_windows_preserve_unicode_source_and_overlap():
    body = "  甲乙丙丁戊己庚辛壬癸😀甲乙丙丁戊己庚辛壬癸  "
    chunks = chunk_text(body, CharacterTokenizer(), max_tokens=8, overlap_tokens=2)
    assert len(chunks) == 4
    assert chunks[0].start_char == 0 and chunks[-1].end_char == len(body)
    assert all(chunk.text == body[chunk.start_char:chunk.end_char] for chunk in chunks)
    assert all(chunk.token_count <= 8 for chunk in chunks)
    assert [chunk.chunk_no for chunk in chunks] == list(range(len(chunks)))
    assert all(right.start_char < left.end_char for left, right in zip(chunks, chunks[1:]))
    covered = {index for chunk in chunks for index in range(chunk.start_char, chunk.end_char)}
    assert covered == set(range(len(body)))


def test_zero_overlap_does_not_drop_whitespace_between_tokens():
    body = "甲乙 丙丁\r\n戊己 庚辛"
    chunks = chunk_text(body, CharacterTokenizer(), max_tokens=2, overlap_tokens=0)
    assert "".join(chunk.text for chunk in chunks) == body


def test_paragraph_boundary_preferred_without_losing_text():
    body = "甲乙丙丁戊己\n\n庚辛壬癸子丑寅卯辰巳午未"
    chunks = chunk_text(body, CharacterTokenizer(), max_tokens=10, overlap_tokens=2)
    assert chunks[0].text.endswith("\n\n")
    assert all(chunk.text == body[chunk.start_char:chunk.end_char] for chunk in chunks)
    covered = {index for chunk in chunks for index in range(chunk.start_char, chunk.end_char)}
    assert covered == set(range(len(body)))


@pytest.mark.parametrize("body", ["", " \n\r\t", None])
def test_empty_body_is_rejected(body):
    with pytest.raises(ValueError):
        chunk_text(body, CharacterTokenizer())


@pytest.mark.parametrize("maximum,overlap", [(0, 0), (8, 8), (8, -1), (511, 0), (True, 0)])
def test_invalid_token_budget_is_rejected(maximum, overlap):
    with pytest.raises(ValueError):
        chunk_text("正文", CharacterTokenizer(), max_tokens=maximum, overlap_tokens=overlap)


def test_short_body_and_exact_model_limit():
    chunks = chunk_text("甲" * 510, CharacterTokenizer(), max_tokens=510, overlap_tokens=0)
    assert len(chunks) == 1 and chunks[0].token_count == 510


def test_slow_tokenizer_is_rejected():
    tokenizer = CharacterTokenizer()
    tokenizer.is_fast = False
    with pytest.raises(ValueError, match="fast tokenizer"):
        chunk_text("正文", tokenizer)
