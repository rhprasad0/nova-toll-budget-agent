"""Internal contract loop, called after run_db_tests.sh verifies the disposable target."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

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
    for identity, directory in (("retained", retained), ("candidate", CURRENT)):
        for name in names:
            if identity == "retained" and name not in baseline:
                continue
            label = f"contract={name} identity={identity} profile={profile}"
            if identity == "retained" and baseline[name] == current[name]:
                print(
                    f"{label} elapsed=0 status=identical", file=sys.stderr, flush=True
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
            command.extend(["--file", str(directory / f"{name}_contract.sql")])
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
