from __future__ import annotations

import asyncio
import hashlib
import io
import re
from collections.abc import Callable, Coroutine
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, ParamSpec, cast

import pytest
from pydantic import ValidationError
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from powercontext.sources import SourceDefinitionRegistry, SourceMaterialization, project_source_for_transport
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    PDFPageInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import ScopedMemoryApplication


P = ParamSpec("P")


def _async_test(function: Callable[P, Coroutine[Any, Any, None]]) -> Callable[P, None]:
    @wraps(function)
    def run(*args: P.args, **kwargs: P.kwargs) -> None:
        asyncio.run(function(*args, **kwargs))

    return run


def pdf_bytes(texts: tuple[str, ...], *, password: str | None = None) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if text:
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
            })
            content = DecodedStreamObject()
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content.set_data(f"BT /F1 11 Tf 40 700 Td ({escaped}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(content)
    if password is not None:
        writer.encrypt(password, owner_password="owner")  # noqa: S106 -- synthetic encrypted fixture
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_parse_all_physical_pages_digest_and_numbers():
    raw = pdf_bytes(("Sales 2025: 12,345. Footnote 7.", "", "Debt 2024: 6,789."))
    pages = parse_pdf_document(PDFDocumentInput(document_id="financial report", content=raw))
    assert isinstance(pages, tuple)
    assert [p.page_number for p in pages] == [1, 2, 3]
    assert all(p.document_sha256 == hashlib.sha256(raw).hexdigest() for p in pages)
    assert "12,345" in pages[0].text and "Footnote 7" in pages[0].text
    assert pages[1].text == ""
    assert "6,789" in pages[2].text and "6,789" not in pages[0].text
    originals = ("Sales 2025: 12,345. Footnote 7.", "", "Debt 2024: 6,789.")
    for page, original in zip(pages, originals, strict=True):
        assert re.findall(r"[a-z]+|\d+", page.text.lower()) == re.findall(r"[a-z]+|\d+", original.lower())


@pytest.mark.parametrize("raw", [b"", b"not pdf", b"%PDF-1.7\ntruncated", pdf_bytes(("test",))[:-20]])
def test_invalid_pdf_is_value_error(raw):
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="report", content=raw))


def test_broken_xref_is_not_silently_repaired():
    raw = re.sub(rb"startxref\s+\d+", b"startxref\n0", pdf_bytes(("untrusted xref",)))
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="corrupt", content=raw))


@pytest.mark.parametrize("document_id", ["", "  ", "\n\t"])
def test_blank_document_id_rejected(document_id):
    with pytest.raises(ValueError):
        PDFDocumentInput(document_id=document_id, content=pdf_bytes(("",)))


def test_empty_password_permission_and_required_password():
    assert parse_pdf_document(PDFDocumentInput(document_id="open", content=pdf_bytes(("Visible 123",), password="")))[
        0
    ].text
    with pytest.raises(ValueError):
        parse_pdf_document(
            PDFDocumentInput(
                document_id="locked",
                content=pdf_bytes(
                    ("secret",),
                    password="required",  # noqa: S106
                ),
            )
        )


@_async_test
async def test_captured_identity_revision_and_standard_projection():
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    page = PDFPageInput(document_id="report|页" * 500, document_sha256="a" * 64, page_number=12, text="Revenue 14")
    source = await registry.resolve(page)
    assert source.materialization == SourceMaterialization.CAPTURED
    assert len(source.name) <= 256
    assert (await registry.resolve(page)).name == source.name
    assert await registry.read(source) == page
    for updated in (
        page.model_copy(update={"document_id": page.document_id + "x"}),
        page.model_copy(update={"document_sha256": "b" * 64}),
        page.model_copy(update={"page_number": 13}),
    ):
        assert (await registry.resolve(updated)).name != source.name
    projected = project_source_for_transport(registry, source).projection(TEXT_EVIDENCE_PROJECTION_KEY)
    assert projected == {
        "source_type": "pdf-page",
        "source_id": source.name,
        "content": page.document_id + "\n" + page.text,
        "metadata": {"document_id": page.document_id, "document_sha256": page.document_sha256, "page_number": 12},
    }
    assert await registry.read(source) == page


@pytest.mark.parametrize("updates", [{"page_number": 0}, {"page_number": True}, {"document_sha256": "A" * 64}])
def test_page_validation(updates):
    with pytest.raises(ValidationError):
        PDFPageInput(**({"document_id": "a", "document_sha256": "a" * 64, "page_number": 1, "text": ""} | updates))


@_async_test
async def test_zero_limit_and_blank_question_do_not_create_citations():
    unused_memory = cast("ScopedMemoryApplication", None)
    assert await search_pdf_pages(unused_memory, "Revenue", limit=0) == ()
    assert await search_pdf_pages(unused_memory, "  ", limit=20) == ()
    with pytest.raises(ValueError):
        await search_pdf_pages(unused_memory, "revenue", limit=-1)


def test_late_page_extraction_failure_is_atomic(monkeypatch):
    from pypdf._page import PageObject

    original = PageObject.extract_text

    def fail_second(page, *args, **kwargs):
        text = original(page, *args, **kwargs)
        if "second" in text:
            raise RuntimeError("broken content decoder")  # noqa: TRY003 -- simulated parser failure
        return text

    monkeypatch.setattr(PageObject, "extract_text", fail_second)
    with pytest.raises(ValueError, match="completely parse"):
        parse_pdf_document(PDFDocumentInput(document_id="broken", content=pdf_bytes(("first", "second"))))


@_async_test
async def test_runtime_restart_exact_citations_scopes_and_limits(tmp_path: Path):
    from powercontext.builtin.artifacts.memory import MemoryEntryInput
    from powercontext.builtin.persistence.sqlite import SQLiteConfig
    from powercontext.builtin.runtime import (
        BuiltinConfig,
        GetMemoryEntryRequest,
        RememberMemoryRequest,
        SubmitSourceObservation,
        open_builtin_contexts,
        open_builtin_runtime,
    )
    from powercontext.builtin.scope import ScopeDraft
    from powercontext.sources import SourceObservation, manifest_for_definition

    class Pipeline:
        async def extract(self, request, /):
            return tuple(
                MemoryEntryInput(
                    kind="source-evidence",
                    text=source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"],
                    sources=(source,),
                )
                for source in request.sources
            )

    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'pdf.db'}"))
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    pages = parse_pdf_document(
        PDFDocumentInput(
            document_id="report",
            content=pdf_bytes((
                "Capital expenditures property equipment 2025 6200.",
                "Legal proceedings litigation claims 2025 700.",
                "Cash flows depreciation amortization 2025 900.",
                "",
                "Net sales revenue 2025 25000.",
            )),
        )
    )
    observations = [project_source_for_transport(registry, await registry.resolve(page)) for page in pages]
    async with open_builtin_runtime(config) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="PDF", summary="test", idempotency_key="pdf"))
        other = await runtime.scopes.create(ScopeDraft(title="Other", summary="test", idempotency_key="other"))
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for observation in (*observations, observations[0]):
            await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope.scope_id, observation=observation))
        foreign_page = PDFPageInput(
            document_id="foreign", document_sha256="f" * 64, page_number=1, text="Magnetar offshore reserves 998877"
        )
        foreign = project_source_for_transport(registry, await registry.resolve(foreign_page))
        await runtime.ingestion.submit(SubmitSourceObservation(scope_id=other.scope_id, observation=foreign))
    async with open_builtin_runtime(config, candidate_pipeline=Pipeline()) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        while (await memory.flush()).processed:
            pass
        while (await runtime.memory.for_scope(other.scope_id).flush()).processed:
            pass
        await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(kind="note", text="capex fake 999999"),)))
    async with open_builtin_contexts(config) as contexts:
        journal = await (await contexts.get(scope.scope_id)).sources.journal.entries()
        assert len(journal) == len(pages)
        stored = {entry.source_ref.source_id: entry.source for entry in journal}
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        for limit in (0, 1, 10, 20):
            citations = await search_pdf_pages(memory, "What are capex and depreciation from cash flows 2025?", limit)
            assert len(citations) <= limit
            seen = set()
            for citation in citations:
                record = await memory.get(GetMemoryEntryRequest(citation=citation))
                assert len(record.entry.sources) == 1
                source = stored[record.entry.sources[0].source_id]
                assert isinstance(source, SourceObservation)
                projection = TextEvidence.model_validate(source.projection(TEXT_EVIDENCE_PROJECTION_KEY))
                assert record.entry.text == projection.content.strip()
                assert projection.metadata["document_id"] == "report"
                assert projection.metadata["document_sha256"] == pages[0].document_sha256
                page_number = projection.metadata["page_number"]
                assert isinstance(page_number, int)
                seen.add(page_number)
            assert len(seen) == len(citations)
            if limit:
                assert citations
        assert await search_pdf_pages(runtime.memory.for_scope(other.scope_id), "capital expenditures", 20) == ()
        assert await search_pdf_pages(memory, "Magnetar", 20) == ()
        assert await search_pdf_pages(runtime.memory.for_scope(other.scope_id), "Magnetar", 20)
        capex = await search_pdf_pages(memory, "capital expenditures", 1)
        legal = await search_pdf_pages(memory, "legal proceedings litigation", 1)
        assert capex[0].entry_id != legal[0].entry_id
