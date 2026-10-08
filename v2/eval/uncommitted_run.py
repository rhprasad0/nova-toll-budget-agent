"""Explicit local application-run waiver; reuse the frozen evaluator unchanged.

Run from v2 with the normal golden_run run arguments and
--allow-uncommitted-application. Native corpus approval, harness calibration,
privacy, source snapshots and cumulative spending gates still apply.
"""

import hashlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

from eval import golden
from eval import golden_run as runner


def main() -> None:
    original_argv = sys.argv
    flag = "--allow-uncommitted-application"
    arguments = original_argv[1:]
    if (
        not arguments
        or arguments[0] != "run"
        or arguments.count(flag) != 1
        or any(argument.split("=")[0] == "--cases" for argument in arguments)
    ):
        raise SystemExit("local waiver requires a full application run and " + flag)
    native_identity = runner.identity

    def identity(cases: list[golden.GoldenCase]) -> dict[str, Any]:
        pinned = native_identity(cases, allow_uncommitted_preparation=True)
        pinned["local_checkout_waiver"] = {
            "status": "explicitly_requested",
            "flag": flag,
            "launcher_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        return pinned

    try:
        sys.argv = [original_argv[0], *(a for a in arguments if a != flag)]
        with patch.object(runner, "identity", identity):
            runner.main()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    main()
