"""Enforce monotonic SemVer for registered v2 PostgreSQL schemas."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL_PATH = REPO_ROOT / "v2" / "db" / "schema.sql"
REGISTRY_PATH = REPO_ROOT / "v2" / "db" / "application-schemas.json"
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
UPGRADE_MIGRATION = re.compile(
    r"^v2/db/migrations/[0-9]{3}_upgrade_pricing_"
    r"(?P<previous>[0-9]+_[0-9]+_[0-9]+)_to_"
    r"(?P<current>[0-9]+_[0-9]+_[0-9]+)\.sql$"
)


def version_tuple(value: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid canonical semantic version {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def pricing_version(sql: str) -> str | None:
    match = re.search(r"^-- pricing schema version: (\S+)$", sql, re.MULTILINE)
    if match is None:
        return None
    value = match.group(1)
    version_tuple(value)
    insert = re.search(
        r"INSERT INTO pricing\.schema_version \(version\) VALUES \('([^']+)'\)",
        sql,
    )
    if insert is None or insert.group(1) != value:
        raise ValueError("schema comment and pricing.schema_version insert differ")
    return value


def git_text(base_ref: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{base_ref}:{path}"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else None


def database_files(base_ref: str, *, added_only: bool = False) -> list[str]:
    args = ["git", "diff", "--name-only"]
    if added_only:
        args.append("--diff-filter=A")
    args.extend([base_ref, "--", "v2/db"])
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.endswith(".sql")]


def upgrade_versions(path: str) -> tuple[str, str] | None:
    match = UPGRADE_MIGRATION.fullmatch(path)
    if match is None:
        return None
    previous = match.group("previous").replace("_", ".")
    current = match.group("current").replace("_", ".")
    version_tuple(previous)
    version_tuple(current)
    return previous, current


def validate_schema_update(
    previous: str, current: str, changed: list[str], added: list[str]
) -> None:
    changed_upgrades = [path for path in changed if upgrade_versions(path)]
    modified_upgrades = sorted(set(changed_upgrades) - set(added))
    if modified_upgrades:
        raise ValueError(
            f"released pricing upgrade migrations are immutable: "
            f"{', '.join(modified_upgrades)}"
        )

    added_upgrades = [path for path in added if upgrade_versions(path)]
    for path in added_upgrades:
        migration_previous, migration_current = upgrade_versions(path) or ("", "")
        if migration_current != current or version_tuple(
            migration_current
        ) <= version_tuple(migration_previous):
            raise ValueError(
                f"pricing upgrade migration does not target {current}: {path}"
            )

    versioned_changes = [path for path in changed if not upgrade_versions(path)]
    if versioned_changes:
        if version_tuple(current) <= version_tuple(previous):
            raise ValueError(
                f"v2 database SQL changed without advancing pricing {previous}; "
                f"current is {current}: {', '.join(versioned_changes)}"
            )
        if not any(
            upgrade_versions(path) == (previous, current) for path in added_upgrades
        ):
            raise ValueError(
                f"pricing {previous} -> {current} lacks a new upgrade migration"
            )
    elif current != previous:
        raise ValueError("pricing version changed without a v2 database SQL change")


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} BASE_GIT_REF", file=sys.stderr)
        return 2

    registry = json.loads(REGISTRY_PATH.read_text())
    if registry != {"schemas": ["pricing"]}:
        raise ValueError(
            "application schema registry must contain pricing exactly once"
        )

    current = pricing_version(SCHEMA_SQL_PATH.read_text())
    if current is None:
        raise ValueError("v2/db/schema.sql is missing the pricing schema version")

    base_ref = sys.argv[1]
    if base_ref == "0" * 40:
        print("no prior branch commit; pull-request CI will enforce schema versions")
        return 0

    subprocess.run(
        ["git", "cat-file", "-e", f"{base_ref}^{{commit}}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    previous_sql = git_text(base_ref, "v2/db/schema.sql")
    previous = pricing_version(previous_sql) if previous_sql is not None else None
    changed = database_files(base_ref)
    added = database_files(base_ref, added_only=True)

    if previous is not None:
        validate_schema_update(previous, current, changed, added)

    print(f"pricing schema version {current} advances cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
