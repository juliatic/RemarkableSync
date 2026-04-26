"""
V6 Converter - Internal Helper Module

Converts v6 ``.rm`` files (current reMarkable format) to PDF.

The converter prefers the in-process ``rmc.rm_to_pdf`` Python API for
maximum throughput and full vector fidelity. When that path is not
available (older ``rmc`` releases or restricted environments) it
transparently falls back to the SVG-based pipeline used previously.
"""

import importlib
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .base_converter import BaseConverter


class V6Converter(BaseConverter):
    """Converter for reMarkable v6 ``.rm`` files.

    Conversion strategy (in priority order):

    1. ``rmc.rm_to_pdf`` Python API — direct vector PDF rendering, no
       subprocess overhead, no rasterisation through SVG.
    2. ``rmc`` command-line tool producing SVG, then SVG → PDF via
       ``svglib`` / ``reportlab`` (legacy fallback).
    """

    _RMC_TIMEOUT_SECONDS = 30

    def __init__(self) -> None:
        super().__init__("v6")
        self._rmc_module: Optional[object] = self._import_rmc()

    @staticmethod
    def _import_rmc() -> Optional[object]:
        """Import the ``rmc`` Python package on demand.

        Returns the module on success, ``None`` if the package is not
        installed (allowing the converter to fall back to the CLI).
        """
        try:
            return importlib.import_module("rmc")
        except ImportError:
            return None

    def can_convert(self, rm_file: Path) -> bool:
        """Return True if the file's header advertises the v6 format."""
        return self.detect_version(rm_file) == "6"

    def convert_to_pdf(self, rm_file: Path, output_file: Path) -> bool:
        """Convert a v6 ``.rm`` file to PDF.

        Args:
            rm_file: Path to the source v6 ``.rm`` file.
            output_file: Path where the PDF should be created.

        Returns:
            bool: True if conversion succeeded, False otherwise.
        """
        if self._rmc_module is not None and hasattr(self._rmc_module, "rm_to_pdf"):
            if self._convert_with_rmc_api(rm_file, output_file):
                return True
            # Fall through to the CLI/SVG fallback.

        return self._convert_via_svg_cli(rm_file, output_file)

    def _convert_with_rmc_api(self, rm_file: Path, output_file: Path) -> bool:
        """Render directly to PDF using the in-process ``rmc`` API."""
        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            self._rmc_module.rm_to_pdf(str(rm_file), str(output_file))  # type: ignore[union-attr]
            if output_file.exists() and output_file.stat().st_size > 0:
                self.logger.debug(
                    "v6 conversion via rmc API: %s -> %s", rm_file.name, output_file.name
                )
                return True
            self.logger.debug("rmc.rm_to_pdf produced no output for %s", rm_file.name)
            return False
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("rmc API conversion failed for %s: %s", rm_file.name, exc)
            return False

    def _convert_via_svg_cli(self, rm_file: Path, output_file: Path) -> bool:
        """Legacy fallback: rmc CLI → SVG → svglib/reportlab → PDF."""
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                svg_file = Path(temp_dir) / f"{rm_file.stem}.svg"

                self.logger.debug("Converting %s to SVG using rmc CLI", rm_file.name)
                result = subprocess.run(
                    ["rmc", "-t", "svg", "-o", str(svg_file), str(rm_file)],
                    capture_output=True,
                    text=True,
                    timeout=self._RMC_TIMEOUT_SECONDS,
                    check=False,
                )

                if result.returncode != 0 or not svg_file.exists():
                    self.logger.debug(
                        "rmc CLI conversion failed for %s: %s",
                        rm_file.name,
                        result.stderr.strip(),
                    )
                    return False

                if svg_file.stat().st_size < 100:
                    self.logger.debug("SVG file suspiciously small for %s", rm_file.name)
                    return False

                return self.svg_to_pdf(svg_file, output_file)

        except subprocess.TimeoutExpired:
            self.logger.warning("rmc conversion timeout for %s", rm_file.name)
            return False
        except FileNotFoundError:
            self.logger.debug("rmc CLI not available; install the rmc package")
            return False
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("v6 fallback conversion error for %s: %s", rm_file.name, exc)
            return False

    def is_rmc_available(self) -> bool:
        """Return True if either the Python API or the CLI is available."""
        if self._rmc_module is not None:
            return True
        try:
            result = subprocess.run(
                ["rmc", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def get_requirements(self) -> list[str]:
        """List the external dependencies used by this converter."""
        return [
            "rmc Python package (preferred, in-process PDF rendering)",
            "rmc command-line tool (fallback)",
            "svglib Python library (fallback)",
            "reportlab Python library (fallback)",
        ]
