"""Implementation of the ``RemarkableSync notebooklm-bundle`` command.

Packages a directory of converted notebooks into an upload-ready bundle
for Google NotebookLM. NotebookLM does not currently expose a public
ingestion API, so the user must drag-and-drop the resulting folder
into a NotebookLM project manually.

For each input PDF the bundle prefers, in order:

  1. ``<name>_text.pdf`` — the OCR text PDF (best signal for NotebookLM).
  2. ``<name>.pdf`` — the original graphical PDF (NotebookLM will OCR
     it server-side, but accuracy is lower for handwriting).

A ``manifest.md`` index is written at the bundle root listing every
included document with its source path and approximate size.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ..utils.logging import setup_logging


# NotebookLM's documented per-source upload limits, as of plan date.
# These are conservative; raise via --max-mb if Google later relaxes them.
_DEFAULT_MAX_MB = 200


@dataclass(frozen=True)
class BundleEntry:
    """A single document selected into the bundle."""

    source: Path
    relative_dest: Path
    size_bytes: int
    is_ocr: bool


def run_notebooklm_bundle_command(
    pdf_dir: Path,
    output_dir: Path,
    notebook: Optional[str],
    max_mb: int,
    verbose: bool,
    prefer_ocr: bool = True,
) -> int:
    """Execute the ``notebooklm-bundle`` command.

    Args:
        pdf_dir: Directory containing PDFs (and optionally ``_text.pdf``
            files produced by ``ocr``).
        output_dir: Destination directory for the bundle.
        notebook: When set, only include documents whose stem contains
            this substring.
        max_mb: Skip files larger than this size (in MB).
        verbose: Enable DEBUG logging.
        prefer_ocr: When True (default), prefer ``<name>_text.pdf`` over
            ``<name>.pdf`` for each notebook. Set to False to bundle the
            original graphical PDFs instead.

    Returns:
        Process exit code.
    """
    setup_logging(verbose)

    if not pdf_dir.exists():
        print(f"[ERROR] PDF directory not found: {pdf_dir}")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    entries = _select_entries(pdf_dir, notebook, max_mb, prefer_ocr)
    if not entries:
        print(f"[WARN] No documents found under {pdf_dir}")
        return 0

    print(f"Bundling {len(entries)} document(s) into {output_dir}")
    for entry in entries:
        dest = output_dir / entry.relative_dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(entry.source, dest)
        except OSError as exc:
            logging.error("Failed to copy %s: %s", entry.source, exc)
            return 2

    manifest_path = output_dir / "manifest.md"
    manifest_path.write_text(_render_manifest(entries, pdf_dir), encoding="utf-8")

    print(f"Wrote bundle manifest: {manifest_path}")
    print(
        "\nNext step: open NotebookLM (https://notebooklm.google.com), create "
        "a new notebook, and upload the contents of this directory as sources."
    )
    return 0


def _select_entries(
    pdf_dir: Path,
    notebook: Optional[str],
    max_mb: int,
    prefer_ocr: bool,
) -> List[BundleEntry]:
    """Select one PDF per notebook stem, honouring OCR preference and size."""
    max_bytes = max_mb * 1024 * 1024

    # Group by "logical" stem (strip the trailing ``_text`` suffix so the
    # OCR variant and its source are recognised as the same document).
    by_stem: dict[Path, dict[str, Path]] = {}
    for path in sorted(pdf_dir.rglob("*.pdf")):
        relative_dir = path.parent.relative_to(pdf_dir)
        is_ocr = path.stem.endswith("_text")
        logical_stem = path.stem[:-5] if is_ocr else path.stem
        key = relative_dir / logical_stem
        slot = by_stem.setdefault(key, {})
        slot["ocr" if is_ocr else "graphic"] = path

    selected: List[BundleEntry] = []
    for key, variants in by_stem.items():
        chosen, is_ocr = _pick_variant(variants, prefer_ocr)
        if chosen is None:
            continue
        if notebook and notebook not in key.name:
            continue

        size = chosen.stat().st_size
        if size > max_bytes:
            logging.warning(
                "Skipping %s: %.1f MB exceeds --max-mb=%d",
                chosen.name,
                size / 1024 / 1024,
                max_mb,
            )
            continue

        # Place every document at the bundle root with its logical name to
        # keep NotebookLM's source list flat and human-readable.
        selected.append(
            BundleEntry(
                source=chosen,
                relative_dest=Path(f"{key.name}.pdf"),
                size_bytes=size,
                is_ocr=is_ocr,
            )
        )

    return selected


def _pick_variant(variants: dict, prefer_ocr: bool):
    """Pick the OCR or graphical variant per the caller's preference."""
    if prefer_ocr and "ocr" in variants:
        return variants["ocr"], True
    if "graphic" in variants:
        return variants["graphic"], False
    if "ocr" in variants:
        return variants["ocr"], True
    return None, False


def _render_manifest(entries: List[BundleEntry], pdf_dir: Path) -> str:
    lines = [
        "# RemarkableSync NotebookLM Bundle",
        "",
        f"Source directory: `{pdf_dir}`",
        f"Documents: {len(entries)}",
        "",
        "| File | Type | Size | Original |",
        "| ---- | ---- | ---- | -------- |",
    ]
    for entry in sorted(entries, key=lambda e: str(e.relative_dest)):
        kind = "OCR text" if entry.is_ocr else "Graphical"
        size_kb = entry.size_bytes / 1024
        size_label = (
            f"{size_kb / 1024:.1f} MB"
            if size_kb > 1024
            else f"{size_kb:.0f} KB"
        )
        try:
            original = entry.source.relative_to(pdf_dir)
        except ValueError:
            original = entry.source
        lines.append(
            f"| `{entry.relative_dest}` | {kind} | {size_label} | `{original}` |"
        )
    lines.append("")
    lines.append(
        "_Upload these files as sources in a NotebookLM project. "
        "OCR text PDFs give the best retrieval quality for handwritten notes._"
    )
    return "\n".join(lines)
