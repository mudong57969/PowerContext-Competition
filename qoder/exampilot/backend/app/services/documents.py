"""Upload → parse → classify → index pipeline and classification confirmation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.core.seekdb import get_engine
from app.retrieval.embeddings import EmbeddingProvider
from app.services.classification import classify_document
from app.services.indexing import index_document
from app.services.parsing import ParseError, UnsupportedFileTypeError, parse_bytes

ALLOWED_EXTENSIONS = {".pdf", ".pptx", ".md", ".markdown", ".txt"}


@dataclass
class UploadOutcome:
    document_id: int | None
    filename: str
    ok: bool
    error: str | None = None
    duplicate: bool = False
    file_type: str = ""
    page_count: int = 0
    parse_status: str = ""
    classify_status: str = ""
    classify_confidence: float = 0.0
    classify_reason: str = "ok"
    course: str | None = None
    chapter: str | None = None
    knowledge_points: list[str] = field(default_factory=list)
    course_candidates: list[dict] = field(default_factory=list)
    chapter_candidates: list[dict] = field(default_factory=list)
    kp_evidence: dict = field(default_factory=dict)
    extracted_chars: int = 0
    evidence: dict = field(default_factory=dict)
    ocr_required: bool = False
    warnings: list[str] = field(default_factory=list)


def get_or_create_course(
    cur, session_id: str, name: str, confidence: float, status: str
) -> int:
    cur.execute(
        "SELECT id FROM courses WHERE session_id=%s AND name=%s", (session_id, name)
    )
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur.execute(
        "INSERT INTO courses (session_id, name, confidence, status) VALUES (%s, %s, %s, %s)",
        (session_id, name, confidence, status),
    )
    return int(cur.lastrowid)


def get_or_create_chapter(cur, course_id: int, name: str) -> int:
    cur.execute(
        "SELECT id FROM chapters WHERE course_id=%s AND name=%s", (course_id, name)
    )
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur.execute(
        "SELECT COALESCE(MAX(order_index), 0) + 1 FROM chapters WHERE course_id=%s",
        (course_id,),
    )
    order_index = int(cur.fetchone()[0])
    cur.execute(
        "INSERT INTO chapters (course_id, name, order_index) VALUES (%s, %s, %s)",
        (course_id, name, order_index),
    )
    return int(cur.lastrowid)


def get_or_create_kp(cur, course_id: int, chapter_id: int | None, name: str) -> int:
    cur.execute(
        "SELECT id FROM knowledge_points WHERE course_id=%s AND name=%s",
        (course_id, name),
    )
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur.execute(
        "INSERT INTO knowledge_points (course_id, chapter_id, name) VALUES (%s, %s, %s)",
        (course_id, chapter_id, name),
    )
    return int(cur.lastrowid)


def process_upload(
    session_id: str,
    filename: str,
    data: bytes,
    provider: EmbeddingProvider | None,
    high_threshold: float,
    mid_threshold: float,
) -> UploadOutcome:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return UploadOutcome(
            document_id=None,
            filename=filename,
            ok=False,
            error=f"unsupported file type: {ext or '(none)'}",
        )
    file_hash = hashlib.sha256(data).hexdigest()
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM documents WHERE session_id=%s AND file_hash=%s",
            (session_id, file_hash),
        )
        existing = cur.fetchone()
        if existing:
            return _load_outcome(int(existing[0]), filename, duplicate=True)
        try:
            parsed = parse_bytes(filename, data)
        except (UnsupportedFileTypeError, ParseError) as exc:
            cur.execute(
                "INSERT INTO documents (session_id, filename, file_type, file_hash, "
                "file_size, parse_status, classify_status) "
                "VALUES (%s, %s, %s, %s, %s, 'failed', 'pending')",
                (session_id, filename, ext.lstrip("."), file_hash, len(data)),
            )
            return UploadOutcome(
                document_id=int(cur.lastrowid),
                filename=filename,
                ok=False,
                error=str(exc),
                file_type=ext.lstrip("."),
                parse_status="failed",
            )
        decision = classify_document(
            session_id, filename, parsed, high_threshold, mid_threshold
        )
        course_id: int | None = None
        chapter_id: int | None = None
        if decision.course and decision.status == "auto":
            course_id = get_or_create_course(
                cur, session_id, decision.course, decision.confidence, "auto"
            )
            if decision.chapter:
                chapter_id = get_or_create_chapter(cur, course_id, decision.chapter)
        cur.execute(
            "INSERT INTO documents (session_id, course_id, chapter_id, filename, file_type, "
            "file_hash, file_size, parse_status, classify_status, classify_confidence, "
            "classify_evidence, ocr_required) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'parsed', %s, %s, %s, %s)",
            (
                session_id,
                course_id,
                chapter_id,
                filename,
                ext.lstrip("."),
                file_hash,
                len(data),
                decision.status,
                decision.confidence,
                json.dumps(decision.evidence, ensure_ascii=False),
                1 if parsed.ocr_required else 0,
            ),
        )
        doc_id = int(cur.lastrowid)
        index_result = index_document(
            doc_id, course_id, chapter_id, parsed.pages, provider
        )
        if course_id is not None:
            for kp_name in decision.knowledge_points:
                kp_id = get_or_create_kp(cur, course_id, chapter_id, kp_name)
                slides = decision.kp_evidence.get(kp_name, [])
                cur.execute(
                    "INSERT IGNORE INTO document_knowledge_links "
                    "(document_id, knowledge_point_id, slide_numbers) VALUES (%s, %s, %s)",
                    (doc_id, kp_id, json.dumps(slides) if slides else None),
                )
        cur.execute(
            "UPDATE documents SET page_count=%s WHERE id=%s",
            (parsed.page_count, doc_id),
        )
        outcome = UploadOutcome(
            document_id=doc_id,
            filename=filename,
            ok=True,
            file_type=ext.lstrip("."),
            page_count=parsed.page_count,
            parse_status="parsed",
            classify_status=decision.status,
            classify_confidence=decision.confidence,
            classify_reason=decision.reason,
            course=decision.course,
            chapter=decision.chapter,
            knowledge_points=decision.knowledge_points,
            course_candidates=decision.course_candidates,
            chapter_candidates=decision.chapter_candidates,
            kp_evidence=decision.kp_evidence,
            extracted_chars=parsed.total_chars,
            evidence=decision.evidence,
            ocr_required=parsed.ocr_required,
            warnings=list(parsed.warnings),
        )
        if index_result.warning:
            outcome.warnings.append(index_result.warning)
        if parsed.ocr_required:
            outcome.warnings.append("PDF 没有可提取的文本层，需要 OCR；已按空内容索引")
        return outcome


def _load_outcome(document_id: int, filename: str, *, duplicate: bool) -> UploadOutcome:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT d.file_type, d.page_count, d.parse_status, d.classify_status, "
            "d.classify_confidence, d.ocr_required, d.classify_evidence, co.name, ch.name "
            "FROM documents d "
            "LEFT JOIN courses co ON d.course_id = co.id "
            "LEFT JOIN chapters ch ON d.chapter_id = ch.id "
            "WHERE d.id=%s",
            (document_id,),
        )
        row = cur.fetchone()
        kps = _document_kps(cur, document_id)
        chars = _document_chars(cur, document_id)
        evidence, reason, course_cands, chapter_cands = _parse_evidence(row[6])
    if row is None:
        return UploadOutcome(
            document_id=document_id,
            filename=filename,
            ok=False,
            error="document row missing",
        )
    return UploadOutcome(
        document_id=document_id,
        filename=filename,
        ok=True,
        duplicate=duplicate,
        file_type=str(row[0]),
        page_count=int(row[1]),
        parse_status=str(row[2]),
        classify_status=str(row[3]),
        classify_confidence=float(row[4]),
        classify_reason=reason,
        ocr_required=bool(row[5]),
        course=str(row[7]) if row[7] else None,
        chapter=str(row[8]) if row[8] else None,
        knowledge_points=kps,
        course_candidates=course_cands,
        chapter_candidates=chapter_cands,
        extracted_chars=chars,
        evidence=evidence,
        warnings=["duplicate upload: file already indexed"] if duplicate else [],
    )


def _document_chars(cur, document_id: int) -> int:
    cur.execute(
        "SELECT COALESCE(SUM(CHAR_LENGTH(original_text)),0) FROM document_chunks "
        "WHERE document_id=%s",
        (document_id,),
    )
    row = cur.fetchone()
    return int(row[0]) if row else 0


def _parse_evidence(raw: str | None) -> tuple[dict, str, list[dict], list[dict]]:
    """Parse stored classification evidence.

    Candidates are returned exactly as the classifier persisted them. Rows
    written by classifiers older than v3 have no candidate lists; for those,
    a single candidate is derived from the stored result fields and is
    explicitly marked ``stored_result`` — it is never presented as a freshly
    computed candidate.
    """
    if not raw:
        return {}, "ok", [], []
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 - unparseable stored evidence falls back safely
        return {}, "ok", [], []
    signals = data.get("signals") or {}
    reason = data.get("reason", "ok")
    course_cands = [dict(c) for c in (data.get("course_candidates") or [])]
    chapter_cands = [dict(c) for c in (data.get("chapter_candidates") or [])]
    if not course_cands and data.get("course"):
        course_cands.append(
            {
                "name": data["course"],
                "score": data.get("course_confidence", 0.0),
                "source": "stored_result",
            }
        )
    if not chapter_cands and data.get("chapter"):
        chapter_cands.append(
            {
                "name": data["chapter"],
                "score": data.get("chapter_confidence", 0.0),
                "source": "stored_result",
            }
        )
    if not reason and signals.get("total_chars", 0) < 50:
        reason = "insufficient_text"
    return data, reason, course_cands, chapter_cands


def reclassify_document(
    session_id: str,
    document_id: int,
    provider: EmbeddingProvider | None,
    high_threshold: float,
    mid_threshold: float,
) -> UploadOutcome | None:
    """Re-run the classifier on an already indexed document.

    Pages are rebuilt from the indexed chunks (original text + page numbers);
    the pre-fix classification evidence is snapshotted into
    ``classification_feedback`` before the row is updated, so the original
    upload record and pre-fix state stay auditable.
    """
    from app.services.parsing import ParsedPage, ParseResult

    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT filename, classify_evidence, parse_status FROM documents "
            "WHERE id=%s AND session_id=%s",
            (document_id, session_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        filename, old_evidence, parse_status = str(row[0]), row[1], str(row[2])
        cur.execute(
            "SELECT page_number, original_text FROM document_chunks "
            "WHERE document_id=%s ORDER BY chunk_index",
            (document_id,),
        )
        chunk_rows = cur.fetchall()
        pages_by_no: dict[int, list[str]] = {}
        order: list[int] = []
        for page_no, original in chunk_rows:
            pn = int(page_no)
            if pn not in pages_by_no:
                pages_by_no[pn] = []
                order.append(pn)
            pages_by_no[pn].append(original or "")
        pages = [
            ParsedPage(page_number=pn, text="\n".join(pages_by_no[pn])) for pn in order
        ]
        parse_result = ParseResult(pages=pages)
        decision = classify_document(
            session_id, filename, parse_result, high_threshold, mid_threshold
        )
        new_evidence = json.dumps(decision.evidence, ensure_ascii=False)
        cur.execute(
            "INSERT INTO classification_feedback "
            "(document_id, original_json, corrected_json, user_confirmed) VALUES (%s, %s, %s, 0)",
            (document_id, old_evidence, new_evidence),
        )
        course_id: int | None = None
        chapter_id: int | None = None
        if decision.course and decision.status == "auto":
            course_id = get_or_create_course(
                cur, session_id, decision.course, decision.confidence, "auto"
            )
            if decision.chapter:
                chapter_id = get_or_create_chapter(cur, course_id, decision.chapter)
        cur.execute(
            "UPDATE documents SET course_id=%s, chapter_id=%s, classify_status=%s, "
            "classify_confidence=%s, classify_evidence=%s, updated_at=NOW() WHERE id=%s",
            (
                course_id,
                chapter_id,
                decision.status,
                decision.confidence,
                new_evidence,
                document_id,
            ),
        )
        cur.execute(
            "UPDATE document_chunks SET course_id=%s, chapter_id=%s WHERE document_id=%s",
            (course_id, chapter_id, document_id),
        )
        cur.execute(
            "DELETE FROM document_knowledge_links WHERE document_id=%s", (document_id,)
        )
        if course_id is not None:
            for kp_name in decision.knowledge_points:
                kp_id = get_or_create_kp(cur, course_id, chapter_id, kp_name)
                slides = decision.kp_evidence.get(kp_name, [])
                cur.execute(
                    "INSERT INTO document_knowledge_links "
                    "(document_id, knowledge_point_id, slide_numbers) VALUES (%s, %s, %s)",
                    (document_id, kp_id, json.dumps(slides) if slides else None),
                )
        chars = _document_chars(cur, document_id)
    return UploadOutcome(
        document_id=document_id,
        filename=filename,
        ok=True,
        file_type=Path(filename).suffix.lstrip("."),
        page_count=len(pages),
        parse_status=parse_status,
        classify_status=decision.status,
        classify_confidence=decision.confidence,
        classify_reason=decision.reason,
        course=decision.course,
        chapter=decision.chapter,
        knowledge_points=decision.knowledge_points,
        course_candidates=decision.course_candidates,
        chapter_candidates=decision.chapter_candidates,
        kp_evidence=decision.kp_evidence,
        extracted_chars=chars,
        evidence=decision.evidence,
    )


def _document_kps(cur, document_id: int) -> list[str]:
    cur.execute(
        "SELECT kp.name FROM document_knowledge_links l "
        "JOIN knowledge_points kp ON l.knowledge_point_id = kp.id "
        "WHERE l.document_id=%s ORDER BY kp.id",
        (document_id,),
    )
    return [str(row[0]) for row in cur.fetchall()]


def apply_classification(
    session_id: str,
    document_id: int,
    course_name: str,
    chapter_name: str | None,
    knowledge_points: list[str],
    *,
    source: str,  # "confirm" (accepted suggestion) | "correct" (user correction)
) -> dict:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT classify_evidence FROM documents WHERE id=%s AND session_id=%s",
            (document_id, session_id),
        )
        row = cur.fetchone()
        if not row:
            return {"document_id": document_id, "status": "not_found"}
        original_evidence = row[0]
        course_id = get_or_create_course(cur, session_id, course_name, 1.0, "confirmed")
        chapter_id = (
            get_or_create_chapter(cur, course_id, chapter_name)
            if chapter_name
            else None
        )
        kp_ids = [
            get_or_create_kp(cur, course_id, chapter_id, name)
            for name in knowledge_points
        ]
        cur.execute(
            "UPDATE documents SET course_id=%s, chapter_id=%s, classify_status='confirmed', "
            "classify_confidence=1.0, updated_at=NOW() WHERE id=%s",
            (course_id, chapter_id, document_id),
        )
        cur.execute(
            "UPDATE document_chunks SET course_id=%s, chapter_id=%s WHERE document_id=%s",
            (course_id, chapter_id, document_id),
        )
        for kp_id in kp_ids:
            cur.execute(
                "INSERT IGNORE INTO document_knowledge_links (document_id, knowledge_point_id) "
                "VALUES (%s, %s)",
                (document_id, kp_id),
            )
        corrected_json = json.dumps(
            {
                "course": course_name,
                "chapter": chapter_name,
                "knowledge_points": knowledge_points,
            },
            ensure_ascii=False,
        )
        cur.execute(
            "INSERT INTO classification_feedback "
            "(document_id, original_json, corrected_json, user_confirmed) VALUES (%s, %s, %s, %s)",
            (
                document_id,
                original_evidence,
                corrected_json,
                1 if source == "confirm" else 0,
            ),
        )
    return {
        "document_id": document_id,
        "status": "confirmed",
        "course": course_name,
        "chapter": chapter_name,
        "knowledge_points": knowledge_points,
    }


def list_documents(session_id: str) -> list[dict]:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT d.id, d.filename, d.file_type, d.page_count, d.parse_status, "
            "d.classify_status, d.classify_confidence, d.ocr_required, "
            "d.classify_evidence, co.name, ch.name, d.created_at "
            "FROM documents d "
            "LEFT JOIN courses co ON d.course_id = co.id "
            "LEFT JOIN chapters ch ON d.chapter_id = ch.id "
            "WHERE d.session_id=%s ORDER BY d.id DESC",
            (session_id,),
        )
        rows = cur.fetchall()
        result = []
        for row in rows:
            doc_id = int(row[0])
            evidence, reason, course_cands, chapter_cands = _parse_evidence(row[8])
            result.append(
                {
                    "id": doc_id,
                    "filename": str(row[1]),
                    "file_type": str(row[2]),
                    "page_count": int(row[3]),
                    "parse_status": str(row[4]),
                    "classify_status": str(row[5]),
                    "classify_confidence": float(row[6]),
                    "classify_reason": reason,
                    "ocr_required": bool(row[7]),
                    "course": str(row[9]) if row[9] else None,
                    "chapter": str(row[10]) if row[10] else None,
                    "knowledge_points": _document_kps(cur, doc_id),
                    "course_candidates": course_cands,
                    "chapter_candidates": chapter_cands,
                    "evidence_course": evidence.get("course"),
                    "evidence_chapter": evidence.get("chapter"),
                    "evidence_knowledge_points": evidence.get("knowledge_points") or [],
                    "extracted_chars": _document_chars(cur, doc_id),
                    "evidence": evidence,
                    "created_at": row[11],
                }
            )
    return result
