"""ExamPilot FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.core.config import get_settings
from app.core.ratelimit import RateLimitMiddleware
from app.core.seekdb import SeekDBUnavailableError, configure, get_engine
from app.models.schema import create_all_tables

log = logging.getLogger("exampilot.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine_started = False
    if settings.seekdb_path:
        try:
            configure(str(settings.seekdb_dir))
            create_all_tables()
            engine_started = True
            log.info("seekdb engine ready at %s", settings.seekdb_dir)
        except Exception as exc:  # pragma: no cover - environment dependent  # noqa: BLE001
            log.error("seekdb startup failed: %s", exc)
    else:
        log.warning("EXAMPILOT_SEEKDB_PATH is not set; data endpoints will return 503")
    yield
    if engine_started:
        try:
            get_engine().close()
        except Exception:  # pragma: no cover - best-effort engine shutdown  # noqa: S110, BLE001
            pass


app = FastAPI(
    title="ExamPilot API",
    description="AI 个性化考试教练后端（seekdb + PowerContext）",
    version=__version__,
    lifespan=lifespan,
)

# CORSMiddleware must be added LAST (outermost): rate-limit 429 and oversized
# body 413 responses must pass back through it so browsers can read the error.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(SeekDBUnavailableError)
async def _seekdb_unavailable(
    request: Request, exc: SeekDBUnavailableError
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def _value_error(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/")
def root() -> dict:
    return {
        "service": "exampilot-backend",
        "version": __version__,
        "docs": "/docs",
        "health": "/api/health",
    }


from app.api import (
    ai,
    documents,
    health,
    knowledge,
    memories,
    mistakes,
    practice,
    preferences,
    review,
    search,
    sessions,
)

for module in (
    health,
    sessions,
    documents,
    knowledge,
    search,
    ai,
    practice,
    mistakes,
    review,
    memories,
    preferences,
):
    app.include_router(module.router)
