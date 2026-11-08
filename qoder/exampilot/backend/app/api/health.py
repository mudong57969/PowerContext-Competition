"""Health and capability status endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.api.deps import get_embedding_provider, get_llm_provider, get_memory_service
from app.api.schemas import HealthResponse
from app.core.config import get_settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    seekdb_status: dict = {
        "configured": bool(settings.seekdb_path),
        "ok": False,
        "database": None,
    }
    if settings.seekdb_path:
        try:
            from app.core.seekdb import get_engine

            eng = get_engine()
            with eng.connect() as conn:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                seekdb_status["ok"] = True
                seekdb_status["database"] = eng.database
        except Exception as exc:  # noqa: BLE001 - probe reports engine errors
            seekdb_status["error"] = str(exc)
    memory_service = get_memory_service()
    memory_status = {
        "enabled": memory_service.enabled,
        "base_url": settings.powercontext_base_url,
        "reachable": memory_service.ping() if memory_service.enabled else False,
    }
    provider = get_embedding_provider()
    embedding_status = {
        "provider": settings.embedding_provider,
        "enabled": provider.enabled,
        "model": settings.embedding_model
        if settings.embedding_provider == "local"
        else settings.embedding_openai_model,
        "dimension": settings.embedding_dimension,
    }
    llm_provider = get_llm_provider()
    llm_status = {
        "provider": settings.llm_provider,
        "enabled": llm_provider.enabled,
        "model": settings.llm_model or None,
    }
    status = (
        "ok" if (seekdb_status["ok"] and seekdb_status["configured"]) else "degraded"
    )
    return HealthResponse(
        status=status,
        version=__version__,
        seekdb=seekdb_status,
        memory=memory_status,
        embedding=embedding_status,
        llm=llm_status,
    )
