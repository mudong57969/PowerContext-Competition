"""Unit tests for chunking / normalization in the indexing pipeline."""

from app.services.indexing import (
    CHUNK_OVERLAP_CHARS,
    CHUNK_TARGET_CHARS,
    _normalize,
    chunk_pages,
)
from app.services.parsing import ParsedPage


def test_normalize_collapses_whitespace():
    assert _normalize("  a   b\n c ") == "a b c"


def test_short_page_stays_single_chunk():
    chunks = chunk_pages([ParsedPage(page_number=1, text="短内容")])
    assert chunks == [(1, "短内容")]


def test_blank_pages_skipped():
    chunks = chunk_pages(
        [ParsedPage(page_number=1, text="   "), ParsedPage(page_number=2, text="ok")]
    )
    assert chunks == [(2, "ok")]


def test_long_page_splits_with_overlap():
    text = "甲" * 1200
    chunks = chunk_pages([ParsedPage(page_number=1, text=text)])
    assert len(chunks) == 3
    assert all(page_no == 1 for page_no, _ in chunks)
    sizes = [len(piece) for _, piece in chunks]
    assert max(sizes) <= CHUNK_TARGET_CHARS
    # overlap: second piece starts 80 chars before the first piece ends
    assert (
        chunks[1][1][:10]
        == text[
            CHUNK_TARGET_CHARS - CHUNK_OVERLAP_CHARS : CHUNK_TARGET_CHARS
            - CHUNK_OVERLAP_CHARS
            + 10
        ]
    )


def test_long_page_splits_at_sentence_boundary():
    size = CHUNK_TARGET_CHARS
    text = "乙" * (size - 20) + "。" + "丙" * 500
    chunks = chunk_pages([ParsedPage(page_number=1, text=text)])
    assert len(chunks) == 3
    assert chunks[0][1].endswith("。")
