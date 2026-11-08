"""Document parsing for PDF / PPTX / Markdown / TXT.

Parsers extract ordered pages/slides/sections of plain text. Scanned PDFs
(no extractable text) are flagged ``ocr_required=True`` instead of pretending
to have parsed successfully.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".pptx", ".md", ".markdown", ".txt"}

# Below this many extracted characters, classification is skipped
# (insufficient_text) rather than guessed from a filename.
MIN_TEXT_CHARS = 50

PAGE_NUMBER_ONLY_RE = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")


@dataclass
class ParsedPage:
    page_number: int
    text: str
    section: str | None = None  # detected heading/slide title


@dataclass
class ParseResult:
    pages: list[ParsedPage] = field(default_factory=list)
    ocr_required: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def total_chars(self) -> int:
        return sum(len(p.text.strip()) for p in self.pages)


class UnsupportedFileTypeError(ValueError):
    pass


class ParseError(RuntimeError):
    pass


def parse_bytes(filename: str, data: bytes) -> ParseResult:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(f"unsupported file type: {ext or '(none)'}")
    if ext == ".pdf":
        return _parse_pdf(data)
    if ext == ".pptx":
        return _parse_pptx(data)
    return _parse_text(filename, data)


def _parse_pdf(data: bytes) -> ParseResult:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # pragma: no cover - malformed input
        raise ParseError(f"PDF open failed: {exc}") from exc
    pages: list[ParsedPage] = []
    total_chars = 0
    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        total_chars += len(text.strip())
        pages.append(ParsedPage(page_number=idx, text=text.strip()))
    result = ParseResult(pages=pages)
    if total_chars == 0:
        # No extractable text: likely a scanned PDF.
        result.ocr_required = True
        result.warnings.append("no extractable text layer; OCR required")
    return result


def _shape_texts(shape, out: list[str]) -> None:
    """Collect text from a shape, recursing into groups and tables.

    python-pptx does not surface text inside grouped shapes or tables via
    ``has_text_frame``; real-world decks put most content there.
    """
    try:
        if shape.shape_type == 6:  # MSO_SHAPE_TYPE.GROUP
            for sub in shape.shapes:
                _shape_texts(sub, out)
            return
    except Exception:  # pragma: no cover - shape type introspection varies  # noqa: S110, BLE001
        pass
    if getattr(shape, "has_table", False) and shape.table is not None:
        for row in shape.table.rows:
            for cell in row.cells:
                text = cell.text.strip()
                if text:
                    out.append(text)
        return
    if shape.has_text_frame:
        text = shape.text_frame.text.strip()
        if text:
            out.append(text)


def _pptx_title(parts: list[str]) -> str | None:
    """First short text block is treated as the slide title when the deck
    has no real title placeholder."""
    for part in parts:
        line = part.split("\n")[0].strip()
        if not line or PAGE_NUMBER_ONLY_RE.match(line):
            continue
        if len(line) <= 60:
            return line
        return None
    return None


def _parse_pptx(data: bytes) -> ParseResult:
    from pptx import Presentation

    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as exc:  # pragma: no cover
        raise ParseError(f"PPTX open failed: {exc}") from exc
    pages: list[ParsedPage] = []
    total_chars = 0
    for idx, slide in enumerate(prs.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            _shape_texts(shape, parts)
        if not parts:
            pages.append(ParsedPage(page_number=idx, text=""))
            continue
        joined = "\n".join(parts).replace("\x0b", "\n").replace("\r", "\n")
        title = None
        try:
            if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
                title = slide.shapes.title.text_frame.text.strip() or None
        except Exception:  # pragma: no cover - deck without title placeholder  # noqa: BLE001
            title = None
        if title is None:
            title = _pptx_title(parts)
        total_chars += len(joined.strip())
        pages.append(ParsedPage(page_number=idx, text=joined, section=title))
    if not pages:
        raise ParseError("PPTX contains no slides")
    result = ParseResult(pages=pages)
    if total_chars == 0:
        result.warnings.append("PPTX 没有提取到任何文本（内容可能全部为图片）")
    return result


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")


def _parse_text(filename: str, data: bytes) -> ParseResult:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("gb18030")
        except UnicodeDecodeError as exc:  # pragma: no cover
            raise ParseError("text file is not valid UTF-8 or GB18030") from exc
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    pages: list[ParsedPage] = []
    current_section: str | None = None
    page_text: list[str] = []

    def flush(page_no: int) -> None:
        nonlocal page_text
        if page_text:
            pages.append(
                ParsedPage(
                    page_number=page_no,
                    text="\n".join(page_text).strip(),
                    section=current_section,
                )
            )
        page_text = []

    page_no = 1
    for line in text.split("\n"):
        m = _MD_HEADING.match(line)
        if m:
            flush(page_no)
            current_section = m.group(2).strip()
            page_no += 1
            page_text.append(line)
            continue
        if not line.strip():
            if page_text:
                flush(page_no)
                page_no += 1
            continue
        page_text.append(line)
    flush(page_no)
    if not pages and text.strip():
        pages.append(ParsedPage(page_number=1, text=text.strip()))
    return ParseResult(pages=pages)
