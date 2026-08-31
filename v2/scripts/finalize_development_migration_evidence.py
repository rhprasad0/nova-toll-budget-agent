#!/usr/bin/env python3
"""Record the required development application I-395 gate after its release."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("deploy_oracle_migration.py")
SPEC = importlib.util.spec_from_file_location("oracle_migration", SCRIPT)
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def main() -> int:
    if len(sys.argv) != 1:
        print("usage: finalize_development_migration_evidence.py", file=sys.stderr)
        return 2
    try:
        migration.require_tools()
        commit = migration.checked_main()
        digest = migration.migration_digest()
        candidates = [
            path
            for path in migration.EVIDENCE_ROOT.glob("development-*")
            if path.is_dir()
            and not path.is_symlink()
            and path.stat().st_mode & 0o222
            and (path / "migration.txt").read_text().find(f"commit={commit}\n") >= 0
            and (path / "migration.txt")
            .read_text()
            .find(f"migration_sha256={digest}\n")
            >= 0
            and (path / "development-release-receipt.txt").is_file()
            and (path / "development-release-receipt.txt").read_text()
            == f"commit={commit}\napplication_smoke=passed\n"
        ]
        if len(candidates) != 1:
            raise migration.Stop(
                "exact writable development migration evidence is required"
            )
        evidence = candidates[0]
        reports = {
            "current": migration.capture_eval(
                "leesburg-to-washington-i395-current-price", "i95_southbound", "direct"
            ),
            "annual": migration.capture_eval(
                "leesburg-to-washington-i395-job-offer", "all", "annual"
            ),
        }
        values = migration.parse_record(evidence / "migration.txt")
        allowed = {
            "environment",
            "commit",
            "timestamp_utc",
            "migration",
            "migration_sha256",
            "rds_identifier",
            "rds_resource_id",
            "oracle_before",
            "pricing_before",
            "oracle_after",
            "pricing_after",
            "connections",
            "handoffs",
        }
        if set(values) != allowed or values["environment"] != "development":
            raise migration.Stop(
                "development migration evidence has an unexpected schema"
            )
        for label, report in reports.items():
            copied = evidence / f".{label}.json"
            shutil.copyfile(report, copied)
            values[f"{label}_report_sha256"] = migration.sha256(copied)
            os.replace(copied, evidence / f"{label}.json")
        values.update(
            {
                "schema_label": "oracle-1.14.0",
                "current_case": "leesburg-to-washington-i395-current-price",
                "current_pass": "true",
                "annual_case": "leesburg-to-washington-i395-job-offer",
                "annual_pass": "true",
            }
        )
        manifest = evidence / ".i395-evals.txt"
        manifest.write_text(
            "".join(f"{key}={value}\n" for key, value in sorted(values.items()))
        )
        os.replace(manifest, evidence / "i395-evals.txt")
        for item in evidence.iterdir():
            item.chmod(0o400)
        evidence.chmod(0o500)
        print(f"development application gate finalized: {evidence}")
        return 0
    except migration.Stop as error:
        print(f"development gate stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
