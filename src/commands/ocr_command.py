"""Implementation of the ``RemarkableSync ocr`` CLI command.

Walks a directory of converted PDFs (the output of ``convert``) and
produces, for each input ``<name>.pdf``:

  * ``<name>_text.pdf`` — a text-only PDF rendered from OCR results
  * optional ``<name>.txt`` — plain text sidecar
  * optional ``<name>.md`` — markdown sidecar with per-page headings

OCR is done locally; no data leaves the machine. On macOS the default
backend is Apple Vision; elsewhere (or if explicitly requested) the
Tesseract backend is used.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from tqdm import tqdm

from ..ocr import OCRBackendUnavailable, discover_backend
from ..ocr.writers import write_markdown_sidecar, write_text_pdf, write_text_sidecar
from ..utils.logging import setup_logging

_VALID_FORMATS = {"pdf", "txt", "md", "all"}


def run_ocr_command(
    pdf_dir: Path,
    output_dir: Optional[Path],
    engine: Optional[str],
    output_formats: List[str],
    verbose: bool,
    notebook: Optional[str] = None,
) -> int:
    """Execute the ``ocr`` command.

    Args:
        pdf_dir: Directory containing PDFs produced by ``convert``.
        output_dir: Directory to write OCR artefacts (defaults to ``pdf_dir``).
        engine: One of ``"vision"``, ``"tesseract"``, or ``None`` for
            auto-detect.
        output_formats: Subset of ``{"pdf", "txt", "md", "all"}``.
        verbose: Enable DEBUG-level logging.
        notebook: When set, only OCR PDFs whose stem matches this string.

    Returns:
        Process exit code (0 on success, non-zero on failure).
    """
    log_path = setup_logging(verbose, log_dir=pdf_dir)

    if not pdf_dir.exists():
        print(f"[ERROR] PDF directory not found: {pdf_dir}")
        return 1

    formats = _normalise_formats(output_formats)
    if not formats:
        print(f"[ERROR] Invalid --format value(s); choose from: " f"{sorted(_VALID_FORMATS)}")
        return 2

    target_dir = output_dir or pdf_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    pdfs = _collect_pdfs(pdf_dir, notebook)
    if not pdfs:
        print(f"[WARN] No PDFs found under {pdf_dir}")
        return 0

    try:
        backend = discover_backend(engine)
    except OCRBackendUnavailable as exc:
        print(f"[ERROR] {exc}")
        return 3

    if not backend.is_available():
        print(f"[ERROR] OCR backend '{backend.name}' is not available on this host.")
        return 3

    print(f"OCR backend: {backend.name}")
    print(f"Processing {len(pdfs)} PDF(s)")

    successes = 0
    with tqdm(pdfs, desc="OCR", unit="pdf") as pbar:
        for pdf_path in pbar:
            pbar.set_postfix_str(pdf_path.stem[:40])
            try:
                result = backend.recognize_pdf(pdf_path)
            except Exception as exc:  # noqa: BLE001
                logging.error("OCR failed for %s: %s", pdf_path, exc)
                continue

            relative = pdf_path.relative_to(pdf_dir)
            base = (target_dir / relative).with_suffix("")
            wrote_any = False

            if "pdf" in formats:
                wrote_any |= write_text_pdf(result, base.with_name(f"{base.name}_text.pdf"))
            if "txt" in formats:
                wrote_any |= write_text_sidecar(result, base.with_suffix(".txt"))
            if "md" in formats:
                wrote_any |= write_markdown_sidecar(result, base.with_suffix(".md"))

            if wrote_any:
                successes += 1

    print(f"\nOCR complete: {successes}/{len(pdfs)} PDFs processed")
    print(f"Log file: {log_path}")
    return 0 if successes > 0 else 1


def _normalise_formats(formats: List[str]) -> List[str]:
    selected: set[str] = set()
    for fmt in formats:
        fmt = fmt.lower()
        if fmt not in _VALID_FORMATS:
            return []
        if fmt == "all":
            selected |= {"pdf", "txt", "md"}
        else:
            selected.add(fmt)
    return sorted(selected)


def _collect_pdfs(pdf_dir: Path, notebook: Optional[str]) -> List[Path]:
    """Find candidate PDFs, skipping previously generated text PDFs."""
    pdfs: List[Path] = []
    for path in sorted(pdf_dir.rglob("*.pdf")):
        if path.stem.endswith("_text"):
            continue
        if notebook and notebook not in path.stem:
            continue
        pdfs.append(path)
    return pdfs
