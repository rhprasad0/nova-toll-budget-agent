#!/usr/bin/env python3
"""Plan the development application root without credentials.

    python3 v2/scripts/infrastructure_plan.py BASE_GIT_REF

Compares what v2/infra plans at BASE_GIT_REF with what the working tree plans,
and fails when the difference is one an application release may not apply.
Development delivery rejects such a change only after merge, as
`phase_boundary`, and every later delivery fails with it.

Providers are mocked by v2/infra/tests/development.tftest.hcl, so this needs
only `terraform -chdir=v2/infra init -backend=false`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2" / "scripts"))

import blue_green  # noqa: E402
import cost_dashboard_release  # noqa: E402
import shared_packages  # noqa: E402

FIXTURE = ROOT / "v2/infra/tests/development.tftest.hcl"
PROVIDERS = ROOT / "v2/infra/.terraform/providers"
# A reviewed line here says an administrator applied that address by hand.
ADMINISTRATOR_APPLIED = ROOT / ".github/administrator-applied-infrastructure"
ENTRY_LIFETIME = timedelta(days=30)
READ_PATHS = ("v2/infra", "v2/agent", "v2/analytics", "infra/account-contract.json")
PACKAGES = ("loader", "publisher", "timed-checks")

Plan = dict[str, dict[str, Any]]


def planned(tree: Path) -> Plan:
    """Return each planned resource's known values for the checkout at `tree`."""
    if not PROVIDERS.is_dir():
        raise SystemExit("Run: terraform -chdir=v2/infra init -backend=false")
    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch)
        module = work / "v2/infra"
        module.mkdir(parents=True)
        for source in (tree / "v2/infra").glob("*.tf"):
            # A mocked provider cannot import; the imported resource plans as a create.
            text = re.sub(r"(?m)^import \{\n(?:.*\n)*?\}\n", "", source.read_text())
            (module / source.name).write_text(text)
        shutil.copytree(tree / "v2/infra/lambda-stub", module / "lambda-stub")
        (module / "build").mkdir()
        for name in PACKAGES:
            (module / "build" / f"{name}.zip").write_bytes(b"placeholder")
        (module / "tests").mkdir()
        shutil.copy(FIXTURE, module / "tests")
        shutil.copy(ROOT / "v2/infra/.terraform.lock.hcl", module)
        (module / ".terraform").mkdir()
        (module / ".terraform/providers").symlink_to(
            PROVIDERS, target_is_directory=True
        )
        for name in ("agent", "analytics"):
            (work / "v2" / name).symlink_to(
                tree / "v2" / name, target_is_directory=True
            )
        (work / "infra").symlink_to(tree / "infra", target_is_directory=True)
        result = subprocess.run(
            ["terraform", f"-chdir={module}", "test", "-json", "-verbose"],
            capture_output=True,
            text=True,
            check=False,
        )
    events = [
        json.loads(line) for line in result.stdout.splitlines() if line[:1] == "{"
    ]
    plans = [event["test_plan"] for event in events if event["type"] == "test_plan"]
    if result.returncode or len(plans) != 1:
        problems = [
            f"{item['summary']}: {item.get('detail', '')}"
            for event in events
            if (item := event.get("diagnostic")) and item["severity"] == "error"
        ]
        raise SystemExit(
            "The credential-free plan failed. If v2/infra needs a new input, "
            f"add it to {FIXTURE.relative_to(ROOT)}.\n"
            + "\n".join(problems or [result.stderr])
        )
    return {
        item["address"]: item["change"]["after"]
        for item in plans[0]["resource_changes"]
        if item["mode"] == "managed"
    }


def releasable(address: str, fields: set[str], added_or_removed: bool) -> bool:
    """Whether the release gate has any path for this difference."""
    # The cost and shared-package releases validate their own resources, creates included.
    if (
        address in shared_packages.RESOURCES
        or address in cost_dashboard_release.RESOURCES
        or address in shared_packages.COMPONENTS
    ):
        return True
    if added_or_removed:
        return False
    name = re.sub(r"\[[^\]]*\]$", "", address)
    allowed = blue_green.SLOT_RESOURCES.get(name) or blue_green.ROUTING_RESOURCES.get(
        address
    )
    return allowed is not None and fields <= allowed


def administrator_applied(today: date) -> set[str]:
    """Addresses with an unexpired `YYYY-MM-DD approver ADDRESS reason` line."""
    if not ADMINISTRATOR_APPLIED.exists():
        return set()
    entries = (line.split() for line in ADMINISTRATOR_APPLIED.read_text().splitlines())
    return {
        entry[2]
        for entry in entries
        if len(entry) >= 4
        and not entry[0].startswith("#")
        and today - date.fromisoformat(entry[0]) <= ENTRY_LIFETIME
    }


def blocked(base: Plan, head: Plan, approved: set[str]) -> dict[str, set[str]]:
    """Map each address a release cannot apply to the top-level fields that differ."""
    result: dict[str, set[str]] = {}
    for address in sorted(base.keys() | head.keys()):
        added_or_removed = (address in base) != (address in head)
        fields = blue_green.changed(base.get(address, {}), head.get(address, {}))
        if (
            (fields or added_or_removed)
            and address not in approved
            and not releasable(address, fields, added_or_removed)
        ):
            result[address] = fields
    return result


def main(arguments: list[str]) -> int:
    if len(arguments) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    unchanged = not subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--quiet", arguments[0], "--", "v2/infra"],
        check=False,
    ).returncode
    if unchanged:
        print("v2/infra is unchanged")
        return 0
    with tempfile.TemporaryDirectory() as scratch:
        archive = subprocess.run(
            ["git", "-C", str(ROOT), "archive", arguments[0], *READ_PATHS],
            check=True,
            capture_output=True,
        ).stdout
        subprocess.run(["tar", "-x", "-C", scratch], input=archive, check=True)
        base = planned(Path(scratch))
    problems = blocked(
        base, planned(ROOT), administrator_applied(datetime.now(UTC).date())
    )
    if not problems:
        print("v2/infra changes only what an application release may apply")
        return 0
    print(
        "An application release cannot apply these v2/infra changes; development "
        "delivery would fail after merge with phase_boundary:",
        file=sys.stderr,
    )
    for address, fields in problems.items():
        detail = ", ".join(sorted(fields)) or "added or removed"
        print(f"  {address}: {detail}", file=sys.stderr)
    print(
        "Take them out of this change, or have an administrator apply a reviewed "
        "targeted plan first (v2/runbooks/development-release.md) and record each "
        f"address in {ADMINISTRATOR_APPLIED.relative_to(ROOT)}:\n"
        "  YYYY-MM-DD  approver  ADDRESS  reason",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
