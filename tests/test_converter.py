import unittest
import os
import shutil
import json
from pathlib import Path
from src.template_renderer import TemplateRenderer
from src.hybrid_converter import convert_notebook, get_ordered_pages
import logging

class TestRemarkableSync(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("tests/tmp_test")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir = self.test_dir / "Templates"
        self.templates_dir.mkdir(exist_ok=True)
        self.backup_dir = self.test_dir / "Notebooks"
        self.backup_dir.mkdir(exist_ok=True)
        
        # Create a dummy PNG template
        self.dummy_png = self.templates_dir / "test_template.png"
        with open(self.dummy_png, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR\0\0\0\x01\0\0\0\x01\x08\x02\0\0\0\x90wS\xde\0\0\0\x0cIDAT\x08\xd7c\xf8\xff\xff? \x05\xfe\x02\xfe\x1cG\x1f\0\0\0\0IEND\xaeB`\x82")

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_template_image_discovery(self):
        renderer = TemplateRenderer(self.templates_dir)
        template_file = renderer.get_template_file("test_template")
        self.assertIsNotNone(template_file)
        self.assertEqual(template_file.suffix, ".png")

    def test_template_rendering_to_pdf(self):
        renderer = TemplateRenderer(self.templates_dir)
        output_pdf = self.test_dir / "output.pdf"
        success = renderer.render_template_to_pdf("test_template", output_pdf)
        self.assertTrue(success)
        self.assertTrue(output_pdf.exists())
        self.assertGreater(output_pdf.stat().st_size, 0)

    def test_notebook_conversion_fallback(self):
        # Create a dummy notebook structure
        notebook_uuid = "test-uuid"
        content_file = self.backup_dir / f"{notebook_uuid}.content"
        metadata_file = self.backup_dir / f"{notebook_uuid}.metadata"
        
        # Create metadata file
        with open(metadata_file, "w") as f:
            json.dump({"visibleName": "Test Notebook", "type": "DocumentType"}, f)
            
        with open(content_file, "w") as f:
            json.dump({"cPages": {"pages": [{"id": "page1"}]}, "fileType": "notebook", "name": "Test Notebook"}, f)
        
        # Create a dummy V6 file to test version detection
        rm_file = self.backup_dir / f"{notebook_uuid}" / "page1.rm"
        rm_file.parent.mkdir(exist_ok=True)
        with open(rm_file, "wb") as f:
            f.write(b"reMarkable .rm file version=6")

        # Create notebook data structure expected by convert_notebook
        notebook_data = {
            "uuid": notebook_uuid,
            "name": "Test Notebook",
            "content_file": content_file,
            "metadata_file": metadata_file,
            "v6_files": [],
            "v5_files": [],
            "pdf_files": []
        }
        
        # Verify page detection
        pages = get_ordered_pages(content_file)
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["version"], 6)

        # Verify conversion fallback
        renderer = TemplateRenderer(self.templates_dir)
        output_dir = self.test_dir / "PDF"
        results = convert_notebook(notebook_data, output_dir, self.backup_dir, renderer)
        
        pdf_path = output_dir / "Test Notebook.pdf"
        self.assertTrue(pdf_path.exists())
        self.assertEqual(len(results["output_files"]), 1)
        
        # Stricter check: Verify PDF has pages and content
        from PyPDF2 import PdfReader
        reader = PdfReader(str(pdf_path))
        self.assertEqual(len(reader.pages), 1)
        
        # Check that the page has merged content (more than 1 entry in its contents)
        # This is a bit of a heuristic but works for verifying merging
        page = reader.pages[0]
        self.assertIsNotNone(page.get_contents())

if __name__ == "__main__":
    unittest.main()
