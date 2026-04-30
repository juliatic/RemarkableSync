"""OCR pipeline for converted reMarkable notebooks.

This package provides a pluggable OCR backend interface plus two ready
backends (Apple Vision on macOS, Tesseract elsewhere) and helpers for
emitting OCR output as a separate text-only PDF and/or sidecar text/
markdown files alongside the original graphical PDF.

The on-device reMarkable handwriting recogniser is not exposed over SSH
(it lives inside ``xochitl`` and only round-trips through the cloud /
myScript), so this pipeline runs locally.
"""

from .base import (
    OCRBackend,
    OCRPage,
    OCRResult,
    OCRBackendUnavailable,
    discover_backend,
)

__all__ = [
    "OCRBackend",
    "OCRPage",
    "OCRResult",
    "OCRBackendUnavailable",
    "discover_backend",
]
