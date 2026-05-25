#!/usr/bin/env python3
"""CLI entry point that delegates to analyze_openclaw_release.py for consistent output.

This module exists as a compatibility shim so that both entry points
  python scripts/main.py ...
  python scripts/analyze_openclaw_release.py ...
produce identical reports. All analysis logic lives in analyze_openclaw_release.py.
"""

from __future__ import annotations

import sys
from typing import Optional, Sequence

from analyze_openclaw_release import main as _analyzer_main


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Delegate to analyze_openclaw_release.py to ensure consistent report output."""
    return _analyzer_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
