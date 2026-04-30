"""Tests for ``RemarkableSync notebooklm-bundle``.

Verifies that:
- the OCR text variant is preferred over the graphical PDF when both exist,
- ``--no-prefer-ocr`` flips that preference,
- ``--max-mb`` excludes oversized files,
- a ``manifest.md`` is always emitted at the bundle root.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner
from reportlab.pdfgen import canvas

from RemarkableSync import cli
from src.commands.notebooklm_command import run_notebooklm_bundle_command


def _write_pdf(path: Path, label: str = "stub", pad_kb: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path))
    c.drawString(72, 720, label)
    c.showPage()
    c.save()
    if pad_kb:
        with open(path, "ab") as fh:
            # PDF readers ignore trailing junk; this lets us inflate file
            # sizes deterministically to exercise the --max-mb filter.
            fh.write(b"%PDF-PADDING\n" + b"x" * (pad_kb * 1024))


class NotebookLMBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rmsync_lm_"))
        self.pdf_dir = self.tmp / "PDF"
        self.bundle_dir = self.tmp / "bundle"
        self.pdf_dir.mkdir()

        # "Alpha" has both graphical + OCR variants → OCR should win by default.
        _write_pdf(self.pdf_dir / "Alpha.pdf", "alpha graphical")
        _write_pdf(self.pdf_dir / "Alpha_text.pdf", "alpha OCR text")
        # "Beta" has only the graphical PDF.
        _write_pdf(self.pdf_dir / "Beta.pdf", "beta only")
        # Nested folder to exercise rglob.
        _write_pdf(self.pdf_dir / "Folder" / "Gamma.pdf", "gamma nested")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _bundle(self, **kwargs):
        defaults = dict(
            pdf_dir=self.pdf_dir,
            output_dir=self.bundle_dir,
            notebook=None,
            max_mb=200,
            verbose=False,
            prefer_ocr=True,
        )
        defaults.update(kwargs)
        return run_notebooklm_bundle_command(**defaults)

    # --------------------------------------------------------------

    def test_prefers_ocr_text_pdf_over_graphical(self) -> None:
        rc = self._bundle()
        self.assertEqual(rc, 0)
        bundled = self.bundle_dir / "Alpha.pdf"
        self.assertTrue(bundled.exists())
        # The bundled file must be the OCR variant, not the graphical one.
        self.assertEqual(
            bundled.read_bytes(),
            (self.pdf_dir / "Alpha_text.pdf").read_bytes(),
        )

    def test_prefer_ocr_off_uses_graphical(self) -> None:
        rc = self._bundle(prefer_ocr=False)
        self.assertEqual(rc, 0)
        bundled = self.bundle_dir / "Alpha.pdf"
        self.assertTrue(bundled.exists())
        self.assertEqual(
            bundled.read_bytes(),
            (self.pdf_dir / "Alpha.pdf").read_bytes(),
        )

    def test_includes_documents_without_ocr_variant(self) -> None:
        self._bundle()
        self.assertTrue((self.bundle_dir / "Beta.pdf").exists())
        self.assertTrue((self.bundle_dir / "Gamma.pdf").exists())

    def test_manifest_lists_every_bundled_file(self) -> None:
        self._bundle()
        manifest = (self.bundle_dir / "manifest.md").read_text(encoding="utf-8")
        self.assertIn("Alpha.pdf", manifest)
        self.assertIn("Beta.pdf", manifest)
        self.assertIn("Gamma.pdf", manifest)
        # Per-file type column should advertise the OCR variant for Alpha.
        self.assertRegex(manifest, r"Alpha\.pdf.*OCR text")

    def test_max_mb_excludes_oversized_files(self) -> None:
        # Pad Beta over 1 MB; cap bundle at 1 MB.
        _write_pdf(self.pdf_dir / "Beta.pdf", "beta", pad_kb=1100)
        self._bundle(max_mb=1)
        self.assertTrue((self.bundle_dir / "Alpha.pdf").exists())
        self.assertFalse((self.bundle_dir / "Beta.pdf").exists())

    def test_notebook_filter(self) -> None:
        self._bundle(notebook="Alpha")
        self.assertTrue((self.bundle_dir / "Alpha.pdf").exists())
        self.assertFalse((self.bundle_dir / "Beta.pdf").exists())
        self.assertFalse((self.bundle_dir / "Gamma.pdf").exists())

    def test_cli_exposes_command(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["notebooklm-bundle", "--help"])
        self.assertEqual(result.exit_code, 0)
        for token in ("--pdf-dir", "--output", "--max-mb", "--no-prefer-ocr"):
            self.assertIn(token, result.output)


if __name__ == "__main__":
    unittest.main()
