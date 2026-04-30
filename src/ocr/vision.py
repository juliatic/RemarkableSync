"""Apple Vision OCR backend (macOS only).

Uses Quartz (PDFKit / Core Graphics) to render each PDF page to an
in-memory bitmap, then submits each image to ``VNRecognizeTextRequest``
which is the same engine that powers system-wide handwriting and
printed-text recognition. No model download or network call is required.

All Cocoa/Quartz imports are lazy so the rest of the project remains
importable on non-Darwin hosts.
"""

from __future__ import annotations

import logging
import platform
from pathlib import Path
from typing import List, Optional

from .base import OCRBackend, OCRBackendUnavailable, OCRPage, OCRResult

logger = logging.getLogger(__name__)


class AppleVisionBackend(OCRBackend):
    """OCR backend backed by macOS ``VNRecognizeTextRequest``.

    The Vision recognition level is set to *accurate* and language
    correction is enabled, which produces the best handwriting results
    in our testing. Fast mode is available via ``recognition_level``.
    """

    name = "vision"

    def __init__(
        self,
        languages: Optional[List[str]] = None,
        recognition_level: str = "accurate",
        render_dpi: int = 200,
    ) -> None:
        super().__init__()
        self.languages = languages or ["en-US"]
        self.recognition_level = recognition_level
        self.render_dpi = render_dpi
        self._import_error: Optional[str] = None
        self._available: Optional[bool] = None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        if platform.system() != "Darwin":
            self._import_error = "Apple Vision is macOS-only"
            self._available = False
            return False
        try:
            self._load_frameworks()
        except Exception as exc:  # noqa: BLE001
            self._import_error = str(exc)
            self._available = False
            return False
        self._available = True
        return True

    def _load_frameworks(self):
        """Import the pyobjc frameworks lazily; raise on failure."""
        # pylint: disable=import-outside-toplevel
        try:
            import Quartz  # type: ignore
            import Vision  # type: ignore
            from Cocoa import NSURL  # type: ignore
        except ImportError as exc:
            raise OCRBackendUnavailable(
                "pyobjc Vision/Quartz frameworks not installed. "
                "Install with: pip install "
                "pyobjc-framework-Vision pyobjc-framework-Quartz"
            ) from exc
        return Quartz, Vision, NSURL

    # ------------------------------------------------------------------
    # Recognition
    # ------------------------------------------------------------------

    def recognize_pdf(self, pdf_path: Path) -> OCRResult:
        if not self.is_available():
            raise OCRBackendUnavailable(
                self._import_error or "Apple Vision not available"
            )

        Quartz, Vision, NSURL = self._load_frameworks()
        url = NSURL.fileURLWithPath_(str(pdf_path))
        document = Quartz.PDFDocument.alloc().initWithURL_(url)
        if document is None:
            raise RuntimeError(f"Could not open PDF: {pdf_path}")

        result = OCRResult(source_pdf=pdf_path, backend_name=self.name)
        page_count = document.pageCount()
        for index in range(page_count):
            pdf_page = document.pageAtIndex_(index)
            text, confidence = self._ocr_pdf_page(pdf_page, Quartz, Vision)
            result.pages.append(
                OCRPage(
                    page_number=index + 1, text=text, confidence=confidence
                )
            )
            self.logger.debug(
                "Vision OCR page %d/%d: %d chars (conf=%s)",
                index + 1,
                page_count,
                len(text),
                f"{confidence:.2f}" if confidence is not None else "n/a",
            )
        return result

    def _ocr_pdf_page(self, pdf_page, Quartz, Vision):  # type: ignore[no-untyped-def]
        """Rasterise one PDF page and run Vision text recognition."""
        # 1. Render the page to a CGImage at the configured DPI.
        media_box = pdf_page.boundsForBox_(Quartz.kPDFDisplayBoxMediaBox)
        scale = self.render_dpi / 72.0
        width = int(media_box.size.width * scale)
        height = int(media_box.size.height * scale)
        if width <= 0 or height <= 0:
            return "", None

        color_space = Quartz.CGColorSpaceCreateDeviceRGB()
        bitmap_info = (
            Quartz.kCGImageAlphaPremultipliedLast
            | Quartz.kCGBitmapByteOrder32Big
        )
        ctx = Quartz.CGBitmapContextCreate(
            None, width, height, 8, 0, color_space, bitmap_info
        )
        # White background so Vision sees printed-on-paper contrast.
        Quartz.CGContextSetRGBFillColor(ctx, 1.0, 1.0, 1.0, 1.0)
        Quartz.CGContextFillRect(ctx, ((0, 0), (width, height)))
        Quartz.CGContextScaleCTM(ctx, scale, scale)
        pdf_page.drawWithBox_toContext_(Quartz.kPDFDisplayBoxMediaBox, ctx)
        cg_image = Quartz.CGBitmapContextCreateImage(ctx)

        # 2. Configure and run the Vision request synchronously.
        request = Vision.VNRecognizeTextRequest.alloc().init()
        if self.recognition_level == "fast":
            request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelFast)
        else:
            request.setRecognitionLevel_(
                Vision.VNRequestTextRecognitionLevelAccurate
            )
        request.setUsesLanguageCorrection_(True)
        request.setRecognitionLanguages_(self.languages)

        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
            cg_image, None
        )
        success, error = handler.performRequests_error_([request], None)
        if not success:
            self.logger.warning(
                "Vision request failed: %s",
                error.localizedDescription() if error else "unknown",
            )
            return "", None

        observations = request.results() or []
        lines: List[str] = []
        confidences: List[float] = []
        for obs in observations:
            candidates = obs.topCandidates_(1)
            if not candidates:
                continue
            top = candidates[0]
            lines.append(str(top.string()))
            confidences.append(float(top.confidence()))

        text = "\n".join(lines)
        confidence = (
            sum(confidences) / len(confidences) if confidences else None
        )
        return text, confidence
