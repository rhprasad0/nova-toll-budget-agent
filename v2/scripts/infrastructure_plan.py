#!/usr/bin/env python3
"""Plan the development application root without credentials.

    python3 v2/scripts/infrastructure_plan.py BASE_GIT_REF

Compares what v2/infra plans at BASE_GIT_REF with what the working tree plans,
and fails when the difference is one an application release may not apply.
Development delivery rejects such a change only after merge, as
`phase_boundary`, and every later delivery fails with it.

Both plans get the same inputs, so a difference comes from the repository's
Terraform or the files it reads. It sees planned values only: IAM policy text
is unknown at plan time, so a policy change passes here unseen.

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
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "v2" / "scripts"))

import blue_green  # noqa: E402
import cost_dashboard_release  # noqa: E402
import shared_packages  # noqa: E402

DISTRIBUTIONS = {
    "aws_cloudfront_distribution.site",
    "aws_cloudfront_distribution.staging",
}

FIXTURE = ROOT / "v2/infra/tests/development.tftest.hcl"
PROVIDERS = ROOT / "v2/infra/.terraform/providers"
# One address per line: resources an administrator applies by hand.
ADMINISTRATOR_APPLIED = ROOT / "v2/infra/administrator-applied.txt"
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
    """Whether the release gate has a path for this repository-made difference.

    Slot and shared-package resources change through release inputs, which are
    the same in both plans; a difference here is a configuration change the
    gate rejects. See the `prepare` branch of blue_green.validate_plan.
    """
    # The cost release validates its own resources, creates included.
    if address in cost_dashboard_release.RESOURCES:
        return True
    if added_or_removed:
        return False
    if address == shared_packages.CHAT_ROUTES:
        return fields <= {"code"}
    return address in DISTRIBUTIONS and fields <= {"ordered_cache_behavior"}


def administrator_applied() -> set[str]:
    return {
        line.strip()
        for line in ADMINISTRATOR_APPLIED.read_text().splitlines()
        if line.strip() and not line.startswith("#")
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
    base_ref = arguments[0]
    # A tag push passes an all-zero base; compare with the parent, as the contract checks do.
    if subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{base_ref}^{{commit}}"],
        capture_output=True,
        check=False,
    ).returncode:
        base_ref = "HEAD^"
    # The plan reads these paths; exit 1 means they differ from the base.
    differs = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--quiet", base_ref, "--", *READ_PATHS],
        check=False,
    ).returncode
    if differs == 0:
        print("nothing v2/infra plans from has changed")
        return 0
    if differs != 1:
        print(f"Cannot compare with {base_ref}.", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as scratch:
        archive = subprocess.run(
            ["git", "-C", str(ROOT), "archive", base_ref, *READ_PATHS],
            check=True,
            capture_output=True,
        ).stdout
        subprocess.run(["tar", "-x", "-C", scratch], input=archive, check=True)
        # shortcut: uses this change's fixture; a change that drops a required input
        # fails here. Plan the base with its own fixture if that happens.
        base = planned(Path(scratch))
    problems = blocked(base, planned(ROOT), administrator_applied())
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
        "Take them out of this change, or have an administrator apply them first "
        "(v2/runbooks/development-release.md) and add each address to "
        f"{ADMINISTRATOR_APPLIED.relative_to(ROOT)}.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
