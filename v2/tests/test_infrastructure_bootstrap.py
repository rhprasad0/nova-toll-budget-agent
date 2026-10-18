import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import cast

import yaml

from tests.infrastructure_support import (
    AGENTS,
    DEPLOYMENT,
    DEVELOPMENT_MIGRATION_HELPER,
    DEVELOPMENT_MIGRATIONS_WORKFLOW,
    FOUNDATION_IAM,
    REPO_ROOT,
    V2_ROOT,
    must_reject,
    parsed_policy_document,
    top_level_terraform_block,
    workflow_trigger,
)


def test_manual_oracle_migration_030_contract_is_offline_guarded_and_syntax_checked() -> (
    None
):
    section = DEPLOYMENT.split("## Manual Oracle migration 030", maxsplit=1)[1].split(
        "## Environment-tag inventory", maxsplit=1
    )[0]
    shell_blocks = re.findall(r"```sh\n(.*?)\n```", section, flags=re.DOTALL)
    assert len(shell_blocks) == 1
    shell = shell_blocks[0]

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as script:
        script.write(shell)
        script.flush()
        assert subprocess.run(["bash", "-n", script.name], check=False).returncode == 0

    for required in (
        "explicit operator authorization",
        "nova-toll-prod",
        "920534282028",
        "us-east-1",
        "AWS_PROFILE=nova-toll-prod aws --region us-east-1",
        "set -euo pipefail",
        "set +x",
        'command -v "$command_name"',
        "MIGRATION_SHA256=101ee53eb4e37f00e4bf711d9c97bf97b4c53981f5b0a6bd7a932cfea9ecee40",
        'test ! -L "$MIGRATION"',
        '"$MIGRATION_SHA256" "$MIGRATION"',
        "describe-db-instances",
        "--db-instance-identifier nova-toll-db",
        "--query 'DBInstances'",
        "Endpoint.Address",
        "Endpoint.Port",
        "MasterUserSecret.SecretArn",
        'DBInstanceStatus == "available"',
        "PubliclyAccessible == false",
        '. != "None"',
        'test("^[A-Za-z0-9][A-Za-z0-9.-]*[.]rds[.]amazonaws[.]com$")',
        'get-secret-value --secret-id "$SECRET_ARN"',
        'type == "object"',
        "CA_URL=https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem",
        "CA_SHA256=90a6f1a7978a1b1b096dca6c57511ca48d3b8cf052f8e704baf358f34ea2f21b",
        "sha256sum --check --status",
        "PGSSLMODE=verify-full",
        'PGSSLROOTCERT="$CA_FILE"',
        "psql -X --set ON_ERROR_STOP=1",
        "1.3.0|1.13.1|995|13|0",
        "1.3.0|1.14.0|996|14|1|1",
        "required_i95_direction IS NULL",
        "source_route_key IS NULL",
        'source_metadata = \'{"basis":"v2/db/oracle/CONTRACT.md","curated":true}\'::jsonb',
        "trap cleanup EXIT",
        "rm -f --",
        "unset DB_PASSWORD DB_USER SECRET_JSON",
        "v2/db/migrations/030_upgrade_oracle_1_13_1_to_1_14_0.sql",
        "process_environment()",
        'source="$(source_state "$database")"',
        "if [ \"$source\" = '1.3.0|1.13.1|995|13|0' ]; then",
        'apply_migration "$database"',
        'require_target_state "$database"',
        'target="$(target_state "$database")"',
        "if [ \"$target\" = '1.3.0|1.14.0|996|14|1|1' ]; then",
        "already has the exact target state; verifying and skipping",
        "Incompatible migration state for %s; stop without applying.",
        "process_environment nova_toll_development",
        "process_environment nova_toll",
        "Apply outcome is unknown",
        'actual="$(target_state "$database")"',
        "SQL error before `COMMIT`",
        "connection loss during or after `COMMIT` makes the outcome unknown",
        "before retrying an apply or",
        "separately authorized RDS backup/PITR incident handling",
    ):
        assert required in section

    assert not re.search(r"(?m)^\s*set\s+-x(?:\s|$)", shell)
    assert not re.search(r"(?m)^\s*SECRET_ARN=arn:", shell)
    assert not re.search(r"(?m)^DB_HOST=(?:[A-Za-z0-9]|['\"][A-Za-z0-9])", shell)
    assert not re.search(
        r"(?m)^\s*(?:echo|printf).*\$(?:SECRET_JSON|DB_PASSWORD)", shell
    )
    assert not re.search(r"(?m)^\s*.*>[^\n]*\$(?:SECRET_JSON|DB_PASSWORD)", shell)
    assert 'PGPASSWORD="$DB_PASSWORD"' in shell
    assert "sslmode=require" not in shell
    assert "sslmode=disable" not in shell
    assert "sslmode=verify-ca" not in shell
    assert "AWS_ACCESS_KEY_ID" not in shell
    assert "AWS_SECRET_ACCESS_KEY" not in shell
    for forbidden in (
        "Schema-changing work is not deployable",
        "Current releases are schema-neutral",
    ):
        assert forbidden not in (DEPLOYMENT + AGENTS)
    for forbidden in (
        "deploy_oracle_migration.py",
        "migration-finalizer",
        "migrator_role",
        "RELEASE_EVIDENCE",
        "configure-aws-credentials",
    ):
        assert forbidden not in section

    for before, after in (
        ("describe-db-instances", "get-secret-value"),
        ('test ! -L "$MIGRATION"\n', "get-secret-value"),
        ("sha256sum --check --status", "get-secret-value"),
        ("get-secret-value", "psql -X --set ON_ERROR_STOP=1"),
        (
            "process_environment() {\n",
            "process_environment nova_toll_development\n",
        ),
        (
            "process_environment nova_toll_development\n",
            "process_environment nova_toll\n",
        ),
    ):
        assert shell.index(before) < shell.index(after)

    process_body = re.search(r"(?ms)^process_environment\(\) \{.*?^\}", shell)
    assert process_body is not None
    process_body = process_body.group(0)
    source_branch = process_body.split(
        "if [ \"$source\" = '1.3.0|1.13.1|995|13|0' ]; then", maxsplit=1
    )[1].split('target="$(target_state "$database")"', maxsplit=1)[0]
    assert source_branch.index('apply_migration "$database"') < source_branch.index(
        'require_target_state "$database"'
    )
    target_branch = process_body.split(
        'target="$(target_state "$database")"', maxsplit=1
    )[1]
    assert "apply_migration" not in target_branch
    assert "Incompatible migration state" in target_branch
    assert "exit 1" in target_branch
    assert process_body.index('require_target_state "$database"') < process_body.index(
        "return 0"
    )
    target_skip = process_body.index("already has the exact target state")
    assert target_skip < process_body.index("return 0", target_skip)


def test_development_migrations_iam_is_development_only_and_least_privilege() -> None:
    assume = top_level_terraform_block(
        FOUNDATION_IAM,
        'data "aws_iam_policy_document" "development_migrations_assume"',
    )
    policy = top_level_terraform_block(
        FOUNDATION_IAM,
        'data "aws_iam_policy_document" "development_migrations"',
    )
    role = top_level_terraform_block(
        FOUNDATION_IAM,
        'resource "aws_iam_role" "development_migrations"',
    )
    inline = top_level_terraform_block(
        FOUNDATION_IAM,
        'resource "aws_iam_role_policy" "development_migrations"',
    )
    for block in (assume, policy, role, inline):
        assert re.search(
            r'count\s*=\s*var\.environment == "development" \? 1 : 0', block
        )
    statements = parsed_policy_document(FOUNDATION_IAM, "development_migrations")
    assert [statement["actions"] for statement in statements] == [
        ["rds:DescribeDBInstances"],
        ["rds-db:connect"],
    ]
    assert all(statement["resources"] for statement in statements)
    assert "aws_db_instance.main.identifier" in policy
    assert "aws_db_instance.main.resource_id" in policy
    assert "/schema_migrator_development" in policy
    assert "nova-toll-v2-development-migrations-dev" in role
    assert 'actions = ["sts:AssumeRoleWithWebIdentity"]' in assume
    assert 'variable = "token.actions.githubusercontent.com:aud"' in assume
    assert 'values   = ["sts.amazonaws.com"]' in assume
    assert (
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"
        in assume
    )
    for forbidden in (
        "sts:AssumeRole",
        "ssm:",
        "secretsmanager:",
        "terraform.tfstate",
        "development_delivery",
        "timed_checks",
        "production",
        "*",
    ):
        assert forbidden not in policy


def test_development_migrations_workflow_is_main_only_private_and_sanitized(
    tmp_path: Path,
) -> None:
    workflow = cast(dict[str, object], yaml.safe_load(DEVELOPMENT_MIGRATIONS_WORKFLOW))
    assert workflow_trigger(workflow) == {"workflow_dispatch": None}
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    job = jobs["migrate"]
    assert job["if"] == (
        "github.ref == 'refs/heads/main' && github.actor_id == '91573985' "
        "&& github.triggering_actor == github.actor"
    )
    assert job["environment"] == "development"
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    assert job["concurrency"] == {
        "group": "v2-development-apply",
        "queue": "max",
    }
    migration_step = next(
        step
        for step in cast(list[dict[str, object]], job["steps"])
        if step.get("name") == "Run fixed-target migrations and emit sanitized evidence"
    )
    baselines = json.loads((V2_ROOT / "db/migration-baselines.json").read_text())
    expected_versions = {
        f"EXPECTED_{row['schema'].upper()}_VERSION": row["version"]
        for row in baselines
        if hashlib.sha256((REPO_ROOT / row["source_path"]).read_bytes()).hexdigest()
        == row["source_sha256"]
    }
    assert set(expected_versions) == {
        "EXPECTED_PRICING_VERSION",
        "EXPECTED_ORACLE_VERSION",
    }
    assert migration_step["env"] == expected_versions
    defaults = cast(dict[str, object], job["defaults"])
    run_defaults = cast(dict[str, object], defaults["run"])
    assert run_defaults["working-directory"] == "v2"
    assert "workflow_dispatch" in DEVELOPMENT_MIGRATIONS_WORKFLOW
    assert (
        "arn:aws:iam::903859731897:role/nova-toll-v2-development-migrations-dev"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert "tag:ci-development" in DEVELOPMENT_MIGRATIONS_WORKFLOW
    assert "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112" in DEVELOPMENT_MIGRATION_HELPER
    assert 'PGHOST="$DB_HOST"' in DEVELOPMENT_MIGRATION_HELPER
    assert 'PGHOSTADDR="$TRANSPORT_IPV6"' in DEVELOPMENT_MIGRATION_HELPER
    assert "PGSSLMODE=verify-full" in DEVELOPMENT_MIGRATION_HELPER
    assert 'RDS_CA_BUNDLE="$ROOT/v2/infra/build/ca/rds-ca-bundle.pem"' in (
        DEVELOPMENT_MIGRATION_HELPER
    )
    fetched = tmp_path / "v2/infra/build/ca/rds-ca-bundle.pem"
    fetched.parent.mkdir(parents=True)
    fetched.write_text("disposable CA fixture", encoding="utf-8")
    assert fetched == tmp_path / "v2/infra/build/ca/rds-ca-bundle.pem"
    assert fetched != tmp_path / "infra/build/ca/rds-ca-bundle.pem"
    assert "generate-db-auth-token" in DEVELOPMENT_MIGRATION_HELPER
    assert (
        "python3 scripts/run_development_migrations.py" in DEVELOPMENT_MIGRATION_HELPER
    )
    assert (
        'test("^v2/db/migrations/[0-9]{3}_upgrade_(pricing|oracle)_.*\\\\.sql$")'
        in DEVELOPMENT_MIGRATION_HELPER
    )
    assert (
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert (
        "tailscale/github-action@d1b6cd204f8dceda5b3eaad7f1f767be390056cd"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert (
        "aws-actions/configure-aws-credentials@e1253824e5c10ff9df46874f81ed3ec929e19cfd"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert (
        "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert (
        "90a6f1a7978a1b1b096dca6c57511ca48d3b8cf052f8e704baf358f34ea2f21b"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert "jq -cn" in DEVELOPMENT_MIGRATION_HELPER
    assert "RUNNER_TEMP" in DEVELOPMENT_MIGRATION_HELPER
    for forbidden in (
        "secretsmanager",
        "ssm:",
        "terraform apply",
        "terraform plan",
        'nova_toll"',
        "raw psql",
    ):
        assert forbidden not in DEVELOPMENT_MIGRATIONS_WORKFLOW


def test_development_migrations_workflow_is_main_only_private_and_sanitized_owner_gate() -> (
    None
):
    def assert_owner_gate(source: str) -> None:
        workflow = cast(dict[str, object], yaml.safe_load(source))
        jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
        assert jobs["migrate"]["if"] == (
            "github.ref == 'refs/heads/main' && github.actor_id == '91573985' "
            "&& github.triggering_actor == github.actor"
        )

    assert_owner_gate(DEVELOPMENT_MIGRATIONS_WORKFLOW)
    for original, replacement in (
        (" && github.actor_id == '91573985'", ""),
        ("github.actor_id == '91573985'", "github.actor_id == '123456'"),
        ("&& github.actor_id == '91573985'", "|| github.actor_id == '91573985'"),
        ("github.actor_id == '91573985'", "github.actor == 'owner'"),
        (" && github.triggering_actor == github.actor", ""),
        (
            "github.triggering_actor == github.actor",
            "github.triggering_actor == 'owner'",
        ),
        (
            "&& github.triggering_actor == github.actor",
            "|| github.triggering_actor == github.actor",
        ),
        (
            "github.triggering_actor == github.actor",
            "github.triggering_actor == github.actor && github.actor_id == '123456'",
        ),
    ):
        must_reject(
            assert_owner_gate,
            DEVELOPMENT_MIGRATIONS_WORKFLOW,
            original,
            replacement,
        )


def test_development_migrations_runbook_requires_post_merge_order_and_allowlist() -> (
    None
):
    section = DEPLOYMENT.split(
        "### Protected development migration workflow (#305 slice 3)", 1
    )[1].split("### Protected production migration component", 1)[0]
    assert section.index("human review and merge") < section.index("foundation plan")
    assert section.index("foundation plan") < section.index(
        "fresh development bootstrap"
    )
    assert section.index("fresh development bootstrap") < section.index(
        "gh workflow run"
    )
    for required in (
        "nova-toll-v2-development-migrations-dev",
        "schema_migrator_development",
        "PGHOST",
        "PGHOSTADDR",
        "applied=[]",
        "commit=<40 lowercase hex>;run=<UUID>",
        "token, password, endpoint",
    ):
        assert required in section
