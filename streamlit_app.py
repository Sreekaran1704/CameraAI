"""Deployment entry point: upload-only Web Demo, never the filesystem edition."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from photocull.ui.web_app import main  # noqa: E402

main()
