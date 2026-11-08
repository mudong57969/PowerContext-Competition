"""Shared singletons and helpers for API routes."""

from __future__ import annotations

import hashlib
import json
import secrets
from functools import lru_cache

from fastapi import Header, HTTPException

from app.core.config import get_settings
from app.core.seekdb import get_engine
from app.memory.powercontext import MemoryService, MemoryUnavailableError
from app.retrieval.embeddings import EmbeddingProvider
from app.services.llm import LLMProvider

TOKEN_BYTES = 32  # 256-bit random bearer token


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    return EmbeddingProvider(get_settings())


@lru_cache
def get_memory_service() -> MemoryService:
    return MemoryService(get_settings())


@lru_cache
def get_llm_provider() -> LLMProvider:
    return LLMProvider(get_settings())


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="unauthorized: missing or invalid bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def authenticate(authorization: str | None) -> str:
    """Validate the bearer token and return the authenticated session id.

    Only the token digest is stored server-side; the full token is never
    logged or persisted. Missing, malformed or unknown tokens all get the
    same 401 (no session-existence oracle).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized()
    token = authorization[len("Bearer ") :].strip()
    if not token:
        raise _unauthorized()
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT session_id FROM identities WHERE token_digest=%s",
            (hash_token(token),),
        )
        row = cur.fetchone()
        if row is None:
            raise _unauthorized()
        cur.execute(
            "UPDATE identities SET last_used_at=NOW() WHERE session_id=%s",
            (str(row[0]),),
        )
    return str(row[0])


def require_owned_session(identity_session_id: str, session_id: str) -> None:
    """Default-deny: a valid token only unlocks its own session's data."""
    if identity_session_id != session_id:
        raise HTTPException(
            status_code=403, detail="forbidden: session not owned by this identity"
        )


def require_session(
    session_id: str, authorization: str | None = Header(default=None)
) -> None:
    """Authenticate the caller and verify the URL session id is owned by it.

    When invoked directly from inside another endpoint (not via FastAPI
    dependency injection), ``authorization`` is the ``Header`` sentinel
    object rather than the parsed string — treat that as a missing header.
    """
    if not isinstance(authorization, str):
        authorization = None
    require_owned_session(authenticate(authorization), session_id)


def session_scope_id(session_id: str) -> str | None:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT scope_id FROM demo_sessions WHERE id=%s", (session_id,))
        row = cur.fetchone()
        return str(row[0]) if row and row[0] else None


def record_memory_event(
    session_id: str,
    scope_id: str | None,
    kind: str,
    summary: str,
    status: str,
    reference: str | None,
) -> None:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO memory_events (session_id, scope_id, kind, summary, "
            "memory_reference, status) VALUES (%s, %s, %s, %s, %s, %s)",
            (session_id, scope_id or "", kind, summary, reference, status),
        )


def remember_for_session(session_id: str, kind: str, text: str) -> dict:
    """Write one memory entry for the session's scope and audit it locally."""
    scope_id = session_scope_id(session_id)
    if not scope_id:
        warning = "session has no PowerContext scope"
        record_memory_event(session_id, None, kind, text, "failed", None)
        return {"ok": False, "warning": warning}
    try:
        reference = get_memory_service().remember(scope_id, kind, text)
    except MemoryUnavailableError as exc:
        record_memory_event(session_id, scope_id, kind, text, "failed", None)
        return {"ok": False, "warning": str(exc)}
    reference_json = json.dumps(reference, ensure_ascii=False) if reference else None
    record_memory_event(session_id, scope_id, kind, text, "ok", reference_json)
    return {"ok": True, "reference": reference}
