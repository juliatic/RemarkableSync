"""OCR backend interface and shared data types."""

from __future__ import annotations

import logging
import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class OCRBackendUnavailable(RuntimeError):
    """Raised when an OCR backend cannot be initialised on this host.

    Carries a short human-readable reason so the CLI can suggest the
    missing system or Python dependency.
    """


@dataclass(frozen=True)
class OCRPage:
    """OCR result for a single page.

    Attributes:
        page_number: 1-based page index in the source PDF.
        text: Recognised text as a single string with embedded newlines.
            Empty string when no text was found.
        confidence: Average per-token confidence in ``[0.0, 1.0]`` when
            the backend exposes it, else ``None``.
    """

    page_number: int
    text: str
    confidence: Optional[float] = None


@dataclass
class OCRResult:
    """Result of OCR-ing a complete PDF document."""

    source_pdf: Path
    pages: List[OCRPage] = field(default_factory=list)
    backend_name: str = ""

    @property
    def is_empty(self) -> bool:
        return not any(page.text.strip() for page in self.pages)

    def joined_text(self, page_separator: str = "\n\n") -> str:
        """Return all page text joined with ``page_separator``."""
        return page_separator.join(page.text for page in self.pages)


class OCRBackend(ABC):
    """Abstract OCR backend.

    Concrete backends are instantiated lazily so that missing optional
    dependencies (``pyobjc`` for Apple Vision, ``pytesseract`` /
    ``pdf2image`` for Tesseract) do not break import of this module on
    hosts where those backends are not available.
    """

    name: str = "base"

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"ocr.{self.name}")

    @abstractmethod
    def is_available(self) -> bool:
        """Return True when the backend can run on this host."""

    @abstractmethod
    def recognize_pdf(self, pdf_path: Path) -> OCRResult:
        """OCR every page of ``pdf_path`` and return the result.

        Implementations must raise :class:`OCRBackendUnavailable` if the
        underlying engine cannot be loaded.
        """


def discover_backend(preferred: Optional[str] = None) -> OCRBackend:
    """Return the best available OCR backend on this host.

    Args:
        preferred: Optional explicit choice (``"vision"``, ``"tesseract"``).
            When set, the named backend is returned even if not available
            (callers may then call ``is_available()`` to short-circuit).
            When ``None``, prefer Apple Vision on macOS, otherwise
            fall back to Tesseract.

    Returns:
        An :class:`OCRBackend` instance. Caller should still verify
        ``is_available()`` before invoking ``recognize_pdf``.

    Raises:
        OCRBackendUnavailable: if no backend can be loaded.
    """
    # Local imports avoid pulling pyobjc / pytesseract at package import time.
    from .tesseract import TesseractBackend  # noqa: WPS433
    from .vision import AppleVisionBackend  # noqa: WPS433

    if preferred == "vision":
        return AppleVisionBackend()
    if preferred == "tesseract":
        return TesseractBackend()

    if platform.system() == "Darwin":
        backend: OCRBackend = AppleVisionBackend()
        if backend.is_available():
            return backend

    backend = TesseractBackend()
    if backend.is_available():
        return backend

    raise OCRBackendUnavailable(
        "No OCR backend available. Install pyobjc-framework-Vision (macOS) "
        "or pytesseract + tesseract + pdf2image."
    )
