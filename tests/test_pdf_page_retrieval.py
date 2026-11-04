from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    SearchMemoryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    SourceDefinitionRegistry,
    manifest_for_definition,
    pdf_pages,
    project_source_for_transport,
)
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY
from tests.test_pdf_pages import _async_test, pdf_bytes

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import ScopedMemoryApplication


class _PagePipeline:
    async def extract(self, request, /):
        return tuple(
            MemoryEntryInput(
                kind="source-evidence", text=s.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"], sources=(s,)
            )
            for s in request.sources
        )


async def _persist(tmp_path: Path, documents: dict[str, tuple[str, ...]]):
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'retrieval.db'}"))
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    metadata = {}
    async with open_builtin_runtime(config) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="PDF", summary="offline", idempotency_key="pages"))
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for document_id, texts in documents.items():
            pages = parse_pdf_document(PDFDocumentInput(document_id=document_id, content=pdf_bytes(texts)))
            for page in pages:
                observation = project_source_for_transport(registry, await registry.resolve(page))
                await runtime.ingestion.submit(
                    SubmitSourceObservation(scope_id=scope.scope_id, observation=observation)
                )
                metadata[observation.name] = (document_id, page.page_number)
    async with open_builtin_runtime(config, candidate_pipeline=_PagePipeline()) as runtime:
        while (await runtime.memory.for_scope(scope.scope_id).flush()).processed:
            pass
    return config, scope.scope_id, metadata


@pytest.mark.parametrize(
    ("question", "text"),
    [
        ("What are liabilities?", "Liability 125."),
        ("What is liability?", "Liabilities 125."),
        ("What companies are listed?", "Company ownership 375."),
        ("Which company is listed?", "Companies ownership 375."),
        ("What are expenses?", "Expense 500."),
        ("What is the expense?", "Expenses 500."),
        ("How much D&A?", "Depreciation and amortization 625."),
        ("How much depreciation and amortization?", "D&A 625."),
        ("How much PP&E?", "Property plant and equipment 750."),
        ("How much property plant and equipment?", "PP&E 750."),
        ("What is EPS?", "Earnings per share 875."),
        ("What are earnings per share?", "EPS 875."),
        ("What are revenues?", "Revenue 250."),
        ("What is revenue?", "Revenues 250."),
        ("What is CapEx?", "Capital expenditures 1000."),
        ("What is EBITDA?", "Operating income 1000. Depreciation amortization 250."),
        (
            "Outline historical strategic context general corporate narrative overview qualitative aspects background "
            "discussion outlook broad directional regional patterns multiple categories pension obligation",
            "Pension obligation 1125.",
        ),
    ],
)
@_async_test
async def test_query_forms_retrieve_real_persisted_page(tmp_path: Path, question: str, text: str):
    config, scope, locations = await _persist(tmp_path, {"ledger": (text, "Supplier inventory appendix.")})
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope)
        citations = await search_pdf_pages(memory, question, 20)
        found = set()
        for citation in citations:
            record = await memory.get(GetMemoryEntryRequest(citation=citation))
            found.update(locations[source.source_id] for source in record.entry.sources)
        assert ("ledger", 1) in found


@_async_test
async def test_requested_issuer_signal_survives_reranking(tmp_path: Path):
    distractor = "Pension obligation " * 12
    config, scope, locations = await _persist(
        tmp_path,
        {
            "Lyra_2025_10K": (distractor,) * 25,
            "Vega_2025_10K": (distractor,) * 25,
            "Orion_2025_10K": ("Pension obligation 1250.",),
        },
    )
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope)
        citations = await search_pdf_pages(memory, "What is the pension obligation reported by Orion?", 20)
        found = set()
        for citation in citations:
            record = await memory.get(GetMemoryEntryRequest(citation=citation))
            found.update(locations[source.source_id] for source in record.entry.sources)
        assert ("Orion_2025_10K", 1) in found


@_async_test
async def test_numeric_account_evidence_is_not_replaced_by_policy_mentions(tmp_path: Path):
    policy = "Accounting policies discuss operating income recognition and depreciation amortization principles. " * 4
    config, scope, locations = await _persist(
        tmp_path,
        {"ledger": ("Operating income 128528.", "Depreciation and amortization other 34153.", *((policy,) * 25))},
    )
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope)
        citations = await search_pdf_pages(
            memory, "Which statement pages supply EBITDA from operating results and D&A?", 20
        )
        found = set()
        for citation in citations:
            record = await memory.get(GetMemoryEntryRequest(citation=citation))
            found.update(locations[source.source_id] for source in record.entry.sources)
        assert {("ledger", 1), ("ledger", 2)} <= found


@_async_test
async def test_original_query_and_bounded_public_search_work(tmp_path: Path):
    config, scope, _ = await _persist(tmp_path, {"ledger": ("Operating income 1234. Depreciation amortization 56.",)})
    question = "Compare D&A PP&E EPS CapEx EBITDA revenue debt legal cash flow and pension obligation across years"
    async with open_builtin_runtime(config) as runtime:
        real = runtime.memory.for_scope(scope)
        calls = []

        class CountedMemory:
            async def search(self, request):
                calls.append(request)
                return await real.search(request)

            async def get(self, request):
                return await real.get(request)

        await search_pdf_pages(cast("ScopedMemoryApplication", CountedMemory()), question, 20)
        assert calls[0].query == question
        assert len(calls) <= 16
        assert all(request.limit <= 80 for request in calls)
        keys = [" ".join(request.query.split()).casefold() for request in calls]
        assert len(keys) == len(set(keys))


@pytest.mark.parametrize(
    ("question", "text"),
    [
        ("What was revenue?", "Turnover 1250."),
        ("What was cash flow?", "Cashflow 1250."),
        ("What are the geographies?", "Countries 1250."),
        ("Are there legal matters?", "Lawsuits 1250."),
        ("What were restructuring costs?", "Reorganisation 1250."),
        ("What were receivables?", "Debtors 1250."),
        ("What were payables?", "Creditors 1250."),
        ("What was inventory?", "Stock 1250."),
        ("Which pages discuss revenue, debt or inventory for reporting companies?", "Stock 1250."),
    ],
)
@_async_test
async def test_later_concept_alias_retrieves_real_page(tmp_path: Path, question: str, text: str):
    config, scope, locations = await _persist(tmp_path, {"ledger": (text, "Supplier appendix.")})
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope)
        citations = await search_pdf_pages(memory, question, 20)
        found = set()
        for citation in citations:
            record = await memory.get(GetMemoryEntryRequest(citation=citation))
            found.update(locations[source.source_id] for source in record.entry.sources)
        assert ("ledger", 1) in found


@pytest.mark.parametrize("accounts", ["EBITDA D&A PP&E", "EBITDA PP&E EPS", "EBITDA D&A PP&E EPS CapEx"])
@_async_test
async def test_alias_budget_preserves_late_financial_term(tmp_path: Path, accounts: str):
    question = (
        "Outline historical strategic context general corporate narrative overview qualitative aspects background "
        f"discussion outlook broad directional regional patterns multiple categories {accounts} and pension obligation"
    )
    config, scope, locations = await _persist(tmp_path, {"ledger": ("Pension obligation 1250.", "Supplier appendix.")})
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope)
        citations = await search_pdf_pages(memory, question, 20)
        found = set()
        for citation in citations:
            record = await memory.get(GetMemoryEntryRequest(citation=citation))
            found.update(locations[source.source_id] for source in record.entry.sources)
        assert ("ledger", 1) in found


@pytest.mark.parametrize(
    ("question", "texts"),
    [
        ("legal battles", ("Legal overview 1250.", "Battles overview 1250.")),
        ("cash flow rivalry", ("Cash flow overview 1250.", "Cash rivalry overview 1250.")),
    ],
)
@_async_test
async def test_topic_breaks_close_relevance_tie(tmp_path: Path, question: str, texts: tuple[str, ...]):
    config, scope, locations = await _persist(tmp_path, {"ledger": texts})
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope)
        hits = await memory.search(SearchMemoryRequest(query="overview", limit=20, mode="fts"))
        candidates = []
        for hit in hits.hits:
            citation = MemoryCitation(
                memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id
            )
            record = await memory.get(GetMemoryEntryRequest(citation=citation))
            source_id = record.entry.sources[0].source_id
            page = locations[source_id][1]
            # A controlled, tiny score difference tests the bonus with real references.
            candidates.append(
                pdf_pages._Candidate(record.citation, source_id, record.entry.text.partition("\n")[2], float(page == 2))
            )
        ordered = pdf_pages._rank_body(candidates, question)
        assert locations[ordered[0].source_id] == ("ledger", 1)
        assert (await memory.get(GetMemoryEntryRequest(citation=ordered[0].citation))).citation == ordered[0].citation


@pytest.mark.parametrize(
    ("question", "text"),
    [
        ("revenue", "Sales"),
        ("debt", "Borrowings"),
        ("geographies", "Countries"),
        ("legal", "Litigation"),
        ("restructuring", "Reorganisation"),
        ("receivables", "Debtors"),
        ("payables", "Creditors"),
        ("inventory", "Stock"),
        ("cash flow", "CASH-FLOWS"),
        ("capital expenditures", "CapEx"),
        ("EBITDA", "D & A"),
        ("income statement", "Income-statements"),
    ],
)
def test_topic_normalization_matches_aliases(question: str, text: str):
    assert pdf_pages._matched_concepts(question) & pdf_pages._matched_concepts(text)


@pytest.mark.parametrize(
    ("question", "text"),
    [
        ("legal", "illegal"),
        ("debt", "debtors"),
        ("cash flow", "cash flower"),
        ("sales", "wholesales"),
        ("inventory", "stocks and bonds"),
        ("sales", "sale of assets"),
    ],
)
def test_topic_boundaries_reject_substrings(question: str, text: str):
    assert not pdf_pages._matched_concepts(question) & pdf_pages._matched_concepts(text)


def test_topic_aliases_and_repetitions_count_once():
    question = pdf_pages._matched_concepts("revenue revenues sales turnover")
    body = pdf_pages._matched_concepts("Sales turnover revenue revenues. " * 10)
    assert len(question & body) == 1
