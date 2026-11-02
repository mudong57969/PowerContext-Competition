"""Offline query-aware literal windows, measured with their complete wire envelope."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

if TYPE_CHECKING:
    from powercontext.builtin.runtime.prepared_context import MemoryEntryAddress

_WORDS = re.compile(r"[a-z]+|\d+(?:\.\d+)?|[\u3400-\u9fff]", re.IGNORECASE)
_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|(?<=[。！？])|\n+")  # noqa: RUF001 -- Chinese sentence punctuation
_COST_POWER = 0.2
_WINDOW_SENTENCES = 4
_WINDOW_SUPPORT = 0.45
_NEIGHBOR_WEIGHT = 0.15
# Thirteen generic sentence features, fitted offline on document-disjoint
# SciFact training data (CC BY 4.0); no annotation or data file is read here.
_LEARNED_WEIGHTS: tuple[float, ...] = (
    -6.4388918791,
    0.9436157991,
    0.9768331806,
    0.4475537454,
    1.8010359858,
    -1.0773793797,
    1.1501450471,
    0.3627968487,
    0.7902543981,
    0.4195363383,
    -0.1428609225,
    -0.1609261334,
    0.6529204823,
)
_RELATIONS = frozenset({
    "find",
    "found",
    "observ",
    "show",
    "demonstrat",
    "reveal",
    "significant",
    "associat",
    "compar",
    "reduc",
    "increas",
    "decreas",
    "effect",
    "result",
    "risk",
    "rate",
    "suggest",
    "conclud",
    "confirm",
    "measur",
    "caus",
})
_STOP = frozenset([
    "a",
    "an",
    "the",
    "of",
    "in",
    "on",
    "at",
    "to",
    "by",
    "for",
    "from",
    "with",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "and",
    "or",
    "that",
    "this",
    "these",
    "those",
    "it",
    "its",
    "their",
    "there",
    "which",
    "who",
    "can",
    "could",
    "may",
    "might",
    "would",
    "should",
    "has",
    "have",
    "had",
    "do",
    "does",
    "did",
    "than",
    "through",
    "between",
    "into",
    "using",
    "used",
    "also",
    "we",
    "our",
    "they",
    "them",
    "such",
    "both",
    "each",
    "all",
])


@dataclass(frozen=True)
class EvidenceFragment:
    address: MemoryEntryAddress
    start: int
    end: int
    text: str

    def __post_init__(self) -> None:
        if type(self.start) is not int or type(self.end) is not int or not 0 <= self.start < self.end:
            raise ValueError("Invalid evidence character interval")  # noqa: TRY003
        if not isinstance(self.text, str) or len(self.text) != self.end - self.start:
            raise ValueError("Evidence text and character interval disagree")  # noqa: TRY003


@dataclass(frozen=True)
class EvidenceDocument:
    address: MemoryEntryAddress
    text: str


@dataclass(frozen=True)
class EvidenceSelection:
    fragments: tuple[EvidenceFragment, ...]
    budget_dropped_items: int


def render_evidence(fragments: Sequence[EvidenceFragment]) -> str:
    items = [
        {
            "citation": {
                "scope_id": f.address.memory.scope_id,
                "memory_ref": f.address.memory.artifact.model_dump(mode="json"),
                "entry_id": f.address.entry_id,
                "entry_version_id": f.address.entry_version_id,
            },
            "content": f.text,
            "start": f.start,
            "end": f.end,
        }
        for f in fragments
    ]
    encoded = json.dumps({"trust": "untrusted_history", "items": items}, ensure_ascii=False, separators=(",", ":"))
    return (
        TRUST_POLICY
        + "\n\nBEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n"
        + encoded
        + "\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1"
    )


def _term(word: str) -> str:
    word = word.lower()
    irregular = {"mice": "mouse", "men": "man", "women": "woman", "children": "child"}
    if word in irregular:
        return irregular[word]
    if len(word) > 4 and word.endswith("ies"):
        word = word[:-3] + "y"
    elif len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    for suffix in ("ing", "ed"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            word = word[: -len(suffix)]
            if len(word) > 3 and word[-1] == word[-2] and word[-1] in "bdgmnprt":
                word = word[:-1]
            break
    if len(word) > 7 and word.endswith(("ion", "ive")):
        word = word[:-3]
    if len(word) > 6 and word.endswith("ly"):
        word = word[:-2]
    return word.rstrip("e") if len(word) > 4 else word


def _terms(text: str) -> list[str]:
    return [_term(m.group()) for m in _WORDS.finditer(text) if m.group().lower() not in _STOP]


def _sentences(text: str) -> list[tuple[int, int]]:
    intervals = []
    start = 0
    for boundary in _BOUNDARY.finditer(text):
        end = boundary.start()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            intervals.append((start, end))
        start = boundary.end()
    if text[start:].strip():
        end = len(text.rstrip())
        start += len(text[start:]) - len(text[start:].lstrip())
        intervals.append((start, end))
    return intervals


@dataclass(frozen=True)
class _Window:
    document: int
    start: int
    end: int
    score: float


def _anchored_windows(
    document: int, text: str, intervals: Sequence[tuple[int, int]], query_terms: set[str], score: float
) -> list[_Window]:
    windows = []
    for start, end in intervals:
        if end - start <= 500:
            continue
        for match in _WORDS.finditer(text, start, end):
            if _term(match.group()) in query_terms:
                windows.append(_Window(document, max(start, match.start() - 160), min(end, match.end() + 240), score))
    return windows


def _relevance(counter: Counter[str], idf: dict[str, float], average: float, total_weight: float) -> float:
    length = sum(counter.values())
    bm25 = sum(
        weight * counter[term] * 2.2 / (counter[term] + 1.2 * (0.25 + 0.75 * length / average))
        for term, weight in idf.items()
        if counter[term]
    )
    coverage = sum(weight for term, weight in idf.items() if counter[term]) / total_weight
    return bm25 + 3 * coverage


def _feature_rows(documents: Sequence[EvidenceDocument], query: str) -> list[tuple[int, int, int, tuple[float, ...]]]:
    query_words = _terms(query)
    query_terms = set(query_words)
    phrases = set(pairwise(query_words))
    spans = [_sentences(doc.text) for doc in documents]
    words = [[_terms(doc.text[a:b]) for a, b in intervals] for doc, intervals in zip(documents, spans, strict=True)]
    counters = [[Counter(sentence) for sentence in sentences] for sentences in words]
    all_counters = [counter for group in counters for counter in group]
    size = max(1, len(all_counters))
    frequency = Counter(term for counter in all_counters for term in counter)
    idf = {term: math.log(1 + (size - frequency[term] + 0.5) / (frequency[term] + 0.5)) for term in query_terms}
    total = sum(idf.values()) or 1
    average = sum(sum(c.values()) for c in all_counters) / size or 1
    rows = []
    for index, (doc, intervals, group, sentences) in enumerate(zip(documents, spans, counters, words, strict=True)):
        doc_terms = set().union(*group)
        doc_coverage = sum(weight for term, weight in idf.items() if term in doc_terms) / total
        raw = [_relevance(c, idf, average, total) for c in group]
        maximum = max(raw, default=1) or 1
        title_end = doc.text.find("\n")
        long_total = sum(weight for term, weight in idf.items() if len(term) >= 6) or 1
        for position, ((start, end), counter, sentence, score) in enumerate(
            zip(intervals, group, sentences, raw, strict=True)
        ):
            coverage = sum(weight for term, weight in idf.items() if counter[term]) / total
            bigrams = set(pairwise(sentence))
            title = position == 0 and 0 < title_end <= 240 and end <= title_end
            neighbor = max(raw[max(0, position - 1) : position] + raw[position + 1 : position + 2], default=0) / maximum
            features = (
                1.0,
                coverage,
                math.log1p(score),
                doc_coverage,
                position / max(1, len(group) - 1),
                float(title),
                math.log1p(sum(counter.values())) / 5,
                float(bool(counter.keys() & _RELATIONS)),
                len(phrases & bigrams) / max(1, len(phrases)),
                float(any(term[0].isdigit() for term in counter)),
                score / maximum,
                neighbor,
                sum(weight for term, weight in idf.items() if len(term) >= 6 and counter[term]) / long_total,
            )
            rows.append((index, start, end, features))
    return rows


def _windows(documents: Sequence[EvidenceDocument], query: str) -> list[_Window]:
    query_terms = set(_terms(query))
    grouped: list[list[tuple[int, int, float]]] = [[] for _ in documents]
    for index, start, end, features in _feature_rows(documents, query):
        linear = sum(a * b for a, b in zip(_LEARNED_WEIGHTS, features, strict=True))
        grouped[index].append((start, end, 1 / (1 + math.exp(-max(-30.0, min(30.0, linear))))))
    result = []
    for index, (doc, rows) in enumerate(zip(documents, grouped, strict=True)):
        intervals = [(a, b) for a, b, _ in rows]
        scores = [score for _, _, score in rows]
        contextual = [
            score + _NEIGHBOR_WEIGHT * max(scores[max(0, i - 1) : i + 2], default=0) for i, score in enumerate(scores)
        ]
        for start in range(len(intervals)):
            for end in range(start, min(len(intervals), start + _WINDOW_SENTENCES)):
                local = contextual[start : end + 1]
                score = max(local) + _WINDOW_SUPPORT * (sum(local) - max(local))
                if score > 0 or not query_terms:
                    result.append(_Window(index, intervals[start][0], intervals[end][1], score or 0.01))
        # Long unsplit passages still expose late matches without rewriting text.
        result.extend(_anchored_windows(index, doc.text, intervals, query_terms, max(scores, default=0)))
    return sorted(result, key=lambda w: (-w.score, w.document, w.start, w.end))


def _merge(windows: Sequence[_Window]) -> list[_Window]:
    merged: list[_Window] = []
    for window in sorted(windows, key=lambda w: (w.document, w.start, w.end)):
        if merged and merged[-1].document == window.document and window.start <= merged[-1].end + 1:
            previous = merged.pop()
            merged.append(
                _Window(
                    window.document, previous.start, max(previous.end, window.end), max(previous.score, window.score)
                )
            )
        else:
            merged.append(window)
    return merged


def _budget_drops(
    selected: Sequence[_Window],
    candidates: Sequence[_Window],
    entry_limit: int,
    max_bytes: int,
    measure: Callable[[Sequence[_Window]], int],
) -> int:
    represented = {window.document for window in selected}
    blocked, fitting = set(), set()
    for candidate in candidates:
        if candidate.document in represented:
            continue
        trial = _merge((*selected, candidate))
        if len(trial) > entry_limit:
            continue
        if measure(trial) <= max_bytes:
            fitting.add(candidate.document)
        else:
            blocked.add(candidate.document)
    return len(blocked - fitting)


def select_evidence(
    documents: Sequence[EvidenceDocument], query: str, max_bytes: int, *, entry_limit: int = 8
) -> EvidenceSelection:
    def fragments(windows: Sequence[_Window]) -> tuple[EvidenceFragment, ...]:
        return tuple(
            EvidenceFragment(documents[w.document].address, w.start, w.end, documents[w.document].text[w.start : w.end])
            for w in windows
        )

    selected: list[_Window] = []
    current_bytes = 0
    ranked = _windows(documents, query)[:192]
    candidates = list(ranked)
    while candidates:
        best = None
        best_gain = 0.0
        for candidate in candidates:
            trial = _merge((*selected, candidate))
            if len(trial) > entry_limit or [(w.document, w.start, w.end) for w in trial] == [
                (w.document, w.start, w.end) for w in selected
            ]:
                continue
            measured = len(render_evidence(fragments(trial)).encode("utf-8"))
            if measured > max_bytes:
                continue
            overlap = max(
                (
                    max(0, min(w.end, candidate.end) - max(w.start, candidate.start))
                    / (candidate.end - candidate.start)
                    for w in selected
                    if w.document == candidate.document
                ),
                default=0,
            )
            gain = candidate.score * (1 - overlap) / max(1, measured - current_bytes) ** _COST_POWER
            if gain > best_gain:
                best_gain = gain
                best = (candidate, trial, measured)
        if best is None:
            break
        candidate, selected, current_bytes = best
        candidates.remove(candidate)
    dropped = _budget_drops(
        selected,
        ranked,
        entry_limit,
        max_bytes,
        lambda windows: len(render_evidence(fragments(windows)).encode("utf-8")),
    )
    return EvidenceSelection(fragments(selected), dropped)
