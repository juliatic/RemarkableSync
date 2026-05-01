"""Tests for M3 quality improvements: PDF metadata + backup integrity."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from PyPDF2 import PdfReader
from reportlab.pdfgen import canvas

from src.backup.backup_manager import _verify_download_size
from src.hybrid_converter import (
    REMARKABLE_HEIGHT_POINTS,
    REMARKABLE_WIDTH_POINTS,
    _format_pdf_date,
    _stamp_pdf_metadata,
    convert_notebook,
)


def _write_pdf(path: Path, label: str = "stub") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=(REMARKABLE_WIDTH_POINTS, REMARKABLE_HEIGHT_POINTS))
    c.drawString(72, 72, label)
    c.showPage()
    c.save()


class PdfDateFormattingTests(unittest.TestCase):
    def test_millisecond_string_round_trips_to_pdf_date_format(self) -> None:
        # 2025-01-02T03:04:05Z
        dt = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        ms = str(int(dt.timestamp() * 1000))
        self.assertEqual(_format_pdf_date(ms), "D:20250102030405Z")

    def test_invalid_input_returns_none(self) -> None:
        self.assertIsNone(_format_pdf_date(None))
        self.assertIsNone(_format_pdf_date(""))
        self.assertIsNone(_format_pdf_date("not-a-number"))


class StampPdfMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rmsync_meta_"))
        self.pdf = self.tmp / "doc.pdf"
        _write_pdf(self.pdf)
        self.metadata_file = self.tmp / "doc.metadata"
        created_dt = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        modified_dt = datetime(2025, 1, 3, 3, 4, 5, tzinfo=timezone.utc)
        self.metadata_file.write_text(
            json.dumps(
                {
                    "visibleName": "My Notebook",
                    "createdTime": str(int(created_dt.timestamp() * 1000)),
                    "lastModified": str(int(modified_dt.timestamp() * 1000)),
                }
            )
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_title_and_dates_round_trip_into_pdf(self) -> None:
        notebook = {
            "name": "My Notebook",
            "metadata_file": self.metadata_file,
        }
        _stamp_pdf_metadata(self.pdf, notebook)

        reader = PdfReader(str(self.pdf))
        info = reader.metadata
        self.assertEqual(info.title, "My Notebook")
        self.assertEqual(str(info.get("/Producer", "")), "RemarkableSync")
        self.assertEqual(str(info.get("/CreationDate", "")), "D:20250102030405Z")
        self.assertEqual(str(info.get("/ModDate", "")), "D:20250103030405Z")

    def test_missing_metadata_file_does_not_break_conversion(self) -> None:
        """A missing/invalid .metadata file must not corrupt the PDF."""
        notebook = {
            "name": "My Notebook",
            "metadata_file": self.tmp / "does-not-exist.metadata",
        }
        _stamp_pdf_metadata(self.pdf, notebook)
        # PDF still readable, title still set from notebook["name"].
        reader = PdfReader(str(self.pdf))
        self.assertEqual(reader.metadata.title, "My Notebook")


class ConvertNotebookEmbedsMetadataTests(unittest.TestCase):
    """End-to-end check that convert_notebook stamps metadata on the merged PDF."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rmsync_meta_e2e_"))
        self.backup_root = self.tmp
        self.notebook_dir = self.tmp / "Notebooks"
        self.notebook_dir.mkdir()
        uuid = "uuid-e2e"
        (self.notebook_dir / f"{uuid}.metadata").write_text(
            json.dumps(
                {
                    "visibleName": "Stamped Notebook",
                    "type": "DocumentType",
                    "createdTime": "1735782245000",
                    "lastModified": "1735868645000",
                }
            )
        )
        (self.notebook_dir / f"{uuid}.content").write_text(
            json.dumps({"cPages": {"pages": [{"id": "p1"}]}})
        )
        page_dir = self.notebook_dir / uuid
        page_dir.mkdir()
        (page_dir / "p1.rm").write_bytes(b"reMarkable .rm file version=6")

        self.notebook = {
            "uuid": uuid,
            "name": "Stamped Notebook",
            "content_file": self.notebook_dir / f"{uuid}.content",
            "metadata_file": self.notebook_dir / f"{uuid}.metadata",
            "v6_files": [page_dir / "p1.rm"],
            "v5_files": [],
            "v4_files": [],
            "v3_files": [],
            "pdf_files": [],
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_merged_pdf_carries_notebook_metadata(self) -> None:
        out = self.tmp / "PDF"

        def fake_engine(_rm, output):
            _write_pdf(output, "stroke")
            return True

        with mock.patch(
            "src.hybrid_converter.convert_v6_file_with_rmc",
            side_effect=fake_engine,
        ):
            convert_notebook(self.notebook, out, self.backup_root, None)

        pdf = out / "Stamped Notebook.pdf"
        self.assertTrue(pdf.exists())
        info = PdfReader(str(pdf)).metadata
        self.assertEqual(info.title, "Stamped Notebook")
        self.assertEqual(str(info.get("/Producer", "")), "RemarkableSync")


class VerifyDownloadSizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rmsync_dl_"))
        self.local = self.tmp / "file.bin"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_matching_size_is_accepted(self) -> None:
        self.local.write_bytes(b"x" * 100)
        self.assertTrue(_verify_download_size(self.local, {"size": 100, "path": "/r"}))

    def test_truncated_download_is_rejected_and_removed(self) -> None:
        self.local.write_bytes(b"x" * 50)
        self.assertFalse(_verify_download_size(self.local, {"size": 100, "path": "/r"}))
        # The corrupted file must be removed so the next sync retries it.
        self.assertFalse(self.local.exists())

    def test_missing_local_file_is_rejected(self) -> None:
        self.assertFalse(_verify_download_size(self.local, {"size": 100, "path": "/r"}))

    def test_missing_remote_size_does_not_block_sync(self) -> None:
        self.local.write_bytes(b"data")
        self.assertTrue(_verify_download_size(self.local, {"path": "/r"}))


class TruncatedDownloadExcludedFromConversionTests(unittest.TestCase):
    """Regression: notebooks with any truncated download must be excluded from
    same-run conversion so the converter never receives incomplete .rm files."""

    UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    def _make_remote_file(self, path: str, size: int) -> dict:
        return {"path": path, "mtime": 1000, "size": size}

    def test_truncated_rm_file_excludes_notebook_from_conversion(self) -> None:
        """If a .rm download is truncated, the owning notebook UUID must NOT
        appear in the set returned by backup_files (safe_to_convert)."""
        from unittest.mock import MagicMock, patch

        from src.backup.backup_manager import ReMarkableBackup

        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp)
            tool = ReMarkableBackup(backup_dir, password=None)

            remote_rm = self._make_remote_file(
                f"/home/root/.local/share/remarkable/xochitl/{self.UUID}/{self.UUID}.rm",
                size=1000,
            )
            remote_meta = self._make_remote_file(
                f"/home/root/.local/share/remarkable/xochitl/{self.UUID}.metadata",
                size=50,
            )

            def fake_list_files(path):
                return [remote_rm, remote_meta]

            def fake_get(remote_path, local_path):
                p = Path(local_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                if remote_path.endswith(".rm"):
                    p.write_bytes(b"x" * 500)  # truncated — 500 != 1000
                else:
                    p.write_bytes(b"y" * 50)

            mock_conn = MagicMock()
            mock_conn.connect.return_value = True
            mock_conn.list_files.side_effect = fake_list_files
            mock_conn.scp_client = MagicMock()
            mock_conn.scp_client.get.side_effect = fake_get
            tool.connection = mock_conn

            success, safe_uuids = tool.backup_files()

            self.assertTrue(success)
            self.assertNotIn(
                self.UUID,
                safe_uuids,
                "Notebook with a truncated .rm file must be excluded from same-run conversion",
            )


if __name__ == "__main__":
    unittest.main()
