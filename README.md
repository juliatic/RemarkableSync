# RemarkableSync
[![GitHub](https://img.shields.io/badge/GitHub-RemarkableSync-blue?logo=github)](https://github.com/JeffSteinbok/RemarkableSync)
[![GitHub release](https://img.shields.io/github/v/release/JeffSteinbok/RemarkableSync)](https://github.com/JeffSteinbok/RemarkableSync/releases)

[![CI](https://github.com/JeffSteinbok/RemarkableSync/actions/workflows/ci.yml/badge.svg)](https://github.com/JeffSteinbok/RemarkableSync/actions/workflows/ci.yml)
[![Build Executables](https://github.com/JeffSteinbok/RemarkableSync/actions/workflows/build-executables.yml/badge.svg)](https://github.com/JeffSteinbok/RemarkableSync/actions/workflows/build-executables.yml)
[![Release](https://github.com/JeffSteinbok/RemarkableSync/actions/workflows/release.yml/badge.svg)](https://github.com/JeffSteinbok/RemarkableSync/actions/workflows/release.yml)

[![Publish to PyPI](https://github.com/JeffSteinbok/RemarkableSync/actions/workflows/publish-pypi.yml/badge.svg)](https://github.com/JeffSteinbok/RemarkableSync/actions/workflows/publish-pypi.yml)
[![PyPI version](https://img.shields.io/pypi/v/remarkablesync.svg)](https://pypi.org/project/remarkablesync/)
[![Homebrew](https://github.com/JeffSteinbok/RemarkableSync/actions/workflows/update-homebrew.yml/badge.svg)](https://github.com/JeffSteinbok/RemarkableSync/actions/workflows/update-homebrew.yml)


A comprehensive Python toolkit for backing up and converting reMarkable tablet notebooks to PDF, with template support, on-device folder hierarchy preservation, local OCR, and a Google NotebookLM bundling step.

> [!IMPORTANT]
> This tool has been tested exclusively on reMarkable 2. Compatibility with reMarkable 1 is not guaranteed.


## Features

### 🔄 Backup & Sync
- **Flexible Connection**: Connects via USB (10.11.99.1) or WiFi (with `--host`)
- **Incremental Sync**: Only downloads files that have changed since last backup
- **Complete Backup**: Backs up all notebooks, documents, and metadata
- **Template Support**: Automatically backs up template files from the device
- **File Integrity**: MD5 hash verification for synced files, plus a
  post-download size guard that detects truncated SCP transfers and forces
  a retry on the next run instead of marking the partial file as "synced"

### 📄 PDF Conversion
- **Hybrid Converter**: Supports both v5 and v6 .rm file formats
- **Vector-first Engine**: Renders v6 notebooks straight to PDF through the
  in-process `rmc` Python API — no subprocess round-trip, no SVG rasterisation
- **Reliable Template Compositing**: Per-page background re-read eliminates the
  shallow-copy bug that previously caused missing backgrounds and stroke bleed
  on multi-page notebooks
- **Structured Page Resolver**: Pages declared in `.content` are validated
  against `.rm` files on disk; missing pages are reported (not silently
  swallowed) and surfaced in the end-of-run summary
- **Strict Mode**: `--strict` aborts a notebook when its manifest references
  pages that are not present on disk, instead of emitting placeholders
- **Embedded PDF Metadata**: Each output PDF carries the notebook title,
  creation date, and last-modified date pulled from the device `.metadata`
- **Template Rendering**: Optionally embeds original notebook templates
  (grids, lines, dots, custom PNG/SVG backgrounds) with accurate 226 DPI → 72 pt scaling
- **Parametric Output**: Point `--output/-o` anywhere; defaults to `<backup>/PDF`
- **Configurable Templates**: Use `--templates-dir` for custom assets or
  `--no-templates` to emit content-only PDFs
- **Folder Hierarchy**: Recreates original device folder structure in output
- **Single PDF per Notebook**: Merges all pages into one PDF file per notebook
- **Compact Output**: Content streams are compressed on write for smaller files
  with full vector fidelity
- **Smart Conversion**: Only converts notebooks updated in the last backup
- **Progress Tracking**: Visual progress bars and detailed logging

### 🔠 Local OCR (`ocr` command)
- **Pluggable Backends**: Apple Vision on macOS (default; uses the same engine
  that powers system-wide handwriting recognition) and Tesseract elsewhere
- **No Cloud Calls**: OCR runs entirely on your machine
- **Multiple Outputs**: Produces a separate `<name>_text.pdf` (text-only PDF
  with one page per source page), and optional `.txt` and `.md` sidecars
- **Notebook Filter & Engine Override**: `--notebook` to scope a single
  document, `--engine vision|tesseract` to force a backend

### 🧠 Google NotebookLM Bundling (`notebooklm-bundle` command)
- **Best-Variant Selection**: Prefers the OCR text PDF when present, falls
  back to the graphical PDF; flip with `--no-prefer-ocr`
- **Size Guard**: `--max-mb` skips files above NotebookLM's per-source limit
  (default 200 MB)
- **Manifest Index**: Writes a `manifest.md` listing every bundled document
  with its type, size, and original path — ready to drag-and-drop into a
  NotebookLM project

## Prerequisites

1. **reMarkable Tablet Setup**:
   - Connect your reMarkable tablet to your computer via USB
   - Enable SSH access (it's enabled by default)
   - Get your SSH password from Settings → Help → Copyright and licenses

2. **Python Requirements**:
   - Python 3.11 or higher (required)
   - Required packages (install with `pip install -r requirements.txt`)
   - All dependencies including `rmc` are installed automatically

3. **Optional — for the `ocr` command**:
   - **macOS** (recommended): the Apple Vision backend ships with the OS;
     `pip install -r requirements.txt` will pull in
     `pyobjc-framework-Vision` and `pyobjc-framework-Quartz` automatically.
   - **Linux/Windows or override**: install the `tesseract` binary
     (e.g. `brew install tesseract poppler` on macOS,
     `apt install tesseract-ocr poppler-utils` on Debian/Ubuntu) — the Python
     wrappers (`pytesseract`, `pdf2image`) are already in `requirements.txt`.

## Installation

### Option 1: Homebrew (Recommended for macOS)

**macOS users** can install RemarkableSync using Homebrew:

```bash
# Add the tap (one time only)
brew tap jeffsteinbok/remarkablesync

# Install RemarkableSync
brew install remarkablesync
```

This will automatically:
- Install Python 3.13 and all dependencies (including `rmc`)
- Set up everything needed for PDF conversion

**Updating to latest version:**
```bash
brew upgrade remarkablesync
```

**Uninstalling:**
```bash
brew uninstall remarkablesync
brew untap jeffsteinbok/remarkablesync
```

### Option 2: pip (All Platforms)

**For users with Python 3.11+** installed:

```bash
# 1. Create a virtual environment
python3 -m venv .venv

# 2. Activate the virtual environment
# On macOS/Linux:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate

# 3. Install RemarkableSync
pip install remarkablesync

# 4. Run the application
RemarkableSync backup
```

**Updating to latest version:**
```bash
pip install --upgrade remarkablesync
```

### Option 3: Pre-built Executables (Windows/macOS)

**For users without Python** or who prefer standalone executables, download from the [Releases page](https://github.com/JeffSteinbok/RemarkableSync/releases).

> [!IMPORTANT]
> **macOS Users:** Use the included `RemarkableSync.sh` script to launch the application. This automatically handles macOS Gatekeeper security:
> ```bash
> ./RemarkableSync.sh
> ```
> The script removes the quarantine flag and runs the executable. You can pass any command-line arguments:
> ```bash
> ./RemarkableSync.sh backup -v
> ./RemarkableSync.sh convert --sample 5
> ```


### Option 4: From Source (For Developers)

1. Clone this repository:
   ```bash
   git clone https://github.com/JeffSteinbok/RemarkableSync.git
   cd RemarkableSync
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   ```

   > [!IMPORTANT]
   > **macOS + external drives:** If the repository lives on an external volume (e.g. `/Volumes/…`), macOS Gatekeeper will block native libraries (such as `cryptography`'s Rust extension) regardless of ad-hoc re-signing. Create the virtual environment on your **local drive** instead:
   > ```bash
   > python3 -m venv ~/venvs/remarkablesync
   > source ~/venvs/remarkablesync/bin/activate
   > pip install -e /Volumes/<your-drive>/RemarkableSync
   > ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Option 5: Interactive Wizard (`start.sh`)

If you have cloned the repository and want a guided experience without memorising flags, use the bundled wizard:

```bash
./start.sh
```

The wizard will:
- Create and activate a virtual environment on your **local drive** (`~/venvs/remarkablesync`) — safe on macOS external volumes
- Install / update the package automatically via `pip install -e .`
- Ask step-by-step questions:
  - **Connection**: USB (default `10.11.99.1`) or WiFi (custom IP)
  - **Command**: `sync`, `backup`, `convert`, or `ocr`
  - **Backup scope**: incremental (changed only) or force full backup
  - **Conversion scope**: changed only, force all, single notebook, or sample N
  - **Templates**: embed device templates, use a custom directory, or skip entirely
  - **OCR engine**: Apple Vision or Tesseract, plus output formats (PDF / TXT / MD)
  - **Strict mode** and **verbose logging**
- Print the exact `RemarkableSync` command it will run, and ask for confirmation before executing

## Quick Start

The simplest way to get started:

1. **Connect your reMarkable tablet** via USB
2. **Get your SSH password** from Settings → Help → Copyright and licenses on your tablet
3. **Run RemarkableSync** — pick whichever method suits you:
   ```bash
   # Guided interactive wizard (recommended for first-time / from-source users)
   ./start.sh

   # If installed via Homebrew (macOS)
   RemarkableSync

   # If using Python directly
   python3 RemarkableSync.py
   ```
4. Enter your password when prompted (you can save it for future use)
5. Your notebooks will be backed up to `./remarkable_backup/Notebooks/`
6. PDFs will be created in `./remarkable_backup/PDF/`

That's it! The tool will only sync changed files and convert updated notebooks on subsequent runs.

## Usage

### Unified Command Line Interface

RemarkableSync provides a single entry point with five commands:

| Command | Purpose |
| ------- | ------- |
| `sync` *(default)* | Backup the tablet, then convert updated notebooks to PDF |
| `backup` | Backup only — no conversion |
| `convert` | Convert an existing backup to PDF |
| `ocr` | Run local OCR on converted PDFs (Apple Vision or Tesseract) |
| `notebooklm-bundle` | Package PDFs (preferring OCR text PDFs) for upload to Google NotebookLM |

#### Default Command: Sync (Backup + Convert)

The most common workflow - backs up your device and converts only updated notebooks:

```bash
# If installed via Homebrew
RemarkableSync

# If using Python
python3 RemarkableSync.py
```

This will:
1. Connect to your ReMarkable tablet via USB (or WiFi)
2. Backup all changed files (including templates)
3. Convert only notebooks that were updated in this backup

#### Connecting via WiFi

If your tablet and computer are on the same WiFi network, you can sync without a USB cable:

1. Enable WiFi on your tablet and ensure it's connected to your network
2. Find your tablet's IP address (Settings → Help → Copyright and licenses)
3. Run with the `--host` (or `-h`) option:
   ```bash
   RemarkableSync --host 192.168.68.53
   ```

#### Individual Commands

**Backup only** (no conversion):
```bash
# Homebrew
RemarkableSync backup

# Python
python3 RemarkableSync.py backup
```

**Convert only** (from existing backup):
```bash
# Homebrew
RemarkableSync convert

# Python
python3 RemarkableSync.py convert
```

**Sync with options**:
```bash
# Force full backup and conversion (ignore sync status)
RemarkableSync sync --force-backup --force-convert

# Skip template backup
RemarkableSync sync --skip-templates

# Verbose output
RemarkableSync sync -v

# Connect via WiFi (shorthand defaults to sync)
RemarkableSync --host 192.168.68.53
```

#### Testing and Selective Conversion

**Convert a single notebook** (by name or UUID):
```bash
RemarkableSync convert --notebook "My Notebook"
```

**Convert first N notebooks** (for testing):
```bash
RemarkableSync convert --sample 5
```

**Force convert all notebooks** (ignore sync status):
```bash
RemarkableSync convert --force
```

**Emit PDFs to a custom location** (e.g. a Dropbox folder):
```bash
RemarkableSync convert -o ~/Dropbox/rmNotes
# or, combined with sync:
RemarkableSync sync -o ~/Dropbox/rmNotes
```

**Disable template backgrounds** for a minimalist, ink-only export:
```bash
RemarkableSync convert --no-templates
```

**Use a custom template library**:
```bash
RemarkableSync convert --templates-dir ~/my-rm-templates
```

**Fail loud on missing pages** (CI / archival workflows):
```bash
# Aborts a notebook (exits with an error logged) if its .content manifest
# references .rm files that aren't on disk, instead of writing a placeholder
# "[Page X - Drawing data missing]" page.
RemarkableSync convert --strict
```

#### OCR (handwriting → searchable text)

Once a backup has been converted to PDF, run OCR over the result:

```bash
# Default: Apple Vision on macOS, Tesseract elsewhere; emits <name>_text.pdf per notebook.
RemarkableSync ocr

# Multiple output formats at once.
RemarkableSync ocr --format pdf --format md --format txt

# Force a specific engine.
RemarkableSync ocr --engine tesseract

# Limit to one document.
RemarkableSync ocr --notebook "Meeting Notes"
```

OCR runs entirely on your machine (no cloud calls). The `_text.pdf` is a
text-only document with one page per source page; combine with the original
PDF in your reader of choice, or feed it to NotebookLM (next section).

#### Bundle for Google NotebookLM

Package converted notebooks into an upload-ready folder:

```bash
# Prefers <name>_text.pdf when present, falls back to <name>.pdf.
RemarkableSync notebooklm-bundle -o ~/notebooklm/my-project

# Bundle a single notebook (substring match).
RemarkableSync notebooklm-bundle -o ~/notebooklm/standup --notebook "Standup"

# Use the original graphical PDFs instead of the OCR text PDFs.
RemarkableSync notebooklm-bundle -o ~/out --no-prefer-ocr

# Tighten the per-source size cap (NotebookLM enforces ~200 MB by default).
RemarkableSync notebooklm-bundle -o ~/out --max-mb 100
```

The output directory contains one PDF per notebook plus a `manifest.md`
index. Drag the folder into a new NotebookLM project to upload as sources;
NotebookLM does not currently expose a public ingestion API, so this step
is manual.

### Command Line Options

**Common Options** (all commands):
- `-d, --backup-dir`: Directory for backups (default: `./remarkable_backup`)
- `-h, --host`: ReMarkable IP address (default: `10.11.99.1`)
- `-v, --verbose`: Enable debug logging
- `--version`: Show version and repository information

**Backup/Sync Options**:
- `-p, --password`: ReMarkable SSH password (will prompt if not provided)
- `--skip-templates`: Don't backup template files
- `-f, --force` / `--force-backup`: Backup all files (ignore sync status)

**Convert / Sync PDF Options** (apply to both `convert` and `sync`):
- `-o, --output PATH`: Destination directory for generated PDFs (default: `<backup-dir>/PDF`)
- `--templates-dir PATH`: Use a custom directory of template assets
  (defaults to `<backup-dir>/Templates` when present)
- `--no-templates`: Disable template embedding and emit content-only PDFs
- `--strict`: Fail (do not emit placeholders) when a notebook page is missing on disk
- `-f, --force` / `--force-convert`: Convert all notebooks (ignore sync status)
- `-s, --sample N`: Convert only first N notebooks *(convert only)*
- `-n, --notebook NAME`: Convert only specific notebook by UUID or name *(convert only)*

**OCR Options** (`ocr` command):
- `-d, --pdf-dir PATH`: Directory of converted PDFs (default: `./remarkable_backup/PDF`)
- `-o, --output PATH`: Where to write OCR artefacts (default: same as `--pdf-dir`)
- `--engine [vision|tesseract]`: Force a specific OCR backend
- `-f, --format [pdf|txt|md|all]`: Output format(s); may be repeated; default `pdf`
- `-n, --notebook NAME`: OCR only PDFs whose name contains this string

**NotebookLM Bundle Options** (`notebooklm-bundle` command):
- `-d, --pdf-dir PATH`: Directory containing PDFs (and optional `_text.pdf` OCR variants)
- `-o, --output PATH`: Destination directory for the bundle (**required**)
- `-n, --notebook NAME`: Bundle only documents whose name contains this string
- `--max-mb N`: Skip files larger than N MB (default: 200)
- `--no-prefer-ocr`: Bundle the original graphical PDFs instead of the OCR text PDFs

## How It Works

1. **Connection**: Establishes SSH connection to ReMarkable tablet (default: 10.11.99.1)
2. **File Discovery**: Scans `/home/root/.local/share/remarkable/xochitl/` for notebook files
3. **Template Backup**: Downloads template files from `/usr/share/remarkable/templates/`
4. **Incremental Sync**: Compares file metadata (size, modification time, hash) to determine what needs updating
5. **Download + Integrity Check**: Uses SCP to transfer only changed files; each
   downloaded file is size-verified against the remote-reported size and rejected
   on mismatch so truncated transfers cannot be marked as up-to-date
6. **Page Resolution**: Parses each notebook's `.content` manifest into an
   ordered list of pages, locates the matching `.rm` files via a documented
   fallback chain, detects the format version per file, and reports any
   misses to the user
7. **PDF Conversion**:
   - Renders v6 `.rm` files directly to PDF via the in-process `rmc` Python API
     (falls back to the `rmc` CLI + SVG pipeline when the API is unavailable)
   - Optionally embeds template backgrounds (grids, lines, dots, or custom PNG/SVG assets)
     using accurate 226 DPI → 72 pt scaling
   - Composites templates with notebook content page-by-page (template re-read
     per page to guarantee no cross-page bleed)
   - Combines all pages into a single compressed PDF per notebook and stamps
     it with notebook title, creation date, last-modified date, and a
     `RemarkableSync` producer marker
8. **Smart Updates**: Tracks which notebooks changed and only converts those
9. **Optional OCR Pass**: `RemarkableSync ocr` rasterises each PDF page and
   submits it to a local OCR engine (Apple Vision on macOS, Tesseract
   elsewhere), producing `<name>_text.pdf` (one text page per source page)
   and optional `.txt` / `.md` sidecars
10. **Optional NotebookLM Bundle**: `RemarkableSync notebooklm-bundle` copies
    the best PDF variant per notebook into a flat upload folder with a
    `manifest.md` index

## File Structure

After backup, your directory will contain three clean folders:

```
remarkable_backup/
├── Notebooks/                # All notebook files and metadata
│   ├── [uuid].metadata       # Document metadata files
│   ├── [uuid].content        # Document content info
│   └── [uuid]/               # Notebook directories
│       ├── [uuid]-metadata.json  # Page metadata
│       └── *.rm              # Drawing/writing data (v5 or v6 format)
├── Templates/                # Template files from device
│   ├── *.png                 # Template preview images
│   ├── *.template            # Template definition files
│   └── templates.json        # Template metadata
├── PDF/                      # Generated PDF outputs
│   ├── [notebook folders with PDFs preserving hierarchy]
│   ├── *_text.pdf            # (Optional) Text-only PDF from `ocr` command
│   ├── *.txt                 # (Optional) Plain-text OCR sidecar
│   └── *.md                  # (Optional) Markdown OCR sidecar
├── sync_metadata.json        # Sync state tracking
├── updated_notebooks.txt     # List of notebooks updated in last backup
└── .remarkable_backup.log    # Backup operation log
```

`RemarkableSync notebooklm-bundle -o <dir>` writes its output to a separate
user-chosen directory (not under `remarkable_backup/`) containing:

```
<bundle-dir>/
├── *.pdf                     # One PDF per notebook (OCR variant preferred)
└── manifest.md               # Index with type, size and original path per file
```

## PDF Conversion Technical Details

RemarkableSync includes a hybrid converter that supports both v5 and v6 .rm file formats:

- **v6 Format** (newer tablets): Uses the `rmc` Python API (`rmc.rm_to_pdf`)
  for direct vector PDF rendering. The legacy `rmc` CLI → SVG → PDF path is
  kept as an automatic fallback for older installations.
- **v5 Format** (older tablets): Direct Python-based conversion via `rmrl` when available.
- **Template Rendering**: Custom renderer applies original device templates
  with accurate scaling (226 DPI → 72 DPI PDF points); toggle with
  `--no-templates` or override with `--templates-dir`.
- **Page Merging**: Uses PyPDF2 to composite template backgrounds with
  notebook content. The template page is re-read from disk on every
  iteration to avoid PyPDF2's shared `/Contents` reference issue (which
  previously caused backgrounds to render only on the first page and
  strokes from one page to bleed onto the next). Final PDFs are written
  with content-stream compression for smaller file sizes.
- **Page Resolution & Strict Mode**: A dedicated `PageResolver` parses the
  notebook `.content` manifest, resolves each page id to a `.rm` file via a
  small fallback chain, and detects format version per file. Missing pages
  produce a warning and a placeholder page in the output by default; pass
  `--strict` to instead fail the notebook entirely.
- **Embedded Metadata**: Every output PDF carries `/Title` (notebook name),
  `/Producer = RemarkableSync`, plus `/CreationDate` and `/ModDate` derived
  from the device `.metadata` file (in PDF date format `D:YYYYMMDDHHmmSSZ`).

### rmc Python Package

For v6 notebook conversion, RemarkableSync uses the `rmc` Python package:
- **Repository**: https://github.com/ricklupton/rmc
- **Installation**: Automatically installed as a dependency with RemarkableSync
- **Note**: This is included in `requirements.txt` and installed via pip

## Incremental Sync Details

The tool maintains a `sync_metadata.json` file that tracks:
- File modification times
- File sizes  
- MD5 hashes of local files
- Last sync timestamps

Files are only downloaded if:
- They don't exist locally
- Remote modification time changed
- Remote file size changed
- Local file hash doesn't match stored hash

## Troubleshooting

### Connection Issues
- Ensure ReMarkable is connected via USB OR on the same WiFi network
- Verify the tablet shows up as network interface (USB) or is reachable (WiFi)
- Try pinging the host (e.g., `ping 10.11.99.1` or `ping 192.168.1.15`)
- Check SSH password from tablet settings

### Permission Errors
- Run as administrator on Windows if needed
- Ensure backup directory is writable

### File Access Issues
- Restart ReMarkable tablet if SSH becomes unresponsive
- Check available disk space on both devices

## Security & Privacy Notes

- SSH password is requested interactively (not stored)
- Uses paramiko with auto-add host key policy
- Files are transferred over local USB network (not internet)
- **OCR is fully local**: Apple Vision runs on-device on macOS, Tesseract
  runs on-device on every platform. No notebook content is sent to any
  cloud service by RemarkableSync.
- **NotebookLM upload is manual**: the `notebooklm-bundle` command only
  prepares files locally; you choose whether and when to upload them.

## License

This tool is for personal use with your own ReMarkable tablet. Respect ReMarkable's terms of service.
