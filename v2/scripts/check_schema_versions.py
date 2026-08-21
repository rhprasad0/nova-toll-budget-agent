"""Enforce independent monotonic SemVer for registered v2 PostgreSQL schemas."""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "v2" / "db" / "application-schemas.json"
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
UPGRADE_MIGRATION = re.compile(
    r"^v2/db/migrations/[0-9]{3}_upgrade_(?P<schema>[a-z][a-z0-9_]*)_"
    r"(?P<previous>[0-9]+_[0-9]+_[0-9]+)_to_"
    r"(?P<current>[0-9]+_[0-9]+_[0-9]+)\.sql$"
)


@dataclass(frozen=True)
class RegisteredSchema:
    name: str
    canonical_sql: str
    owned_paths: tuple[str, ...]


def version_tuple(value: str) -> tuple[int, int, int]:
    match = SEMVER.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid canonical semantic version {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def schema_version(schema_name: str, sql: str) -> str | None:
    comment = re.search(
        rf"^-- {re.escape(schema_name)} schema version: (\S+)$", sql, re.MULTILINE
    )
    if comment is None:
        return None
    value = comment.group(1)
    version_tuple(value)
    insert = re.search(
        rf"INSERT INTO {re.escape(schema_name)}[.]schema_version "
        rf"\(version\) VALUES \('([^']+)'\)",
        sql,
    )
    if insert is None or insert.group(1) != value:
        raise ValueError(
            f"schema comment and {schema_name}.schema_version insert differ"
        )
    return value


def load_registry(text: str) -> tuple[RegisteredSchema, ...]:
    raw: object = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("application schema registry must contain a schemas list")
    typed_raw = cast(dict[str, Any], raw)
    raw_schemas = typed_raw.get("schemas")
    if not isinstance(raw_schemas, list):
        raise ValueError("application schema registry must contain a schemas list")
    schemas: list[RegisteredSchema] = []
    for item in cast(list[object], raw_schemas):
        if not isinstance(item, dict):
            raise ValueError("each registered schema must be an object")
        typed_item = cast(dict[str, Any], item)
        name = typed_item.get("name")
        canonical_sql = typed_item.get("canonical_sql")
        owned_paths = typed_item.get("owned_paths")
        owned_objects = (
            cast(list[object], owned_paths) if isinstance(owned_paths, list) else []
        )
        if (
            not isinstance(name, str)
            or not isinstance(canonical_sql, str)
            or not isinstance(owned_paths, list)
            or not owned_paths
            or not all(isinstance(path, str) for path in owned_objects)
        ):
            raise ValueError(f"invalid registered schema entry: {item!r}")
        schemas.append(
            RegisteredSchema(
                name=name,
                canonical_sql=canonical_sql,
                owned_paths=tuple(cast(list[str], owned_paths)),
            )
        )
    names = [schema.name for schema in schemas]
    if len(names) != len(set(names)):
        raise ValueError("application schemas must be registered exactly once")
    if names != sorted(names):
        raise ValueError("application schemas must be sorted by name")
    return tuple(schemas)


def load_previous_registry(text: str) -> tuple[RegisteredSchema, ...]:
    raw: object = json.loads(text)
    if raw == {"schemas": ["pricing"]}:
        return (
            RegisteredSchema(
                name="pricing",
                canonical_sql="v2/db/schema.sql",
                owned_paths=(),
            ),
        )
    return load_registry(text)


def git_text(base_ref: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{base_ref}:{path}"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else None


def changed_repository_files(base_ref: str, *, added_only: bool = False) -> list[str]:
    args = ["git", "diff", "--name-only"]
    if added_only:
        args.append("--diff-filter=A")
    args.append(base_ref)
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    untracked = subprocess.run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            ".",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths = set(result.stdout.splitlines()) | set(untracked.stdout.splitlines())
    return sorted(paths)


def _owns(schema: RegisteredSchema, path: str) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in schema.owned_paths)


def upgrade_versions(schema_name: str, path: str) -> tuple[str, str] | None:
    match = UPGRADE_MIGRATION.fullmatch(path)
    if match is None or match.group("schema") != schema_name:
        return None
    previous = match.group("previous").replace("_", ".")
    current = match.group("current").replace("_", ".")
    version_tuple(previous)
    version_tuple(current)
    return previous, current


def validate_schema_update(
    schema_name: str,
    previous: str,
    current: str,
    changed: list[str],
    added: list[str],
) -> None:
    changed_upgrades = [path for path in changed if upgrade_versions(schema_name, path)]
    modified_upgrades = sorted(set(changed_upgrades) - set(added))
    if modified_upgrades:
        raise ValueError(
            f"released {schema_name} upgrade migrations are immutable: "
            f"{', '.join(modified_upgrades)}"
        )

    added_upgrades = [path for path in added if upgrade_versions(schema_name, path)]
    added_versions = [
        (path, *cast(tuple[str, str], upgrade_versions(schema_name, path)))
        for path in added_upgrades
    ]
    for path, migration_previous, migration_current in added_versions:
        if version_tuple(migration_current) <= version_tuple(migration_previous):
            raise ValueError(
                f"{schema_name} upgrade migration is not monotonic: {path}"
            )

    versioned_changes = [
        path for path in changed if not upgrade_versions(schema_name, path)
    ]
    if versioned_changes:
        if version_tuple(current) <= version_tuple(previous):
            raise ValueError(
                f"{schema_name} contract changed without advancing {previous}; "
                f"current is {current}: {', '.join(versioned_changes)}"
            )
        remaining = added_versions.copy()
        chain_version = previous
        while chain_version != current:
            matches = [item for item in remaining if item[1] == chain_version]
            if len(matches) != 1:
                raise ValueError(
                    f"{schema_name} {previous} -> {current} lacks a new upgrade "
                    "migration chain contiguous from previous to current"
                )
            migration = matches[0]
            remaining.remove(migration)
            chain_version = migration[2]
        if remaining:
            raise ValueError(
                f"{schema_name} {previous} -> {current} has upgrade migrations "
                f"outside its chain: {', '.join(item[0] for item in remaining)}"
            )
    elif current != previous:
        raise ValueError(
            f"{schema_name} version changed without an owned contract change"
        )
    elif any(
        migration_current != current for _, _, migration_current in added_versions
    ):
        raise ValueError(f"{schema_name} upgrade migration does not target {current}")


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} BASE_GIT_REF", file=sys.stderr)
        return 2

    current_registry_text = REGISTRY_PATH.read_text(encoding="utf-8")
    schemas = load_registry(current_registry_text)
    current_versions: dict[str, str] = {}
    for schema in schemas:
        canonical_path = REPO_ROOT / schema.canonical_sql
        current = schema_version(
            schema.name, canonical_path.read_text(encoding="utf-8")
        )
        if current is None:
            raise ValueError(
                f"{schema.canonical_sql} is missing the {schema.name} schema version"
            )
        if not _owns(schema, schema.canonical_sql):
            raise ValueError(
                f"{schema.name} does not own its canonical SQL path "
                f"{schema.canonical_sql}"
            )
        current_versions[schema.name] = current

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
    changed = changed_repository_files(base_ref)
    added = changed_repository_files(base_ref, added_only=True)
    production_sql = [
        path for path in changed if path.startswith("v2/db/") and path.endswith(".sql")
    ]
    for path in production_sql:
        owners = [schema.name for schema in schemas if _owns(schema, path)]
        if len(owners) != 1:
            raise ValueError(
                "changed production SQL must have exactly one registered owner: "
                f"{path} has {owners}"
            )

    previous_registry_text = git_text(base_ref, "v2/db/application-schemas.json")
    previous_by_name: dict[str, RegisteredSchema] = {}
    if previous_registry_text is not None:
        previous_by_name = {
            schema.name: schema
            for schema in load_previous_registry(previous_registry_text)
        }

    for schema in schemas:
        current = current_versions[schema.name]
        previous_schema = previous_by_name.get(schema.name)
        previous_sql = (
            git_text(base_ref, previous_schema.canonical_sql)
            if previous_schema is not None
            else None
        )
        previous = (
            schema_version(schema.name, previous_sql)
            if previous_sql is not None
            else None
        )
        schema_changes = [
            path
            for path in changed
            if _owns(schema, path)
            or (previous_schema is not None and _owns(previous_schema, path))
        ]
        schema_additions = [
            path
            for path in added
            if _owns(schema, path)
            or (previous_schema is not None and _owns(previous_schema, path))
        ]
        if previous is None:
            if not schema_changes:
                raise ValueError(f"new schema {schema.name} has no owned SQL changes")
            continue
        validate_schema_update(
            schema.name, previous, current, schema_changes, schema_additions
        )

    rendered = ", ".join(
        f"{name}={version}" for name, version in sorted(current_versions.items())
    )
    print(f"application schema versions advance cleanly: {rendered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
