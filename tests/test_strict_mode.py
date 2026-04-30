"""Regression tests for ``convert_notebook`` strict mode and miss reporting.

These tests ensure that pages declared in the ``.content`` manifest but
missing on disk are no longer silently swallowed: they must show up in
the ``missing_pages`` field of the results dict (lenient mode, default)
and must raise :class:`PageResolutionError` in strict mode.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PyPDF2 import PdfReader
from reportlab.pdfgen import canvas

from src.hybrid_converter import (
    PageResolutionError,
    REMARKABLE_HEIGHT_POINTS,
    REMARKABLE_WIDTH_POINTS,
    convert_notebook,
)


def _fake_v6_engine(_rm_file: Path, output_file: Path) -> bool:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(
        str(output_file), pagesize=(REMARKABLE_WIDTH_POINTS, REMARKABLE_HEIGHT_POINTS)
    )
    c.drawString(72, 72, "stroke")
    c.showPage()
    c.save()
    return True


class StrictModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rmsync_strict_"))
        self.backup_root = self.tmp
        (self.backup_root / "Notebooks").mkdir()
        self.backup_dir = self.backup_root / "Notebooks"
        self.uuid = "uuid-1"

        # Manifest declares two pages, but only the first one exists on disk.
        (self.backup_dir / f"{self.uuid}.metadata").write_text(
            json.dumps({"visibleName": "Holey Notebook", "type": "DocumentType"})
        )
        (self.backup_dir / f"{self.uuid}.content").write_text(
            json.dumps(
                {
                    "cPages": {
                        "pages": [
                            {"id": "present"},
                            {"id": "missing-on-disk"},
                        ]
                    }
                }
            )
        )
        page_dir = self.backup_dir / self.uuid
        page_dir.mkdir()
        (page_dir / "present.rm").write_bytes(
            b"reMarkable .rm file version=6\x00"
        )

        self.notebook = {
            "uuid": self.uuid,
            "name": "Holey Notebook",
            "content_file": self.backup_dir / f"{self.uuid}.content",
            "metadata_file": self.backup_dir / f"{self.uuid}.metadata",
            "v6_files": [page_dir / "present.rm"],
            "v5_files": [],
            "v4_files": [],
            "v3_files": [],
            "pdf_files": [],
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lenient_mode_records_missing_pages_in_results(self) -> None:
        output_dir = self.tmp / "PDF_lenient"

        with mock.patch(
            "src.hybrid_converter.convert_v6_file_with_rmc",
            side_effect=_fake_v6_engine,
        ):
            results = convert_notebook(
                self.notebook, output_dir, self.backup_root, None, strict=False
            )

        self.assertEqual(results["expected_page_count"], 2)
        self.assertEqual(results["resolved_page_count"], 2)
        self.assertEqual(results["missing_pages"], ["missing-on-disk"])

        # The PDF still gets written (placeholder for the missing page).
        pdf_path = output_dir / "Holey Notebook.pdf"
        self.assertTrue(pdf_path.exists())
        reader = PdfReader(str(pdf_path))
        self.assertEqual(len(reader.pages), 2)

    def test_strict_mode_raises_page_resolution_error(self) -> None:
        output_dir = self.tmp / "PDF_strict"

        with mock.patch(
            "src.hybrid_converter.convert_v6_file_with_rmc",
            side_effect=_fake_v6_engine,
        ):
            with self.assertRaises(PageResolutionError) as ctx:
                convert_notebook(
                    self.notebook,
                    output_dir,
                    self.backup_root,
                    None,
                    strict=True,
                )

        self.assertEqual(ctx.exception.notebook_name, "Holey Notebook")
        self.assertEqual(ctx.exception.missing_pages, ["missing-on-disk"])


if __name__ == "__main__":
    unittest.main()
