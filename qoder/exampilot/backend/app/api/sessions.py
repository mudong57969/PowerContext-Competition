"""Session endpoints (session = one student's study space).

Auth model: creating a session also creates an anonymous learning identity
and returns a 256-bit bearer token exactly once. Only the token digest is
stored. Every data endpoint authenticates via ``Authorization: Bearer`` and
defaults to deny; the session id in a URL never acts as a credential.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header

from app.api.deps import (
    authenticate,
    generate_token,
    get_memory_service,
    hash_token,
    require_owned_session,
)
from app.api.schemas import SessionCreate, SessionCreatedOut, SessionOut
from app.core.seekdb import get_engine
from app.memory.powercontext import MemoryUnavailableError

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _session_stats(session_id: str) -> dict:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM documents WHERE session_id=%s", (session_id,))
        documents = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM questions WHERE session_id=%s", (session_id,))
        questions = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM courses WHERE session_id=%s", (session_id,))
        courses = int(cur.fetchone()[0])
        cur.execute(
            "SELECT COUNT(*) FROM attempts a "
            "JOIN practice_sessions ps ON a.practice_session_id = ps.id "
            "WHERE ps.session_id=%s",
            (session_id,),
        )
        attempts = int(cur.fetchone()[0])
        cur.execute(
            "SELECT AVG(mastery_score), COUNT(*) FROM knowledge_mastery WHERE session_id=%s",
            (session_id,),
        )
        row = cur.fetchone()
    return {
        "documents": documents,
        "questions": questions,
        "courses": courses,
        "attempts": attempts,
        "mastered_knowledge_points": int(row[1]),
        "average_mastery": round(float(row[0]), 3)
        if row and row[0] is not None
        else 0.0,
    }


def _row_to_session(row: tuple) -> SessionOut:
    session_id = str(row[0])
    return SessionOut(
        id=session_id,
        name=str(row[1]),
        created_at=row[2],
        stats=_session_stats(session_id),
    )


def _session_out(session_id: str) -> SessionOut:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, created_at FROM demo_sessions WHERE id=%s", (session_id,)
        )
        row = cur.fetchone()
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="session not found")
    return _row_to_session(row)


@router.post("", response_model=SessionCreatedOut)
def create_session(body: SessionCreate) -> SessionCreatedOut:
    session_id = uuid.uuid4().hex[:16]
    token = generate_token()
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO demo_sessions (id, name) VALUES (%s, %s)",
            (session_id, body.name),
        )
        cur.execute(
            "INSERT INTO identities (session_id, token_digest) VALUES (%s, %s)",
            (session_id, hash_token(token)),
        )
    scope_id: str | None = None
    memory_warning: str | None = None
    try:
        scope_id = get_memory_service().ensure_scope(
            session_id,
            f"ExamPilot 会话 {body.name or session_id}",
            f"学习会话「{body.name or session_id}」的课程资料、练习表现与长期记忆",
        )
        with eng.connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE demo_sessions SET scope_id=%s WHERE id=%s",
                (scope_id, session_id),
            )
    except MemoryUnavailableError as exc:
        memory_warning = str(exc)
    session = _session_out(session_id)
    session.memory_warning = memory_warning
    return SessionCreatedOut(session=session, token=token)


@router.get("/me", response_model=SessionOut)
def current_session(authorization: str | None = Header(default=None)) -> SessionOut:
    """Return only the authenticated identity's own session (no scope id)."""
    return _session_out(authenticate(authorization))


@router.get("/{session_id}", response_model=SessionOut)
def get_session(
    session_id: str, authorization: str | None = Header(default=None)
) -> SessionOut:
    identity_session = authenticate(authorization)
    require_owned_session(identity_session, session_id)
    return _session_out(session_id)
