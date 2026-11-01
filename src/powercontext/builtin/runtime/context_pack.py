"""Canonical v1 context transport with stateless prefix reconstruction."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

_PACK_SCHEMA = "powercontext.context-pack.v1"
_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"


class ContextPackError(ValueError):
    """Invalid context pack, delta, or UTF-8 chunk boundary."""


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContextPackError("Duplicate JSON field")  # noqa: TRY003
        result[key] = value
    return result


def _payload(data: bytes, schema: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(data, bytes):
        raise ContextPackError("Wire payload must be bytes")  # noqa: TRY003
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, TypeError, RecursionError) as error:
        raise ContextPackError("Invalid context wire payload") from error  # noqa: TRY003
    if not isinstance(value, dict) or set(value) != fields or value["schema"] != schema:
        raise ContextPackError("Invalid context wire fields or schema")  # noqa: TRY003
    return value


def _check_items(items: tuple[bytes, ...]) -> None:
    if not isinstance(items, tuple) or any(not isinstance(item, bytes) for item in items):
        raise ContextPackError("Chunks must be a tuple of bytes")  # noqa: TRY003
    try:
        for item in items:
            item.decode("utf-8")
    except UnicodeError as error:
        raise ContextPackError("Chunks must be valid UTF-8") from error  # noqa: TRY003


def _encoded(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decoded(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError("Chunks must be a Base64 array")  # noqa: TRY003
    result = []
    for item in value:
        if not isinstance(item, str):
            raise ContextPackError("Base64 chunks must be strings")  # noqa: TRY003
        try:
            raw = base64.b64decode(item, validate=True)
        except ValueError as error:
            raise ContextPackError("Invalid standard Base64") from error  # noqa: TRY003
        # validate=True alone accepts nonzero padding bits and excess padding.
        if base64.b64encode(raw).decode("ascii") != item:
            raise ContextPackError("Noncanonical standard Base64")  # noqa: TRY003
        result.append(raw)
    return tuple(result)


def _check_digest(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ContextPackError("Invalid SHA-256 digest")  # noqa: TRY003


@dataclass(frozen=True)
class ContextPack:
    """Immutable full pack whose digest covers schema and encoded chunks."""

    items: tuple[bytes, ...]
    digest: str = field(init=False)
    byte_count: int = field(init=False)

    def __post_init__(self) -> None:
        _check_items(self.items)
        unsigned = {"schema": _PACK_SCHEMA, "items": _encoded(self.items)}
        digest = "sha256:" + hashlib.sha256(_json(unsigned)).hexdigest()
        count = 0
        while True:
            size = len(_json({**unsigned, "digest": digest, "byte_count": count}))
            if size == count:
                break
            count = size
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "byte_count", count)

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        return cls(items)

    @classmethod
    def from_content(cls, content: str, *, chunk_bytes: int = 512) -> ContextPack:
        """Use the first line ending after half capacity, or a full UTF-8 chunk."""
        if not isinstance(content, str) or type(chunk_bytes) is not int or chunk_bytes <= 0:
            raise ContextPackError("Expected text and a positive integer chunk limit")  # noqa: TRY003
        try:
            data = content.encode("utf-8")
        except UnicodeError as error:
            raise ContextPackError("Content must be valid UTF-8") from error  # noqa: TRY003
        items = []
        start = 0
        while start < len(data):
            end = min(start + chunk_bytes, len(data))
            while end < len(data) and data[end] & 0xC0 == 0x80:
                end -= 1
            if end == start:
                raise ContextPackError("Chunk limit cannot fit a UTF-8 codepoint")  # noqa: TRY003
            # First qualifying boundary stays stable on append; half capacity avoids tiny chunks.
            newline = data.find(b"\n", start + max(1, chunk_bytes // 2) - 1, end)
            if newline != -1:
                end = newline + 1
            items.append(data[start:end])
            start = end
        return cls.build(tuple(items))

    def to_bytes(self) -> bytes:
        return _json({
            "schema": _PACK_SCHEMA,
            "items": _encoded(self.items),
            "digest": self.digest,
            "byte_count": self.byte_count,
        })

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        value = _payload(data, _PACK_SCHEMA, {"schema", "items", "digest", "byte_count"})
        pack = cls.build(_decoded(value["items"]))
        if (
            value["digest"] != pack.digest
            or type(value["byte_count"]) is not int
            or value["byte_count"] != pack.byte_count
        ):
            raise ContextPackError("Pack digest or byte count mismatch")  # noqa: TRY003
        return pack


@dataclass(frozen=True)
class ContextPackDelta:
    """Retain a base prefix and append the complete target suffix."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        _check_digest(self.base_digest)
        _check_digest(self.target_digest)
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("Prefix must be a nonnegative integer")  # noqa: TRY003
        _check_items(self.appended)

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        if not isinstance(base, ContextPack) or not isinstance(target, ContextPack):
            raise ContextPackError("Expected full base and target packs")  # noqa: TRY003
        prefix = 0
        for left, right in zip(base.items, target.items, strict=False):
            if left != right:
                break
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    def to_bytes(self) -> bytes:
        return _json({
            "schema": _DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _encoded(self.appended),
        })

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        value = _payload(data, _DELTA_SCHEMA, {"schema", "base_digest", "target_digest", "prefix_items", "appended"})
        return cls(value["base_digest"], value["target_digest"], value["prefix_items"], _decoded(value["appended"]))


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Reconstruct and authenticate a target using only the base and delta."""
    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("Expected a full base pack and delta")  # noqa: TRY003
    if base.digest != delta.base_digest or delta.prefix_items > len(base.items):
        raise ContextPackError("Base digest or prefix bounds mismatch")  # noqa: TRY003
    target = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        raise ContextPackError("Target digest mismatch")  # noqa: TRY003
    return target
