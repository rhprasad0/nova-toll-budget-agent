import pytest

from scripts.check_schema_versions import validate_schema_update

MIGRATION = "v2/db/migrations/002_upgrade_pricing_1_0_0_to_1_0_1.sql"


def test_schema_bump_requires_a_matching_new_upgrade_migration():
    with pytest.raises(ValueError, match="lacks a new upgrade migration"):
        validate_schema_update("1.0.0", "1.0.1", ["v2/db/schema.sql"], [])

    validate_schema_update(
        "1.0.0", "1.0.1", ["v2/db/schema.sql", MIGRATION], [MIGRATION]
    )


def test_released_upgrade_migrations_are_immutable():
    with pytest.raises(ValueError, match="immutable"):
        validate_schema_update("1.0.1", "1.0.1", [MIGRATION], [])


def test_current_release_can_add_its_missing_upgrade_migration():
    validate_schema_update("1.0.1", "1.0.1", [MIGRATION], [MIGRATION])
