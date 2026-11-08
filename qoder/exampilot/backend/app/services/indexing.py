"""Chunking and embedding pipeline for ``document_chunks``.

Pages are split into ~500-character chunks (long pages cut near sentence
boundaries with overlap). Chunk embeddings come from the configured
embedding provider; if embeddings are unavailable the chunks are still
indexed for fulltext search and the result is flagged as degraded.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.core.seekdb import get_engine
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.fts_text import fts_tokenize
from app.retrieval.vector_format import vector_literal
from app.services.parsing import ParsedPage

log = logging.getLogger("exampilot.indexing")

CHUNK_TARGET_CHARS = 500
CHUNK_OVERLAP_CHARS = 80


@dataclass
class IndexResult:
    chunk_count: int
    embedding_count: int
    degraded: bool
    warning: str | None = None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _split_long(text: str) -> list[str]:
    size = CHUNK_TARGET_CHARS
    overlap = CHUNK_OVERLAP_CHARS
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind(sep) for sep in ("。", ".", "；", ";"))
            if cut > size // 2:
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        start = end - overlap
    return pieces


def chunk_pages(pages: list[ParsedPage]) -> list[tuple[int, str]]:
    chunks: list[tuple[int, str]] = []
    for page in pages:
        text = page.text.strip()
        if not text:
            continue
        if len(text) <= CHUNK_TARGET_CHARS + CHUNK_OVERLAP_CHARS:
            chunks.append((page.page_number, text))
        else:
            chunks.extend((page.page_number, piece) for piece in _split_long(text))
    return chunks


def index_document(
    document_id: int,
    course_id: int | None,
    chapter_id: int | None,
    pages: list[ParsedPage],
    provider: EmbeddingProvider | None,
) -> IndexResult:
    chunks = chunk_pages(pages)
    if not chunks:
        return IndexResult(chunk_count=0, embedding_count=0, degraded=False)

    embeddings: list[list[float]] = []
    warning: str | None = None
    if provider is not None and provider.enabled:
        try:
            embeddings = provider.embed([text for _, text in chunks])
        except Exception as exc:  # noqa: BLE001 - embedding failure is logged and reported
            log.warning("embedding failed for document %s: %s", document_id, exc)
            warning = f"embedding failed: {exc}"

    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM document_chunks WHERE document_id=%s", (document_id,))
        for idx, (page_no, text) in enumerate(chunks):
            embedding = (
                vector_literal(embeddings[idx])
                if len(embeddings) == len(chunks)
                else None
            )
            normalized = _normalize(text)
            cur.execute(
                "INSERT INTO document_chunks "
                "(document_id, course_id, chapter_id, chunk_index, page_number, "
                " original_text, normalized_text, fts_text, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    document_id,
                    course_id,
                    chapter_id,
                    idx,
                    page_no,
                    text,
                    normalized,
                    fts_tokenize(normalized),
                    embedding,
                ),
            )
    return IndexResult(
        chunk_count=len(chunks),
        embedding_count=len(embeddings),
        degraded=len(embeddings) != len(chunks),
        warning=warning,
    )
