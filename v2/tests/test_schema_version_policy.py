import pytest

from scripts.check_schema_versions import (
    REPO_ROOT,
    RegisteredSchema,
    owning_schemas,
    validate_baselines_append_only,
    validate_documented_version,
    validate_registry_continuity,
    validate_schema_update,
)

PRICING_MIGRATION = "v2/db/migrations/002_upgrade_pricing_1_0_0_to_1_0_1.sql"
ORACLE_MIGRATION = "v2/db/migrations/004_upgrade_oracle_1_0_0_to_1_0_1.sql"
ORACLE_MIGRATION_2 = "v2/db/migrations/005_upgrade_oracle_1_0_1_to_1_0_2.sql"


def test_deleted_contract_path_keeps_its_previous_owner() -> None:
    previous = (
        RegisteredSchema(
            name="pricing",
            canonical_sql="v2/db/schema.sql",
            owned_paths=("v2/db/migrations/retired.sql",),
        ),
    )
    assert owning_schemas("v2/db/migrations/retired.sql", (), previous) == {"pricing"}


def test_registered_schema_cannot_be_removed() -> None:
    previous = (RegisteredSchema("pricing", "v2/db/schema.sql", ("v2/db/*.sql",)),)
    with pytest.raises(ValueError, match="cannot be removed: \\['pricing'\\]"):
        validate_registry_continuity((), previous)


@pytest.mark.parametrize(
    ("schema_name", "canonical_sql", "migration"),
    [
        ("pricing", "v2/db/schema.sql", PRICING_MIGRATION),
        ("oracle", "v2/db/oracle/schema.sql", ORACLE_MIGRATION),
    ],
)
def test_schema_bump_requires_a_matching_new_upgrade_migration(
    schema_name: str, canonical_sql: str, migration: str
) -> None:
    with pytest.raises(ValueError, match="lacks a new upgrade migration"):
        validate_schema_update(schema_name, "1.0.0", "1.0.1", [canonical_sql], [])

    validate_schema_update(
        schema_name,
        "1.0.0",
        "1.0.1",
        [canonical_sql, migration],
        [migration],
    )


def test_released_upgrade_migrations_are_immutable() -> None:
    with pytest.raises(ValueError, match="immutable"):
        validate_schema_update("pricing", "1.0.1", "1.0.1", [PRICING_MIGRATION], [])


def test_schema_bump_accepts_only_a_contiguous_upgrade_chain() -> None:
    canonical_sql = "v2/db/oracle/schema.sql"
    validate_schema_update(
        "oracle",
        "1.0.0",
        "1.0.2",
        [canonical_sql, ORACLE_MIGRATION, ORACLE_MIGRATION_2],
        [ORACLE_MIGRATION, ORACLE_MIGRATION_2],
    )

    with pytest.raises(ValueError, match="lacks a new upgrade migration chain"):
        validate_schema_update(
            "oracle",
            "1.0.0",
            "1.0.2",
            [canonical_sql, ORACLE_MIGRATION_2],
            [ORACLE_MIGRATION_2],
        )


def test_current_release_can_add_its_missing_upgrade_migration() -> None:
    validate_schema_update(
        "pricing",
        "1.0.1",
        "1.0.1",
        [PRICING_MIGRATION],
        [PRICING_MIGRATION],
    )


def test_migration_baselines_are_append_only() -> None:
    validate_baselines_append_only('[{"v": 1}]', '[{"v": 1}, {"v": 2}]')
    for current in ('[{"v": 2}]', "[]", '[{"v": 0}, {"v": 1}]'):
        with pytest.raises(ValueError, match="append-only"):
            validate_baselines_append_only('[{"v": 1}]', current)


def test_owned_contract_document_states_the_canonical_version() -> None:
    oracle = RegisteredSchema(
        "oracle", "v2/db/oracle/schema.sql", ("v2/db/oracle/CONTRACT.md",)
    )
    text = (REPO_ROOT / "v2/db/oracle/CONTRACT.md").read_text()
    current = text.split("oracle schema `", 1)[1].split("`", 1)[0]
    validate_documented_version(oracle, current)
    with pytest.raises(ValueError, match=r"update it to the canonical 99\.0\.0"):
        validate_documented_version(oracle, "99.0.0")
