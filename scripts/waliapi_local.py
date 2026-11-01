"""Stable absolute script path for MCP clients launched outside the repository."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.local_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
