"""
Page Resolver - Internal Helper Module

Resolves the ordered list of pages for a notebook from its ``.content``
metadata file, locating the matching ``.rm`` files on disk and detecting
the ``.rm`` format version of each one.

This module exists to keep ``convert_notebook`` focused on orchestration
and to make page-resolution behaviour independently testable. It also
introduces a single, structured definition of what a "missed" page looks
like so the converter can report misses to the user instead of silently
emitting placeholder pages.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


_VERSION_HEADER_BYTES = 50


def detect_rm_version(rm_file: Path, default: int = 6) -> int:
    """Return the format version advertised in an ``.rm`` file's header.

    The reMarkable ``.rm`` binary format begins with an ASCII header
    containing ``version=N``. We read at most :data:`_VERSION_HEADER_BYTES`
    bytes and look for one of the known version markers.

    Args:
        rm_file: Path to a ``.rm`` file. The file must exist.
        default: Version to assume when the header cannot be read or
            does not contain a recognised marker.

    Returns:
        Detected version as an integer (3, 4, 5, or 6). Returns
        ``default`` on any failure.
    """
    try:
        with open(rm_file, "rb") as fh:
            header = fh.read(_VERSION_HEADER_BYTES).decode("ascii", errors="ignore")
    except OSError as exc:
        logger.debug("Cannot read header for %s: %s", rm_file, exc)
        return default

    for version in (6, 5, 4, 3):
        if f"version={version}" in header:
            return version
    return default


@dataclass(frozen=True)
class ResolvedPage:
    """A single page resolved from a notebook's ``.content`` manifest.

    Attributes:
        index: Zero-based ordinal in the notebook (matches ``.content`` order).
        page_id: UUID string from the manifest.
        rm_file: Path to the ``.rm`` file when found, else ``None``.
        version: Detected ``.rm`` format version (default 6 when missing).
        template_name: Template name from the manifest, or ``"Blank"``.
    """

    index: int
    page_id: str
    rm_file: Optional[Path]
    version: int
    template_name: str

    @property
    def is_missing(self) -> bool:
        """True when no ``.rm`` file could be located for this page."""
        return self.rm_file is None


@dataclass
class ResolutionReport:
    """Result of resolving every page in a notebook's ``.content`` file.

    Carries both the ordered page list and any structural anomalies that
    the converter or CLI may want to surface to the user.
    """

    pages: List[ResolvedPage] = field(default_factory=list)
    expected_page_count: int = 0
    missing_page_ids: List[str] = field(default_factory=list)
    parse_errors: List[str] = field(default_factory=list)

    @property
    def has_misses(self) -> bool:
        return bool(self.missing_page_ids)

    @property
    def page_count_mismatch(self) -> bool:
        """True when the resolved page count differs from the manifest count."""
        return self.expected_page_count != len(self.pages)


class PageResolver:
    """Resolve and order pages declared in a notebook's ``.content`` file.

    The resolver performs three responsibilities that were previously
    interleaved inside ``hybrid_converter.convert_notebook``:

    1. Parse ``cPages.pages`` (current) or legacy ``pages`` from the
       ``.content`` manifest, preserving order.
    2. Locate the matching ``.rm`` file per page using a small set of
       documented fallback strategies.
    3. Detect each ``.rm`` file's format version via
       :func:`detect_rm_version`.

    Misses are recorded in :class:`ResolutionReport` rather than swallowed
    silently, so callers can decide whether to abort, warn, or emit
    placeholders.
    """

    def __init__(self, default_version: int = 6) -> None:
        self._default_version = default_version

    def resolve(self, content_file: Path) -> ResolutionReport:
        """Resolve all pages declared in ``content_file``.

        Args:
            content_file: Path to a notebook's ``.content`` JSON file.

        Returns:
            A :class:`ResolutionReport` whose ``pages`` list preserves
            the order declared in the manifest.
        """
        report = ResolutionReport()

        if not content_file or not content_file.exists():
            report.parse_errors.append(
                f".content file not found: {content_file}"
            )
            return report

        try:
            with open(content_file, "r", encoding="utf-8") as fh:
                content_data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            msg = f"Failed to parse .content file {content_file}: {exc}"
            logger.warning(msg)
            report.parse_errors.append(msg)
            return report

        page_entries = self._extract_page_entries(content_data)
        report.expected_page_count = len(page_entries)

        notebook_dir = content_file.parent / content_file.stem
        sibling_dir = content_file.parent

        for index, entry in enumerate(page_entries):
            page_id = entry.get("id")
            if not page_id:
                logger.warning(
                    "Page entry %d in %s has no id; skipping",
                    index,
                    content_file.name,
                )
                continue

            template_name = (
                entry.get("template", {}).get("value") or "Blank"
            )
            rm_file = self._locate_rm_file(page_id, notebook_dir, sibling_dir)
            version = (
                detect_rm_version(rm_file, default=self._default_version)
                if rm_file is not None
                else self._default_version
            )

            page = ResolvedPage(
                index=index,
                page_id=page_id,
                rm_file=rm_file,
                version=version,
                template_name=template_name,
            )
            report.pages.append(page)
            if page.is_missing:
                report.missing_page_ids.append(page_id)

        return report

    @staticmethod
    def _extract_page_entries(content_data: dict) -> List[dict]:
        """Normalise the manifest's heterogeneous page layouts.

        ``.content`` manifests have appeared in two shapes across firmware
        versions and within ``cPages``:
          * ``[{"id": "...", "template": {"value": "..."}}, ...]`` (current)
          * ``["uuid-string", ...]`` (legacy)
        """
        c_pages = content_data.get("cPages", {})
        raw_entries = c_pages.get("pages") or content_data.get("pages") or []

        normalised: List[dict] = []
        for entry in raw_entries:
            if isinstance(entry, str):
                normalised.append({"id": entry})
            elif isinstance(entry, dict):
                normalised.append(entry)
        return normalised

    @staticmethod
    def _locate_rm_file(
        page_id: str, notebook_dir: Path, sibling_dir: Path
    ) -> Optional[Path]:
        """Find the ``.rm`` file for ``page_id`` using ordered fallbacks.

        Strategy:
          1. ``<notebook_dir>/<page_id>.rm`` — canonical layout.
          2. ``<sibling_dir>/<page_id>.rm`` — flat layout used by some backups.
          3. Recursive glob under ``<sibling_dir>`` — last-resort match.

        Returns ``None`` when no matching file exists.
        """
        candidate = notebook_dir / f"{page_id}.rm"
        if candidate.exists():
            return candidate

        candidate = sibling_dir / f"{page_id}.rm"
        if candidate.exists():
            return candidate

        matches = list(sibling_dir.glob(f"**/{page_id}.rm"))
        if matches:
            return matches[0]

        return None
