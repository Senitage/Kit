"""A file as text, page by page: PDFs through pypdf, Word through python-docx (tables
as tab-separated rows), spreadsheets through openpyxl (a page per sheet), slides
through python-pptx (a page per slide), and plain text read as UTF-8. Each library
is imported only when needed; a missing one raises ``Unavailable`` so the indexer
can record it and carry on. Install them with ``pip install -e ".[files]"``."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

PACKAGES = {
    "pdf": ("pypdf", "pypdf"),
    "docx": ("docx", "python-docx"),
    "xlsx": ("openpyxl", "openpyxl"),
    "pptx": ("pptx", "python-pptx"),
}
SCANNED_CHARS = 50  # a PDF page with less text than this is probably a scan


@dataclass(frozen=True)
class Page:
    number: int  # from 1; a sheet or slide number for those
    text: str
    title: str = ""  # a sheet's name


class Unavailable(Exception):
    """The library for a kind of file isn't installed."""

    def __init__(self, kind: str, package: str) -> None:
        super().__init__(f'reading {kind} files needs {package} (pip install -e ".[files]")')
        self.kind = kind
        self.package = package


def available() -> dict[str, bool]:
    """Which file libraries are installed, by package name, for ``kit check``."""
    import importlib.util

    return {pkg: importlib.util.find_spec(mod) is not None for mod, pkg in PACKAGES.values()}


def _need(kind: str):
    import importlib

    module, package = PACKAGES[kind]
    try:
        return importlib.import_module(module)
    except ImportError as e:
        raise Unavailable(kind, package) from e


def extract(path: Path, kind: str, ocr: bool = False, max_rows: int = 2000) -> list[Page]:
    if kind == "pdf":
        return _pdf(path, ocr)
    if kind == "docx":
        return _docx(path)
    if kind == "xlsx":
        return _xlsx(path, max_rows)
    if kind == "pptx":
        return _pptx(path)
    return [Page(1, path.read_text(encoding="utf-8", errors="replace"))]


def _pdf(path: Path, ocr: bool) -> list[Page]:
    pypdf = _need("pdf")
    reader = pypdf.PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        if ocr and len(text.strip()) < SCANNED_CHARS:
            text = _ocr_page(path, i) or text
        pages.append(Page(i, text))
    return pages


def _ocr_page(path: Path, number: int) -> str:
    """One page of a scan read by OCR, or "" when the OCR extras aren't there."""
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError:
        log.info('no OCR for %s page %d: pip install -e ".[ocr]"', path.name, number)
        return ""
    try:
        images = convert_from_path(str(path), first_page=number, last_page=number)
        return "\n".join(pytesseract.image_to_string(img) for img in images)
    except Exception as e:  # tesseract or poppler missing, or a bad page
        log.info("OCR failed on %s page %d: %s", path.name, number, e)
        return ""


def _docx(path: Path) -> list[Page]:
    docx = _need("docx")
    doc = docx.Document(str(path))
    lines = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            lines.append("\t".join(cell.text.strip() for cell in row.cells))
    return [Page(1, "\n\n".join(line for line in lines if line.strip()))]


def _xlsx(path: Path, max_rows: int) -> list[Page]:
    openpyxl = _need("xlsx")
    book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    pages = []
    try:
        for i, sheet in enumerate(book.worksheets, 1):
            rows = []
            for n, row in enumerate(sheet.iter_rows(values_only=True)):
                if n >= max_rows:
                    break
                cells = ["" if v is None else str(v) for v in row]
                if any(cells):
                    rows.append("\t".join(cells).rstrip())
            pages.append(Page(i, "\n".join(rows), sheet.title))
    finally:
        book.close()
    return pages


def _pptx(path: Path) -> list[Page]:
    pptx = _need("pptx")
    deck = pptx.Presentation(str(path))
    pages = []
    for i, slide in enumerate(deck.slides, 1):
        texts = [
            shape.text_frame.text
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip()
        ]
        pages.append(Page(i, "\n".join(texts)))
    return pages
