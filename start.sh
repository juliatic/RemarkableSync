#!/usr/bin/env bash
# start.sh — Interactive wizard for RemarkableSync
# Handles venv setup (local-drive safe on macOS) and builds the right command.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/venvs/remarkablesync"

# ── colour helpers ──────────────────────────────────────────────────────────
bold=$'\e[1m'; reset=$'\e[0m'; cyan=$'\e[36m'; green=$'\e[32m'; yellow=$'\e[33m'

header()  { echo; echo "${bold}${cyan}$*${reset}"; echo "$(printf '─%.0s' {1..50})"; }
ask()     { printf "${bold}%s${reset} " "$1"; }
info()    { echo "${green}▶ $*${reset}"; }
warn()    { echo "${yellow}⚠  $*${reset}"; }
tolower() { echo "$1" | tr '[:upper:]' '[:lower:]'; }

# ── venv bootstrap ──────────────────────────────────────────────────────────
header "RemarkableSync — Environment Setup"

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

info "Activating virtual environment ..."
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

info "Installing / updating RemarkableSync from source ..."
pip install --quiet -e "$SCRIPT_DIR"

# ── wizard ──────────────────────────────────────────────────────────────────
header "RemarkableSync — Wizard"

# 1. Connection type
echo
echo "  1) USB   (10.11.99.1 — default)"
echo "  2) WiFi  (custom IP)"
ask "Connection type [1/2, default 1]:"
read -r conn_choice
conn_choice="${conn_choice:-1}"

if [[ "$conn_choice" == "2" ]]; then
    ask "  Enter tablet IP address:"
    read -r HOST
    HOST="${HOST:-10.11.99.1}"
else
    HOST="10.11.99.1"
fi
info "Using host: $HOST"

# 2. Command
echo
echo "  1) sync    — backup + convert in one step (recommended)"
echo "  2) backup  — backup only"
echo "  3) convert — convert only (from existing backup)"
echo "  4) ocr     — run OCR on converted PDFs"
ask "What do you want to do? [1/2/3/4, default 1]:"
read -r cmd_choice
cmd_choice="${cmd_choice:-1}"

case "$cmd_choice" in
    2) COMMAND="backup" ;;
    3) COMMAND="convert" ;;
    4) COMMAND="ocr" ;;
    *) COMMAND="sync" ;;
esac
info "Command: $COMMAND"

# 3. Backup directory
echo
ask "Backup directory [default: ./remarkable_backup]:"
read -r BACKUP_DIR
BACKUP_DIR="${BACKUP_DIR:-./remarkable_backup}"

# ── command-specific options ─────────────────────────────────────────────────

EXTRA_ARGS=""

if [[ "$COMMAND" == "backup" || "$COMMAND" == "sync" ]]; then
    # Force backup
    echo
    ask "Force full backup (re-download all files, not just changed)? [y/N]:"
    read -r force_backup
    if [[ "$(tolower "$force_backup")" == "y" ]]; then
        if [[ "$COMMAND" == "backup" ]]; then
            EXTRA_ARGS="$EXTRA_ARGS --force"
        else
            EXTRA_ARGS="$EXTRA_ARGS --force-backup"
        fi
    fi

    # Skip templates
    ask "Skip backing up device templates? [y/N]:"
    read -r skip_tpl
    if [[ "$(tolower "$skip_tpl")" == "y" ]]; then
        EXTRA_ARGS="$EXTRA_ARGS --skip-templates"
    fi

    # SSH password
    ask "SSH password (leave blank to use keyring / no password):"
    read -rs SSH_PASS
    echo
    if [[ -n "$SSH_PASS" ]]; then
        EXTRA_ARGS="$EXTRA_ARGS --password '$SSH_PASS'"
    fi
fi

if [[ "$COMMAND" == "convert" || "$COMMAND" == "sync" ]]; then
    # Scope: all / only changed / single notebook
    echo
    echo "  1) Only notebooks changed in last backup (default, fastest)"
    echo "  2) Force-convert ALL notebooks"
    echo "  3) One specific notebook (by name or UUID)"
    echo "  4) Sample — first N notebooks (testing)"
    ask "Conversion scope [1/2/3/4, default 1]:"
    read -r scope_choice
    scope_choice="${scope_choice:-1}"

    case "$scope_choice" in
        2)
            if [[ "$COMMAND" == "convert" ]]; then
                EXTRA_ARGS="$EXTRA_ARGS --force"
            else
                EXTRA_ARGS="$EXTRA_ARGS --force-convert"
            fi
            ;;
        3)
            ask "  Notebook name or UUID:"
            read -r NB_NAME
            EXTRA_ARGS="$EXTRA_ARGS --notebook '$NB_NAME'"
            ;;
        4)
            ask "  Number of notebooks to convert:"
            read -r SAMPLE_N
            EXTRA_ARGS="$EXTRA_ARGS --sample $SAMPLE_N"
            ;;
    esac

    # Output directory
    ask "PDF output directory [default: <backup-dir>/PDF]:"
    read -r OUTPUT_DIR
    if [[ -n "$OUTPUT_DIR" ]]; then
        EXTRA_ARGS="$EXTRA_ARGS --output '$OUTPUT_DIR'"
    fi

    # Templates
    echo
    echo "  1) Embed device templates as page backgrounds (default)"
    echo "  2) Use a custom templates directory"
    echo "  3) No templates (content-only PDFs)"
    ask "Template mode [1/2/3, default 1]:"
    read -r tpl_choice
    tpl_choice="${tpl_choice:-1}"

    case "$tpl_choice" in
        2)
            ask "  Templates directory path:"
            read -r TPL_DIR
            EXTRA_ARGS="$EXTRA_ARGS --templates-dir '$TPL_DIR'"
            ;;
        3)
            EXTRA_ARGS="$EXTRA_ARGS --no-templates"
            ;;
    esac

    # Strict mode
    ask "Strict mode (fail on missing pages instead of placeholders)? [y/N]:"
    read -r strict_mode
    if [[ "$(tolower "$strict_mode")" == "y" ]]; then
        EXTRA_ARGS="$EXTRA_ARGS --strict"
    fi
fi

if [[ "$COMMAND" == "ocr" ]]; then
    ask "PDF directory to OCR [default: ./remarkable_backup/PDF]:"
    read -r OCR_DIR
    OCR_DIR="${OCR_DIR:-./remarkable_backup/PDF}"

    echo
    echo "  1) Apple Vision — macOS only, best for handwriting (default on macOS)"
    echo "  2) Tesseract    — cross-platform (requires tesseract binary on PATH)"
    ask "OCR engine [1/2, default 1]:"
    read -r ocr_engine
    case "${ocr_engine:-1}" in
        2) EXTRA_ARGS="$EXTRA_ARGS --engine tesseract" ;;
        *) EXTRA_ARGS="$EXTRA_ARGS --engine vision" ;;
    esac

    echo
    echo "Output formats (can choose multiple):"
    ask "  Include PDF output? [Y/n]:" ; read -r fmt_pdf;  fmt_pdf="${fmt_pdf:-y}"
    ask "  Include TXT output? [y/N]:" ; read -r fmt_txt
    ask "  Include MD  output? [y/N]:" ; read -r fmt_md

    [[ "$(tolower "$fmt_pdf")" != "n" ]] && EXTRA_ARGS="$EXTRA_ARGS --format pdf"
    [[ "$(tolower "$fmt_txt")" == "y" ]] && EXTRA_ARGS="$EXTRA_ARGS --format txt"
    [[ "$(tolower "$fmt_md")"  == "y" ]] && EXTRA_ARGS="$EXTRA_ARGS --format md"

    ask "Scope to one notebook (name substring, leave blank for all):"
    read -r OCR_NB
    [[ -n "$OCR_NB" ]] && EXTRA_ARGS="$EXTRA_ARGS --notebook '$OCR_NB'"
fi

# Verbose
echo
ask "Enable verbose logging? [y/N]:"
read -r verbose_flag
[[ "$(tolower "$verbose_flag")" == "y" ]] && EXTRA_ARGS="$EXTRA_ARGS --verbose"

# ── build final command ───────────────────────────────────────────────────────
header "Ready to run"

# host flag only applies to backup/sync
HOST_FLAG=""
if [[ "$COMMAND" != "convert" && "$COMMAND" != "ocr" ]]; then
    HOST_FLAG="--host $HOST"
fi

# OCR uses --pdf-dir, all others use --backup-dir
if [[ "$COMMAND" == "ocr" ]]; then
    DIR_FLAG="--pdf-dir '$OCR_DIR'"
else
    DIR_FLAG="--backup-dir '$BACKUP_DIR'"
fi

FULL_CMD="RemarkableSync $COMMAND $HOST_FLAG $DIR_FLAG $EXTRA_ARGS"

# normalise whitespace
FULL_CMD=$(echo "$FULL_CMD" | tr -s ' ')

echo
info "Command to execute:"
echo "  ${bold}${FULL_CMD}${reset}"
echo
ask "Run now? [Y/n]:"
read -r run_now
run_now="${run_now:-y}"

if [[ "$(tolower "$run_now")" == "n" ]]; then
    echo
    warn "Aborted. You can run manually:"
    echo "  source $VENV_DIR/bin/activate"
    echo "  $FULL_CMD"
else
    echo
    eval "$FULL_CMD"
fi
