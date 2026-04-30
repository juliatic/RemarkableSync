"""Regression tests for :mod:`src.page_resolver`.

These tests pin down the structural behaviour the converter depends on:
- pages are returned in the order declared by the manifest,
- missing ``.rm`` files are reported (not silently dropped),
- the legacy ``["uuid", ...]`` manifest layout is still understood,
- ``.rm`` version is detected from the file header,
- malformed manifests degrade gracefully instead of crashing.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from src.page_resolver import (
    PageResolver,
    ResolutionReport,
    detect_rm_version,
)


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data))
    elif isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(str(data))


class PageResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rmsync_resolver_"))
        self.uuid = "nb-uuid"
        self.content_file = self.tmp / f"{self.uuid}.content"
        self.notebook_dir = self.tmp / self.uuid
        self.notebook_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- ordering & template extraction -----------------------------------

    def test_pages_returned_in_manifest_order(self) -> None:
        _write(
            self.content_file,
            {
                "cPages": {
                    "pages": [
                        {"id": "p1", "template": {"value": "Blank"}},
                        {"id": "p2", "template": {"value": "P Grid small"}},
                        {"id": "p3", "template": {"value": "Lines"}},
                    ]
                }
            },
        )
        for pid in ("p1", "p2", "p3"):
            _write(self.notebook_dir / f"{pid}.rm", b"reMarkable .rm file version=6")

        report = PageResolver().resolve(self.content_file)

        self.assertEqual(report.expected_page_count, 3)
        self.assertEqual([p.page_id for p in report.pages], ["p1", "p2", "p3"])
        self.assertEqual(
            [p.template_name for p in report.pages],
            ["Blank", "P Grid small", "Lines"],
        )
        self.assertFalse(report.has_misses)
        self.assertFalse(report.page_count_mismatch)

    def test_legacy_string_pages_layout(self) -> None:
        """Old firmware stored pages as a flat list of UUID strings."""
        _write(self.content_file, {"pages": ["a", "b"]})
        _write(self.notebook_dir / "a.rm", b"reMarkable .rm file version=5")
        _write(self.notebook_dir / "b.rm", b"reMarkable .rm file version=6")

        report = PageResolver().resolve(self.content_file)

        self.assertEqual([p.page_id for p in report.pages], ["a", "b"])
        self.assertEqual([p.version for p in report.pages], [5, 6])
        self.assertEqual(
            [p.template_name for p in report.pages], ["Blank", "Blank"]
        )

    # -- miss reporting ---------------------------------------------------

    def test_missing_rm_files_are_reported_not_swallowed(self) -> None:
        """Missing pages must be visible to the caller, not silently filled."""
        _write(
            self.content_file,
            {
                "cPages": {
                    "pages": [
                        {"id": "present"},
                        {"id": "ghost"},
                    ]
                }
            },
        )
        _write(
            self.notebook_dir / "present.rm",
            b"reMarkable .rm file version=6",
        )

        report = PageResolver().resolve(self.content_file)

        self.assertEqual(report.expected_page_count, 2)
        self.assertEqual(len(report.pages), 2)
        self.assertTrue(report.has_misses)
        self.assertEqual(report.missing_page_ids, ["ghost"])
        self.assertIsNone(report.pages[1].rm_file)
        self.assertTrue(report.pages[1].is_missing)

    def test_recursive_fallback_locates_rm_file(self) -> None:
        """Files that aren't in the canonical dir are still located."""
        _write(self.content_file, {"cPages": {"pages": [{"id": "deep"}]}})
        nested = self.notebook_dir / "subfolder"
        nested.mkdir()
        _write(nested / "deep.rm", b"reMarkable .rm file version=6")

        report = PageResolver().resolve(self.content_file)

        self.assertEqual(len(report.pages), 1)
        self.assertIsNotNone(report.pages[0].rm_file)
        self.assertEqual(report.pages[0].rm_file.name, "deep.rm")

    # -- error tolerance --------------------------------------------------

    def test_missing_content_file_returns_empty_report_with_error(self) -> None:
        report = PageResolver().resolve(self.tmp / "does-not-exist.content")
        self.assertEqual(report.pages, [])
        self.assertEqual(report.expected_page_count, 0)
        self.assertTrue(report.parse_errors)

    def test_malformed_json_returns_empty_report_with_error(self) -> None:
        self.content_file.write_text("{not json")
        report = PageResolver().resolve(self.content_file)
        self.assertEqual(report.pages, [])
        self.assertTrue(report.parse_errors)


class DetectRmVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="rmsync_detect_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detects_v6(self) -> None:
        f = self.tmp / "a.rm"
        f.write_bytes(b"reMarkable .rm file version=6\x00")
        self.assertEqual(detect_rm_version(f), 6)

    def test_detects_v5(self) -> None:
        f = self.tmp / "a.rm"
        f.write_bytes(b"reMarkable .rm file version=5\x00")
        self.assertEqual(detect_rm_version(f), 5)

    def test_unknown_header_falls_back_to_default(self) -> None:
        f = self.tmp / "a.rm"
        f.write_bytes(b"\x00\x00\x00")
        self.assertEqual(detect_rm_version(f, default=6), 6)
        self.assertEqual(detect_rm_version(f, default=0), 0)


if __name__ == "__main__":
    unittest.main()
