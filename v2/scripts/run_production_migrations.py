#!/usr/bin/env python3
"""Run only the fixed production profile of the shared migration engine."""

from __future__ import annotations

import json
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_development_migrations as engine


def main() -> int:
    if len(sys.argv) != 1:
        print(f"usage: {Path(sys.argv[0]).name}", file=sys.stderr)
        return 2
    try:
        print(
            json.dumps(engine.run_production(), sort_keys=True, separators=(",", ":"))
        )
    except (
        engine.MigrationError,
        OSError,
        ValueError,
        engine.subprocess.SubprocessError,
    ):
        print("production migrations failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
