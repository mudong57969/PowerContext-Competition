"""Vector literal serialization for seekdb/OceanBase SQL.

VECTOR columns accept a JSON-array string literal, e.g. ``[0.1,0.2,0.3]``.
"""

from __future__ import annotations


def vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}".rstrip("0").rstrip(".") for v in vec) + "]"


def parse_vector_literal(value: str) -> list[float]:
    inner = value.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    if not inner:
        return []
    return [float(part) for part in inner.split(",")]
