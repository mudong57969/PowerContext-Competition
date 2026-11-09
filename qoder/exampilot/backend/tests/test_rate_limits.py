"""Unit + integration tests for the sliding-window rate limiter middleware."""

from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.ratelimit import (
    RateLimitMiddleware,
    SlidingWindow,
    _route_name,
)

NOW = 1000.0


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.post("/api/sessions")
    def _create() -> dict:
        return {"ok": True}

    @app.post("/api/sessions/x/search")
    def _search() -> dict:
        return {"ok": True}

    @app.get("/api/other")
    def _other() -> dict:
        return {"ok": True}

    return app


def _make_client() -> TestClient:
    return TestClient(_make_app())


class _SyncASGITransport(httpx.BaseTransport):
    """httpx 0.28's ASGITransport is async-only; adapt it for sync clients."""

    def __init__(self, app: FastAPI, host: str) -> None:
        self._transport = httpx.ASGITransport(app=app, client=(host, 12345))

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        async def _run() -> httpx.Response:
            response = await self._transport.handle_async_request(request)
            await response.aread()
            return httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=response.content,
                request=request,
            )

        return asyncio.run(_run())


def _make_client_from(host: str) -> httpx.Client:
    return httpx.Client(
        transport=_SyncASGITransport(_make_app(), host),
        base_url="http://testserver",
    )


class TestSlidingWindow:
    def test_allows_up_to_limit_then_blocks(self):
        window = SlidingWindow(3)
        assert [window.allow(now=NOW + i) for i in range(3)] == [
            True,
            True,
            True,
        ]
        assert window.allow(now=NOW + 3.5) is False

    def test_window_slides_and_recovers(self):
        window = SlidingWindow(2)
        assert window.allow(now=NOW) is True
        assert window.allow(now=NOW + 1.0) is True
        assert window.allow(now=NOW + 20.0) is False
        # 61s later the first hit has fallen out of the window.
        assert window.allow(now=NOW + 61.0) is True

    def test_is_idle_after_window_elapses(self):
        window = SlidingWindow(2)
        window.allow(now=NOW)
        assert window.is_idle(now=NOW) is False
        assert window.is_idle(now=NOW + 61.0) is True


class TestRouteNames:
    def test_known_routes(self):
        assert _route_name("POST", "/api/sessions") == "create_identity"
        assert _route_name("POST", "/api/sessions/abc123/documents") == "upload"
        assert _route_name("POST", "/api/sessions/abc123/search") == "search"
        assert _route_name("POST", "/api/sessions/abc123/explain") == "explain"
        assert _route_name("POST", "/api/sessions/abc123/practice/start") == "practice"
        assert (
            _route_name("POST", "/api/sessions/abc123/mistakes/practice") == "practice"
        )
        assert _route_name("POST", "/api/practice/42/submit") == "practice"
        assert _route_name("POST", "/api/sessions/abc123/memories") == "memories"

    def test_unmatched_routes_are_not_rate_limited(self):
        assert _route_name("GET", "/api/sessions/abc123") is None
        assert _route_name("POST", "/api/sessions/") is None
        assert _route_name("POST", "/api/health") is None
        assert _route_name("POST", "/api/sessions/abc123/documents/extra") is None


class TestMiddlewareIntegration:
    def test_route_limit_returns_429_with_retry_after(self, monkeypatch):
        monkeypatch.setenv("EXAMPILOT_RATE_LIMIT_PER_MINUTE_CREATE_IDENTITY", "3")
        get_settings.cache_clear()
        try:
            client = _make_client()
            for _ in range(3):
                assert client.post("/api/sessions").status_code == 200
            response = client.post("/api/sessions")
            assert response.status_code == 429
            assert response.headers["retry-after"] == "60"
            assert "max 3" in response.json()["detail"]
        finally:
            get_settings.cache_clear()

    def test_global_limit_applies_to_all_routes(self, monkeypatch):
        monkeypatch.setenv("EXAMPILOT_RATE_LIMIT_PER_MINUTE_GLOBAL", "2")
        get_settings.cache_clear()
        try:
            client = _make_client()
            assert client.post("/api/sessions").status_code == 200
            assert client.get("/api/other").status_code == 200
            response = client.post("/api/sessions/x/search")
            assert response.status_code == 429
            assert "max 2" in response.json()["detail"]
        finally:
            get_settings.cache_clear()

    def test_rate_limiting_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("EXAMPILOT_RATE_LIMIT_ENABLED", "false")
        monkeypatch.setenv("EXAMPILOT_RATE_LIMIT_PER_MINUTE_GLOBAL", "1")
        get_settings.cache_clear()
        try:
            client = _make_client()
            assert client.post("/api/sessions").status_code == 200
            assert client.post("/api/sessions").status_code == 200
        finally:
            get_settings.cache_clear()

    def test_large_json_body_rejected_with_413(self, monkeypatch):
        monkeypatch.setenv("EXAMPILOT_MAX_JSON_BODY_BYTES", "100")
        get_settings.cache_clear()
        try:
            client = _make_client()
            response = client.post("/api/sessions", json={"pad": "x" * 200})
            assert response.status_code == 413
            assert "too large" in response.json()["detail"]
        finally:
            get_settings.cache_clear()

    def test_small_json_body_passes(self, monkeypatch):
        monkeypatch.setenv("EXAMPILOT_MAX_JSON_BODY_BYTES", "100")
        get_settings.cache_clear()
        try:
            client = _make_client()
            response = client.post("/api/sessions", json={"pad": "x" * 20})
            assert response.status_code == 200
        finally:
            get_settings.cache_clear()


class TestProxyHeaderSpoofing:
    def test_rotating_xff_cannot_bypass_route_limit(self, monkeypatch):
        monkeypatch.setenv("EXAMPILOT_RATE_LIMIT_PER_MINUTE_CREATE_IDENTITY", "3")
        get_settings.cache_clear()
        try:
            client = _make_client_from("203.0.113.7")
            for i in range(3):
                response = client.post(
                    "/api/sessions",
                    headers={"X-Forwarded-For": f"198.51.100.{i + 1}"},
                )
                assert response.status_code == 200
            response = client.post(
                "/api/sessions",
                headers={"X-Forwarded-For": "198.51.100.99"},
            )
            assert response.status_code == 429
        finally:
            get_settings.cache_clear()

    def test_forwarded_header_ignored_even_when_trusted(self, monkeypatch):
        monkeypatch.setenv("EXAMPILOT_RATE_LIMIT_PER_MINUTE_CREATE_IDENTITY", "2")
        monkeypatch.setenv("EXAMPILOT_RATE_LIMIT_TRUST_PROXY_HEADERS", "true")
        get_settings.cache_clear()
        try:
            client = _make_client_from("203.0.113.7")
            assert (
                client.post(
                    "/api/sessions", headers={"Forwarded": "for=192.0.2.1"}
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/api/sessions", headers={"Forwarded": "for=192.0.2.2"}
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/api/sessions", headers={"Forwarded": "for=192.0.2.3"}
                ).status_code
                == 429
            )
        finally:
            get_settings.cache_clear()

    def test_trusted_mode_gives_each_xff_its_own_bucket(self, monkeypatch):
        monkeypatch.setenv("EXAMPILOT_RATE_LIMIT_PER_MINUTE_CREATE_IDENTITY", "2")
        monkeypatch.setenv("EXAMPILOT_RATE_LIMIT_TRUST_PROXY_HEADERS", "true")
        get_settings.cache_clear()
        try:
            client = _make_client_from("203.0.113.7")
            for _ in range(2):
                assert (
                    client.post(
                        "/api/sessions", headers={"X-Forwarded-For": "198.51.100.1"}
                    ).status_code
                    == 200
                )
            assert (
                client.post(
                    "/api/sessions", headers={"X-Forwarded-For": "198.51.100.1"}
                ).status_code
                == 429
            )
            # A different XFF value is a different client in trusted mode.
            assert (
                client.post(
                    "/api/sessions", headers={"X-Forwarded-For": "198.51.100.2"}
                ).status_code
                == 200
            )
            # Only the first entry of a comma-separated chain is used.
            assert (
                client.post(
                    "/api/sessions",
                    headers={"X-Forwarded-For": "198.51.100.1, 10.0.0.9"},
                ).status_code
                == 429
            )
        finally:
            get_settings.cache_clear()

    def test_trusted_mode_falls_back_to_socket_peer_without_xff(self, monkeypatch):
        monkeypatch.setenv("EXAMPILOT_RATE_LIMIT_PER_MINUTE_CREATE_IDENTITY", "1")
        monkeypatch.setenv("EXAMPILOT_RATE_LIMIT_TRUST_PROXY_HEADERS", "true")
        get_settings.cache_clear()
        try:
            app = _make_app()
            first = httpx.Client(
                transport=_SyncASGITransport(app, "203.0.113.7"),
                base_url="http://testserver",
            )
            second = httpx.Client(
                transport=_SyncASGITransport(app, "203.0.113.8"),
                base_url="http://testserver",
            )
            assert first.post("/api/sessions").status_code == 200
            assert first.post("/api/sessions").status_code == 429
            assert second.post("/api/sessions").status_code == 200
        finally:
            get_settings.cache_clear()
