"""Persistent Source dependency graphs with resumable native state propagation."""

from __future__ import annotations

import logging
from graphlib import TopologicalSorter
from typing import TYPE_CHECKING, Literal, Never, TypedDict

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator
from sqlalchemy import delete, insert, select, update

from powercontext._logging import log_safely
from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import InvalidMemoryCitationError, MemoryEntryNotFoundError
from powercontext.builtin.persistence.database import AsyncDatabase
from powercontext.builtin.persistence.errors import RepositoryNotFoundError
from powercontext.builtin.persistence.source_lifecycle import LIFECYCLE_GRAPHS, LIFECYCLE_HIDDEN_TOPICS
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.builtin.sources import validate_scope_id
from powercontext.errors import ArtifactNotFoundError
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import BuiltinRuntime

Reference = SourceRef | MemoryCitation | ArtifactRef
logger = logging.getLogger(__name__)
_UNREADABLE = (InvalidMemoryCitationError, MemoryEntryNotFoundError, ArtifactNotFoundError, RepositoryNotFoundError)


class SourceLifecycleError(ValueError):
    """A lifecycle registration, event, or resolution violates its contract."""


class SourceLifecycleStatus(TypedDict):
    pending: bool
    fault: dict[str, str] | None


def _nonblank(value: str) -> str:
    if not value.strip():
        raise SourceLifecycleError("blank-value")
    return value


class SourceLifecycleEvent(BaseModel):
    """An immutable, strictly validated Source lifecycle event."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    node_id: str
    reason: str
    revision: int = Field(gt=0)
    sequence: int = Field(gt=0)
    available: bool

    @field_validator("node_id", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        return _nonblank(value)


class _Node(BaseModel):
    kind: Literal["source", "memory", "topic"]
    reference: dict[str, JsonValue]
    parents: tuple[str, ...] = ()
    policy: Literal["all", "any"] = "all"
    revision: int = 1
    available: bool = True
    event: SourceLifecycleEvent | None = None

    def ref(self) -> Reference:
        model = {"source": SourceRef, "memory": MemoryCitation, "topic": ArtifactRef}[self.kind]
        return model.model_validate(self.reference)

    def native_identity(self) -> tuple[str, ...] | None:
        reference = self.ref()
        if isinstance(reference, MemoryCitation):
            return ("memory", reference.memory_ref.artifact_id, reference.entry_id)
        if isinstance(reference, ArtifactRef):
            return ("topic", reference.artifact_id)
        return None


class _Graph(BaseModel):
    nodes: dict[str, _Node] = Field(default_factory=dict)
    pending: bool = False
    fault: dict[str, str] | None = None

    def duplicate_native_binding(self) -> str | None:
        identities = set()
        for key, node in self.nodes.items():
            identity = node.native_identity()
            if identity is not None:
                if identity in identities:
                    return key
                identities.add(identity)
        return None

    def recompute(self) -> None:
        for key in TopologicalSorter({key: node.parents for key, node in self.nodes.items()}).static_order():
            node = self.nodes[key]
            if node.kind != "source":
                values = [self.nodes[parent].available for parent in node.parents]
                node.available = all(values) if node.policy == "all" else any(values)


class ScopedSourceLifecycle:
    """Operate one single-writer scope's durable dependency graph."""

    def __init__(self, application: SourceLifecycleApplication, scope_id: str) -> None:
        self._application = application
        self._runtime = application.runtime
        self.scope_id = validate_scope_id(scope_id)

    async def _load(self) -> _Graph:
        async with self._application.database.transaction() as connection:
            value = await connection.scalar(
                select(LIFECYCLE_GRAPHS.c.graph).where(LIFECYCLE_GRAPHS.c.scope_id == self.scope_id)
            )
        return _Graph() if value is None else _Graph.model_validate_json(value)

    async def _store(self, graph: _Graph) -> None:
        async with self._application.database.transaction() as connection:
            exists = await connection.scalar(
                select(LIFECYCLE_GRAPHS.c.scope_id).where(LIFECYCLE_GRAPHS.c.scope_id == self.scope_id)
            )
            if exists is None:
                await connection.execute(
                    insert(LIFECYCLE_GRAPHS).values(scope_id=self.scope_id, graph=graph.model_dump_json())
                )
            else:
                await connection.execute(
                    update(LIFECYCLE_GRAPHS)
                    .where(LIFECYCLE_GRAPHS.c.scope_id == self.scope_id)
                    .values(graph=graph.model_dump_json())
                )
            await connection.execute(
                delete(LIFECYCLE_HIDDEN_TOPICS).where(LIFECYCLE_HIDDEN_TOPICS.c.scope_id == self.scope_id)
            )
            hidden = {
                ArtifactRef.model_validate(node.reference).artifact_id
                for node in graph.nodes.values()
                if node.kind == "topic" and (not node.available or graph.fault is not None)
            }
            if hidden:
                await connection.execute(
                    insert(LIFECYCLE_HIDDEN_TOPICS),
                    [{"scope_id": self.scope_id, "artifact_id": key} for key in sorted(hidden)],
                )

    async def register_source(self, node_id: str, source_ref: SourceRef, *, revision: int) -> None:
        if type(revision) is not int or revision <= 0 or not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("source-registration")
        await self._register(
            node_id, _Node(kind="source", reference=source_ref.model_dump(mode="json"), revision=revision)
        )

    async def register_memory(
        self, node_id: str, citation: MemoryCitation, *, parents: tuple[str, ...], policy: Literal["all", "any"] = "all"
    ) -> None:
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("memory-reference")
        await self._register_derived(node_id, "memory", citation, parents, policy)

    async def register_topic(
        self,
        node_id: str,
        artifact_ref: ArtifactRef,
        *,
        parents: tuple[str, ...],
        policy: Literal["all", "any"] = "any",
    ) -> None:
        if not isinstance(artifact_ref, ArtifactRef) or artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("topic-reference")
        await self._register_derived(node_id, "topic", artifact_ref, parents, policy)

    async def _register_derived(
        self,
        node_id: str,
        kind: Literal["memory", "topic"],
        reference: MemoryCitation | ArtifactRef,
        parents: tuple[str, ...],
        policy: Literal["all", "any"],
    ) -> None:
        if (
            policy not in {"all", "any"}
            or not isinstance(parents, tuple)
            or not parents
            or any(not isinstance(parent, str) or not parent.strip() for parent in parents)
            or len(set(parents)) != len(parents)
        ):
            raise SourceLifecycleError("parents-or-policy")
        await self._register(
            node_id,
            _Node(
                kind=kind, reference=reference.model_dump(mode="json"), parents=tuple(sorted(parents)), policy=policy
            ),
        )

    async def _register(self, node_id: str, node: _Node) -> None:
        if not isinstance(node_id, str):
            raise SourceLifecycleError("node-id")
        _nonblank(node_id)
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            graph = await self._load()
            old = graph.nodes.get(node_id)
            if old is not None:
                if old.model_dump(exclude={"available", "event"}) != node.model_dump(exclude={"available", "event"}):
                    raise SourceLifecycleError("binding-conflict")
                await self._repair(graph)
                return
            await self._repair(graph)
            if node_id in node.parents or any(parent not in graph.nodes for parent in node.parents):
                raise SourceLifecycleError("missing-or-cyclic-parent")
            identity = node.native_identity()
            if identity is not None and any(other.native_identity() == identity for other in graph.nodes.values()):
                raise SourceLifecycleError("duplicate-native-binding")
            reference = node.ref()
            try:
                await self._read_reference(reference)
                if isinstance(reference, MemoryCitation):
                    current = await self._runtime.memory.for_scope(self.scope_id).list(include_inactive=True)
                    if not any(item.entry.entry_id == reference.entry_id for item in current.entries):
                        raise SourceLifecycleError("memory-entry-not-current")  # noqa: TRY301
            except Exception as error:
                raise SourceLifecycleError("unreadable-reference") from error
            graph.nodes[node_id] = node
            graph.recompute()
            graph.pending = True
            await self._store(graph)
            await self._repair(graph)

    async def apply(self, event: SourceLifecycleEvent) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("event-type")
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            graph = await self._load()
            node = graph.nodes.get(event.node_id)
            if node is None or node.kind != "source" or node.revision != event.revision:
                raise SourceLifecycleError("source-or-revision")
            if node.event is not None and event.sequence <= node.event.sequence:
                if event != node.event:
                    raise SourceLifecycleError("event-sequence-conflict")
            else:
                await self._repair(graph)
                node.event = event
                node.available = event.available
                graph.recompute()
                graph.pending = True
                await self._store(graph)
            await self._repair(graph)
            return sorted(key for key, value in graph.nodes.items() if value.available)

    async def resolve(self, node_id: str, *, purpose: str = "generation") -> Reference:
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            graph = await self._load()
            node = graph.nodes.get(node_id)
            if node is None or purpose not in {"generation", "audit"}:
                raise SourceLifecycleError("node-or-purpose")
            if purpose == "generation":
                await self._repair(graph)
                if not node.available:
                    raise SourceLifecycleError("unavailable")
            reference = node.ref()
            try:
                await self._read_reference(reference)
            except _UNREADABLE:
                await self._fail(graph, node_id, "unreadable-reference")
            return reference

    async def status(self) -> SourceLifecycleStatus:
        """Read durable propagation intent and faults without retrying or hiding them."""

        async with self._runtime._scope_operation(self.scope_id):
            graph = await self._load()
            return {"pending": graph.pending, "fault": graph.fault}

    async def _read_reference(self, reference: Reference) -> None:
        if isinstance(reference, SourceRef):
            await self._runtime.records.for_scope(self.scope_id).get_source(reference.source_type, reference.source_id)
        elif isinstance(reference, MemoryCitation):
            await self._runtime.memory.for_scope(self.scope_id).get(GetMemoryEntryRequest(citation=reference))
        else:
            await self._runtime.records.for_scope(self.scope_id).get_artifact_revision(
                reference.family, reference.artifact_id, reference.revision
            )

    async def _fail(self, graph: _Graph, node_id: str, code: str) -> Never:
        graph.pending = True
        graph.fault = {"node_id": node_id, "code": code}
        await self._store(graph)
        raise SourceLifecycleError(code)

    async def _repair(self, graph: _Graph) -> None:
        if duplicate := graph.duplicate_native_binding():
            await self._fail(graph, duplicate, "duplicate-native-binding")
        if not graph.pending:
            return
        # Persist intent first; native commits may finish before this completion marker.
        # Retrying compares current native state, so already-completed writes stay no-ops.
        async with self._runtime._context(self.scope_id) as context:
            service = context.artifacts.memory
            memory_nodes = [(key, node) for key, node in graph.nodes.items() if node.kind == "memory"]
            if memory_nodes:
                try:
                    current = await service.head(context.artifacts.memory_artifact_id)
                    entries = await service.entries(current)
                except _UNREADABLE:
                    await self._fail(graph, "", "memory-storage-inconsistent")
                by_id = {entry.entry_id: entry for entry in entries}
                # Preflight every binding before native writes; historical readability
                # and current manifest membership are distinct invariants.
                for key, node in memory_nodes:
                    citation = MemoryCitation.model_validate(node.reference)
                    try:
                        await service.validate_citation(citation)
                    except _UNREADABLE:
                        await self._fail(graph, key, "unreadable-reference")
                    if citation.entry_id not in by_id:
                        await self._fail(graph, key, "bound-memory-entry-missing")
                for _, node in memory_nodes:
                    citation = MemoryCitation.model_validate(node.reference)
                    entry = by_id[citation.entry_id]
                    state = next(
                        item.state for item in current.content.manifest.entries if item.entry_id == entry.entry_id
                    )
                    if (state == "active") != node.available:
                        transition = service.reactivate if node.available else service.forget
                        current = await transition(current, entries=(entry,), reason="source-lifecycle")
        graph.pending = False
        graph.fault = None
        await self._store(graph)


class SourceLifecycleApplication:
    """Select scope services and resume interrupted propagation during Runtime startup."""

    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase | None) -> None:
        self.runtime = runtime
        self._database = database

    @property
    def database(self) -> AsyncDatabase:
        if self._database is None:
            raise SourceLifecycleError("lifecycle-storage-unavailable")
        return self._database

    def for_scope(self, scope_id: str) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self, scope_id)

    async def recover(self) -> None:
        async with self.database.transaction() as connection:
            scopes = (await connection.execute(select(LIFECYCLE_GRAPHS.c.scope_id))).scalars().all()
        for scope in scopes:
            try:
                service = self.for_scope(scope)
                async with self.runtime._scope_operation(scope), self.runtime._locked(scope):
                    await service._repair(await service._load())
            except Exception as error:
                # One failed scope must not prevent healthy scopes from opening.
                # Pending stays durable; cancellation and global database-open failures propagate.
                log_safely(
                    logger,
                    logging.ERROR,
                    "Source lifecycle scope recovery failed",
                    exc_info=error,
                    extra={"event": "source_lifecycle.recovery.failed", "scope_id": scope},
                )


__all__ = ["SourceLifecycleError", "SourceLifecycleEvent"]
