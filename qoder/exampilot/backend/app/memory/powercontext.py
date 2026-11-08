"""PowerContext long-term memory integration.

The backend talks to a PowerContext server (``powercontext server run``) over
HTTP using the official async client. Calls run inside a short-lived event
loop on a fresh client instance, which keeps them safe from FastAPI's
threadpool workers.

Each demo session owns one PowerContext scope, keyed idempotently by
``<prefix>:<session_id>``. Every write is mirrored into the local
``memory_events`` audit table by the API layer (real DB evidence).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings

log = logging.getLogger("exampilot.memory")


class MemoryUnavailableError(RuntimeError):
    pass


@dataclass
class MemoryHit:
    text: str
    score: float
    matched_by: list[str]
    entry_id: str
    entry_version_id: str


@dataclass
class MemoryEntryRecord:
    entry_id: str
    entry_version_id: str
    kind: str
    text: str
    state: str
    version: int


@dataclass
class MemorySearchOutcome:
    hits: list[MemoryHit]
    mode: str
    memory_ref: dict | None = None


class MemoryService:
    """Sync facade over the PowerContext async client."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._models: Any = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.powercontext_base_url)

    # --- plumbing ----------------------------------------------------------
    def _models_module(self) -> Any:
        if self._models is None:
            try:
                from powercontext.http._generated import models
            except ModuleNotFoundError as exc:
                raise MemoryUnavailableError("powercontext is not installed") from exc
            self._models = models
        return self._models

    def _make_client(self) -> Any:
        try:
            from powercontext.client import PowerContextClient
        except ModuleNotFoundError as exc:
            raise MemoryUnavailableError(
                "powercontext is not installed; memory features are disabled"
            ) from exc
        kwargs: dict[str, Any] = {
            "base_url": self.settings.powercontext_base_url,
            "timeout": 30.0,
        }
        if self.settings.powercontext_token:
            kwargs["token"] = self.settings.powercontext_token
        if self.settings.powercontext_base_url.startswith("http://"):
            kwargs["allow_insecure_http"] = True
        return PowerContextClient(**kwargs)

    def _run(self, coro_factory: Callable[[Any], Any]) -> Any:
        if not self.enabled:
            raise MemoryUnavailableError("powercontext base URL is not configured")

        async def _inner() -> Any:
            client = self._make_client()
            try:
                return await coro_factory(client)
            finally:
                await client.aclose()

        try:
            return asyncio.run(_inner())
        except MemoryUnavailableError:
            raise
        except Exception as exc:  # network / server errors surface uniformly
            raise MemoryUnavailableError(f"PowerContext call failed: {exc}") from exc

    # --- API ---------------------------------------------------------------
    def ensure_scope(self, session_id: str, title: str, summary: str) -> str:
        """Create (idempotently) the scope for a demo session; returns scope_id."""
        models = self._models_module()
        key = f"{self.settings.memory_scope_prefix}:{session_id}"

        async def _call(client: Any) -> str:
            scope = await client.create_scope(
                models.CreateScopeRequest(
                    title=title, summary=summary, idempotency_key=key
                )
            )
            return str(scope.scope_id)

        scope_id = self._run(_call)
        log.info("memory scope %s ready for session %s", scope_id, session_id)
        return scope_id

    def remember(
        self,
        scope_id: str,
        kind: str,
        text: str,
        reason: str | None = None,
    ) -> dict:
        models = self._models_module()

        async def _call(client: Any) -> dict:
            resp = await client.remember_memory(
                models.RememberMemoryRequest(
                    scope_id=scope_id, kind=kind, text=text, reason=reason
                )
            )
            ref = resp.memory
            result: dict = {
                "family": ref.family,
                "artifact_id": ref.artifact_id,
                "revision": ref.revision,
            }
            if resp.entry is not None:
                result["entry_id"] = resp.entry.citation.entry_id
                result["entry_version_id"] = resp.entry.citation.entry_version_id
            return result

        return self._run(_call)

    def search(self, scope_id: str, query: str, limit: int = 10) -> MemorySearchOutcome:
        models = self._models_module()

        async def _call(client: Any) -> MemorySearchOutcome:
            resp = await client.search_memory(
                models.SearchMemoryRequest(scope_id=scope_id, query=query, limit=limit)
            )
            mode = resp.mode.value if resp.mode else "unknown"
            hits = [
                MemoryHit(
                    text=h.text,
                    score=h.score,
                    matched_by=[str(m.value) for m in h.matched_by],
                    entry_id=h.citation.entry_id,
                    entry_version_id=h.citation.entry_version_id,
                )
                for h in resp.hits
            ]
            memory_ref = None
            if resp.memory is not None:
                memory_ref = {
                    "family": resp.memory.family,
                    "artifact_id": resp.memory.artifact_id,
                    "revision": resp.memory.revision,
                }
            return MemorySearchOutcome(hits=hits, mode=mode, memory_ref=memory_ref)

        return self._run(_call)

    def list_entries(self, scope_id: str) -> list[MemoryEntryRecord]:
        models = self._models_module()

        async def _call(client: Any) -> list[MemoryEntryRecord]:
            resp = await client.list_memory_entries(
                models.ListMemoryEntriesRequest(scope_id=scope_id)
            )
            return [
                MemoryEntryRecord(
                    entry_id=e.citation.entry_id,
                    entry_version_id=e.citation.entry_version_id,
                    kind=e.kind,
                    text=e.text,
                    state=e.state.value,
                    version=e.version,
                )
                for e in resp.entries
            ]

        return self._run(_call)

    def prepare_context(self, scope_id: str, query: str, max_bytes: int = 8000) -> dict:
        models = self._models_module()

        async def _call(client: Any) -> dict:
            resp = await client.prepare_context(
                models.PrepareContextRequest(
                    scope_id=scope_id, query=query, max_bytes=max_bytes
                )
            )
            return {
                "content": resp.content,
                "content_bytes": resp.content_bytes,
                "status": resp.status.value,
                "schema": resp.schema_.value,
            }

        return self._run(_call)

    def retire(self, citation: dict, scope_id: str, reason: str | None = None) -> None:
        models = self._models_module()

        async def _call(client: Any) -> None:
            await client.retire_memory_entry(
                models.RetireMemoryEntryRequest(
                    scope_id=scope_id,
                    citation=models.MemoryCitation(
                        memory_ref=models.ArtifactReference(**citation["memory_ref"]),
                        entry_id=citation["entry_id"],
                        entry_version_id=citation["entry_version_id"],
                    ),
                    reason=reason,
                )
            )

        self._run(_call)

    def ping(self) -> bool:
        if not self.enabled:
            return False

        async def _call(client: Any) -> bool:
            await client.get_liveness()
            return True

        try:
            return bool(self._run(_call))
        except Exception:  # noqa: BLE001 - liveness probe is best-effort
            return False
