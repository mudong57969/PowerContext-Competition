"""In-memory sliding-window rate limiting and JSON body size guard.

Self-contained middleware (no third-party dependency). Two layers:

- one global bucket caps total requests per minute regardless of caller;
- per-route buckets cap each protected route per client per minute.

Client identity: by default only the socket peer address
(``request.client.host``) is used. ``X-Forwarded-For`` is honored only when
``rate_limit_trust_proxy_headers`` is explicitly enabled (i.e. the backend
sits behind a proxy the operator controls); the RFC 7239 ``Forwarded``
header is deliberately never read. The ASGI server must therefore run with
proxy-header parsing disabled (uvicorn: ``--no-proxy-headers``), otherwise
the server itself rewrites ``scope["client"]`` from the spoofable
``X-Forwarded-For`` before this middleware ever sees the request. Behind
Tailscale Funnel every request arrives from the local tailscaled daemon
(127.0.0.1), so with the default (untrusting) policy all public clients
share the same buckets — a conservative, spoof-proof ceiling. The global
bucket additionally caps total traffic no matter what client key is
derived.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import get_settings

WINDOW_SECONDS = 60.0
MAX_TRACKED_KEYS = 1000

_ROUTE_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("POST", re.compile(r"^/api/sessions$"), "create_identity"),
    ("POST", re.compile(r"^/api/sessions/[^/]+/documents$"), "upload"),
    ("POST", re.compile(r"^/api/sessions/[^/]+/search$"), "search"),
    ("POST", re.compile(r"^/api/sessions/[^/]+/explain$"), "explain"),
    ("POST", re.compile(r"^/api/sessions/[^/]+/practice/start$"), "practice"),
    ("POST", re.compile(r"^/api/sessions/[^/]+/mistakes/practice$"), "practice"),
    ("POST", re.compile(r"^/api/practice/\d+/submit$"), "practice"),
    ("POST", re.compile(r"^/api/sessions/[^/]+/memories$"), "memories"),
]


def _route_name(method: str, path: str) -> str | None:
    for route_method, pattern, name in _ROUTE_PATTERNS:
        if method == route_method and pattern.match(path):
            return name
    return None


class SlidingWindow:
    """Thread-safe hit counter over a fixed trailing time window."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._prune(now)
            if len(self._hits) >= self.limit:
                return False
            self._hits.append(now)
            return True

    def is_idle(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._prune(now)
            return not self._hits

    def _prune(self, now: float) -> None:
        cutoff = now - WINDOW_SECONDS
        while self._hits and self._hits[0] <= cutoff:
            self._hits.popleft()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._settings = get_settings()
        self._buckets: dict[str, SlidingWindow] = {}
        self._lock = threading.Lock()

    def _bucket(self, key: str, limit: int) -> SlidingWindow:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = SlidingWindow(limit)
                self._buckets[key] = bucket
                if len(self._buckets) > MAX_TRACKED_KEYS:
                    for stale, window in list(self._buckets.items()):
                        if window.is_idle():
                            del self._buckets[stale]
            return bucket

    @staticmethod
    def _client_key(request: Request, trust_proxy_headers: bool) -> str:
        # The Forwarded (RFC 7239) header is deliberately never read: it is
        # fully client-controlled. X-Forwarded-For is honored only when the
        # operator explicitly trusts a proxy in front of this app; otherwise
        # the socket peer is the only spoof-proof client identity.
        if trust_proxy_headers:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
        host = getattr(request.client, "host", None) if request.client else None
        return host or "unknown"

    @staticmethod
    def _rate_limited(limit: int) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"detail": f"rate limit exceeded: max {limit} requests per minute"},
            headers={"Retry-After": str(int(WINDOW_SECONDS))},
        )

    async def dispatch(self, request: Request, call_next):
        settings = self._settings
        if request.method == "OPTIONS":
            return await call_next(request)
        name = _route_name(request.method, request.url.path)
        if settings.rate_limit_enabled:
            global_limit = settings.rate_limit_per_minute_global
            if not self._bucket("__all__", global_limit).allow():
                return self._rate_limited(global_limit)
            if name is not None:
                route_limit = getattr(settings, f"rate_limit_per_minute_{name}")
                key = f"{name}:{self._client_key(request, settings.rate_limit_trust_proxy_headers)}"
                if not self._bucket(key, route_limit).allow():
                    return self._rate_limited(route_limit)
        if request.method in ("POST", "PUT", "PATCH") and name != "upload":
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    size = int(content_length)
                except ValueError:  # malformed header: let the endpoint decide
                    size = 0
                if size > settings.max_json_body_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": (
                                "request body too large "
                                f"(max {settings.max_json_body_bytes} bytes)"
                            )
                        },
                    )
        return await call_next(request)
