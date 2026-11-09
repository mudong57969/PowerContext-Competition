"""Document upload, listing and classification confirmation endpoints."""

from __future__ import annotations

import threading
from typing import Annotated

from fastapi import APIRouter, File, Header, HTTPException, UploadFile

from app.api.deps import (
    authenticate,
    get_embedding_provider,
    require_owned_session,
    require_session,
)
from app.api.schemas import (
    ConfirmClassificationRequest,
    DocumentOut,
    UploadResponse,
)
from app.core.config import get_settings
from app.core.seekdb import get_engine
from app.services.documents import (
    apply_classification,
    list_documents,
    process_upload,
    reclassify_document,
)

router = APIRouter(prefix="/api", tags=["documents"])

_upload_slots: threading.BoundedSemaphore | None = None
_upload_slots_lock = threading.Lock()


def _upload_semaphore() -> threading.BoundedSemaphore:
    global _upload_slots
    if _upload_slots is None:
        with _upload_slots_lock:
            if _upload_slots is None:
                _upload_slots = threading.BoundedSemaphore(
                    get_settings().max_concurrent_uploads
                )
    return _upload_slots


def _document_session(document_id: int) -> str:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT session_id FROM documents WHERE id=%s", (document_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"document not found: {document_id}"
        )
    return str(row[0])


def _to_out(o) -> DocumentOut:
    return DocumentOut(
        id=o.document_id,
        filename=o.filename,
        ok=o.ok,
        error=o.error,
        duplicate=o.duplicate,
        file_type=o.file_type,
        page_count=o.page_count,
        parse_status=o.parse_status,
        classify_status=o.classify_status,
        classify_confidence=o.classify_confidence,
        classify_reason=getattr(o, "classify_reason", "ok"),
        course=o.course,
        chapter=o.chapter,
        knowledge_points=o.knowledge_points,
        course_candidates=getattr(o, "course_candidates", []),
        chapter_candidates=getattr(o, "chapter_candidates", []),
        kp_evidence=getattr(o, "kp_evidence", {}),
        extracted_chars=getattr(o, "extracted_chars", 0),
        ocr_required=o.ocr_required,
        warnings=o.warnings,
    )


@router.post("/sessions/{session_id}/documents", response_model=UploadResponse)
def upload_documents(
    session_id: str,
    files: Annotated[list[UploadFile], File(...)],
    authorization: str | None = Header(default=None),
) -> UploadResponse:
    require_session(session_id, authorization)
    # FastAPI spools multipart parts to temp files before this endpoint runs,
    # so oversized bodies briefly use disk; the per-minute upload rate limit
    # caps that exposure.
    settings = get_settings()
    if len(files) > settings.max_upload_files:
        raise HTTPException(
            status_code=413,
            detail=(f"too many files in one upload (max {settings.max_upload_files})"),
        )
    if not _upload_semaphore().acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="too many concurrent uploads; please retry shortly",
        )
    try:
        provider = get_embedding_provider()
        results: list[DocumentOut] = []
        total_bytes = 0
        for file in files:
            filename = file.filename or "unnamed"
            data = file.file.read(settings.max_file_bytes + 1)
            total_bytes += len(data)
            if total_bytes > settings.max_upload_total_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        "upload total too large "
                        f"(max {settings.max_upload_total_bytes // (1024 * 1024)} "
                        "MB per request)"
                    ),
                )
            if len(data) > settings.max_file_bytes:
                results.append(
                    DocumentOut(
                        filename=filename,
                        ok=False,
                        error=(
                            "file too large "
                            f"(max {settings.max_file_bytes // (1024 * 1024)} MB)"
                        ),
                    )
                )
                continue
            outcome = process_upload(
                session_id,
                filename,
                data,
                provider,
                settings.classify_high_confidence,
                settings.classify_mid_confidence,
            )
            results.append(_to_out(outcome))
        return UploadResponse(session_id=session_id, results=results)
    finally:
        _upload_semaphore().release()


@router.get("/sessions/{session_id}/documents", response_model=list[DocumentOut])
def get_documents(
    session_id: str, authorization: str | None = Header(default=None)
) -> list[DocumentOut]:
    require_session(session_id, authorization)
    return [
        DocumentOut(
            id=doc["id"],
            filename=doc["filename"],
            file_type=doc["file_type"],
            page_count=doc["page_count"],
            parse_status=doc["parse_status"],
            classify_status=doc["classify_status"],
            classify_confidence=doc["classify_confidence"],
            classify_reason=doc["classify_reason"],
            ocr_required=doc["ocr_required"],
            course=doc["course"],
            chapter=doc["chapter"],
            knowledge_points=doc["knowledge_points"],
            course_candidates=doc["course_candidates"],
            chapter_candidates=doc["chapter_candidates"],
            evidence_course=doc["evidence_course"],
            evidence_chapter=doc["evidence_chapter"],
            evidence_knowledge_points=doc["evidence_knowledge_points"],
            extracted_chars=doc["extracted_chars"],
        )
        for doc in list_documents(session_id)
    ]


@router.post("/documents/{document_id}/reclassify", response_model=DocumentOut)
def reclassify(
    document_id: int, authorization: str | None = Header(default=None)
) -> DocumentOut:
    identity_session = authenticate(authorization)
    session_id = _document_session(document_id)
    require_owned_session(identity_session, session_id)
    settings = get_settings()
    outcome = reclassify_document(
        session_id,
        document_id,
        get_embedding_provider(),
        settings.classify_high_confidence,
        settings.classify_mid_confidence,
    )
    if outcome is None:
        raise HTTPException(
            status_code=404, detail=f"document not found: {document_id}"
        )
    return _to_out(outcome)


@router.post("/documents/{document_id}/confirm")
def confirm_document(
    document_id: int,
    body: ConfirmClassificationRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    identity_session = authenticate(authorization)
    session_id = _document_session(document_id)
    require_owned_session(identity_session, session_id)
    return apply_classification(
        session_id,
        document_id,
        body.course,
        body.chapter,
        body.knowledge_points,
        source="confirm",
    )


@router.post("/documents/{document_id}/correct")
def correct_document(
    document_id: int,
    body: ConfirmClassificationRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    identity_session = authenticate(authorization)
    session_id = _document_session(document_id)
    require_owned_session(identity_session, session_id)
    return apply_classification(
        session_id,
        document_id,
        body.course,
        body.chapter,
        body.knowledge_points,
        source="correct",
    )
