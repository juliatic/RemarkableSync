"""Tesseract OCR backend (cross-platform fallback).

Renders each PDF page to a PIL image via ``pdf2image`` (which wraps the
``poppler`` binary) and then submits each image to ``pytesseract``.
Both dependencies are optional and imported lazily.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from .base import OCRBackend, OCRBackendUnavailable, OCRPage, OCRResult

logger = logging.getLogger(__name__)


class TesseractBackend(OCRBackend):
    """OCR backend backed by ``tesseract`` via ``pytesseract``.

    Best results are obtained with ``--psm 6`` (assume a uniform block
    of text) and the default English language pack. Pass ``language``
    to use other tesseract language packs (e.g. ``"eng+spa"``).
    """

    name = "tesseract"

    def __init__(self, language: str = "eng", render_dpi: int = 200) -> None:
        super().__init__()
        self.language = language
        self.render_dpi = render_dpi
        self._unavailable_reason: Optional[str] = None

    def is_available(self) -> bool:
        # pylint: disable=import-outside-toplevel
        try:
            import pytesseract  # noqa: F401
            import pdf2image  # noqa: F401
        except ImportError as exc:
            self._unavailable_reason = (
                "Install with: pip install pytesseract pdf2image"
            )
            self.logger.debug("Tesseract backend unavailable: %s", exc)
            return False
        if shutil.which("tesseract") is None:
            self._unavailable_reason = (
                "tesseract binary not found on PATH (install via brew/apt)"
            )
            return False
        return True

    def recognize_pdf(self, pdf_path: Path) -> OCRResult:
        if not self.is_available():
            raise OCRBackendUnavailable(
                self._unavailable_reason or "Tesseract not available"
            )

        # pylint: disable=import-outside-toplevel
        import pytesseract
        from pdf2image import convert_from_path

        result = OCRResult(source_pdf=pdf_path, backend_name=self.name)
        images = convert_from_path(str(pdf_path), dpi=self.render_dpi)
        for index, image in enumerate(images):
            text = pytesseract.image_to_string(
                image, lang=self.language, config="--psm 6"
            )
            result.pages.append(
                OCRPage(page_number=index + 1, text=text.strip())
            )
            self.logger.debug(
                "Tesseract OCR page %d/%d: %d chars",
                index + 1,
                len(images),
                len(text),
            )
        return result
