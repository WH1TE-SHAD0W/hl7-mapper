"""Entry point for the HL7 Message Data Explorer desktop application."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from hl7msg.ui.app import run  # noqa: E402

if __name__ == "__main__":
    run()
