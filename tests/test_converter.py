import json
import logging
import shutil
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner
from PyPDF2 import PdfReader
from reportlab.pdfgen import canvas

from RemarkableSync import cli
from src.converter import run_conversion
from src.hybrid_converter import (
    REMARKABLE_HEIGHT_POINTS,
    REMARKABLE_WIDTH_POINTS,
    convert_notebook,
    get_ordered_pages,
)
from src.template_renderer import TemplateRenderer

# 1x1 transparent PNG used as a stand-in for real reMarkable templates.
_DUMMY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR\0\0\0\x01\0\0\0\x01\x08\x02\0\0\0"
    b"\x90wS\xde\0\0\0\x0cIDAT\x08\xd7c\xf8\xff\xff? \x05\xfe\x02\xfe"
    b"\x1cG\x1f\0\0\0\0IEND\xaeB`\x82"
)


def _write_real_pdf(path: Path, label: str = "page") -> None:
    """Produce a small but structurally valid single-page PDF.

    Used by tests to simulate a successful v6 conversion without depending
    on the real ``rmc`` engine or shipping binary ``.rm`` fixtures.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=(REMARKABLE_WIDTH_POINTS, REMARKABLE_HEIGHT_POINTS))
    c.setFont("Helvetica", 12)
    c.drawString(72, 72, f"mock content: {label}")
    c.showPage()
    c.save()


def _fake_v6_engine(rm_file: Path, output_file: Path) -> bool:
    """Drop-in replacement for ``convert_v6_file_with_rmc`` used in tests."""
    _write_real_pdf(output_file, label=rm_file.stem)
    return True


class _NullProgressBar:
    """Minimal stand-in for ``tqdm`` that emits no output yet supports the
    same iteration / postfix protocol used by the converter."""

    def __init__(self, iterable):
        self._iterable = iterable

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._iterable)

    def set_postfix_str(self, *_a, **_kw):
        return None


class TestRemarkableSync(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("tests/tmp_test")
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir = self.test_dir / "Templates"
        self.templates_dir.mkdir(exist_ok=True)
        # The hybrid converter scans <backup_dir>/Notebooks for metadata,
        # so the test backup root must be the parent of "Notebooks".
        self.backup_root = self.test_dir
        self.backup_dir = self.backup_root / "Notebooks"
        self.backup_dir.mkdir(exist_ok=True)

        self.dummy_png = self.templates_dir / "test_template.png"
        self.dummy_png.write_bytes(_DUMMY_PNG_BYTES)

        # A real-shaped templates manifest keeps the renderer quiet and
        # exercises the parsing path the production code relies on.
        (self.templates_dir / "templates.json").write_text(
            json.dumps(
                {
                    "templates": [
                        {
                            "name": "test_template",
                            "filename": "test_template",
                            "iconCode": "\\ue000",
                            "categories": ["test"],
                        }
                    ]
                }
            )
        )

        # Silence tqdm progress bars during tests so the output channel only
        # ever surfaces real log records (which we now assert against).
        tqdm_patch = mock.patch(
            "src.converter.tqdm",
            lambda iterable, **_: _NullProgressBar(iterable),
        )
        tqdm_patch.start()
        self.addCleanup(tqdm_patch.stop)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _seed_notebook(self, name: str = "Test Notebook", uuid: str = "test-uuid") -> str:
        """Materialise a minimal v6 notebook layout under ``self.backup_dir``."""
        metadata_file = self.backup_dir / f"{uuid}.metadata"
        content_file = self.backup_dir / f"{uuid}.content"
        metadata_file.write_text(json.dumps({"visibleName": name, "type": "DocumentType"}))
        content_file.write_text(json.dumps({"cPages": {"pages": [{"id": "page1"}]}}))

        page_dir = self.backup_dir / uuid
        page_dir.mkdir(exist_ok=True)
        (page_dir / "page1.rm").write_bytes(b"reMarkable .rm file version=6")
        return name

    def _build_notebook_struct(self, name: str = "Test Notebook", uuid: str = "test-uuid") -> dict:
        """Build the dict shape expected by ``convert_notebook`` directly."""
        metadata_file = self.backup_dir / f"{uuid}.metadata"
        content_file = self.backup_dir / f"{uuid}.content"
        return {
            "uuid": uuid,
            "name": name,
            "content_file": content_file,
            "metadata_file": metadata_file,
            "v6_files": [self.backup_dir / uuid / "page1.rm"],
            "v5_files": [],
            "v4_files": [],
            "v3_files": [],
            "pdf_files": [],
        }

    # ------------------------------------------------------------------
    # Template renderer
    # ------------------------------------------------------------------

    def test_template_renderer_loads_manifest_without_warnings(self):
        """A well-formed templates.json must initialise silently."""
        with self.assertNoLogs(level=logging.WARNING):
            renderer = TemplateRenderer(self.templates_dir)
        self.assertIn("test_template", renderer.templates_metadata)

    def test_template_renderer_warns_when_manifest_missing(self):
        """Missing templates.json is signalled at WARNING (regression guard)."""
        empty_dir = self.test_dir / "empty_templates"
        empty_dir.mkdir()
        with self.assertLogs(level=logging.WARNING) as captured:
            TemplateRenderer(empty_dir)
        self.assertTrue(
            any("templates.json not found" in msg for msg in captured.output),
            f"unexpected log output: {captured.output}",
        )

    def test_template_image_discovery(self):
        renderer = TemplateRenderer(self.templates_dir)
        template_file = renderer.get_template_file("test_template")
        self.assertIsNotNone(template_file)
        self.assertEqual(template_file.suffix, ".png")

    def test_template_rendering_to_pdf(self):
        renderer = TemplateRenderer(self.templates_dir)
        output_pdf = self.test_dir / "output.pdf"
        with self.assertNoLogs(level=logging.WARNING):
            success = renderer.render_template_to_pdf("test_template", output_pdf)
        self.assertTrue(success)
        self.assertTrue(output_pdf.exists())
        self.assertGreater(output_pdf.stat().st_size, 0)
        # The rendered template must itself be a valid 1-page PDF.
        reader = PdfReader(str(output_pdf))
        self.assertEqual(len(reader.pages), 1)

    # ------------------------------------------------------------------
    # convert_notebook: success and failure paths
    # ------------------------------------------------------------------

    def test_get_ordered_pages_detects_v6_header(self):
        self._seed_notebook()
        content_file = self.backup_dir / "test-uuid.content"
        pages = get_ordered_pages(content_file)
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["version"], 6)
        self.assertEqual(pages[0]["id"], "page1")

    def test_convert_notebook_success_with_template(self):
        """Mock the v6 engine to assert the *real* success path runs cleanly.

        Verifies:
        - the produced PDF actually contains the mocked content stream,
        - the template background is composited over it,
        - the per-page conversion counter is incremented,
        - no ERROR / WARNING is logged.
        """
        name = self._seed_notebook()
        output_dir = self.test_dir / "PDF"
        renderer = TemplateRenderer(self.templates_dir)

        with mock.patch(
            "src.hybrid_converter.convert_v6_file_with_rmc", side_effect=_fake_v6_engine
        ), self.assertNoLogs(level=logging.WARNING):
            results = convert_notebook(
                self._build_notebook_struct(name=name),
                output_dir,
                self.backup_root,
                renderer,
            )

        pdf_path = output_dir / f"{name}.pdf"
        self.assertTrue(pdf_path.exists(), "expected merged PDF to be written")
        self.assertEqual(results["v6_converted"], 1)
        self.assertEqual(len(results["output_files"]), 1)

        reader = PdfReader(str(pdf_path))
        self.assertEqual(len(reader.pages), 1)
        # The content stream of the merged page must be non-empty: the mock
        # engine drew text and the template renderer drew a background.
        contents = reader.pages[0].get_contents()
        self.assertIsNotNone(contents)
        self.assertGreater(len(contents.get_data()), 0)

    def test_convert_notebook_emits_placeholder_when_engine_fails(self):
        """When the v6 engine fails, a placeholder page is generated and logged.

        This pins the *fallback* behaviour explicitly, so silently regressing
        from real conversion to placeholders cannot pass unnoticed.
        """
        name = self._seed_notebook()
        output_dir = self.test_dir / "PDF"
        renderer = TemplateRenderer(self.templates_dir)

        with mock.patch(
            "src.hybrid_converter.convert_v6_file_with_rmc", return_value=False
        ), self.assertLogs(level=logging.ERROR) as captured:
            results = convert_notebook(
                self._build_notebook_struct(name=name),
                output_dir,
                self.backup_root,
                renderer,
            )

        self.assertEqual(results["v6_converted"], 0)
        self.assertTrue((output_dir / f"{name}.pdf").exists())
        self.assertTrue(
            any("Conversion function failed" in msg for msg in captured.output),
            f"expected failure log, got {captured.output}",
        )

    # ------------------------------------------------------------------
    # run_conversion: --output, --no-templates, --templates-dir
    # ------------------------------------------------------------------

    def test_run_conversion_uses_custom_output_dir(self):
        """`--output` / output_dir parametrises destination without breaking layout."""
        name = self._seed_notebook()
        custom_output = self.test_dir / "custom_pdfs"

        with mock.patch(
            "src.hybrid_converter.convert_v6_file_with_rmc", side_effect=_fake_v6_engine
        ), self.assertNoLogs(level=logging.WARNING):
            success = run_conversion(
                backup_dir=self.backup_root,
                output_dir=custom_output,
                no_templates=True,
            )

        self.assertTrue(success)
        self.assertTrue((custom_output / f"{name}.pdf").exists())
        # Ensure we did not write to the historical default path.
        self.assertFalse((self.backup_root / "PDF").exists())

    def test_run_conversion_no_templates_flag_disables_renderer(self):
        """`--no-templates` skips embedding even when Templates/ is populated."""
        name = self._seed_notebook()
        output_dir = self.test_dir / "no_tpl"
        self.assertTrue(self.templates_dir.exists())

        with mock.patch(
            "src.hybrid_converter.convert_v6_file_with_rmc", side_effect=_fake_v6_engine
        ), mock.patch(
            "src.converter.TemplateRenderer"
        ) as renderer_cls, self.assertNoLogs(level=logging.WARNING):
            ok = run_conversion(
                backup_dir=self.backup_root,
                output_dir=output_dir,
                no_templates=True,
            )

        self.assertTrue(ok)
        self.assertTrue((output_dir / f"{name}.pdf").exists())
        # The renderer must never be constructed when --no-templates is set.
        renderer_cls.assert_not_called()

    def test_run_conversion_with_explicit_templates_dir(self):
        """Custom `--templates-dir` is honoured when embedding is enabled."""
        name = self._seed_notebook()
        alt_templates = self.test_dir / "alt_templates"
        alt_templates.mkdir()
        (alt_templates / "test_template.png").write_bytes(_DUMMY_PNG_BYTES)
        (alt_templates / "templates.json").write_text(
            json.dumps(
                {"templates": [{"name": "test_template", "filename": "test_template"}]}
            )
        )
        output_dir = self.test_dir / "tpl_pdfs"

        with mock.patch(
            "src.hybrid_converter.convert_v6_file_with_rmc", side_effect=_fake_v6_engine
        ), self.assertNoLogs(level=logging.WARNING):
            ok = run_conversion(
                backup_dir=self.backup_root,
                output_dir=output_dir,
                templates_dir=alt_templates,
            )
        self.assertTrue(ok)
        self.assertTrue((output_dir / f"{name}.pdf").exists())

    def test_cli_default_host_is_usb_ip(self):
        """The WiFi/USB toggle defaults to the USB IP for backwards compatibility."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("10.11.99.1", result.output)
        self.assertIn("--host", result.output)

    def test_cli_convert_exposes_new_flags(self):
        """`-o/--output`, `--templates-dir`, `--no-templates` are wired into the CLI."""
        runner = CliRunner()
        result = runner.invoke(cli, ["convert", "--help"])
        self.assertEqual(result.exit_code, 0)
        for token in ("--output", "-o", "--templates-dir", "--no-templates"):
            self.assertIn(token, result.output)


if __name__ == "__main__":
    unittest.main()
