"""Fulltext tokenization for seekdb's FULLTEXT parser.

seekdb tokenizes on whitespace/punctuation: a contiguous CJK run becomes one
token, and tokens shorter than 3 characters are dropped (verified
empirically against the embedded engine). To make Chinese substring queries
match, CJK runs are expanded into overlapping trigrams plus the full run for
exact matches; ASCII words pass through unchanged. Indexing and query time
must apply the same expansion.
"""

from __future__ import annotations

import re

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_RUN = re.compile(r"[a-z0-9]+")

MIN_TOKEN_CHARS = 3


def fts_tokenize(text: str) -> str:
    lowered = text.lower()
    tokens: list[str] = []
    pos = 0
    for match in _CJK_RUN.finditer(lowered):
        tokens.extend(_ASCII_RUN.findall(lowered[pos : match.start()]))
        run = match.group()
        if len(run) >= MIN_TOKEN_CHARS:
            tokens.append(run)
            tokens.extend(run[i : i + 3] for i in range(len(run) - 2))
        pos = match.end()
    tokens.extend(_ASCII_RUN.findall(lowered[pos:]))
    return " ".join(tokens)
