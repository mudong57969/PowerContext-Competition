"""Upload resource-protection tests against the real embedded seekdb engine.

Verifies the endpoint-level caps end to end: too-many-files (413),
per-file oversize (per-file error result, batch continues) and cumulative
request size (413). On Windows these tests are skipped; run the suite inside
WSL2 to exercise the actual OceanBase-compatible engine, like
test_seekdb_integration.py.
"""

from __future__ import annotations

import os

import pytest

_AVAILABLE = os.name == "posix"
if _AVAILABLE:
    try:
        import pylibseekdb  # noqa: F401
    except Exception:  # pragma: no cover  # noqa: BLE001 - optional native module probe
        _AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _AVAILABLE,
    reason="seekdb embedded engine requires Linux/macOS with pylibseekdb",
)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    monkeypatch.setenv("EXAMPILOT_SEEKDB_PATH", str(tmp_path / "seekdb"))
    monkeypatch.setenv("EXAMPILOT_POWERCONTEXT_BASE_URL", "")
    monkeypatch.setenv("EXAMPILOT_POWERCONTEXT_TOKEN", "")
    monkeypatch.setenv("EXAMPILOT_EMBEDDING_PROVIDER", "none")
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def _fresh_settings(monkeypatch, **extra: str):
    for key, value in extra.items():
        monkeypatch.setenv(key, value)
    from app.core.config import get_settings

    get_settings.cache_clear()


def _create_session(client) -> tuple[str, str]:
    response = client.post("/api/sessions", json={"name": "upload-limits"})
    assert response.status_code == 200, response.text
    body = response.json()
    return body["token"], body["session"]["id"]


def _upload(client, token: str, session_id: str, contents: list[tuple[str, bytes]]):
    return client.post(
        f"/api/sessions/{session_id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files=[("files", (name, data, "text/markdown")) for name, data in contents],
    )


class TestUploadLimits:
    def test_too_many_files_rejected_with_413(self, client, monkeypatch):
        _fresh_settings(monkeypatch, EXAMPILOT_MAX_UPLOAD_FILES="2")
        token, session_id = _create_session(client)
        files = [(f"f{i}.md", b"### sample") for i in range(3)]
        response = _upload(client, token, session_id, files)
        assert response.status_code == 413
        assert "max 2" in response.json()["detail"]

    def test_oversize_file_returns_per_file_error(self, client, monkeypatch):
        _fresh_settings(monkeypatch, EXAMPILOT_MAX_FILE_BYTES="1024")
        token, session_id = _create_session(client)
        small = b"### short\n\nshort content"
        big = b"x" * 2048
        response = _upload(
            client, token, session_id, [("small.md", small), ("big.md", big)]
        )
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) == 2
        assert results[0]["ok"] is True
        assert results[1]["ok"] is False
        assert "file too large" in results[1]["error"]

    def test_cumulative_size_cap_rejected_with_413(self, client, monkeypatch):
        _fresh_settings(
            monkeypatch,
            EXAMPILOT_MAX_FILE_BYTES="1024",
            EXAMPILOT_MAX_UPLOAD_TOTAL_BYTES="1024",
        )
        token, session_id = _create_session(client)
        chunk = b"a" * 700
        response = _upload(
            client, token, session_id, [("c0.md", chunk), ("c1.md", chunk)]
        )
        assert response.status_code == 413
        assert "total" in response.json()["detail"]
