"""Sync command implementation - backup and convert in one go."""

import logging
from pathlib import Path
from typing import Optional

from ..backup import ReMarkableBackup
from ..utils.logging import setup_logging


def run_sync_command(
    backup_dir: Path,
    password: Optional[str],
    verbose: bool,
    skip_templates: bool,
    force_backup: bool,
    force_convert: bool,
    host: str = "10.11.99.1",
    output_dir: Optional[Path] = None,
    templates_dir: Optional[Path] = None,
    no_templates: bool = False,
    strict: bool = False,
) -> int:
    """Execute the sync command (backup + convert).

    This is the most common workflow: backup the tablet and then convert
    any notebooks that were updated during the backup.

    Args:
        backup_dir: Directory to store backup files
        password: SSH password for tablet
        verbose: Enable verbose logging
        skip_templates: Skip backing up template files
        force_backup: Force backup all files
        force_convert: Force convert all notebooks
        host: ReMarkable tablet IP address

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    setup_logging(verbose)

    if output_dir is None:
        output_dir = backup_dir / "PDF"

    print("ReMarkable Sync (Backup + Convert)")
    print("=" * 40)
    print(f"Backup directory: {backup_dir.absolute()}")
    print(f"Output directory: {output_dir}")
    print(f"ReMarkable host: {host}")
    if no_templates:
        print("Template embedding: disabled (--no-templates)")
    elif templates_dir:
        print(f"Template directory: {templates_dir}")

    if not skip_templates:
        print("Template backup: Enabled")
    if force_backup:
        print("Force backup: All files will be backed up")
    if force_convert:
        print("Force convert: All notebooks will be converted")

    backup_tool = ReMarkableBackup(
        backup_dir, password, host=host, output_dir=output_dir
    )

    try:
        # Run backup with PDF conversion enabled
        success = backup_tool.run_backup(
            force_convert_all=force_convert,
            convert_to_pdf=True,
            backup_templates=not skip_templates,
            templates_dir=templates_dir,
            no_templates=no_templates,
            strict=strict,
        )

        if success:
            print("\n[SUCCESS] Sync completed successfully!")
            print(f"Files backed up to: {backup_tool.files_dir}")
            if not skip_templates:
                print(f"Templates backed up to: {backup_tool.templates_dir}")

            if output_dir.exists():
                print(f"PDFs generated in: {output_dir}")
            return 0
        else:
            print("\n[ERROR] Sync failed. Check logs for details.")
            return 1

    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Sync interrupted by user")
        return 130
    except Exception as e:
        logging.error("Unexpected error: %s", e)
        print(f"\n[ERROR] Unexpected error: {e}")
        return 1
