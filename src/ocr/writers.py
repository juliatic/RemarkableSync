"""Render an :class:`OCRResult` to disk in various formats.

Outputs are intentionally simple — one page per source page, plain
single-column text — because the goal is to feed the result into search
indexes, NotebookLM, or grep. We do *not* try to position recognised
text underneath the original strokes; users who need that should run a
dedicated tool such as ``ocrmypdf``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from .base import OCRResult

logger = logging.getLogger(__name__)


_PAGE_WIDTH, _PAGE_HEIGHT = LETTER
_MARGIN = 54  # 0.75 inch
_LINE_HEIGHT = 12
_FONT_NAME = "Helvetica"
_FONT_SIZE = 10


def write_text_pdf(result: OCRResult, output_pdf: Path) -> bool:
    """Write a text-only PDF with one page per source page.

    Args:
        result: OCR result to render.
        output_pdf: Path where the PDF should be created.

    Returns:
        ``True`` on success, ``False`` otherwise.
    """
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    try:
        c = canvas.Canvas(str(output_pdf), pagesize=LETTER)
        c.setTitle(f"OCR: {result.source_pdf.stem}")
        c.setSubject(f"OCR via {result.backend_name}")

        for page in result.pages:
            _draw_page_header(c, page.page_number, page.confidence)
            _draw_page_body(c, page.text)
            c.showPage()

        if not result.pages:
            # Always emit at least one page so downstream tools see the file.
            _draw_page_header(c, 1, None)
            _draw_page_body(c, "(no text recognised)")
            c.showPage()

        c.save()
        return output_pdf.exists() and output_pdf.stat().st_size > 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write OCR text PDF %s: %s", output_pdf, exc)
        return False


def write_text_sidecar(result: OCRResult, output_path: Path) -> bool:
    """Write the OCR result as a plain ``.txt`` file."""
    return _write_file(
        output_path,
        _format_plain(result.pages),
    )


def write_markdown_sidecar(result: OCRResult, output_path: Path) -> bool:
    """Write the OCR result as a Markdown file with per-page headings."""
    return _write_file(
        output_path,
        _format_markdown(result),
    )


# ---------------------------------------------------------------------------


def _draw_page_header(c: canvas.Canvas, page_number: int, confidence) -> None:
    c.setFont("Helvetica-Bold", _FONT_SIZE)
    suffix = (
        f"  (confidence {confidence:.0%})"
        if confidence is not None
        else ""
    )
    c.drawString(
        _MARGIN,
        _PAGE_HEIGHT - _MARGIN,
        f"Page {page_number}{suffix}",
    )


def _draw_page_body(c: canvas.Canvas, text: str) -> None:
    c.setFont(_FONT_NAME, _FONT_SIZE)
    y = _PAGE_HEIGHT - _MARGIN - 2 * _LINE_HEIGHT
    for line in (text or "").splitlines() or ["(no text recognised)"]:
        if y < _MARGIN:
            c.showPage()
            c.setFont(_FONT_NAME, _FONT_SIZE)
            y = _PAGE_HEIGHT - _MARGIN
        # Naive wrapping: reportlab will not wrap on its own.
        for chunk in _wrap(line, max_chars=110):
            c.drawString(_MARGIN, y, chunk)
            y -= _LINE_HEIGHT


def _wrap(line: str, max_chars: int) -> Iterable[str]:
    if not line:
        yield ""
        return
    words = line.split(" ")
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            yield current
            current = word
        else:
            current = candidate
    if current:
        yield current


def _format_plain(pages) -> str:
    parts = []
    for page in pages:
        parts.append(f"--- Page {page.page_number} ---")
        parts.append(page.text or "(no text recognised)")
        parts.append("")
    return "\n".join(parts)


def _format_markdown(result: OCRResult) -> str:
    parts = [
        f"# OCR: {result.source_pdf.stem}",
        f"_Backend: {result.backend_name}_",
        "",
    ]
    for page in result.pages:
        parts.append(f"## Page {page.page_number}")
        if page.confidence is not None:
            parts.append(f"_Confidence: {page.confidence:.0%}_")
            parts.append("")
        parts.append(page.text or "_(no text recognised)_")
        parts.append("")
    return "\n".join(parts)


def _write_file(path: Path, content: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return True
    except OSError as exc:
        logger.warning("Failed to write %s: %s", path, exc)
        return False
