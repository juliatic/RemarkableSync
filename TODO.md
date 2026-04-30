# TODO

## Completed (delivered in current release)

- [x] **Sync reliability** — fixed multi-page background merging (template
  re-read per page eliminates the shallow-copy `/Contents` bug), added a
  `PageResolver` that surfaces missing pages instead of silently skipping
  them, added `--strict` mode for CI/archival workflows, added post-download
  size verification so truncated SCP transfers cannot be marked as synced.
- [x] **OCR** — added `RemarkableSync ocr` with pluggable backends (Apple
  Vision on macOS, Tesseract elsewhere). Produces a `<name>_text.pdf` text
  layer and optional `.txt` / `.md` sidecars. Runs entirely on-device.
- [x] **Export quality** — embedded PDF metadata (title, creation date,
  modification date, producer = `RemarkableSync`) sourced from `.metadata`.
- [x] **Google NotebookLM bundling** — added
  `RemarkableSync notebooklm-bundle` that gathers per-notebook PDFs
  (preferring the OCR text PDF), enforces NotebookLM's per-source size cap,
  and writes a `manifest.md` index ready to drag-and-drop.

## Future ideas

- [ ] Native support for older `.rm` v3/v4 formats (currently best-effort
      via the v6 fallback path).
- [ ] First-class TrOCR / EasyOCR backends for higher-quality OCR on
      Linux/Windows than Tesseract.
- [ ] PDF/A export profile for long-term archival.
- [ ] Generate PDF bookmarks from the device folder hierarchy.
- [ ] Direct NotebookLM ingestion if/when Google publishes a public API.
- [ ] Optional cloud-sync target (Dropbox / OneDrive / WebDAV) post-conversion.
- [ ] GUI / web front-end wrapping the CLI.

