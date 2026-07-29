"""Entry point for the Sick Certificate Data Explorer desktop application."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from sickcert.ui.app import run  # noqa: E402

if __name__ == "__main__":
    run()
