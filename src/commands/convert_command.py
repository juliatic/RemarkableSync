"""Convert command implementation."""

import logging
from pathlib import Path
from typing import Optional

from ..converter import run_conversion
from ..utils.logging import setup_logging


def run_convert_command(
    backup_dir: Path,
    output_dir: Optional[Path],
    verbose: bool,
    force_all: bool,
    sample: Optional[int],
    notebook: Optional[str],
    templates_dir: Optional[Path] = None,
    no_templates: bool = False,
    strict: bool = False,
) -> int:
    """Execute the convert command.

    Args:
        backup_dir: Directory containing ReMarkable backup files.
        output_dir: Destination directory for the generated PDFs. Defaults to
            ``<backup_dir>/PDF`` to preserve the historical layout.
        verbose: Enable verbose logging.
        force_all: Convert all notebooks (ignore sync status).
        sample: Convert only the first ``N`` notebooks (testing helper).
        notebook: Convert only this notebook (by UUID or display name).
        templates_dir: Custom directory with template assets to embed as page
            backgrounds. When ``None``, ``<backup_dir>/Templates`` is used if it
            exists.
        no_templates: When ``True`` skip template embedding entirely and emit
            content-only PDFs.
        strict: When ``True`` abort a notebook if any page declared in its
            manifest cannot be located on disk.

    Returns:
        Exit code (``0`` for success, non-zero for failure).
    """
    log_path = setup_logging(verbose, log_dir=backup_dir)

    if not backup_dir.exists():
        print(f"[ERROR] Backup directory not found: {backup_dir}")
        return 1

    # Default output directory mirrors the historical layout used by the backup
    # tooling so existing users do not see a behavioural change.
    if not output_dir:
        output_dir = backup_dir / "PDF"

    print("ReMarkable PDF Converter")
    print("=" * 40)
    print(f"Backup directory: {backup_dir}")
    print(f"Output directory: {output_dir}")
    if no_templates:
        print("Template embedding: disabled (--no-templates)")
    elif templates_dir:
        print(f"Template directory: {templates_dir}")

    if force_all:
        print("Force mode: Converting all notebooks")
    if sample:
        print(f"Sample mode: Converting first {sample} notebooks")
    if notebook:
        print(f"Single notebook mode: Converting {notebook}")

    try:
        # Determine updated notebooks list
        updated_only_file = None
        if not force_all and not notebook and not sample:
            updated_list = backup_dir / "updated_notebooks.txt"
            if updated_list.exists():
                updated_only_file = updated_list
                print("Converting recently updated notebooks only")

        success = run_conversion(
            backup_dir=backup_dir,
            output_dir=output_dir,
            verbose=verbose,
            sample=sample,
            notebook_filter=notebook,
            updated_only=updated_only_file,
            templates_dir=templates_dir,
            no_templates=no_templates,
            strict=strict,
        )

        if success:
            print(f"Log file: {log_path}")
        return 0 if success else 1

    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Conversion interrupted by user")
        return 130
    except Exception as e:
        logging.error("Unexpected error: %s", e)
        print(f"\n[ERROR] Unexpected error: {e}")
        return 1
