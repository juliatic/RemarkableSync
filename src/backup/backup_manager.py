"""
Backup Manager - Internal Helper Module

This is a helper module providing backup orchestration functionality.
Do not run directly - use RemarkableSync.py as the entry point.

Entry Point:
    RemarkableSync.py backup [OPTIONS]
    RemarkableSync.py sync [OPTIONS]

This module provides:
- SSH connection management to ReMarkable tablet
- File synchronization with incremental updates
- Metadata management and tracking
- Optional automatic PDF conversion after backup
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import paramiko
from scp import SCPException
from tqdm import tqdm

from .connection import ReMarkableConnection
from .metadata import FileMetadata


def _verify_download_size(local_path: Path, remote_file: Dict) -> bool:
    """Verify a freshly downloaded file matches the remote size.

    SCP transfers can silently truncate when the connection drops
    mid-stream — paramiko raises in some cases but not all, and a
    zero-byte or short file would otherwise be recorded as "synced"
    and skipped on subsequent runs. Comparing the on-disk size with
    the remote-reported size is a cheap last-line-of-defence check.

    Returns:
        True if the file is present and matches the expected size,
        False if it is missing or truncated. The caller should skip
        metadata recording when this returns False so the next run
        retries the download.
    """
    if not local_path.exists():
        logging.warning("Downloaded file vanished: %s", local_path)
        return False
    expected = remote_file.get("size")
    if expected is None:
        return True  # Nothing to compare against.
    actual = local_path.stat().st_size
    if actual != expected:
        logging.warning(
            "Size mismatch for %s: expected %d bytes, got %d (will retry next run)",
            local_path.name,
            expected,
            actual,
        )
        try:
            local_path.unlink()
        except OSError:
            pass
        return False
    return True


class ReMarkableBackup:  # pylint: disable=too-many-instance-attributes
    """Main backup orchestrator for ReMarkable tablet.

    Coordinates SSH connection, file synchronization, metadata management,
    and optional PDF conversion to provide a complete backup solution.

    Key features:
    - Incremental sync based on file modification times
    - Integrity verification using MD5 checksums
    - Automatic PDF conversion integration
    - Progress tracking and detailed logging
    """

    def __init__(
        self,
        backup_dir: Path,
        password: Optional[str] = None,
        host: str = "10.11.99.1",
        output_dir: Optional[Path] = None,
    ):
        """Initialize backup orchestrator.

        Args:
            backup_dir: Local directory to store backup files.
            password: SSH password for tablet (prompted if not provided).
            host: ReMarkable tablet IP address (default: ``10.11.99.1`` for USB).
            output_dir: Directory where converted PDFs should be written.
                Defaults to ``<backup_dir>/PDF`` to preserve historical layout.
        """
        self.backup_dir = backup_dir
        self.files_dir = backup_dir / "Notebooks"  # Clean folder name
        self.pdfs_dir = output_dir if output_dir is not None else backup_dir / "PDF"
        self.templates_dir = backup_dir / "Templates"  # Clean folder name
        self.metadata_file = backup_dir / "sync_metadata.json"

        # Create directories
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.pdfs_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir.mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.connection = ReMarkableConnection(host=host, password=password)
        self.metadata = FileMetadata(self.metadata_file)

        # ReMarkable paths
        self.remote_xochitl_dir = "/home/root/.local/share/remarkable/xochitl"
        self.remote_templates_dir = "/usr/share/remarkable/templates"

    def backup_files(self) -> Tuple[bool, Set[str]]:  # pylint: disable=too-many-branches
        """Backup files from ReMarkable tablet.

        Returns:
            Tuple of (success, set of notebook UUIDs that were *fully* updated).
            Notebooks that had any truncated/failed download are excluded from
            the returned set so the caller does not attempt to convert an
            incomplete notebook in the same run.  They will be retried on the
            next backup invocation.
        """
        logging.info("Starting file backup...")

        if not self.connection.connect():
            return False, set()

        try:
            # Get list of remote files
            remote_files = self.connection.list_files(self.remote_xochitl_dir)

            if not remote_files:
                logging.warning("No files found on ReMarkable tablet")
                return True, set()

            # Filter files that need syncing
            files_to_sync = []
            for remote_file in remote_files:
                relative_path = os.path.relpath(remote_file["path"], self.remote_xochitl_dir)
                local_path = self.files_dir / relative_path

                if self.metadata.should_sync_file(remote_file, local_path):
                    files_to_sync.append((remote_file, local_path))

            if not files_to_sync:
                logging.info("All files are up to date")
                return True, set()

            logging.info("Syncing %d files...", len(files_to_sync))

            # Track which notebooks have been updated and which had failures.
            updated_notebooks: Set[str] = set()
            failed_notebooks: Set[str] = set()

            # Download files with progress bar
            with tqdm(total=len(files_to_sync), desc="Downloading") as pbar:
                for remote_file, local_path in files_to_sync:
                    try:
                        # Create local directory if needed
                        local_path.parent.mkdir(parents=True, exist_ok=True)

                        # Download file
                        if self.connection.scp_client is None:
                            logging.error("SCP client not initialized")
                            return False, set()
                        self.connection.scp_client.get(remote_file["path"], str(local_path))

                        # Integrity guard: detect a truncated/incomplete
                        # transfer before we record metadata that would
                        # mark the file as up-to-date next run.
                        if not _verify_download_size(local_path, remote_file):
                            # Record the owning notebook so we can exclude it
                            # from same-run conversion (files are incomplete).
                            _rel = os.path.relpath(remote_file["path"], self.remote_xochitl_dir)
                            _parts = _rel.split(os.sep)
                            _uuid = _parts[0].split(".")[0]
                            if len(_uuid) == 36:
                                failed_notebooks.add(_uuid)
                            continue

                        # Update metadata
                        self.metadata.update_file_metadata(remote_file, local_path)
                        # Handle both top-level files and files in subdirectories
                        relative_path = os.path.relpath(
                            remote_file["path"], self.remote_xochitl_dir
                        )
                        path_parts = relative_path.split(os.sep)

                        # Check if this is a notebook-related file
                        notebook_uuid = None
                        if len(path_parts) >= 1:
                            # Top-level files like uuid.metadata, uuid.content
                            first_part = path_parts[0].split(".")[0]
                            if len(first_part) == 36 and first_part not in [  # UUID length
                                "templates",
                                "version",
                            ]:
                                notebook_uuid = first_part

                        if len(path_parts) >= 2:
                            # Files in subdirectories like uuid/page.rm
                            if len(path_parts[0]) == 36 and path_parts[0] not in [
                                "templates",
                                "version",
                            ]:
                                notebook_uuid = path_parts[0]

                        if notebook_uuid:
                            updated_notebooks.add(notebook_uuid)

                        pbar.set_postfix_str(f"Downloaded {local_path.name}")

                    except (OSError, SCPException) as e:
                        logging.error("Failed to download %s: %s", remote_file["path"], e)

                    pbar.update(1)

            # Save metadata
            self.metadata.save()

            # Exclude any notebook that had at least one failed download; it
            # will be retried next run once all its files are intact.
            incomplete = updated_notebooks & failed_notebooks
            if incomplete:
                logging.warning(
                    "%d notebook(s) had truncated downloads and will be skipped for "
                    "conversion this run (will retry next sync): %s",
                    len(incomplete),
                    sorted(incomplete),
                )
            safe_to_convert = updated_notebooks - failed_notebooks

            if safe_to_convert:
                logging.debug("Updated notebook UUIDs: %s", sorted(safe_to_convert))

            logging.info(
                "File backup completed successfully. Updated %d notebooks.",
                len(safe_to_convert),
            )
            return True, safe_to_convert

        except (paramiko.SSHException, OSError) as e:
            logging.error("Backup failed: %s", e)
            return False, set()

        finally:
            self.connection.disconnect()

    def backup_templates(self) -> bool:
        """Backup template files from ReMarkable tablet.

        Templates are stored in /usr/share/remarkable/templates/ and include
        PNG/SVG template images and a templates.json configuration file.

        Returns:
            bool: True if successful, False otherwise
        """
        logging.info("Starting template backup...")

        if not self.connection.connect():
            return False

        try:
            # Get list of template files
            remote_files = self.connection.list_files(self.remote_templates_dir)

            if not remote_files:
                logging.warning("No template files found on ReMarkable tablet")
                return True

            # Filter templates that need syncing
            files_to_sync = []
            for remote_file in remote_files:
                relative_path = os.path.relpath(remote_file["path"], self.remote_templates_dir)
                local_path = self.templates_dir / relative_path

                if self.metadata.should_sync_file(remote_file, local_path):
                    files_to_sync.append((remote_file, local_path))

            if not files_to_sync:
                logging.info("All template files are up to date")
                self._ensure_custom_template_assets(remote_files)
                return True

            logging.info("Syncing %d template files...", len(files_to_sync))

            # Download template files with progress bar
            with tqdm(total=len(files_to_sync), desc="Downloading templates") as pbar:
                for remote_file, local_path in files_to_sync:
                    try:
                        # Create local directory if needed
                        local_path.parent.mkdir(parents=True, exist_ok=True)

                        # Download file
                        if self.connection.scp_client is None:
                            logging.error("SCP client not initialized")
                            return False
                        self.connection.scp_client.get(remote_file["path"], str(local_path))

                        if not _verify_download_size(local_path, remote_file):
                            continue

                        # Update metadata
                        self.metadata.update_file_metadata(remote_file, local_path)

                        pbar.set_postfix_str(f"Downloaded {local_path.name}")

                    except (OSError, SCPException) as e:
                        logging.error("Failed to download %s: %s", remote_file["path"], e)

                    pbar.update(1)

            # Save metadata
            self.metadata.save()

            # Cross-check templates.json for custom template image files that
            # are referenced but not present locally.  The incremental sync
            # can silently miss them when the metadata record was written before
            # a custom template was created (or when its mtime hasn't changed).
            self._ensure_custom_template_assets(remote_files)

            logging.info("Template backup completed successfully")
            return True

        except (paramiko.SSHException, OSError) as e:
            logging.error("Template backup failed: %s", e)
            return False

        finally:
            self.connection.disconnect()

    def _ensure_custom_template_assets(self, remote_files: List[Dict]) -> None:
        """Force-download any custom template image files missing from the local backup.

        After a normal incremental sync the remote ``templates.json`` may
        reference custom template filenames (``filename`` field, category
        ``"Custom"``) whose image files were never downloaded — either because
        the template was added after the last full sync or because the
        incremental metadata considered them up-to-date.

        This method parses the local ``templates.json``, identifies every
        custom-template filename, checks whether any image variant exists
        locally, and fetches the missing ones directly from the device.
        """
        tpl_json_path = self.templates_dir / "templates.json"
        if not tpl_json_path.exists():
            return

        try:
            with open(tpl_json_path, "r", encoding="utf-8") as fh:
                tpl_data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logging.warning("Could not parse templates.json for custom asset check: %s", exc)
            return

        image_extensions = [".png", ".svg", ".jpg", ".jpeg"]
        remote_by_name = {os.path.basename(f["path"]): f for f in remote_files}

        missing_filenames = []
        for template in tpl_data.get("templates", []):
            if "Custom" not in template.get("categories", []):
                continue
            filename = template.get("filename", "")
            if not filename:
                continue
            local_present = any(
                (self.templates_dir / (filename + ext)).exists() for ext in image_extensions
            )
            if not local_present:
                missing_filenames.append(filename)

        if not missing_filenames:
            return

        logging.warning(
            "%d custom template asset(s) are missing locally: %s — attempting forced download.",
            len(missing_filenames),
            missing_filenames,
        )

        for filename in missing_filenames:
            downloaded = False
            for ext in image_extensions:
                remote_name = filename + ext
                remote_file = remote_by_name.get(remote_name)
                if remote_file is None:
                    continue
                local_path = self.templates_dir / remote_name
                try:
                    if self.connection.scp_client is None:
                        logging.error("SCP client not available for custom template download")
                        break
                    self.connection.scp_client.get(remote_file["path"], str(local_path))
                    if _verify_download_size(local_path, remote_file):
                        self.metadata.update_file_metadata(remote_file, local_path)
                        logging.info("Downloaded missing custom template asset: %s", remote_name)
                        downloaded = True
                        break
                except (OSError, SCPException) as exc:
                    logging.error(
                        "Failed to force-download custom template asset %s: %s", remote_name, exc
                    )

            if not downloaded:
                logging.warning(
                    "Custom template asset %r not found on device " "(expected one of %s in %s).",
                    filename,
                    [filename + ext for ext in image_extensions],
                    self.remote_templates_dir,
                )

    def find_notebooks(self) -> List[Dict]:
        """Find and parse notebook metadata.

        Scans the backup directory for .metadata files and extracts
        notebook information including name, type, and associated files.

        Returns:
            List of dictionaries containing notebook information
        """
        notebooks = []

        # Look for .metadata files which indicate notebooks/documents
        for metadata_file in self.files_dir.glob("*.metadata"):
            try:
                with open(metadata_file, "r", encoding="utf-8") as f:
                    metadata = json.load(f)

                uuid = metadata_file.stem
                notebook_info = {
                    "uuid": uuid,
                    "name": metadata.get("visibleName", "Untitled"),
                    "type": metadata.get("type", "unknown"),
                    "parent": metadata.get("parent", ""),
                    "metadata_file": metadata_file,
                    "content_file": self.files_dir / f"{uuid}.content",
                    "rm_files": list(self.files_dir.glob(f"{uuid}/*.rm")),
                    "pagedata_files": list(self.files_dir.glob(f"{uuid}/*.json")),
                }

                if notebook_info["content_file"].exists():
                    notebooks.append(notebook_info)

            except (OSError, json.JSONDecodeError) as e:
                logging.warning("Failed to parse %s: %s", metadata_file, e)

        return notebooks

    def _find_unconverted_notebooks(self, output_dir: Path) -> Set[str]:
        """Return UUIDs of backed-up documents that have no output PDF yet.

        Scans ``Notebooks/`` for ``.metadata`` files whose type is
        ``DocumentType``, resolves the expected output path (honouring the
        folder hierarchy), and returns the UUID whenever the output PDF is
        absent.  This is used as a catch-up pass after a sync run that
        downloaded nothing new.
        """
        from ..hybrid_converter import find_notebooks, get_folder_hierarchy

        unconverted: Set[str] = set()
        for notebook in find_notebooks(self.backup_dir):
            if notebook["type"] != "DocumentType":
                continue
            hierarchy = get_folder_hierarchy(notebook, self.backup_dir)
            folder_path = "/".join(hierarchy) if hierarchy else ""
            output_notebook_dir = output_dir
            if folder_path:
                for folder in folder_path.split("/"):
                    output_notebook_dir = output_notebook_dir / folder
            safe_name = (
                "".join(c for c in notebook["name"] if c.isalnum() or c in (" ", "-", "_")).rstrip()
                or f"notebook_{notebook['uuid'][:8]}"
            )
            expected_pdf = output_notebook_dir / f"{safe_name}.pdf"
            if not expected_pdf.exists():
                unconverted.add(notebook["uuid"])
        return unconverted

    def convert_to_pdf(self, notebook: Dict) -> Optional[Path]:
        """Convert notebook to PDF using available tools.

        Creates a placeholder metadata file for the notebook.
        In a full implementation, this would integrate with PDF conversion tools.

        Args:
            notebook: Dictionary containing notebook information

        Returns:
            Optional[Path]: Path to created file, None on error
        """
        output_path = self.pdfs_dir / f"{notebook['name']}.pdf"

        # For now, create a placeholder PDF indicating conversion is needed
        # In a real implementation, you would integrate with rm2pdf or rmc
        try:
            with open(output_path.with_suffix(".txt"), "w", encoding="utf-8") as f:
                f.write(f"Notebook: {notebook['name']}\n")
                f.write(f"UUID: {notebook['uuid']}\n")
                f.write(f"Type: {notebook['type']}\n")
                f.write(f"RM Files: {len(notebook['rm_files'])}\n")
                f.write(f"Pages: {len(notebook['pagedata_files'])}\n")
                f.write("\nTo convert to PDF, you'll need to install rmc or rm2pdf tools\n")
                f.write("See: https://github.com/ricklupton/rmc\n")

            logging.info("Created metadata for %s", notebook["name"])
            return output_path.with_suffix(".txt")

        except OSError as e:
            logging.error("Failed to create PDF metadata for %s: %s", notebook["name"], e)
            return None

    def run_backup(
        self,
        force_convert_all: bool = False,
        convert_to_pdf: bool = False,
        backup_templates: bool = True,
        templates_dir: Optional[Path] = None,
        no_templates: bool = False,
        strict: bool = False,
    ) -> bool:
        """Run complete backup process with optional PDF conversion.

        Args:
            force_convert_all: If True, convert all notebooks to PDF regardless of sync status.
            convert_to_pdf: If True, automatically convert notebooks to PDF.
            backup_templates: If True, backup template files from the tablet.
            templates_dir: Optional override for the directory holding template
                assets used during conversion.
            no_templates: When True, disable template embedding entirely.
            strict: When True, abort notebooks with unresolved/missing pages.

        Returns:
            bool: True if backup successful, False otherwise.
        """
        logging.info("Starting ReMarkable backup process")

        # Backup files and get list of updated notebooks
        success, updated_notebook_uuids = self.backup_files()
        if not success:
            return False

        # Backup templates if requested
        if backup_templates:
            templates_success = self.backup_templates()
            if not templates_success:
                logging.warning("Template backup failed, but continuing with main backup")

        # Automatic PDF conversion using hybrid converter
        if convert_to_pdf:
            return self.run_pdf_conversion(
                updated_notebook_uuids,
                force_convert_all,
                templates_dir=templates_dir,
                no_templates=no_templates,
                strict=strict,
            )

        logging.info("Backup process completed successfully")
        return True

    def run_pdf_conversion(
        self,
        updated_notebook_uuids: Set[str],
        force_convert_all: bool = False,
        templates_dir: Optional[Path] = None,
        no_templates: bool = False,
        strict: bool = False,
    ) -> bool:
        """Run PDF conversion using the converter module.

        Args:
            updated_notebook_uuids: Set of notebook UUIDs that were updated during sync.
            force_convert_all: Convert all notebooks regardless of sync status.
            templates_dir: Optional template directory override.
            no_templates: When True, skip template embedding.
            strict: When True, abort notebooks with unresolved/missing pages.

        Returns:
            bool: True if conversion successful, False otherwise.
        """
        from ..converter import run_conversion

        logging.info("Starting PDF conversion...")

        # Honour the configured output directory (parametric, defaults to <backup>/PDF)
        output_dir = self.pdfs_dir

        # Determine conversion strategy
        updated_only_file = None
        is_catchup = False
        if force_convert_all:
            logging.info("Force conversion enabled - converting all notebooks to PDF")
        elif updated_notebook_uuids:
            # Create a temporary file list of updated notebooks for selective conversion
            updated_list_file = self.backup_dir / "updated_notebooks.txt"
            try:
                with open(updated_list_file, "w", encoding="utf-8") as f:
                    for uuid in sorted(updated_notebook_uuids):
                        f.write(f"{uuid}\n")

                updated_only_file = updated_list_file
                logging.info("Converting %d updated notebooks to PDF", len(updated_notebook_uuids))
            except OSError as e:
                logging.error("Failed to create updated notebooks list: %s", e)
                return False
        else:
            # No new downloads — but check if any backed-up documents are
            # missing their output PDF (e.g. newly supported sibling-PDF
            # documents that were skipped by older versions of the converter).
            catchup_uuids = self._find_unconverted_notebooks(output_dir)
            if not catchup_uuids:
                logging.info("No notebooks were updated - skipping PDF conversion")
                return True
            logging.info(
                "No new downloads, but %d notebook(s) have no output PDF yet — converting",
                len(catchup_uuids),
            )
            updated_list_file = self.backup_dir / "updated_notebooks.txt"
            try:
                with open(updated_list_file, "w", encoding="utf-8") as f:
                    for uuid in sorted(catchup_uuids):
                        f.write(f"{uuid}\n")
                updated_only_file = updated_list_file
                strict = False  # catch-up: never block on missing .rm files
                is_catchup = True
            except OSError as e:
                logging.error("Failed to create updated notebooks list: %s", e)
                return False

        # Run conversion
        try:
            success = run_conversion(
                backup_dir=self.backup_dir,
                output_dir=output_dir,
                verbose=True,
                sample=None,
                notebook_filter=None,
                updated_only=updated_only_file,
                templates_dir=templates_dir,
                no_templates=no_templates,
                strict=strict,
            )

            # Clean up temporary file if created
            if updated_only_file and updated_only_file.exists():
                try:
                    updated_only_file.unlink()
                except OSError:
                    pass  # Ignore cleanup errors

            if success:
                logging.info("PDF conversion completed successfully")
            elif is_catchup:
                logging.warning(
                    "PDF conversion completed with some failures (check warnings above)"
                )
            else:
                logging.error("PDF conversion failed")

            return success or is_catchup

        except Exception as e:  # pylint: disable=broad-except
            logging.error("Failed to execute PDF conversion: %s", e)
            return False
