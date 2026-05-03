"""
Hybrid ReMarkable PDF Converter - Internal Module

This is a helper module providing core conversion functionality.
Do not run directly - use the main RemarkableSync entry point instead.

Entry Point:
    RemarkableSync.py convert [OPTIONS]

This module provides:
- Automatic file version detection by reading .rm file headers
- Batch conversion with progress tracking
- Folder structure preservation matching ReMarkable organization
- PDF merging to create single documents from multi-page notebooks
- Support for v5 format files (rmrl) and v6 format files (rmc)
- Detection and reporting for v4/v3 files (limited support)
"""

import json
import logging
import shutil
import tempfile
import warnings
from pathlib import Path
from typing import Dict, List, Optional

from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

# ReMarkable screen dimensions in PDF points (72 DPI)
# Physical screen is 1404x1872 pixels at 226 DPI
REMARKABLE_WIDTH_POINTS = 1404 * 72 / 226  # ~447.6 pts
REMARKABLE_HEIGHT_POINTS = 1872 * 72 / 226  # ~596.7 pts

# Known file sizes of the rmc "blank skeleton" PDF — produced when rmc
# successfully runs but the .rm file uses a format it cannot parse.
# All PDF structure is present but no paths are drawn.
_RMC_BLANK_SIZES = frozenset({1391, 1394})

# Import modular converter classes
from .converters import V4Converter, V5Converter, V6Converter
from .page_resolver import PageResolver, ResolutionReport, detect_rm_version
from .template_renderer import TemplateRenderer
from .utils.logging import setup_logging

# Suppress warnings from third-party libraries to reduce output noise
warnings.filterwarnings("ignore")


class PageResolutionError(Exception):
    """Raised in strict mode when a notebook has unresolved/missing pages.

    Carries enough structured detail for the CLI to render a useful
    summary without having to re-parse log lines.
    """

    def __init__(
        self,
        notebook_name: str,
        missing_pages: List[str],
        parse_errors: List[str],
    ) -> None:
        self.notebook_name = notebook_name
        self.missing_pages = list(missing_pages)
        self.parse_errors = list(parse_errors)
        details = []
        if missing_pages:
            details.append(f"missing .rm files: {len(missing_pages)}")
        if parse_errors:
            details.append(f"parse errors: {len(parse_errors)}")
        super().__init__(
            f"Strict mode: notebook {notebook_name!r} has unresolved pages "
            f"({', '.join(details) or 'unknown reason'})"
        )


# Initialize converter instances as module-level objects for reuse
v4_converter = V4Converter()
v5_converter = V5Converter()
v6_converter = V6Converter()


def find_notebooks(backup_dir: Path) -> List[Dict]:
    """Find and parse notebook metadata from backup directory.

    Scans the backup directory for .metadata files and analyzes associated
    .rm files to classify them by version for appropriate conversion tools.

    File Version Detection:
    - Reads the first 8 bytes of each .rm file to detect format version
    - version=5: Uses rmrl library (legacy format)
    - version=6: Uses rmc library (current format)
    - version=4: Detected but limited support (attempts rmrl fallback)
    - version=3: Detected but no conversion support

    Args:
        backup_dir: Path to the ReMarkable backup directory

    Returns:
        List of dictionaries containing notebook information:
        - uuid: Unique identifier for the notebook
        - name: Display name of the notebook
        - type: DocumentType or CollectionType (folder)
        - parent: UUID of parent folder (empty if root level)
        - metadata_file: Path to the .metadata file
        - rm_files: List of all .rm files for this notebook
        - v5_files, v6_files, v4_files, v3_files: Files categorized by version
        - pdf_files: Any existing PDF files in the notebook directory
    """
    notebooks: List[Dict] = []
    files_dir = backup_dir / "Notebooks"

    if not files_dir.exists():
        logging.error(f"Backup files directory not found: {files_dir}")
        return []

    for metadata_file in files_dir.glob("*.metadata"):
        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            uuid = metadata_file.stem
            notebook_type = metadata.get("type", "unknown")

            if notebook_type in ["CollectionType", "DocumentType"]:
                # A document may be backed up as a sibling {uuid}.pdf file
                # (imported PDFs / ePubs rendered to PDF by the device) or as
                # individual page PDFs inside a {uuid}/ subdirectory.
                sibling_pdf = files_dir / f"{uuid}.pdf"
                notebook_info: Dict = {
                    "uuid": uuid,
                    "name": metadata.get("visibleName", "Untitled"),
                    "type": notebook_type,
                    "parent": metadata.get("parent", ""),
                    "metadata_file": metadata_file,
                    "rm_files": list(files_dir.glob(f"{uuid}/*.rm")),
                    "pdf_files": list(files_dir.glob(f"{uuid}/*.pdf")),
                    "sibling_pdf": sibling_pdf if sibling_pdf.exists() else None,
                }

                # Analyze file versions
                notebook_info["v5_files"] = []
                notebook_info["v6_files"] = []
                notebook_info["v4_files"] = []
                notebook_info["v3_files"] = []

                for rm_file in notebook_info["rm_files"]:
                    version = detect_rm_version(rm_file, default=0)
                    if version == 6:
                        notebook_info["v6_files"].append(rm_file)
                    elif version == 5:
                        notebook_info["v5_files"].append(rm_file)
                    elif version == 4:
                        notebook_info["v4_files"].append(rm_file)
                    elif version == 3:
                        notebook_info["v3_files"].append(rm_file)

                # Include in conversion list if it's a folder or has convertible content
                # - CollectionType: Folders (included for directory structure)
                # - Documents with any version of .rm files, page PDFs, or a sibling PDF
                if (
                    notebook_type == "CollectionType"
                    or notebook_info["v5_files"]
                    or notebook_info["v6_files"]
                    or notebook_info["v4_files"]
                    or notebook_info["v3_files"]
                    or notebook_info["pdf_files"]
                    or notebook_info["sibling_pdf"]
                ):
                    notebooks.append(notebook_info)

        except Exception as e:  # noqa: BLE001
            logging.warning(f"Failed to parse {metadata_file}: {e}")

    return notebooks


def svg_to_pdf(svg_file: Path, pdf_file: Path) -> bool:
    """Convert SVG to PDF using modular converter utilities.

    This is a wrapper function that maintains backward compatibility
    while using the new modular converter architecture.

    Args:
        svg_file: Path to input SVG file
        pdf_file: Path to output PDF file

    Returns:
        bool: True if conversion successful, False otherwise
    """
    # Use any converter instance for the utility method since it's in the base class
    return v6_converter.svg_to_pdf(svg_file, pdf_file)


def _write_pdf(writer: PdfWriter, output_file: Path) -> bool:
    """Write a ``PdfWriter`` to disk with stream compression enabled.

    Compressing content streams typically shrinks the resulting PDF by
    30-60% with no loss of vector or stroke precision. The fallback
    silently skips compression on PyPDF2 builds that do not expose the
    helper, keeping behaviour backwards compatible.
    """
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # PyPDF2 >= 2.x ships ``compress_content_streams``; older releases do not.
    compress = getattr(writer, "compress_identical_objects", None)
    try:
        for page in writer.pages:
            page_compress = getattr(page, "compress_content_streams", None)
            if callable(page_compress):
                try:
                    page_compress()
                except Exception:  # noqa: BLE001
                    # Compression is purely an optimisation; never fatal.
                    pass
        if callable(compress):
            try:
                compress()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass

    with open(output_file, "wb") as fh:
        writer.write(fh)
    return output_file.exists() and output_file.stat().st_size > 0


def _format_pdf_date(timestamp_ms: Optional[str]) -> Optional[str]:
    """Format a millisecond-precision timestamp string as a PDF ``D:`` date.

    reMarkable ``.metadata`` stores timestamps as decimal millisecond
    strings since the epoch. PDF expects ``D:YYYYMMDDHHmmSSOHH'mm'`` per
    the PDF 1.7 spec; we emit the ``Z`` (UTC) variant which is the
    interoperable subset every viewer accepts.
    """
    if not timestamp_ms:
        return None
    try:
        from datetime import datetime, timezone

        ts = int(timestamp_ms) / 1000.0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("D:%Y%m%d%H%M%SZ")
    except (TypeError, ValueError):
        return None


def _stamp_pdf_metadata(pdf_path: Path, notebook: Dict) -> None:
    """Embed notebook metadata (title, dates, app marker) into ``pdf_path``.

    Reads the source ``.metadata`` JSON when available so the resulting
    PDF carries the same display name and timestamps the device showed.
    Failures are logged at DEBUG only — bad metadata must never break
    the conversion pipeline.
    """
    try:
        title = notebook.get("name", "")
        metadata_file = notebook.get("metadata_file")
        created = modified = None
        if metadata_file and Path(metadata_file).exists():
            try:
                with open(metadata_file, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                created = _format_pdf_date(raw.get("createdTime"))
                modified = _format_pdf_date(raw.get("lastModified"))
            except (OSError, json.JSONDecodeError):
                pass

        info = {
            "/Title": title,
            "/Producer": "RemarkableSync",
            "/Subject": notebook.get("uuid", ""),
        }
        if created:
            info["/CreationDate"] = created
        if modified:
            info["/ModDate"] = modified

        # Round-trip the PDF through PdfWriter just to attach metadata.
        reader = PdfReader(str(pdf_path))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.add_metadata(info)
        with open(pdf_path, "wb") as fh:
            writer.write(fh)
    except Exception as exc:  # noqa: BLE001
        logging.debug("Failed to stamp metadata on %s: %s", pdf_path, exc)


def merge_pdf_with_template(
    content_pdf: Path, template_pdf: Optional[Path], output_pdf: Path
) -> bool:
    """Merge a content PDF with a template background PDF.

    For every content page a *fresh* copy of the template page is read
    from disk. ``PageObject.merge_page`` mutates the receiver's
    ``/Contents`` and ``/Resources`` references in place; sharing a
    single ``PageObject`` (even via ``copy.copy``) across pages causes
    one page's strokes to bleed onto subsequent pages or causes the
    background to render only on the first page. Re-reading the template
    is cheap relative to PDF rendering and removes that whole class of
    cross-page contamination bugs.

    Content is drawn *on top of* the template so vector strokes remain
    crisp and visible.

    Args:
        content_pdf: Path to PDF with notebook content.
        template_pdf: Path to PDF with template background (``None`` for no
            template).
        output_pdf: Path where the merged PDF should be saved.

    Returns:
        bool: True if merge successful, False otherwise.
    """
    try:
        if not content_pdf.exists():
            return False

        content_reader = PdfReader(str(content_pdf))
        writer = PdfWriter()

        has_template = bool(
            template_pdf and template_pdf.exists() and len(PdfReader(str(template_pdf)).pages) > 0
        )

        if not has_template:
            for page in content_reader.pages:
                writer.add_page(page)
        else:
            for content_page in content_reader.pages:
                try:
                    # Re-read the template per iteration so each background
                    # page has its own independent /Contents stream. This is
                    # the safe alternative to ``copy.copy(template_page)``
                    # which previously caused stroke bleed and missing
                    # backgrounds across multi-page notebooks.
                    bg_page = PdfReader(str(template_pdf)).pages[0]
                    bg_page.merge_page(content_page)
                    writer.add_page(bg_page)
                except Exception as e:  # noqa: BLE001
                    logging.warning("Failed to merge template for a page: %s", e)
                    writer.add_page(content_page)

        return _write_pdf(writer, output_pdf)

    except Exception as e:  # noqa: BLE001
        logging.debug("PDF template merge failed: %s", e)
        return False


def merge_pdfs(pdf_files: List[Path], output_file: Path) -> bool:
    """Merge multiple PDF files into a single PDF document.

    Takes a list of individual page PDFs and combines them into a
    single multi-page PDF document, maintaining page order. Content
    streams are compressed on write to minimise file size while
    preserving vector quality.

    Args:
        pdf_files: List of PDF file paths to merge (in order).
        output_file: Path where the merged PDF should be saved.

    Returns:
        bool: True if merge successful, False otherwise.
    """
    try:
        writer = PdfWriter()

        for pdf_file in pdf_files:
            if pdf_file.exists():
                try:
                    reader = PdfReader(str(pdf_file))
                    page_count = len(reader.pages)
                    logging.debug("Adding %d pages from %s", page_count, pdf_file.name)
                    for page in reader.pages:
                        writer.add_page(page)
                except Exception as e:  # noqa: BLE001
                    logging.error("Failed to read PDF file %s: %s", pdf_file, e)
            else:
                logging.warning("PDF chunk missing: %s", pdf_file)

        ok = _write_pdf(writer, output_file)
        logging.debug("Final PDF written to %s (pages: %d)", output_file, len(writer.pages))
        return ok

    except Exception as e:  # noqa: BLE001
        logging.debug("PDF merge failed: %s", e)
        return False


def organize_notebooks_by_structure(notebooks: List[Dict], backup_dir: Path) -> Dict:
    """Organize notebooks into their folder structure for conversion.

    Analyzes the parent-child relationships between notebooks and folders
    to recreate the ReMarkable folder structure in the output directory.
    This ensures PDFs are organized the same way as on the device.

    Args:
        notebooks: List of notebook dictionaries from find_notebooks()
        backup_dir: Path to backup directory (used for hierarchy resolution)

    Returns:
        Dictionary with:
        - 'documents': List of document notebooks to convert
        - 'structure': Dict mapping folder paths to lists of notebooks

    Note:
        Folder hierarchy is determined by following parent UUIDs up
        to the root level, creating folder paths like "Work/Projects/Notes"
    """
    # Build folder structure
    folder_structure = {}
    documents_to_convert = []

    for item in notebooks:
        if item["type"] == "DocumentType":
            # This is a notebook to convert
            hierarchy = get_folder_hierarchy(item, backup_dir)
            folder_path = "/".join(hierarchy) if hierarchy else ""

            item["folder_path"] = folder_path
            documents_to_convert.append(item)

            # Ensure folder exists in structure
            if folder_path not in folder_structure:
                folder_structure[folder_path] = []
            folder_structure[folder_path].append(item)

    return {"folder_structure": folder_structure, "documents_to_convert": documents_to_convert}


def get_folder_hierarchy(notebook: Dict, backup_dir: Path) -> List[str]:
    """Get the folder hierarchy for a notebook by following parent UUIDs."""
    hierarchy = []
    current_uuid = notebook.get("parent")
    files_dir = backup_dir / "Notebooks"

    while current_uuid and current_uuid != "":
        try:
            metadata_file = files_dir / f"{current_uuid}.metadata"
            if metadata_file.exists():
                with open(metadata_file, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                folder_name = metadata.get("visibleName", "Unknown")
                # Create safe folder name
                safe_folder = "".join(
                    c for c in folder_name if c.isalnum() or c in (" ", "-", "_")
                ).strip()
                if safe_folder:
                    hierarchy.insert(0, safe_folder)  # Insert at beginning to build path
                current_uuid = metadata.get("parent")
            else:
                break
        except Exception as e:
            logging.debug(f"Failed to read parent metadata for {current_uuid}: {e}")
            break

    return hierarchy


def convert_v6_file_with_rmc(rm_file: Path, output_file: Path) -> bool:
    """Convert v6 format .rm file to PDF using modular V6Converter.

    This is a wrapper function that maintains backward compatibility
    while using the new modular converter architecture.

    Args:
        rm_file: Path to the v6 format .rm file
        output_file: Path where PDF should be saved

    Returns:
        bool: True if conversion successful, False otherwise
    """
    return v6_converter.convert_to_pdf(rm_file, output_file)


def convert_v5_file_with_rmrl(rm_file: Path, output_file: Path) -> bool:
    """Convert v5 format .rm file to PDF using modular V5Converter.

    This is a wrapper function that maintains backward compatibility
    while using the new modular converter architecture.

    Args:
        rm_file: Path to the v5 format .rm file
        output_file: Path where PDF should be saved

    Returns:
        bool: True if conversion successful, False otherwise
    """
    return v5_converter.convert_to_pdf(rm_file, output_file)


def convert_v4_file_with_rmrl(rm_file: Path, output_file: Path) -> bool:
    """Convert v4 format .rm file to PDF using modular V4Converter.

    This is a wrapper function that maintains backward compatibility
    while using the new modular converter architecture.

    Args:
        rm_file: Path to the v4 format .rm file
        output_file: Path where PDF should be saved

    Returns:
        bool: True if conversion successful, False otherwise

    Note:
        v4 format support is limited and may fail for many files.
    """
    return v4_converter.convert_to_pdf(rm_file, output_file)


def copy_existing_pdf(pdf_file: Path, output_file: Path) -> bool:
    """Copy existing PDF file using base converter utility.

    This is a wrapper function that maintains backward compatibility
    while using the modular converter architecture.

    Args:
        pdf_file: Path to the source PDF file
        output_file: Path where PDF should be copied

    Returns:
        bool: True if copy successful, False otherwise
    """
    # Use any converter instance for the utility method since it's in the base class
    return v6_converter.copy_existing_pdf(pdf_file, output_file)


_default_page_resolver = PageResolver()

_sibling_page_count_cache: dict = {}


def _sibling_page_count(sibling_pdf: Path) -> int:
    """Return the number of pages in *sibling_pdf*, cached per path."""
    key = str(sibling_pdf)
    if key not in _sibling_page_count_cache:
        try:
            _sibling_page_count_cache[key] = len(PdfReader(str(sibling_pdf)).pages)
        except Exception:  # noqa: BLE001
            _sibling_page_count_cache[key] = 0
    return _sibling_page_count_cache[key]


def get_page_templates(content_file: Path) -> Dict[str, str]:
    """Extract template names for each page from .content file.

    Backward-compatible thin shim around :class:`PageResolver`. Prefer
    using ``PageResolver().resolve(content_file)`` directly in new code
    so misses and parse errors can be reported structurally.

    Args:
        content_file: Path to the .content JSON file

    Returns:
        Dictionary mapping page IDs to template names
    """
    if not content_file or not content_file.exists():
        return {}
    report = _default_page_resolver.resolve(content_file)
    return {page.page_id: page.template_name for page in report.pages}


def get_ordered_pages(content_file: Path) -> List[Dict]:
    """Get the list of all pages in the notebook in the correct order.

    Backward-compatible thin shim around :class:`PageResolver`. Prefer
    using ``PageResolver().resolve(content_file)`` directly in new code
    so misses and parse errors can be reported structurally.

    Args:
        content_file: Path to the .content file

    Returns:
        List of dictionaries with:
        - 'path': Path to the .rm file (may not exist if file missing)
        - 'id': Page ID
        - 'version': Format version (5, 6, etc.)
    """
    if not content_file or not content_file.exists():
        return []
    report = _default_page_resolver.resolve(content_file)
    files_dir = content_file.parent / content_file.stem
    return [
        {
            "path": page.rm_file if page.rm_file is not None else files_dir / f"{page.page_id}.rm",
            "id": page.page_id,
            "version": page.version,
        }
        for page in report.pages
    ]


def convert_notebook(
    notebook: Dict,
    output_dir: Path,
    backup_dir: Path,
    template_renderer: Optional[TemplateRenderer] = None,
    strict: bool = False,
) -> Dict:
    """Convert a notebook using appropriate tools for each file type.

    Creates a single PDF per notebook with all pages merged together.
    Organizes output in folder hierarchy matching backup structure.

    Args:
        notebook: Notebook descriptor dict produced by ``find_notebooks``.
        output_dir: Root directory for converted PDFs.
        backup_dir: Backup root (used for hierarchy resolution).
        template_renderer: Optional :class:`TemplateRenderer` instance.
        strict: When True, raise :class:`PageResolutionError` if any page
            declared in the notebook's ``.content`` manifest cannot be
            located on disk. When False, the missing pages are reported
            via the ``missing_pages`` field of the returned results dict
            and a placeholder is emitted for each.
    """
    # Create safe filename
    safe_name = "".join(c for c in notebook["name"] if c.isalnum() or c in (" ", "-", "_")).rstrip()
    if not safe_name:
        safe_name = f"notebook_{notebook['uuid'][:8]}"

    # Use pre-computed folder path from organization
    folder_path = notebook.get("folder_path", "")

    # Create output directory with folder structure
    output_notebook_dir = output_dir
    if folder_path:
        for folder in folder_path.split("/"):
            output_notebook_dir = output_notebook_dir / folder
    output_notebook_dir.mkdir(parents=True, exist_ok=True)

    # Avoid clobbering an existing PDF from a *different* notebook with the
    # same display name in the same folder (e.g. two invoices named identically).
    # If the existing file was produced from this same UUID, overwrite it normally.
    candidate = output_notebook_dir / f"{safe_name}.pdf"
    if candidate.exists():
        existing_belongs_to_us = False
        try:
            _r = PdfReader(str(candidate))
            existing_belongs_to_us = _r.metadata.get("/Subject", "") == notebook["uuid"]
        except Exception:  # noqa: BLE001
            pass
        if not existing_belongs_to_us:
            safe_name = f"{safe_name}_{notebook['uuid'][:8]}"

    results = {
        "name": notebook["name"],
        "folder_path": str(output_notebook_dir.relative_to(output_dir)) if folder_path else "",
        "v5_converted": 0,
        "v6_converted": 0,
        "v4_converted": 0,
        "pdfs_copied": 0,
        "v4_detected": len(notebook.get("v4_files", [])),
        "v3_detected": len(notebook.get("v3_files", [])),
        "total_files": 0,
        "output_files": [],
        # New: structural anomaly reporting (non-empty values surface to the
        # CLI summary so silent page-skipping can no longer pass unnoticed).
        "missing_pages": [],  # list of page UUIDs with no .rm file
        "expected_page_count": 0,  # from .content manifest
        "resolved_page_count": 0,  # what we actually found
    }

    # Collect all PDF pages to merge
    temp_pdfs: List[Path] = []

    # Create temporary directories in OS standard temp location
    temp_dir = Path(tempfile.mkdtemp(prefix="remarkable_pages_"))
    template_temp_dir: Optional[Path] = None
    if template_renderer:
        template_temp_dir = Path(tempfile.mkdtemp(prefix="remarkable_templates_"))

    try:
        # Fast path: document backed up as a single sibling PDF (imported PDFs /
        # ePubs rendered to PDF by the device).  Just copy it to the output dir.
        # Skip this path when .rm files also exist — those are annotated PDFs
        # where the sibling PDF is the source and the .rm files hold annotations.
        #
        # Also take fast path when .rm files exist but are very few compared to
        # the sibling PDF page count - extracting page-by-page is too slow.
        sibling_pdf: Optional[Path] = notebook.get("sibling_pdf")
        has_rm_files = bool(notebook.get("rm_files"))
        rm_file_count = len(notebook.get("rm_files", []))

        # Check if we should take the fast path (copy PDF directly)
        take_fast_path = False
        if sibling_pdf and sibling_pdf.exists() and not has_rm_files:
            take_fast_path = True
        elif sibling_pdf and sibling_pdf.exists() and has_rm_files:
            # Check if .rm files are a small fraction of total pages
            try:
                sibling_page_count = _sibling_page_count(sibling_pdf)
                # If fewer than 10% of pages have .rm files, copy PDF directly
                if rm_file_count < sibling_page_count * 0.1:
                    logging.debug(
                        "%s: Only %d .rm files for %d pages, copying sibling PDF directly",
                        notebook["name"],
                        rm_file_count,
                        sibling_page_count,
                    )
                    take_fast_path = True
            except Exception:
                pass

        if take_fast_path:
            final_pdf = output_notebook_dir / f"{safe_name}.pdf"
            if copy_existing_pdf(sibling_pdf, final_pdf):
                _stamp_pdf_metadata(final_pdf, notebook)
                results["pdfs_copied"] += 1
                results["output_files"].append(final_pdf)
                logging.info("✓ %s: copied PDF to %s", notebook["name"], final_pdf.name)
            else:
                logging.warning("Failed to copy sibling PDF for %s", notebook["name"])
            return results

        # Resolve all pages in the correct order via the dedicated resolver.
        content_path = notebook.get("content_file")
        if not content_path:
            metadata_file = notebook.get("metadata_file")
            content_path = metadata_file.with_suffix(".content") if metadata_file else None

        report: ResolutionReport = (
            _default_page_resolver.resolve(content_path) if content_path else ResolutionReport()
        )
        results["expected_page_count"] = report.expected_page_count
        results["resolved_page_count"] = len(report.pages)
        results["missing_pages"] = list(report.missing_page_ids)

        # Surface misses as structured warnings before we emit placeholders.
        for missing_id in report.missing_page_ids:
            logging.warning(
                "Notebook %r: missing .rm file for page %s",
                notebook["name"],
                missing_id,
            )

        # Strict mode: fail loudly for notebooks with no sibling PDF fallback.
        if (
            strict
            and (report.has_misses or report.parse_errors)
            and not (sibling_pdf and sibling_pdf.exists())
        ):
            raise PageResolutionError(
                notebook_name=notebook["name"],
                missing_pages=report.missing_page_ids,
                parse_errors=report.parse_errors,
            )

        if not report.pages:
            logging.warning(f"No pages found for notebook: {notebook['name']}")
            return results

        # Convert each page in order
        for page in report.pages:
            i = page.index
            rm_file = page.rm_file
            page_id = page.page_id
            version = page.version
            template_name = page.template_name if template_renderer else "Blank"

            logging.debug(
                "Processing page %d: ID=%s, Version=%s, File=%s",
                i + 1,
                page_id,
                version,
                rm_file.name if rm_file else "<missing>",
            )

            # Determine conversion function based on version
            conv_func = None
            if version == 6:
                conv_func = convert_v6_file_with_rmc
                res_key = "v6_converted"
            elif version == 5:
                conv_func = convert_v5_file_with_rmrl
                res_key = "v5_converted"
            elif version == 4:
                conv_func = convert_v4_file_with_rmrl
                res_key = "v4_converted"

            if not conv_func:
                logging.warning(f"Skipping unsupported version {version} for page {page_id}")
                continue

            temp_pdf_content = temp_dir / f"page_{i+1:03d}_content.pdf"
            conversion_success = False
            rm_file_exists = rm_file is not None and rm_file.exists()

            # If the file is missing, no template, and no sibling PDF to fall
            # back to — emit a blank placeholder and move on.
            sibling_has_this_page = (
                sibling_pdf and sibling_pdf.exists() and i < _sibling_page_count(sibling_pdf)
            )
            if (
                not rm_file_exists
                and (template_name == "Blank" or not template_name)
                and not sibling_has_this_page
            ):
                c = canvas.Canvas(
                    str(temp_pdf_content),
                    pagesize=(REMARKABLE_WIDTH_POINTS, REMARKABLE_HEIGHT_POINTS),
                )
                c.setFont("Helvetica", 10)
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.drawString(50, 50, f"[Page {i+1} - Empty]")
                c.save()
                temp_pdfs.append(temp_pdf_content)
                continue

            if rm_file_exists:
                conversion_success = conv_func(rm_file, temp_pdf_content)
                # rmc silently produces a skeleton PDF (1391 or 1394 bytes
                # depending on version) when it cannot parse the .rm format.
                # All PDF operators are present but no paths are drawn.
                # Treat these exact sizes as blank output so sibling fallback fires.
                if conversion_success and temp_pdf_content.exists():
                    if temp_pdf_content.stat().st_size in _RMC_BLANK_SIZES:
                        logging.debug(
                            "Page %d: rmc blank skeleton detected (%d bytes), treating as failed",
                            i + 1,
                            temp_pdf_content.stat().st_size,
                        )
                        conversion_success = False

                # When a sibling PDF exists, rescale the converted .rm page to
                # match the sibling's page dimensions for a consistent output.
                if (
                    conversion_success
                    and temp_pdf_content.exists()
                    and sibling_pdf
                    and sibling_pdf.exists()
                ):
                    try:
                        sibling_reader = PdfReader(str(sibling_pdf))
                        ref_page = sibling_reader.pages[min(i, len(sibling_reader.pages) - 1)]
                        ref_w = float(ref_page.mediabox.width)
                        ref_h = float(ref_page.mediabox.height)
                        src_reader = PdfReader(str(temp_pdf_content))
                        src_page = src_reader.pages[0]
                        src_w = float(src_page.mediabox.width)
                        src_h = float(src_page.mediabox.height)
                        if abs(src_w - ref_w) > 1 or abs(src_h - ref_h) > 1:
                            from PyPDF2.generic import ArrayObject, FloatObject

                            scale_x = ref_w / src_w if src_w else 1.0
                            scale_y = ref_h / src_h if src_h else 1.0
                            # Scale the content stream and update mediabox in-place.
                            src_page.add_transformation((scale_x, 0, 0, scale_y, 0, 0))
                            src_page.mediabox.lower_left = (0, 0)
                            src_page.mediabox.upper_right = (ref_w, ref_h)
                            scaled_writer = PdfWriter()
                            scaled_writer.add_page(src_page)
                            with open(temp_pdf_content, "wb") as fh:
                                scaled_writer.write(fh)
                            logging.debug(
                                "Page %d: scaled from %.0fx%.0f to %.0fx%.0f pts",
                                i + 1,
                                src_w,
                                src_h,
                                ref_w,
                                ref_h,
                            )
                    except Exception as exc:  # noqa: BLE001
                        logging.debug("Page %d: scale to sibling size failed: %s", i + 1, exc)

            if not conversion_success:
                # For missing .rm files: extract the corresponding page from the
                # sibling PDF when available (annotated imported PDF with
                # incomplete backup).  Fall back to a blank placeholder only
                # when no sibling PDF exists or the page index is out of range.
                extracted = False
                if (
                    (not rm_file_exists or not conversion_success)
                    and sibling_pdf
                    and sibling_pdf.exists()
                ):
                    try:
                        sibling_reader = PdfReader(str(sibling_pdf))
                        if i < len(sibling_reader.pages):
                            writer = PdfWriter()
                            writer.add_page(sibling_reader.pages[i])
                            with open(temp_pdf_content, "wb") as fh:
                                writer.write(fh)
                            extracted = True
                            logging.debug("Page %d: extracted from sibling PDF", i + 1)
                    except Exception as exc:  # noqa: BLE001
                        logging.debug("Failed to extract sibling page %d: %s", i + 1, exc)

                if not extracted:
                    c = canvas.Canvas(
                        str(temp_pdf_content),
                        pagesize=(REMARKABLE_WIDTH_POINTS, REMARKABLE_HEIGHT_POINTS),
                    )
                    c.setFont("Helvetica", 10)
                    if not rm_file_exists:
                        c.drawString(50, 50, f"[Page {i+1} - Drawing data missing]")
                    else:
                        logging.error(f"Conversion function failed for page {i+1} ({rm_file.name})")
                        c.drawString(50, 50, f"[Page {i+1} - Conversion failed]")
                    c.save()

            # Apply template if needed
            if template_renderer and template_temp_dir:
                if template_name and template_name != "Blank":
                    temp_template_pdf = template_temp_dir / f"template_{i+1:03d}.pdf"
                    temp_pdf_final = temp_dir / f"page_{i+1:03d}.pdf"

                    if template_renderer.render_template_to_pdf(template_name, temp_template_pdf):
                        if merge_pdf_with_template(
                            temp_pdf_content, temp_template_pdf, temp_pdf_final
                        ):
                            temp_pdfs.append(temp_pdf_final)
                            if conversion_success:
                                results[res_key] += 1
                        else:
                            temp_pdfs.append(temp_pdf_content)
                            if conversion_success:
                                results[res_key] += 1
                    else:
                        temp_pdfs.append(temp_pdf_content)
                        if conversion_success:
                            results[res_key] += 1
                else:
                    # Template is blank, just use the content PDF as is
                    temp_pdfs.append(temp_pdf_content)
                    if conversion_success:
                        results[res_key] += 1
            else:
                temp_pdfs.append(temp_pdf_content)
                if conversion_success:
                    results[res_key] += 1

        # Convert v4 files (best-effort; may not succeed)
        for i, rm_file in enumerate(notebook.get("v4_files", [])):
            temp_pdf = temp_dir / f"v4_page_{i+1:03d}.pdf"
            if convert_v4_file_with_rmrl(rm_file, temp_pdf):
                temp_pdfs.append(temp_pdf)
                results["v4_converted"] += 1

        # Copy existing PDFs
        for i, pdf_file in enumerate(notebook["pdf_files"]):
            temp_pdf = temp_dir / f"existing_{i+1:03d}.pdf"
            if copy_existing_pdf(pdf_file, temp_pdf):
                temp_pdfs.append(temp_pdf)
                results["pdfs_copied"] += 1

        # Create merged PDF if we have any pages
        if temp_pdfs:
            final_pdf = output_notebook_dir / f"{safe_name}.pdf"
            if merge_pdfs(temp_pdfs, final_pdf):
                _stamp_pdf_metadata(final_pdf, notebook)
                results["output_files"].append(final_pdf)
                logging.info(
                    f"✓ {notebook['name']}: Merged {len(temp_pdfs)} pages into {final_pdf.name}"
                )
            else:
                logging.warning(f"✗ {notebook['name']}: Failed to merge {len(temp_pdfs)} pages")

        results["total_files"] = (
            len(notebook["v5_files"])
            + len(notebook["v6_files"])
            + len(notebook.get("v4_files", []))
            + len(notebook.get("v3_files", []))
            + len(notebook["pdf_files"])
        )

        # Unsupported versions note
        if results["v4_detected"] or results["v3_detected"]:
            unsupported_info = output_notebook_dir / f"{safe_name}_unsupported.txt"
            try:
                with open(unsupported_info, "w", encoding="utf-8") as f:
                    f.write(f"Notebook: {notebook['name']}\n")
                    f.write(f"UUID: {notebook['uuid']}\n\n")
                    f.write("Detected unsupported .rm versions:\n")
                    if results["v4_detected"]:
                        f.write(
                            f"  - v4 pages: {results['v4_detected']} (no converter implemented yet)\n"
                        )
                    if results["v3_detected"]:
                        f.write(f"  - v3 pages: {results['v3_detected']} (legacy format)\n")
                    f.write(
                        "\nSuggestion: Keep these files; future tooling or an older firmware converter may be needed.\n"
                    )
                results["output_files"].append(unsupported_info)
            except Exception as e:
                logging.debug("Could not write unsupported info for %s: %s", notebook["name"], e)

    finally:
        # Clean up temporary directories in OS temp location
        try:
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            if template_temp_dir and template_temp_dir.exists():
                shutil.rmtree(template_temp_dir, ignore_errors=True)
        except Exception as e:
            logging.debug(f"Cleanup error: {e}")

    return results
