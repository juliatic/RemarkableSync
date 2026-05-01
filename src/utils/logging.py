"""Logging configuration utilities."""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

_FMT = "%(asctime)s - %(levelname)s - %(message)s"
_DATE = "%Y-%m-%d %H:%M:%S"


def setup_logging(verbose: bool = False, log_dir: Optional[Path] = None) -> Path:
    """Configure logging with console + file handlers.

    Always writes a full DEBUG-level log to a timestamped file inside
    ``log_dir`` (defaults to the current working directory).  The console
    handler honours the ``verbose`` flag: DEBUG when True, INFO when False.

    Args:
        verbose: Enable DEBUG level on the console if True, INFO if False.
        log_dir: Directory to write the ``.log`` file into.  Defaults to
            the current working directory when not supplied.

    Returns:
        Path to the log file that was opened.
    """
    root = logging.getLogger()
    # Remove any handlers added by a previous basicConfig call (e.g. from
    # third-party code that ran before us) so we own the configuration.
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(_FMT, datefmt=_DATE)

    # ── console handler ──────────────────────────────────────────────────────
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(formatter)
    root.addHandler(console)

    # ── file handler (always DEBUG) ──────────────────────────────────────────
    target_dir = Path(log_dir) if log_dir else Path.cwd()
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = target_dir / f"remarkablesync_{timestamp}.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # ── suppress noisy third-party loggers ───────────────────────────────────
    for noisy in ("svglib.svglib", "reportlab", "rmscene", "rmc"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("paramiko").setLevel(logging.DEBUG if verbose else logging.INFO)

    logging.info("Log file: %s", log_path)
    return log_path
