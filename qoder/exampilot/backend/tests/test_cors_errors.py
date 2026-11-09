"""Regression: rate-limit (429) and oversized-body (413) responses must carry
CORS headers so browsers on an allowed origin can read the error status.

app/main.py adds CORSMiddleware LAST (outermost), wrapping RateLimitMiddleware;
if that order is ever flipped the error responses bypass CORS and the browser
only sees a network error. The structural test pins the order in the real app.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.ratelimit import RateLimitMiddleware

ALLOWED = "https://exampilot-ptp2z0mif2r.qoder.zone"
EVIL = "https://evil.example"


def _make_app() -> FastAPI:
    app = FastAPI()
    # Same order as app/main.py: rate limiter first (inner), CORS last (outer).
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ALLOWED],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/api/sessions")
    def _create() -> dict:
        return {"ok": True}

    return app


class TestMainAppMiddlewareOrder:
    def test_cors_wraps_rate_limiter_in_real_app(self):
        from app.main import app

        stack = [mw.cls for mw in app.user_middleware]
        assert stack[0] is CORSMiddleware, "CORS must be the outermost middleware"
        assert RateLimitMiddleware in stack
        assert stack.index(CORSMiddleware) < stack.index(RateLimitMiddleware)


class TestCorsOnErrorResponses:
    def test_429_rate_limited_has_cors_headers(self, monkeypatch):
        monkeypatch.setenv("EXAMPILOT_RATE_LIMIT_PER_MINUTE_CREATE_IDENTITY", "2")
        get_settings.cache_clear()
        try:
            client = TestClient(_make_app())
            for _ in range(2):
                response = client.post("/api/sessions", headers={"Origin": ALLOWED})
                assert response.status_code == 200
            response = client.post("/api/sessions", headers={"Origin": ALLOWED})
            assert response.status_code == 429
            assert response.headers["access-control-allow-origin"] == ALLOWED
            assert response.headers["retry-after"] == "60"
        finally:
            get_settings.cache_clear()

    def test_413_oversized_body_has_cors_headers(self, monkeypatch):
        monkeypatch.setenv("EXAMPILOT_MAX_JSON_BODY_BYTES", "100")
        get_settings.cache_clear()
        try:
            client = TestClient(_make_app())
            response = client.post(
                "/api/sessions",
                headers={"Origin": ALLOWED},
                json={"pad": "x" * 200},
            )
            assert response.status_code == 413
            assert response.headers["access-control-allow-origin"] == ALLOWED
        finally:
            get_settings.cache_clear()

    def test_allowed_origin_preflight_still_passes(self):
        client = TestClient(_make_app())
        response = client.options(
            "/api/sessions",
            headers={
                "Origin": ALLOWED,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == ALLOWED

    def test_disallowed_origin_preflight_rejected(self):
        client = TestClient(_make_app())
        response = client.options(
            "/api/sessions",
            headers={
                "Origin": EVIL,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    def test_disallowed_origin_response_has_no_cors_headers(self):
        client = TestClient(_make_app())
        response = client.post("/api/sessions", headers={"Origin": EVIL})
        # Request still executes (rate limiter must not be bypassed), but the
        # browser cannot read the response without CORS headers.
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers

    def test_allowed_origin_normal_response_has_cors_headers(self):
        client = TestClient(_make_app())
        response = client.post("/api/sessions", headers={"Origin": ALLOWED})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == ALLOWED
