"""Regression tests for ``merge_pdf_with_template``.

The previous implementation cached a single ``PageObject`` for the
template and used ``copy.copy`` to clone it per content page. Because
``PageObject.merge_page`` mutates ``/Contents`` and ``/Resources`` in
place, that cloning was insufficient: strokes from page N could leak
onto page N+1, and the template background would only render on the
first page. These tests pin the fix in place: every page in the merged
output must independently carry both the template *and* its own content.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from PyPDF2 import PdfReader
from reportlab.pdfgen import canvas

from src.hybrid_converter import (
    REMARKABLE_HEIGHT_POINTS,
    REMARKABLE_WIDTH_POINTS,
    merge_pdf_with_template,
)


def _write_template_pdf(path: Path) -> None:
    """A 1-page template containing a single, easily-recognisable marker."""
    c = canvas.Canvas(
        str(path), pagesize=(REMARKABLE_WIDTH_POINTS, REMARKABLE_HEIGHT_POINTS)
    )
    c.setFont("Helvetica", 14)
    c.drawString(50, 500, "TEMPLATEMARKER")
    c.showPage()
    c.save()


def _write_multipage_content_pdf(path: Path, page_labels: list[str]) -> None:
    """A multi-page content PDF with one unique label per page."""
    c = canvas.Canvas(
        str(path), pagesize=(REMARKABLE_WIDTH_POINTS, REMARKABLE_HEIGHT_POINTS)
    )
    c.setFont("Helvetica", 12)
    for label in page_labels:
        c.drawString(72, 72, label)
        c.showPage()
    c.save()


def _page_text_streams(pdf_path: Path) -> list[bytes]:
    """Return raw decoded content stream bytes for each page.

    Used in lieu of full text extraction (which depends on optional deps)
    so the assertions remain self-contained.
    """
    reader = PdfReader(str(pdf_path))
    out: list[bytes] = []
    for page in reader.pages:
        contents = page.get_contents()
        out.append(contents.get_data() if contents is not None else b"")
    return out


class MergePdfWithTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rmsync_merge_"))
        self.template_pdf = self.tmp / "template.pdf"
        self.content_pdf = self.tmp / "content.pdf"
        self.output_pdf = self.tmp / "merged.pdf"
        _write_template_pdf(self.template_pdf)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_template_appears_on_every_page(self) -> None:
        """Regression for shallow-copy bug: background must be on every page."""
        _write_multipage_content_pdf(
            self.content_pdf, ["PAGEONE", "PAGETWO", "PAGETHREE"]
        )

        ok = merge_pdf_with_template(
            self.content_pdf, self.template_pdf, self.output_pdf
        )

        self.assertTrue(ok)
        streams = _page_text_streams(self.output_pdf)
        self.assertEqual(len(streams), 3)
        for i, stream in enumerate(streams):
            self.assertIn(
                b"TEMPLATEMARKER",
                stream,
                f"template missing from output page {i + 1}",
            )

    def test_content_does_not_bleed_across_pages(self) -> None:
        """Each output page must carry its own content only (no cross-page bleed)."""
        labels = ["UNIQUEAAA", "UNIQUEBBB", "UNIQUECCC"]
        _write_multipage_content_pdf(self.content_pdf, labels)

        ok = merge_pdf_with_template(
            self.content_pdf, self.template_pdf, self.output_pdf
        )
        self.assertTrue(ok)

        streams = _page_text_streams(self.output_pdf)
        self.assertEqual(len(streams), 3)
        for i, expected_label in enumerate(labels):
            self.assertIn(expected_label.encode("ascii"), streams[i])
            for j, other_label in enumerate(labels):
                if j == i:
                    continue
                self.assertNotIn(
                    other_label.encode("ascii"),
                    streams[i],
                    f"content from page {j + 1} leaked onto page {i + 1}",
                )

    def test_no_template_path_passes_content_through(self) -> None:
        _write_multipage_content_pdf(self.content_pdf, ["onlycontent"])

        ok = merge_pdf_with_template(self.content_pdf, None, self.output_pdf)
        self.assertTrue(ok)

        reader = PdfReader(str(self.output_pdf))
        self.assertEqual(len(reader.pages), 1)
        contents = reader.pages[0].get_contents()
        self.assertIsNotNone(contents)
        self.assertIn(b"onlycontent", contents.get_data())

    def test_missing_content_pdf_returns_false(self) -> None:
        ok = merge_pdf_with_template(
            self.tmp / "does-not-exist.pdf", self.template_pdf, self.output_pdf
        )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
