"""Hybrid retrieval: fulltext + vector search fused with Reciprocal Rank Fusion.

Both branches run inside seekdb: FULLTEXT ``MATCH ... AGAINST`` on
``fts_text`` (trigram-expanded, see ``fts_text``) and ``l2_distance`` over the
VECTOR column. Each branch contributes up to ``max(limit*4, 32)`` candidates;
ranks are fused with ``1 / (K + rank)`` and the top hits carry ``matched_by``
provenance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.seekdb import get_engine
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.fts_text import fts_tokenize
from app.retrieval.vector_format import vector_literal

log = logging.getLogger("exampilot.retrieval")

RRF_K = 60
CANDIDATE_MULTIPLIER = 4
MIN_CANDIDATES = 32


@dataclass
class HybridHit:
    chunk_id: int
    document_id: int
    filename: str
    course: str | None
    chapter: str | None
    page_number: int
    text: str
    score: float
    matched_by: list[str]


@dataclass
class SearchResult:
    hits: list[HybridHit]
    mode: str  # "hybrid" | "fts-only"
    fts_hits: int
    vector_hits: int
    warning: str | None = None


def _scoped_conditions(
    session_id: str, course_id: int | None, chapter_id: int | None
) -> tuple[str, list]:
    conditions = ["d.session_id=%s"]
    params: list = [session_id]
    if course_id is not None:
        conditions.append("dc.course_id=%s")
        params.append(course_id)
    if chapter_id is not None:
        conditions.append("dc.chapter_id=%s")
        params.append(chapter_id)
    return " AND ".join(conditions), params


def _fts_rank(
    session_id: str,
    query: str,
    course_id: int | None,
    chapter_id: int | None,
    limit: int,
) -> list[int]:
    fts_query = fts_tokenize(query)
    if not fts_query:
        return []
    where, params = _scoped_conditions(session_id, course_id, chapter_id)
    sql = (
        "SELECT dc.id FROM document_chunks dc "
        "JOIN documents d ON dc.document_id = d.id "
        f"WHERE {where} AND MATCH(dc.fts_text) AGAINST (%s) "
        "ORDER BY MATCH(dc.fts_text) AGAINST (%s) DESC LIMIT %s"
    )
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, (*params, fts_query, fts_query, limit))
        return [int(row[0]) for row in cur.fetchall()]


def _vector_rank(
    session_id: str,
    embedding: list[float],
    course_id: int | None,
    chapter_id: int | None,
    limit: int,
) -> list[int]:
    where, params = _scoped_conditions(session_id, course_id, chapter_id)
    sql = (
        "SELECT dc.id FROM document_chunks dc "
        "JOIN documents d ON dc.document_id = d.id "
        f"WHERE {where} AND dc.embedding IS NOT NULL "
        "ORDER BY l2_distance(dc.embedding, %s) LIMIT %s"
    )
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, (*params, vector_literal(embedding), limit))
        return [int(row[0]) for row in cur.fetchall()]


def _rrf(rank_lists: list[list[int]]) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranked in rank_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def _fetch_metadata(session_id: str, chunk_ids: list[int]) -> dict[int, tuple]:
    if not chunk_ids:
        return {}
    placeholders = ",".join(["%s"] * len(chunk_ids))
    sql = (
        "SELECT dc.id, dc.document_id, d.filename, co.name, ch.name, "
        "       dc.page_number, dc.original_text "
        "FROM document_chunks dc "
        "JOIN documents d ON dc.document_id = d.id "
        "LEFT JOIN courses co ON dc.course_id = co.id "
        "LEFT JOIN chapters ch ON dc.chapter_id = ch.id "
        f"WHERE dc.id IN ({placeholders})"
    )
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, chunk_ids)
        return {int(row[0]): row for row in cur.fetchall()}


def hybrid_search(
    session_id: str,
    query: str,
    provider: EmbeddingProvider | None,
    *,
    course_id: int | None = None,
    chapter_id: int | None = None,
    limit: int = 10,
) -> SearchResult:
    candidate_limit = max(limit * CANDIDATE_MULTIPLIER, MIN_CANDIDATES)
    warning: str | None = None

    fts_ids: list[int] = []
    try:
        fts_ids = _fts_rank(session_id, query, course_id, chapter_id, candidate_limit)
    except Exception as exc:  # noqa: BLE001 - search degradation paths are logged
        warning = f"fulltext search failed: {exc}"
        log.warning("fulltext search failed for session %s: %s", session_id, exc)

    vec_ids: list[int] = []
    vec_ok = provider is not None and provider.enabled
    if vec_ok:
        try:
            embedding = provider.embed([query])[0]
            vec_ids = _vector_rank(
                session_id, embedding, course_id, chapter_id, candidate_limit
            )
        except Exception as exc:  # noqa: BLE001 - search degradation paths are logged
            vec_ok = False
            warning = (
                warning + "; " if warning else ""
            ) + f"vector search unavailable: {exc}"
            log.warning("vector search unavailable for session %s: %s", session_id, exc)

    if not vec_ids:
        mode = "fts-only"
        scores = {
            cid: 1.0 / (RRF_K + rank) for rank, cid in enumerate(fts_ids, start=1)
        }
        matched_by = {cid: ["fts"] for cid in fts_ids}
    else:
        mode = "hybrid"
        scores = _rrf([fts_ids, vec_ids])
        matched_by = {
            cid: [
                name
                for name, ids in (("fts", fts_ids), ("vector", vec_ids))
                if cid in ids
            ]
            for cid in scores
        }

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    meta = _fetch_metadata(session_id, [cid for cid, _ in ranked])
    hits: list[HybridHit] = []
    for chunk_id, score in ranked:
        row = meta.get(chunk_id)
        if row is None:
            continue
        hits.append(
            HybridHit(
                chunk_id=chunk_id,
                document_id=int(row[1]),
                filename=str(row[2]),
                course=str(row[3]) if row[3] else None,
                chapter=str(row[4]) if row[4] else None,
                page_number=int(row[5]),
                text=str(row[6]),
                score=round(score, 5),
                matched_by=matched_by[chunk_id],
            )
        )
    return SearchResult(
        hits=hits,
        mode=mode,
        fts_hits=len(fts_ids),
        vector_hits=len(vec_ids),
        warning=warning,
    )
