"""Tests for the OCR pipeline using a fake backend.

We do not exercise the Apple Vision or Tesseract backends directly here
(both require platform-specific dependencies that may not be installed
in CI). Instead we patch ``discover_backend`` with a fake that returns
deterministic ``OCRResult`` instances, which lets us pin the writers
(text PDF, .txt, .md) and the CLI orchestration in place.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner
from PyPDF2 import PdfReader
from reportlab.pdfgen import canvas

from RemarkableSync import cli
from src.commands.ocr_command import run_ocr_command
from src.ocr.base import OCRBackend, OCRPage, OCRResult
from src.ocr.writers import (
    write_markdown_sidecar,
    write_text_pdf,
    write_text_sidecar,
)


def _write_simple_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path))
    c.drawString(72, 720, "stub")
    c.showPage()
    c.save()


class _FakeBackend(OCRBackend):
    """Returns a pre-baked OCRResult so writer/CLI tests are deterministic."""

    name = "fake"

    def __init__(self, pages_text=None) -> None:
        super().__init__()
        self._pages_text = pages_text or ["hello world", "second page text"]

    def is_available(self) -> bool:
        return True

    def recognize_pdf(self, pdf_path: Path) -> OCRResult:
        return OCRResult(
            source_pdf=pdf_path,
            backend_name=self.name,
            pages=[
                OCRPage(page_number=i + 1, text=text, confidence=0.95)
                for i, text in enumerate(self._pages_text)
            ],
        )


class WritersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rmsync_ocr_"))
        self.result = OCRResult(
            source_pdf=self.tmp / "src.pdf",
            backend_name="fake",
            pages=[
                OCRPage(page_number=1, text="line a\nline b", confidence=0.9),
                OCRPage(page_number=2, text="page two", confidence=0.5),
            ],
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_text_pdf_has_one_page_per_source_page(self) -> None:
        out = self.tmp / "out_text.pdf"
        self.assertTrue(write_text_pdf(self.result, out))
        reader = PdfReader(str(out))
        self.assertEqual(len(reader.pages), 2)

    def test_text_pdf_handles_empty_result(self) -> None:
        out = self.tmp / "empty_text.pdf"
        empty = OCRResult(source_pdf=self.tmp / "src.pdf", backend_name="fake")
        self.assertTrue(write_text_pdf(empty, out))
        reader = PdfReader(str(out))
        # Always emits at least one placeholder page so downstream tools
        # can still attach the file as a NotebookLM source.
        self.assertGreaterEqual(len(reader.pages), 1)

    def test_txt_sidecar_contains_page_markers_and_text(self) -> None:
        out = self.tmp / "out.txt"
        self.assertTrue(write_text_sidecar(self.result, out))
        body = out.read_text(encoding="utf-8")
        self.assertIn("--- Page 1 ---", body)
        self.assertIn("line a", body)
        self.assertIn("--- Page 2 ---", body)
        self.assertIn("page two", body)

    def test_markdown_sidecar_uses_headings(self) -> None:
        out = self.tmp / "out.md"
        self.assertTrue(write_markdown_sidecar(self.result, out))
        body = out.read_text(encoding="utf-8")
        self.assertIn("# OCR: src", body)
        self.assertIn("## Page 1", body)
        self.assertIn("## Page 2", body)


class OCRCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rmsync_ocr_cmd_"))
        self.pdf_dir = self.tmp / "PDF"
        self.pdf_dir.mkdir()
        _write_simple_pdf(self.pdf_dir / "Notebook A.pdf")
        _write_simple_pdf(self.pdf_dir / "Notebook B.pdf")
        # An existing _text.pdf should be skipped on re-run (no double OCR).
        _write_simple_pdf(self.pdf_dir / "Notebook A_text.pdf")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, **kwargs):
        defaults = dict(
            pdf_dir=self.pdf_dir,
            output_dir=None,
            engine=None,
            output_formats=["pdf", "txt"],
            verbose=False,
            notebook=None,
        )
        defaults.update(kwargs)
        with mock.patch(
            "src.commands.ocr_command.discover_backend",
            return_value=_FakeBackend(),
        ):
            return run_ocr_command(**defaults)

    def test_writes_pdf_and_txt_for_each_source(self) -> None:
        rc = self._run()
        self.assertEqual(rc, 0)
        # Two source PDFs => two _text.pdf and two .txt outputs.
        self.assertTrue((self.pdf_dir / "Notebook A_text.pdf").exists())
        self.assertTrue((self.pdf_dir / "Notebook B_text.pdf").exists())
        self.assertTrue((self.pdf_dir / "Notebook A.txt").exists())
        self.assertTrue((self.pdf_dir / "Notebook B.txt").exists())

    def test_skips_existing_text_pdfs_as_input(self) -> None:
        """``Notebook A_text.pdf`` must not be OCR'd into ``A_text_text.pdf``."""
        self._run()
        self.assertFalse((self.pdf_dir / "Notebook A_text_text.pdf").exists())

    def test_notebook_filter_limits_inputs(self) -> None:
        rc = self._run(notebook="Notebook A")
        self.assertEqual(rc, 0)
        self.assertTrue((self.pdf_dir / "Notebook A.txt").exists())
        self.assertFalse((self.pdf_dir / "Notebook B.txt").exists())

    def test_invalid_format_returns_error_exit_code(self) -> None:
        rc = self._run(output_formats=["bogus"])
        self.assertEqual(rc, 2)

    def test_cli_exposes_ocr_command(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["ocr", "--help"])
        self.assertEqual(result.exit_code, 0)
        for token in ("--pdf-dir", "--engine", "--format"):
            self.assertIn(token, result.output)


if __name__ == "__main__":
    unittest.main()
