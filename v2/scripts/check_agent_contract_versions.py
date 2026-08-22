"""Reject rewritten v2 agent-contract releases."""

import json
import sys
from pathlib import Path
from typing import Any, cast

from scripts.check_tool_contract_versions import (
    comparison_ref,
    manifest_at,
    validate_contract,
    validate_manifest_update,
)

_MANIFEST_PATH = (
    Path(__file__).resolve().parent.parent / "agent" / "contract-manifest.json"
)
_MANIFEST_GIT_PATH = "v2/agent/contract-manifest.json"


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} BASE_GIT_REF", file=sys.stderr)
        return 2

    current = cast(dict[str, Any], json.loads(_MANIFEST_PATH.read_text()))
    for name in current:
        validate_contract(current, name)
    base_ref = comparison_ref(sys.argv[1])
    if base_ref is None:
        print("root commit has no prior agent contract manifest")
        return 0

    previous = manifest_at(base_ref, _MANIFEST_GIT_PATH)
    if previous is None:
        print("base commit predates the agent contract manifest")
        return 0

    validate_manifest_update(previous, current)
    print("agent contract manifest advances cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
