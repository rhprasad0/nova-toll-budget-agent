"""Internal contract loop, called after run_db_tests.sh verifies the disposable target."""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

CURRENT = Path(__file__).resolve().parents[1] / "tests"
CONTRACTS = (
    "pricing_analysis",
    "pricing_ballpark",
    "monotonic_upsert",
    "oracle_restore",
    "oracle_route",
    "oracle_prompt_points",
    "oracle_pricing_route",
    "oracle_i66_pricing",
    "oracle_i95_pricing",
    "oracle_ballpark",
    "oracle_report",
    "oracle_security",
    "oracle_fast",
)
WRAPPED = {"oracle_prompt_points", "oracle_report", "oracle_security"}


def retained_version_guard(
    source: bytes, candidate: bytes, *, report_labels: bool = False
) -> bytes:
    """Only a retained metadata assertion follows the new canonical version."""
    pattern = rb"\(SELECT version FROM oracle\.schema_version WHERE singleton\) <> '[0-9]+\.[0-9]+\.[0-9]+'"
    old, new = re.findall(pattern, source), re.findall(pattern, candidate)
    if len(old) != 1 or len(new) != 1:
        raise ValueError("expected exactly one retained/candidate Oracle version guard")
    source = source.replace(old[0], new[0], 1)
    if report_labels:
        # Only the approved report endpoint's two metadata expectations change.
        # Retain every route, pricing, availability and security assertion.
        for field in (b"label", b"display_name"):
            guard = rb"report.destination->>'" + field + rb"'\s*<>\s*'[^']+'"
            old, new = re.findall(guard, source), re.findall(guard, candidate)
            if len(old) != 1 or len(new) != 1:
                raise ValueError("expected exactly one destination metadata guard")
            source = source.replace(old[0], new[0], 1)
    return source


def run_contracts(retained: Path, profile: str) -> None:
    if profile not in {"fast", "full"}:
        raise ValueError("database profile must be fast or full")
    names = [name for name in CONTRACTS if profile == "full" or name != "oracle_report"]
    # Validate every input before executing any contract. The new small fixture
    # has no historical version before its introduction.
    current = {name: (CURRENT / f"{name}_contract.sql").read_bytes() for name in names}
    baseline = {
        name: (retained / f"{name}_contract.sql").read_bytes()
        for name in names
        if name != "oracle_fast" or (retained / f"{name}_contract.sql").exists()
    }
    with TemporaryDirectory(prefix="tollchat-retained-contracts-") as temporary:
        adapted: dict[str, Path] = {}
        for name in {"oracle_restore", "oracle_report"} & baseline.keys():
            if baseline[name] != current[name]:
                # Never change archived bytes or the installed schema version.
                content = retained_version_guard(
                    baseline[name], current[name], report_labels=name == "oracle_report"
                )
                path = Path(temporary) / f"{name}_contract.sql"
                path.write_bytes(content)
                adapted[name] = path
        for identity, directory in (("retained", retained), ("candidate", CURRENT)):
            for name in names:
                if identity == "retained" and name not in baseline:
                    continue
                label = f"contract={name} identity={identity} profile={profile}"
                if identity == "retained" and baseline[name] == current[name]:
                    print(
                        f"{label} elapsed=0 status=identical",
                        file=sys.stderr,
                        flush=True,
                    )
                    continue
                command = [
                    "psql",
                    "--dbname",
                    "nova_toll_v2_bootstrap_test",
                    "--set",
                    "ON_ERROR_STOP=1",
                    "--set",
                    f"full_contract={'true' if profile == 'full' else 'false'}",
                ]
                if name in WRAPPED:
                    command.extend(["--command", "BEGIN"])
                source = (
                    adapted.get(name, directory / f"{name}_contract.sql")
                    if identity == "retained"
                    else directory / f"{name}_contract.sql"
                )
                command.extend(["--file", str(source)])
                if name in WRAPPED:
                    command.extend(["--command", "ROLLBACK"])
                started = time.monotonic()
                print(f"{label} elapsed=0 status=start", file=sys.stderr, flush=True)
                try:
                    subprocess.run(command, check=True)
                except subprocess.CalledProcessError as error:
                    print(
                        f"{label} elapsed={time.monotonic() - started:.3f} status=failed exit={error.returncode}",
                        file=sys.stderr,
                        flush=True,
                    )
                    raise
                print(
                    f"{label} elapsed={time.monotonic() - started:.3f} status=passed",
                    file=sys.stderr,
                    flush=True,
                )
