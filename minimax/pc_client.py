"""Minimal standard-library HTTP client for a local PowerContext Server.

The MiniMax sample stays dependency-free: everything here uses ``urllib`` so
the sample can run with a bare Python 3.12 interpreter while the PowerContext
Server itself provides the storage (seekdb or OceanBase).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


class PowerContextError(RuntimeError):
    """Raised when the PowerContext Server is unreachable or rejects a call."""


def base_url() -> str:
    """Return the Server base URL (``POWERCONTEXT_URL`` wins over the default)."""
    return os.environ.get("POWERCONTEXT_URL", DEFAULT_BASE_URL).rstrip("/")


def request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    query: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Any:
    """Send one JSON request to the Server and return the decoded response."""
    url = f"{base_url()}{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"

    headers = {"Accept": "application/json"}
    body: bytes | None = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    token = os.environ.get("POWERCONTEXT_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request_obj = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request_obj, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise PowerContextError(f"{method} {path} -> HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise PowerContextError(f"{method} {path} -> {error.reason}") from error

    return json.loads(raw) if raw else None


# --- Scope -------------------------------------------------------------------


def create_scope(title: str, summary: str, idempotency_key: str) -> str:
    """Create (or reuse) one Scope and return its id.

    The Server keeps the parameters of an idempotency key: re-creating a Scope
    with the same key but a different summary is a conflict. On conflict the
    existing Scope with the same title is reused instead.
    """
    try:
        response = request(
            "POST",
            "/v1/scopes",
            {
                "title": title,
                "summary": summary,
                "idempotency_key": idempotency_key,
            },
        )
        return response["scope_id"]
    except PowerContextError as error:
        if "HTTP 409" not in str(error):
            raise
        existing = find_scope_by_title(title)
        if existing is None:
            raise
        return existing


def find_scope_by_title(title: str) -> str | None:
    """Return the id of the Scope with this title, if the Server has one."""
    response = request("POST", "/v1/scopes/selection/resolve", {"selection": {"mode": "all"}})
    for item in response.get("items", []):
        if item.get("title") == title:
            return item.get("scope_id")
    return None


# --- Sources -----------------------------------------------------------------


def capture_content_source(
    scope_id: str,
    source_id: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store one durable Content Source."""
    return request(
        "POST",
        "/v1/sources/content",
        {
            "scope_id": scope_id,
            "source_id": source_id,
            "content": content,
            "metadata": metadata,
        },
    )


def list_sources(scope_id: str) -> list[dict[str, Any]]:
    """Return every public Source stored in one Scope."""
    response = request("GET", f"/v1/scopes/{scope_id}/sources")
    return list(response.get("items", []))


# --- Memory ------------------------------------------------------------------


def remember(scope_id: str, kind: str, text: str, reason: str | None = None) -> dict[str, Any]:
    """Write one explicit long-term Memory entry."""
    payload: dict[str, Any] = {"scope_id": scope_id, "kind": kind, "text": text}
    if reason:
        payload["reason"] = reason
    return request("POST", "/v1/memory/remember", payload)


def search_memory(scope_id: str, query: str, limit: int = 10) -> dict[str, Any]:
    """Search active Memory entries inside one Scope."""
    return request(
        "POST",
        "/v1/memory/search",
        {"scope_id": scope_id, "query": query, "limit": limit},
    )


def prepare_context(scope_id: str, query: str, max_bytes: int = 8000) -> dict[str, Any]:
    """Ask the Server to assemble bounded historical context for one request."""
    return request(
        "POST",
        "/v1/context/prepare",
        {"scope_id": scope_id, "query": query, "max_bytes": max_bytes},
    )


# --- Atomic Memory (the current Memory contract of PowerContext 1.5) ---------


def list_atomic_memory(
    scope_id: str,
    *,
    kind: str | None = None,
    states: list[str] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List Atomic Memory heads of one Scope, optionally filtered by kind/state."""
    payload: dict[str, Any] = {"scope_id": scope_id, "limit": limit}
    if kind:
        payload["kind"] = kind
    if states:
        payload["states"] = states
    response = request("POST", "/v1/atomic-memory/list", payload)
    return list(response.get("items", []))


def forget_atomic_memory(
    scope_id: str,
    artifact_id: str,
    revision: int | None,
    state_version: int,
) -> dict[str, Any]:
    """Forget one Atomic Memory head (superseded states keep their content)."""
    artifact: dict[str, Any] = {"family": "atomic-memory", "artifact_id": artifact_id}
    if revision is not None:
        artifact["revision"] = revision
    return request(
        "POST",
        "/v1/atomic-memory/lifecycle",
        {
            "scope_id": scope_id,
            "target": {"artifact": artifact, "state_version": state_version},
            "state": "forgotten",
        },
    )
