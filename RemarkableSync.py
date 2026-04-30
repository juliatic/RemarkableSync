#!/usr/bin/env python3
"""
RemarkableSync - Unified command-line interface

Single entry point for backing up and converting ReMarkable tablet files.
"""

import sys
from pathlib import Path
from typing import Optional

# Check Python version before importing anything else
if sys.version_info < (3, 11):
    print("Error: RemarkableSync requires Python 3.11 or higher.")
    print(f"You are using Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    print("\nPlease upgrade your Python installation:")
    print("  - Download from: https://www.python.org/downloads/")
    print("  - Or use a package manager (brew, apt, etc.)")
    sys.exit(1)

import click

from src.__version__ import __repository__, __version__


def print_header():
    """Print the application header."""
    click.echo(f"RemarkableSync v{__version__} by Jeff Steinbok")
    click.echo(f"Repository: {__repository__}")
    click.echo()


def version_callback(ctx, param, value):
    """Display version information."""
    if not value or ctx.resilient_parsing:
        return
    print_header()
    ctx.exit()


@click.group(invoke_without_command=False)
@click.option('--version', is_flag=True, callback=version_callback,
              expose_value=False, is_eager=True,
              help='Show version and repository information')
@click.option('--host', '-h', type=str, default='10.11.99.1',
              help='ReMarkable IP address (default: 10.11.99.1 for USB)')
@click.pass_context
def cli(ctx, host):
    """RemarkableSync - Backup and convert ReMarkable tablet files.

    A unified tool to backup your ReMarkable tablet via USB and convert
    notebooks to PDF format with template support.
    """
    # Store host in context object to be accessible by subcommands
    ctx.ensure_object(dict)
    ctx.obj['host'] = host

    # Print header for all commands (unless it's --version which handles it itself)
    if ctx.invoked_subcommand and not ctx.resilient_parsing:
        print_header()


@cli.command()
@click.option('--backup-dir', '-d', type=click.Path(path_type=Path),
              default=Path('./remarkable_backup'),
              help='Directory to store backup files')
@click.option('--password', '-p', type=str, help='ReMarkable SSH password')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.option('--skip-templates', is_flag=True, help='Skip backing up template files')
@click.option('--force', '-f', is_flag=True, help='Force backup all files (ignore sync status)')
@click.option('--host', '-h', type=str, help='ReMarkable IP address')
@click.pass_context
def backup(ctx, backup_dir: Path, password: Optional[str], verbose: bool, 
           skip_templates: bool, force: bool, host: Optional[str]):
    """Backup files from ReMarkable tablet.

    Connects to your ReMarkable tablet (via USB or WiFi) and backs up all files
    with incremental sync. Template files are backed up by default.
    """
    # Use command-specific host if provided, otherwise fallback to global host
    host = host or ctx.obj.get('host', '10.11.99.1')
    from src.commands.backup_command import run_backup_command
    sys.exit(run_backup_command(backup_dir, password, verbose, skip_templates, force, host))


@cli.command()
@click.option('--backup-dir', '-d', type=click.Path(path_type=Path),
              default=Path('./remarkable_backup'),
              help='Directory containing ReMarkable backup files')
@click.option('--output', '-o', 'output_dir', type=click.Path(path_type=Path),
              help='Destination directory for converted PDF files '
                   '(default: <backup-dir>/PDF, preserving the historical layout)')
@click.option('--templates-dir', type=click.Path(path_type=Path),
              help='Directory with custom template assets to embed as page backgrounds. '
                   'Defaults to <backup-dir>/Templates when present.')
@click.option('--no-templates', is_flag=True,
              help='Disable template embedding and produce content-only PDFs.')
@click.option('--strict', is_flag=True,
              help='Fail (do not emit placeholders) when a notebook page is missing on disk.')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.option('--force', '-f', is_flag=True, help='Convert all notebooks (ignore sync status)')
@click.option('--sample', '-s', type=int, help='Convert only first N notebooks (for testing)')
@click.option('--notebook', '-n', type=str, help='Convert only this notebook (by UUID or name)')
def convert(backup_dir: Path, output_dir: Optional[Path], templates_dir: Optional[Path],
           no_templates: bool, strict: bool, verbose: bool, force: bool,
           sample: Optional[int], notebook: Optional[str]):
    """Convert backed up notebooks to PDF format.

    Converts ReMarkable notebooks to PDF with optional template backgrounds.
    By default, only converts notebooks that were updated in the last backup.
    """
    from src.commands.convert_command import run_convert_command
    sys.exit(run_convert_command(
        backup_dir=backup_dir,
        output_dir=output_dir,
        verbose=verbose,
        force_all=force,
        sample=sample,
        notebook=notebook,
        templates_dir=templates_dir,
        no_templates=no_templates,
        strict=strict,
    ))


@cli.command()
@click.option('--backup-dir', '-d', type=click.Path(path_type=Path),
              default=Path('./remarkable_backup'),
              help='Directory to store backup files')
@click.option('--output', '-o', 'output_dir', type=click.Path(path_type=Path),
              help='Destination directory for converted PDF files '
                   '(default: <backup-dir>/PDF).')
@click.option('--templates-dir', type=click.Path(path_type=Path),
              help='Directory with custom template assets to embed as page backgrounds.')
@click.option('--no-templates', is_flag=True,
              help='Disable template embedding during conversion.')
@click.option('--strict', is_flag=True,
              help='Fail (do not emit placeholders) when a notebook page is missing on disk.')
@click.option('--password', '-p', type=str, help='ReMarkable SSH password')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.option('--skip-templates', is_flag=True, help='Skip backing up template files')
@click.option('--force-backup', is_flag=True, help='Force backup all files')
@click.option('--force-convert', is_flag=True, help='Force convert all notebooks')
@click.option('--host', '-h', type=str, help='ReMarkable IP address')
@click.pass_context
def sync(ctx, backup_dir: Path, output_dir: Optional[Path], templates_dir: Optional[Path],
        no_templates: bool, strict: bool, password: Optional[str], verbose: bool, skip_templates: bool,
        force_backup: bool, force_convert: bool, host: Optional[str]):
    """Backup and convert in one command (default workflow).

    This is the most common use case: backup your tablet and then convert
    any notebooks that were updated during the backup.
    """
    # Use command-specific host if provided, otherwise fallback to global host
    host = host or ctx.obj.get('host', '10.11.99.1')
    from src.commands.sync_command import run_sync_command
    sys.exit(run_sync_command(
        backup_dir=backup_dir,
        password=password,
        verbose=verbose,
        skip_templates=skip_templates,
        force_backup=force_backup,
        force_convert=force_convert,
        host=host,
        output_dir=output_dir,
        templates_dir=templates_dir,
        no_templates=no_templates,
        strict=strict,
    ))


@cli.command()
@click.option('--pdf-dir', '-d', type=click.Path(path_type=Path),
              default=Path('./remarkable_backup/PDF'),
              help='Directory containing converted PDFs to OCR')
@click.option('--output', '-o', 'output_dir', type=click.Path(path_type=Path),
              help='Destination directory for OCR artefacts (default: same as --pdf-dir).')
@click.option('--engine', type=click.Choice(['vision', 'tesseract'], case_sensitive=False),
              help='OCR engine. Defaults to Apple Vision on macOS, Tesseract elsewhere.')
@click.option('--format', '-f', 'output_formats', type=click.Choice(['pdf', 'txt', 'md', 'all']),
              multiple=True, default=('pdf',),
              help='Output format(s). May be specified multiple times. Default: pdf')
@click.option('--notebook', '-n', type=str, help='OCR only PDFs whose name contains this string')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
def ocr(pdf_dir: Path, output_dir: Optional[Path], engine: Optional[str],
        output_formats: tuple, notebook: Optional[str], verbose: bool):
    """Run handwriting/text OCR on converted PDFs.

    Produces a separate text-only PDF (``<name>_text.pdf``) for each
    input PDF, plus optional .txt/.md sidecar files. OCR runs locally
    via Apple Vision (macOS) or Tesseract.
    """
    from src.commands.ocr_command import run_ocr_command
    sys.exit(run_ocr_command(
        pdf_dir=pdf_dir,
        output_dir=output_dir,
        engine=engine,
        output_formats=list(output_formats),
        verbose=verbose,
        notebook=notebook,
    ))


@cli.command(name='notebooklm-bundle')
@click.option('--pdf-dir', '-d', type=click.Path(path_type=Path),
              default=Path('./remarkable_backup/PDF'),
              help='Directory containing PDFs (and optional _text.pdf OCR variants)')
@click.option('--output', '-o', 'output_dir', type=click.Path(path_type=Path),
              required=True,
              help='Destination directory for the bundle')
@click.option('--notebook', '-n', type=str,
              help='Bundle only documents whose name contains this string')
@click.option('--max-mb', type=int, default=200,
              help='Skip files larger than this size in MB (default: 200)')
@click.option('--no-prefer-ocr', is_flag=True,
              help='Bundle the original graphical PDFs instead of the OCR text PDFs')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
def notebooklm_bundle(pdf_dir: Path, output_dir: Path, notebook: Optional[str],
                       max_mb: int, no_prefer_ocr: bool, verbose: bool):
    """Package converted notebooks for upload to Google NotebookLM.

    Copies the best PDF variant per notebook (preferring the OCR text
    PDF when available) into a flat folder with a manifest.md index.
    Upload the resulting folder manually via the NotebookLM web UI.
    """
    from src.commands.notebooklm_command import run_notebooklm_bundle_command
    sys.exit(run_notebooklm_bundle_command(
        pdf_dir=pdf_dir,
        output_dir=output_dir,
        notebook=notebook,
        max_mb=max_mb,
        verbose=verbose,
        prefer_ocr=not no_prefer_ocr,
    ))


def main():
    """Entry point for the application."""
    # If no command specified, default to 'sync'
    commands = ['backup', 'convert', 'sync', 'ocr', 'notebooklm-bundle']
    
    # If the user didn't specify a command and isn't asking for help/version
    if not any(cmd in sys.argv for cmd in commands) and \
       '--help' not in sys.argv and \
       '--version' not in sys.argv:
        # Append 'sync' to the end so global options (like --host) stay before it
        sys.argv.append('sync')
        
    cli()


if __name__ == "__main__":
    main()
