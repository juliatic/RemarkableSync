"""
Converter Module - Internal Helper

This is a helper module providing the conversion API.
Do not run directly - use RemarkableSync.py as the entry point.

Entry Point:
    RemarkableSync.py convert [OPTIONS]

This module provides:
- High-level conversion API with progress tracking
- Integration with hybrid_converter and template renderer
- Batch processing with error handling
"""

import logging
from pathlib import Path
from typing import Optional

from tqdm import tqdm

from .hybrid_converter import convert_notebook, find_notebooks, organize_notebooks_by_structure
from .template_renderer import TemplateRenderer


def run_conversion(
    backup_dir: Path,
    output_dir: Path,
    verbose: bool = False,
    sample: Optional[int] = None,
    notebook_filter: Optional[str] = None,
    updated_only: Optional[Path] = None,
    templates_dir: Optional[Path] = None,
    no_templates: bool = False,
    strict: bool = False,
) -> bool:
    """Run PDF conversion on backed up notebooks.

    Args:
        backup_dir: Directory containing ReMarkable backup files.
        output_dir: Directory where the resulting PDFs are written.
        verbose: Enable verbose logging.
        sample: Convert only the first ``N`` notebooks (testing helper).
        notebook_filter: Convert only this notebook (by UUID or name).
        updated_only: File containing the list of updated notebook UUIDs.
        templates_dir: Optional override for the directory holding template
            assets. Defaults to ``<backup_dir>/Templates`` when present.
        no_templates: When True, skip template embedding entirely.
        strict: When True, abort a notebook (and count it as failed) if any
            page in its ``.content`` manifest cannot be located. When False
            (default), missing pages produce placeholders and a structured
            warning is logged; a per-run summary is printed at the end.

    Returns:
        bool: True if conversion successful, False otherwise.
    """
    if not backup_dir.exists():
        logging.error(f"Backup directory not found: {backup_dir}")
        return False

    output_dir.mkdir(parents=True, exist_ok=True)

    # Load updated notebooks list if provided
    updated_uuids = None
    if updated_only and updated_only.exists():
        try:
            with open(updated_only, "r", encoding="utf-8") as f:
                updated_uuids = {line.strip() for line in f if line.strip()}
            logging.info(f"Converting only {len(updated_uuids)} updated notebooks")
        except OSError as e:
            logging.error(f"Failed to read updated notebooks file: {e}")
            return False

    # Find notebooks
    all_items = find_notebooks(backup_dir)

    if not all_items:
        logging.warning("No items found in backup directory")
        return False

    # Filter by updated UUIDs if provided
    if updated_uuids:
        all_items = [item for item in all_items if item["uuid"] in updated_uuids]
        if not all_items:
            logging.info("No updated notebooks found for conversion")
            return True  # Not an error

    # Filter by notebook name/UUID if provided
    if notebook_filter:
        all_items = [
            item
            for item in all_items
            if item["uuid"] == notebook_filter or item["name"] == notebook_filter
        ]
        if not all_items:
            logging.error(f"Notebook not found: {notebook_filter}")
            return False

    # Organize into folder structure
    organization = organize_notebooks_by_structure(all_items, backup_dir)
    notebooks = organization["documents_to_convert"]

    if not notebooks:
        logging.warning("No convertible notebooks found")
        return False

    # Apply sample limit if specified
    if sample and sample > 0:
        notebooks = notebooks[:sample]

    # Initialize template renderer unless disabled by --no-templates.
    template_renderer = None
    if no_templates:
        logging.info("Template embedding disabled (--no-templates)")
    else:
        resolved_templates_dir = templates_dir or (backup_dir / "Templates")
        if resolved_templates_dir.exists():
            try:
                template_renderer = TemplateRenderer(resolved_templates_dir)
                logging.info(
                    "Template rendering enabled (%d templates loaded from %s)",
                    len(template_renderer.templates_metadata),
                    resolved_templates_dir,
                )
            except Exception as e:  # noqa: BLE001
                logging.warning(f"Failed to initialize template renderer: {e}")
        else:
            logging.info(
                "No templates directory found at %s; producing content-only PDFs",
                resolved_templates_dir,
            )

    # Convert notebooks with progress bar
    successful = 0
    notebooks_with_misses: list = []  # (name, missing_count) for end-of-run summary
    logging.info(f"Converting {len(notebooks)} notebooks...")

    with tqdm(notebooks, desc="Converting", unit="notebook") as pbar:
        for notebook in pbar:
            # Show current notebook name in progress bar
            pbar.set_postfix_str(notebook["name"][:40])

            try:
                results = convert_notebook(
                    notebook,
                    output_dir,
                    backup_dir,
                    template_renderer,
                    strict=strict,
                )
                if results["output_files"]:
                    successful += 1
                if results.get("missing_pages"):
                    notebooks_with_misses.append(
                        (notebook["name"], len(results["missing_pages"]))
                    )
            except Exception as e:
                logging.error(f"Failed to convert {notebook['name']}: {e}")

    logging.info(f"Conversion complete: {successful}/{len(notebooks)} notebooks converted")
    if notebooks_with_misses:
        total_missing = sum(count for _, count in notebooks_with_misses)
        logging.warning(
            "%d notebook(s) had unresolved pages (%d total). Re-run with --strict to fail on these.",
            len(notebooks_with_misses),
            total_missing,
        )
        for name, count in notebooks_with_misses:
            logging.warning("  - %s: %d missing page(s)", name, count)
    return successful > 0
