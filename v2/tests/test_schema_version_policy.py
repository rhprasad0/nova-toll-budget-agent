import pytest

from scripts.check_schema_versions import validate_schema_update

PRICING_MIGRATION = "v2/db/migrations/002_upgrade_pricing_1_0_0_to_1_0_1.sql"
ORACLE_MIGRATION = "v2/db/migrations/004_upgrade_oracle_1_0_0_to_1_0_1.sql"
ORACLE_MIGRATION_2 = "v2/db/migrations/005_upgrade_oracle_1_0_1_to_1_0_2.sql"


@pytest.mark.parametrize(
    ("schema_name", "canonical_sql", "migration"),
    [
        ("pricing", "v2/db/schema.sql", PRICING_MIGRATION),
        ("oracle", "v2/db/oracle/schema.sql", ORACLE_MIGRATION),
    ],
)
def test_schema_bump_requires_a_matching_new_upgrade_migration(
    schema_name: str, canonical_sql: str, migration: str
):
    with pytest.raises(ValueError, match="lacks a new upgrade migration"):
        validate_schema_update(schema_name, "1.0.0", "1.0.1", [canonical_sql], [])

    validate_schema_update(
        schema_name,
        "1.0.0",
        "1.0.1",
        [canonical_sql, migration],
        [migration],
    )


def test_released_upgrade_migrations_are_immutable():
    with pytest.raises(ValueError, match="immutable"):
        validate_schema_update("pricing", "1.0.1", "1.0.1", [PRICING_MIGRATION], [])


def test_schema_bump_accepts_only_a_contiguous_upgrade_chain():
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


def test_current_release_can_add_its_missing_upgrade_migration():
    validate_schema_update(
        "pricing",
        "1.0.1",
        "1.0.1",
        [PRICING_MIGRATION],
        [PRICING_MIGRATION],
    )
