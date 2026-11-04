"""Captured physical PDF pages and offline retrieval through scoped Memory."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pypdf import PdfReader
from typing_extensions import override

from powercontext.builtin.runtime.models import GetMemoryEntryRequest, SearchMemoryRequest
from powercontext.sources.adapters import SourceAdapter
from powercontext.sources.definitions import SourceDefinition, SourceProjection
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TextEvidence

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime.application import ScopedMemoryApplication


class PDFDocumentInput(BaseModel):
    """One complete original document, never pre-extracted text."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    document_id: str
    content: bytes

    @field_validator("document_id")
    @classmethod
    def nonblank_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id must not be blank")  # noqa: TRY003
        return value


class PDFPageInput(BaseModel):
    """A physical, one-based page tied to an exact original byte revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    document_id: str
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(ge=1, strict=True)
    text: str

    _nonblank_id = field_validator("document_id")(PDFDocumentInput.nonblank_id.__func__)


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page atomically, including genuinely blank pages.

    Plain extraction preserves all text-showing operations without layout mode's
    rotated-text exclusion. Whitespace is not a page-quality metric.
    """
    raw = value.content
    if not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-2048:]:
        raise ValueError("incomplete PDF header or trailer")  # noqa: TRY003
    digest = hashlib.sha256(raw).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a user password")  # noqa: TRY003, TRY301
        # Materialize the entire page tree before extracting any page.
        pages = tuple(reader.pages)
        if not pages:
            raise ValueError("PDF has no physical pages")  # noqa: TRY003, TRY301
        return tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=index,
                text=(page.extract_text(extraction_mode="plain") or "").strip(),
            )
            for index, page in enumerate(pages, 1)
        )
    except Exception as error:
        # pypdf can raise parser, codec, decryption or content-stream errors.
        # Never expose a partially extracted document as a successful parse.
        raise ValueError("unable to completely parse PDF") from error  # noqa: TRY003


class _PDFPageSource(Source):
    page: PDFPageInput


class _PDFPageAdapter(SourceAdapter[PDFPageInput, _PDFPageSource, PDFPageInput]):
    name = "pdf-page"
    input_class: type[PDFPageInput] = PDFPageInput
    source_class: type[_PDFPageSource] = _PDFPageSource

    @override
    async def resolve(self, value: PDFPageInput, /) -> _PDFPageSource:
        identity = json.dumps(
            [value.document_id, value.document_sha256, value.page_number], ensure_ascii=False, separators=(",", ":")
        )
        name = "pdf-page:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return _PDFPageSource(name=name, materialization=SourceMaterialization.CAPTURED, page=value)

    @override
    async def read(self, source: _PDFPageSource, /) -> PDFPageInput:
        return source.page


class _PDFPageProjection:
    name = "powercontext.text-evidence"
    version = "1"
    source_class: type[_PDFPageSource] = _PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: _PDFPageSource, /) -> TextEvidence:
        page = source.page
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{page.document_id}\n{page.text}",
            metadata={
                "document_id": page.document_id,
                "document_sha256": page.document_sha256,
                "page_number": page.page_number,
            },
        )


class _PDFPageDefinition(_PDFPageAdapter):
    version = "1"
    projections: tuple[SourceProjection[_PDFPageSource], ...] = (_PDFPageProjection(),)


PDF_PAGE_SOURCE_DEFINITION: SourceDefinition[PDFPageInput, _PDFPageSource, PDFPageInput] = _PDFPageDefinition()

_WORDS = re.compile(r"[a-z]+|\d+")
_STOP = frozenset([
    "a",
    "an",
    "the",
    "of",
    "to",
    "in",
    "on",
    "for",
    "from",
    "by",
    "with",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "as",
    "at",
    "that",
    "this",
    "these",
    "those",
    "what",
    "which",
    "who",
    "how",
    "when",
    "where",
    "why",
    "has",
    "have",
    "had",
    "do",
    "does",
    "did",
    "can",
    "could",
    "would",
    "should",
    "will",
    "its",
    "it",
    "any",
    "all",
    "only",
    "than",
    "then",
    "into",
    "per",
    "using",
    "use",
    "given",
    "give",
    "answer",
    "respond",
    "response",
    "question",
    "calculate",
    "calculated",
    "define",
    "defined",
    "perspective",
    "analyst",
    "investment",
    "assuming",
    "assume",
    "details",
    "shown",
    "relying",
    "rely",
    "please",
    "fiscal",
    "fy",
    "year",
    "years",
    "usd",
    "million",
    "millions",
    "billion",
    "billions",
])
# General accounting vocabulary; no issuer, document, question or page IDs.
_CONCEPTS = (
    ("revenue", "revenues", "sales", "turnover"),
    ("capex", "capital expenditure", "capital expenditures", "additions to property"),
    ("ebitda", "operating income", "depreciation", "amortization"),
    ("income statement", "income statements", "earnings", "profit loss", "operations"),
    ("cash flow", "cash flows", "cashflow", "cash provided", "cash used"),
    ("geography", "geographies", "geographic", "countries", "regions", "segments"),
    ("legal", "litigation", "lawsuits", "proceedings", "contingencies"),
    ("restructuring", "reorganization", "reorganisation", "impairment"),
    ("receivables", "receivable", "debtors"),
    ("payables", "payable", "creditors"),
    ("debt", "borrowings", "borrowing", "indebtedness"),
    ("inventory", "inventories", "stock"),
)


def _terms(text: str) -> list[str]:
    return [_stem(word) for word in _WORDS.findall(text.lower()) if word not in _STOP]


@dataclass(frozen=True)
class _Candidate:
    citation: MemoryCitation
    source_id: str
    text: str
    retrieval_score: float
    document_id: str = ""


_COMMON_QUERY_NOUNS = frozenset(("company", "year", "statement", "page", "input", "report", "result", "category"))
_QUERY_LIMIT = 16
_FOCUS_STOP = frozenset([
    "much",
    "reported",
    "reporting",
    "report",
    "statement",
    "statements",
    "page",
    "pages",
    "filed",
    "supply",
    "inputs",
    "input",
    "estimate",
    "analyst",
    "perspective",
    "adjusted",
    "details",
    "shown",
    "question",
    "answer",
    "use",
    "using",
    "based",
    "according",
    "calculate",
    "calculation",
    "rounding",
    "please",
    "outline",
    "historical",
    "strategic",
    "context",
    "general",
    "corporate",
    "narrative",
    "overview",
    "qualitative",
    "aspects",
    "background",
    "discussion",
    "outlook",
    "broad",
    "directional",
    "regional",
    "patterns",
    "multiple",
    "categories",
    "explain",
    "company",
    "companies",
    "financial",
    "year",
    "years",
])
_ACCOUNTS = (
    ("depreciation amortization", ("depreciation amortization", "d&a"), r"\bd\s*(?:&|and)\s*a\b"),
    ("property plant equipment", ("property plant equipment", "property equipment", "pp&e"), r"\bpp\s*(?:&|and)\s*e\b"),
    ("earnings per share", ("earnings per share", "eps"), r"\beps\b"),
    (
        "capital expenditures",
        ("capital expenditures", "capital expenditure", "additions to property", "capex"),
        r"\bcapex\b",
    ),
    (
        "operating income depreciation amortization",
        ("operating income", "depreciation amortization", "ebitda"),
        r"\bebitda\b",
    ),
    ("free cash flow", ("free cash flow", "fcf"), r"\bfcf\b"),
)
_FINANCE = frozenset([
    "liability",
    "asset",
    "equity",
    "pension",
    "obligation",
    "expense",
    "margin",
    "tax",
    "interest",
    "dividend",
    "depreciation",
    "amortization",
    "earning",
    "share",
    "property",
    "plant",
    "equipment",
    "receivable",
    "payable",
    "inventory",
    "contract",
    "lease",
    "discount",
    "gross",
    "net",
    "cost",
    "goodwill",
    "impairment",
    "commitment",
    "contingency",
    "unearned",
    "deferred",
    "pretax",
    "research",
    "development",
    "revenue",
    "income",
    "expenditure",
    "cash",
    "operating",
    "debt",
])


def _stem(word: str) -> str:
    if word.endswith("ies") and len(word) > 5:
        return word[:-3] + "y"
    if word.endswith(("sses", "shes", "ches", "xes", "zes")) and len(word) > 5:
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 4:
        return word[:-1]
    return word


def _word_forms(word: str) -> tuple[str, ...]:
    singular = _stem(word)
    if singular.endswith("y") and len(singular) > 2 and singular[-2] not in "aeiou":
        plural = singular[:-1] + "ies"
    elif singular.endswith(("s", "x", "z", "ch", "sh")):
        plural = singular + "es"
    else:
        plural = singular + "s"
    return tuple(dict.fromkeys((word, singular, plural)))


def _normalize_finance(text: str) -> str:
    for canonical, _aliases, pattern in _ACCOUNTS:
        text = re.sub(pattern, canonical, text, flags=re.IGNORECASE)
    return text


def _focused(text: str) -> str:
    words = [w for w in _WORDS.findall(_normalize_finance(text).lower()) if w not in _STOP]
    focus = [w for w in words if w not in _FOCUS_STOP]
    return " ".join(focus or words)


def _has_phrase(words: Sequence[str], phrase: str) -> bool:
    return (" " + " ".join(words) + " ").find(" " + " ".join(_terms(phrase)) + " ") >= 0


def _common_probes(question: str) -> tuple[str, ...]:
    # Keep generic nouns out of finance focus, but retain their recall inflections.
    words = [word for word in _WORDS.findall(question.lower()) if word not in _STOP]
    if any(_stem(word) in _FINANCE for word in words):
        return ()
    return tuple(" ".join(_word_forms(word)[:2]) for word in words if _stem(word) in _COMMON_QUERY_NOUNS)


def _account_queries(question: str, tokens: Sequence[str]) -> tuple[str, ...]:
    probes = []
    for _canonical, aliases, pattern in _ACCOUNTS:
        if re.search(pattern, question, re.I) or any(
            _has_phrase(tokens, alias) for alias in aliases if len(_terms(alias)) > 1
        ):
            probes.extend((*aliases[:2], aliases[-1]))
    return tuple(probes)


def _concept_queries(tokens: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        alias for concept in _CONCEPTS if any(_has_phrase(tokens, term) for term in concept) for alias in concept
    )


def _tail_probe(question: str, keywords: Sequence[str], aliases: Sequence[str]) -> str:
    # Reserve one probe for a selected late financial term not covered by aliases.
    words = list(dict.fromkeys(word for word in _WORDS.findall(question.lower()) if word not in _STOP))
    tail = set(words[16:])
    represented = set(_terms(" ".join(aliases)))
    word = next(
        (word for word in keywords if word in tail and _stem(word) in _FINANCE and _stem(word) not in represented),
        "",
    )
    return " ".join(_word_forms(word)[:2]) if word else ""


def _queries(question: str) -> tuple[str, ...]:
    queries: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        key = " ".join(q.split()).casefold()
        if key and key not in seen and len(queries) < _QUERY_LIMIT:
            seen.add(key)
            queries.append(q)

    add(question.strip())
    focused = _focused(question)
    add(focused)
    tokens = _terms(_normalize_finance(question))
    accounts = _account_queries(question, tokens)
    concepts = _concept_queries(tokens)
    words = list(dict.fromkeys(_WORDS.findall(focused)))
    chosen = sorted(enumerate(words), key=lambda item: (-int(_stem(item[1]) in _FINANCE), -len(item[1]), item[0]))[:6]
    add(_tail_probe(question, [word for _, word in chosen], (*accounts, *concepts)))
    for probe in (*accounts, *concepts):
        add(probe)
    for _, word in chosen:
        if word.isdigit():
            continue
        add(" ".join(_word_forms(word)[:2]))
    for probe in _common_probes(question):
        add(probe)
    return tuple(queries)


def _identity_matches(candidate: _Candidate, query: str) -> int:
    ignored = (
        _FOCUS_STOP
        | _FINANCE
        | frozenset(("annual", "inc", "corp", "corporation", "limited", "group", "form", "sec", "document"))
    )
    wanted = {t for t in _terms(query) if len(t) >= 3 and not t.isdigit() and t not in ignored}
    return len(wanted.intersection(_terms(candidate.document_id)))


_VALUE_GROUPS = (
    ("operating income",),
    ("depreciation amortization",),
    ("earnings per share",),
    ("property plant equipment", "property equipment"),
    ("capital expenditure", "additions to property"),
    ("net income",),
    ("current assets",),
    ("current liabilities",),
)


def _value_anchors(candidate: _Candidate, question: str) -> int:
    q = _terms(_normalize_finance(question))
    text = _terms(candidate.text)
    found = 0
    for group in _VALUE_GROUPS:
        if not any(_has_phrase(q, alias) for alias in group):
            continue
        matched = False
        for alias in group:
            terms = _terms(alias)
            for i in range(len(text) - len(terms) + 1):
                if text[i : i + len(terms)] == terms and any(
                    t.isdigit() and not 1900 <= int(t) <= 2100 for t in text[i + len(terms) : i + len(terms) + 6]
                ):
                    matched = True
                    break
            if matched:
                break
        found += matched
    return found


def _rank(candidates: Sequence[_Candidate], question: str) -> list[_Candidate]:
    # Explicit issuer identity and nearby account values precede body relevance.
    # The original body scoring coefficients and native candidate cap are unchanged.
    order = _rank_body(candidates, _focused(question))
    return sorted(order, key=lambda c: (-_identity_matches(c, question), -_value_anchors(c, question)))


def _matched_concepts(text: str) -> frozenset[tuple[str, ...]]:
    def normalized(value: str) -> str:
        words = _WORDS.findall(_normalize_finance(value).lower())
        return " " + " ".join(word for word in words if word not in _STOP) + " "

    body = normalized(text)
    return frozenset(concept for concept in _CONCEPTS if any(normalized(alias) in body for alias in concept))


def _rank_body(candidates: Sequence[_Candidate], question: str) -> list[_Candidate]:
    query = set(_terms(question))
    topics = _matched_concepts(question)
    expanded = set(query)
    lowered = " ".join(_WORDS.findall(question.lower()))
    for concept in _CONCEPTS:
        if any(re.search(r"\b" + re.escape(alias) + r"\b", lowered) for alias in concept):
            expanded.update(_terms(" ".join(concept)))
    counts = [Counter(_terms(candidate.text)) for candidate in candidates]
    count = len(counts)
    lengths = [sum(row.values()) for row in counts]
    average = sum(lengths) / max(1, count)
    idf = {
        term: math.log(
            1 + (count - sum(term in row for row in counts) + 0.5) / (sum(term in row for row in counts) + 0.5)
        )
        for term in expanded
    }
    query_weight = sum(idf.get(term, 0) for term in query) or 1

    def score(index: int) -> float:
        row = counts[index]
        norm = 1.2 * (0.25 + 0.75 * lengths[index] / max(1, average))
        relevance = sum(
            idf[term] * (1 if term in query else 0.35) * row[term] * 2.2 / (row[term] + norm)
            for term in expanded
            if row[term]
        )
        coverage = sum(idf.get(term, 0) for term in query if row[term]) / query_weight
        tokens = _terms(candidates[index].text)
        # Local windows reward terms actually appearing together, rather than
        # unrelated matches scattered through a long page or repeated header.
        local = max(
            (
                sum(idf.get(t, 0) for t in query.intersection(tokens[start : start + 90])) / query_weight
                for start in range(0, len(tokens), 45)
            ),
            default=0,
        )
        phrases = len(topics & _matched_concepts(candidates[index].text))
        return relevance * (0.5 + coverage) + 2 * local + 0.5 * phrases + 0.01 * candidates[index].retrieval_score

    return [candidates[i] for i in sorted(range(count), key=lambda i: (-score(i), candidates[i].source_id))]


async def search_pdf_pages(
    memory: ScopedMemoryApplication, question: str, limit: int = 10
) -> tuple[MemoryCitation, ...]:
    """Find distinct PDF pages using only public scoped Memory search/get.

    This does not open files, load annotations, build a second database, or
    access another scope. Every returned citation is verified against Memory.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a nonnegative integer")  # noqa: TRY003
    if limit == 0 or not question.strip():
        return ()
    hits = {}
    for query in _queries(question):
        result = await memory.search(SearchMemoryRequest(query=query, limit=max(60, min(200, limit * 4)), mode="fts"))
        for hit in result.hits:
            key = (hit.memory_ref.artifact_id, hit.memory_ref.revision, hit.entry_id, hit.entry_version_id)
            if key not in hits:
                hits[key] = hit
    candidates = []
    seen = set()
    # A get validates each exact hit; the citation property uses its real ref.
    from powercontext.builtin.artifacts.memory.models import MemoryCitation

    for hit in hits.values():
        record = await memory.get(
            GetMemoryEntryRequest(
                citation=MemoryCitation(
                    memory_ref=hit.memory_ref,
                    entry_id=hit.entry_id,
                    entry_version_id=hit.entry_version_id,
                )
            )
        )
        pages = [ref for ref in record.entry.sources if ref.source_type == "pdf-page"]
        if record.state != "active" or len(pages) != 1 or pages[0].source_id in seen:
            continue
        seen.add(pages[0].source_id)
        document_id, _, body = record.entry.text.partition("\n")
        candidates.append(_Candidate(record.citation, pages[0].source_id, body, hit.score, document_id))
    return tuple(candidate.citation for candidate in _rank(candidates, question)[:limit])
