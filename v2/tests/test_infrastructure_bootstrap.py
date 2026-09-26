import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from textwrap import dedent
from typing import cast

import pytest
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
        "CA_SHA256=e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3",
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


def _development_bootstrap_script() -> str:
    bootstrap = DEPLOYMENT.split(
        "The following is the executable, fail-closed inventory and repair procedure.",
        maxsplit=1,
    )[1].split("After bootstrap/import", maxsplit=1)[0]
    match = re.search(r"```sh\n(.*?)\n```", bootstrap, re.DOTALL)
    assert match
    return match.group(1)


def _assert_development_bootstrap_contract(script: str) -> None:
    assert 'EXPECTED_PROFILE="nova-toll-dev"' in script
    assert 'EXPECTED_ACCOUNT="903859731897"' in script
    assert 'REGION="us-east-1"' in script
    assert (
        ': "${AWS_PROFILE:?invoke this procedure with AWS_PROFILE=nova-toll-dev}"'
        in script
    )
    assert 'test "$AWS_PROFILE" = "$EXPECTED_PROFILE"' in script
    assert 'test "${AWS_DEFAULT_REGION:-}" = "$REGION"' in script
    assert "AWS_REGION and AWS_DEFAULT_REGION conflict" in script
    assert 'export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"' in script
    assert 'STATE_BUCKET="nova-toll-tfstate-${EXPECTED_ACCOUNT}"' in script
    assert 'LOCK_KEY="nova-toll/v2/development/bootstrap-lock"' in script
    assert 'LOCK_ARN="arn:aws:s3:::${STATE_BUCKET}/${LOCK_KEY}"' in script
    assert "LOCK_PATH=" not in script
    assert "aws ssm put-parameter" not in script
    assert "aws ssm delete-parameter" not in script
    assert (
        'aws s3api put-object --region "$REGION" --bucket "$STATE_BUCKET" --key "$LOCK_KEY"'
        in script
    )
    assert "--if-none-match '*'" in script
    assert "PreconditionFailed" in script
    assert "ConditionalRequestConflict" in script
    assert "LOCK_TOKEN=" in script and "/dev/urandom" in script
    assert 'LOCK_STARTED_AT="$(date -u' in script
    assert 'LOCK_VALUE="${LOCK_TOKEN}|${LOCK_STARTED_AT}"' in script
    assert "LOCK_ETAG=" in script and "LOCK_VERSION_ID=" in script
    assert "lock_is_current()" in script
    assert "acquire_bootstrap_lock" in script
    assert "trap bootstrap_cleanup EXIT" in script
    assert script.index("declare -A STATE_PREEXISTING=()") < script.index(
        "trap bootstrap_cleanup EXIT"
    )
    assert script.index("declare -A STATE_IMPORTED_BY_THIS_RUN=()") < script.index(
        "trap bootstrap_cleanup EXIT"
    )
    assert "release_bootstrap_lock" in script
    assert (
        'aws s3api delete-object --region "$REGION" --bucket "$STATE_BUCKET" --key "$LOCK_KEY" --if-match "$LOCK_ETAG"'
        in script
    )
    assert '--version-id "$LOCK_VERSION_ID"' in script
    assert "There\nis no overwrite, expiry, retry, or lock stealing." in DEPLOYMENT
    lock_permissions = DEPLOYMENT.split(
        "The versioned development state bucket uses SSE-KMS.", 1
    )[1].split("The lock uses the", 1)[0]
    assert all(
        action in lock_permissions
        for action in (
            "s3:PutObject",
            "s3:GetObject",
            "s3:DeleteObject",
            "s3:DeleteObjectVersion",
        )
    )
    assert (
        "arn:aws:s3:::nova-toll-tfstate-903859731897/nova-toll/v2/development/bootstrap-lock"
        in lock_permissions
    )
    assert "kms:GenerateDataKey" in lock_permissions
    assert "kms:EncryptionContext:aws:s3:arn" in lock_permissions
    assert "no `kms:Decrypt`" in lock_permissions
    assert "s3:ListBucket" not in lock_permissions
    assert "s3:GetObjectVersion" not in lock_permissions
    assert (
        "bootstrap lock release stopped: current ETag/version does not match" in script
    )
    assert "BOOTSTRAP_EVIDENCE_DIR" in script
    assert "evidence directory must be an absolute path" in script
    assert "evidence must be outside checkout" in script
    assert "aws sts get-caller-identity" in script
    assert 'aws iam get-role --role-name "$ROLE_NAME"' in script
    assert "grep -q 'NoSuchEntity'" in script
    assert 'test "$CALLER_ACCOUNT" = "$EXPECTED_ACCOUNT"' in script
    assert 'FETCHER_BUILD="$ROOT/v2/scripts/build_fetcher_zip.sh"' in script
    assert 'FETCHER_PACKAGE="$ROOT/infra/build/fetcher.zip"' in script
    assert 'FETCHER_INPUT="$ROOT/v2/lambdas/fetcher/handler.py"' in script
    assert (
        'EXPECTED_FETCHER_SHA256="${EXPECTED_FETCHER_SHA256:?set the reviewed canonical fetcher SHA-256}"'
        in script
    )
    assert 'git -C "$ROOT" fetch --no-tags origin main' in script
    assert 'ORIGIN_URL="$(git -C "$ROOT" remote get-url origin 2>/dev/null)"' in script
    assert "git@github.com:rhprasad0/nova-toll-budget-agent.git" in script
    assert (
        'PROTECTED_MAIN_COMMIT="$(git -C "$ROOT" rev-parse refs/remotes/origin/main)"'
        in script
    )
    assert (
        'test "$(git -C "$ROOT" rev-parse HEAD)" = "$PROTECTED_MAIN_COMMIT"' in script
    )
    assert 'git -C "$ROOT" status --porcelain --untracked-files=all' in script
    assert 'REVIEWED_COMMIT="$PROTECTED_MAIN_COMMIT"' in script
    assert 'git -C "$ROOT" cat-file -e "$REVIEWED_COMMIT^{commit}"' in script
    assert 'git -C "$ROOT" diff --quiet "$REVIEWED_COMMIT" -- "$relative"' in script
    assert 'test ! -L "$path"' in script
    assert "ls-files --others --exclude-standard" in script
    assert 'test -d "$ROOT/infra/build" && test ! -L "$ROOT/infra/build"' in script
    assert 'test ! -L "$FETCHER_PACKAGE"' in script
    assert 'test ! -L "$ROOT/infra/build/fetcher"' in script
    assert 'env -i PATH="/usr/bin:/bin" LC_ALL=C "$FETCHER_BUILD"' in script
    assert (
        'CANONICAL_FETCHER_SHA256="9a2e09f1c46a4ee53a6b17c09687663f41ee66de097342ad572b3c943fb704d1"'
        in script
    )
    assert 'test -s "$FETCHER_PACKAGE"' in script
    assert "placeholder fetcher artifact is not permitted" in script
    assert 'test "$EXPECTED_FETCHER_SHA256" = "$CANONICAL_FETCHER_SHA256"' in script
    assert 'test "$FETCHER_SHA256" = "$CANONICAL_FETCHER_SHA256"' in script
    assert "TF_VAR_tailscale_advertise_routes:-false" in script
    assert "canonicalize_json()" in script
    assert "urllib.parse.unquote" in script
    assert "sort_keys=True" in script
    assert "render_document" in script
    assert "data.aws_iam_policy_document.development_delivery_assume.json" in script
    assert "local.development_delivery_policy_documents.${policy_key}" in script
    assert (
        "EXPECTED_POLICY_KEYS=(state compute observability storage data runtime edge)"
        in script
    )
    assert 'EXPECTED_POLICY_PATH="/nova-toll/v2/development/"' in script
    assert 'EXPECTED_POLICY_NAMES["$policy_key"]="$ROLE_NAME-$policy_key"' in script
    assert (
        'EXPECTED_POLICY_ARNS["$policy_key"]="arn:aws:iam::$EXPECTED_ACCOUNT:policy${EXPECTED_POLICY_PATH}${EXPECTED_POLICY_NAMES[$policy_key]}"'
        in script
    )
    assert 'ROLE_NAME="nova-toll-v2-development-delivery"' in script
    assert 'ROLE_ARN="arn:aws:iam::$EXPECTED_ACCOUNT:role/$ROLE_NAME"' in script
    assert 'Role.Path == "/"' in script
    assert ".Role.MaxSessionDuration == 3600" in script
    assert "PermissionsBoundary? // null) == null" in script
    assert 'cmp -s "$EXPECTED_TRUST" "$ACTUAL_TRUST"' in script
    assert (
        'aws iam create-role --role-name "$ROLE_NAME" --path / --max-session-duration 3600'
        in script
    )
    assert (
        'aws iam create-policy --policy-name "${EXPECTED_POLICY_NAMES[$policy_key]}" --path "$EXPECTED_POLICY_PATH"'
        in script
    )
    assert (
        'aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}"'
        in script
    )
    assert (
        'aws iam get-policy-version --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}"'
        in script
    )
    assert 'aws iam list-role-policies --role-name "$ROLE_NAME"' in script
    assert 'aws iam list-attached-role-policies --role-name "$ROLE_NAME"' in script
    assert (
        'aws iam get-policy --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}"'
        in script
    )
    assert "policy_set_is_exact" in script
    assert "policy_set_is_safe_subset" in script
    assert "NextToken? // null) == null" in script
    assert script.count(".PolicyNames == []") >= 3
    assert script.count(".AttachedPolicies == []") >= 1
    assert "rollback_created_attachments" in script
    assert (
        script.count(
            'cmp -s "${EXPECTED_POLICIES[$policy_key]}" "${ACTUAL_POLICIES[$policy_key]}"'
        )
        >= 3
    )
    assert "role_documents_match" in script
    assert (
        "delivery role failed post-attachment exact effective-policy validation"
        in script
    )
    assert (
        "delivery role create failed; preserving any matching post-state for manual exact reconciliation"
        in script
    )
    assert "assert_dev_account" in script
    assert 'terraform -chdir="$ROOT/infra" state rm' in script
    assert 'terraform -chdir="$ROOT/v2/infra" state rm' in script
    assert "rollback_delivery_state()" in script
    assert "declare -A STATE_PREEXISTING=()" in script
    assert "declare -A STATE_IMPORTED_BY_THIS_RUN=()" in script
    assert (
        "STATE_IMPORTED_BY_THIS_RUN['aws_iam_role.development_delivery[0]']=1" in script
    )
    assert 'STATE_IMPORTED_BY_THIS_RUN["$address"]=1' in script
    assert 'STATE_PREEXISTING["$address"]=1' in script
    assert "already managed or concurrent; refusing state removal" in script
    assert "state ownership is unproven and was retained" in script
    assert "IMPORT_IN_PROGRESS" not in script
    assert (
        script.count('if test "$ROLE_CREATED" -eq 1; then rollback_created_role; fi')
        >= 4
    )
    assert "rollback_created_role" in script
    assert "could not verify created delivery role rollback" in script
    assert "MUTATION_AMBIGUOUS=0" in script
    assert script.count("MUTATION_AMBIGUOUS=1") >= 4
    assert "ambiguous mutation result preserved for manual reconciliation" in script
    assert "rollback_created_url()" in script
    assert "rollback_url_state()" in script
    assert "cleanup_on_failure()" in script
    assert "trap cleanup_on_failure EXIT" in script
    assert "BOOTSTRAP_COMPLETE=1" in script
    assert "import_url_state()" in script
    assert "printf -v \"${stem}_CREATED\" '%s' 1" in script
    assert "aws lambda remove-permission" in script
    assert "reconcile_function_url()" not in script
    assert "exact absent-before/present-after reconciliation" not in script
    assert (
        "Lambda URL create failed; preserving any matching post-state for manual exact reconciliation"
        in script
    )
    assert (
        "ambiguous Lambda URL permission result; preserving any matching post-state for manual exact reconciliation"
        in script
    )
    assert (
        "ambiguous Lambda invoke permission result; preserving any matching post-state for manual exact reconciliation"
        in script
    )
    assert "verify_owned_lambda_permission()" in script
    assert "aws lambda delete-function-url-config" in script
    assert 'terraform -chdir="$ROOT/infra" import' in script
    assert script.count('terraform -chdir="$ROOT/infra" import') == 2
    assert "'aws_iam_role.development_delivery[0]' \"$ROLE_ARN\"" in script
    assert 'address="aws_iam_policy.development_delivery[\\"$policy_key\\"]"' in script
    assert 'terraform -chdir="$ROOT/infra" state show -no-color' in script
    assert "'aws_iam_role.development_delivery[0]'" in script
    assert 'address="aws_iam_policy.development_delivery[\\"$policy_key\\"]"' in script
    assert (
        'aws_iam_role_policy_attachment.development_delivery[\\"$policy_key\\"]'
        in script
    )
    assert "delivery role import state ID or ARN is not the exact target" in script
    assert "delivery managed-policy import state ID is not the exact target" in script
    assert "state_id_matches()" in script
    assert "state_list_contains()" in script
    assert (
        "awk -v address=\"$address\" '$0 == address { found=1 } END { exit found ? 0 : 1 }'"
        in script
    )
    assert (
        'terraform -chdir="$ROOT/infra" state list >"$FOUNDATION_STATE_LIST"' in script
    )
    assert (
        'terraform -chdir="$ROOT/v2/infra" state list >"$APPLICATION_STATE_LIST"'
        in script
    )
    assert "state list | grep -Fxq" not in script
    assert 'state_id_matches "$WORK_DIR/${label// /-}.state" "$identifier"' in script
    assert "Terraform state ID does not match exact target $identifier" in script
    assert (
        "import_url_state 'aws_lambda_function_url.public_chat' \"$FUNCTION_NAME,$QUALIFIER\""
        in script
    )
    assert (
        "import_url_state 'aws_lambda_permission.public_chat_url' \"$FUNCTION_NAME,$QUALIFIER,AllowCloudFrontFunctionUrlV2\""
        in script
    )
    assert (
        "import_url_state 'aws_lambda_permission.public_chat_invoke' \"$FUNCTION_NAME,$QUALIFIER,AllowCloudFrontFunctionInvokeV2\""
        in script
    )
    assert "aws_lambda_function_url.public_chat" in script
    assert 'DISTRIBUTION_ID="E33DVF3KT7BTAC"' in script
    assert 'DISTRIBUTION_DOMAIN="d1wqry4fbd92w5.cloudfront.net"' in script
    assert (
        "DistributionList.Items[?Id==`E33DVF3KT7BTAC` && DomainName==`d1wqry4fbd92w5.cloudfront.net`]"
        in script
    )
    assert "validate_function_url" in script
    assert '.AuthType == "AWS_IAM" and .InvokeMode == "RESPONSE_STREAM"' in script
    assert "validate_lambda_policy" in script
    assert "validate_existing_lambda_policy" in script
    assert "snapshot_lambda_permission" in script
    assert "reconcile_lambda_permission" in script
    assert "lambda-policy-before-" in script and "lambda-policy-after-" in script
    assert "lambda-statement-before-" in script and "lambda-statement-after-" in script
    assert "RevisionId" in script and "--revision-id" in script
    assert (
        "ambiguous Lambda URL permission result; preserving any matching post-state for manual exact reconciliation"
        in script
    )
    assert (
        "ambiguous Lambda invoke permission result; preserving any matching post-state for manual exact reconciliation"
        in script
    )
    assert (
        "Lambda rollback changed a pre-existing or concurrent permission statement"
        in script
    )
    assert 'cmp -s "$expected" "$statement"' in script
    assert "lambda:InvokeFunctionUrl" in script and "lambda:InvokeFunction" in script
    assert [
        line.strip()
        for line in script.splitlines()
        if line.strip().startswith(".Principal == {Service:")
    ] == [
        '.Principal == {Service: "cloudfront.amazonaws.com"} and',
        '.Principal == {Service: "cloudfront.amazonaws.com"} and',
    ]
    assert "AWS:SourceArn" in script
    assert "run_post_bootstrap_gates" in script
    assert "aws iam simulate-principal-policy" in script
    assert "IAM_SIMULATION_EVIDENCE" in script
    assert "SIMULATION_EXPECTED_COUNT=126" in script
    matrix = script.split('cat >"$SIMULATION_MATRIX" <<EOF\n', 1)[1].split("\nEOF", 1)[
        0
    ]
    assert len(matrix.splitlines()) == 126
    assert "runtime-role-wrong-service|iam:PassRole|" in matrix
    assert "unrelated-runtime-role-pass|iam:PassRole|" in matrix
    assert (
        "ContextKeyName=iam:PassedToService,ContextKeyValues=bedrock-agentcore.amazonaws.com"
        in script
    )
    assert "while IFS='|' read -r label action resource expected; do" in script
    assert "--context-entries" in script
    assert "SIMULATION_COUNT" in script
    assert (
        "s3:GetObject|arn:aws:s3:::nova-toll-tfstate-920534282028/nova-toll/terraform.tfstate|denied"
        in script
    )
    assert "nova-toll-state-920534282028" not in script
    for required_simulation in (
        "lambda:UpdateFunctionCode",
        "lambda:PublishVersion",
        "lambda:UpdateAlias",
        "lambda:DeleteFunction",
        "s3:PutObject",
        "s3:DeleteObject",
        "cloudfront:UpdateFunction",
        "cloudfront:PublishFunction",
        "bedrock:CreateGuardrailVersion",
        "apigateway:POST",
        "apigateway:DELETE",
        "bedrock-agentcore:UpdateAgentRuntime",
        "bedrock-agentcore:UpdateAgentRuntimeEndpoint",
        "iam:CreateRole",
        "iam:PutRolePolicy",
        "iam:PassRole",
        "iam:AttachRolePolicy",
        "lambda:AddPermission",
        "lambda:UpdateFunctionConfiguration",
        "bedrock-agentcore:CreateAgentRuntime",
        "bedrock-agentcore:PutResourcePolicy",
        "events:PutRule",
        "logs:PutMetricFilter",
        "cloudwatch:PutMetricAlarm",
        "wafv2:PutLoggingConfiguration",
        "kms:CreateAlias",
        "kms:UpdateAlias",
        "ec2:AuthorizeSecurityGroupIngress",
        "sqs:SetQueueAttributes",
        "sqs:AddPermission",
        "sqs:RemovePermission",
        "s3:PutBucketPolicy",
        "s3:PutBucketPublicAccessBlock",
        "athena:CreateNamedQuery",
        "s3:PutBucketOwnershipControls",
        "s3:PutBucketTagging",
        "s3:PutBucketVersioning",
        "s3:PutEncryptionConfiguration",
        "s3:PutLifecycleConfiguration",
        "s3:AbortMultipartUpload",
        "events:DisableRule",
        "events:EnableRule",
        "events:RemoveTargets",
        "events:TagResource",
        "events:UntagResource",
        "logs:TagResource",
        "logs:UntagResource",
        "dynamodb:UpdateContinuousBackups",
        "dynamodb:UpdateTimeToLive",
        "glue:UpdateDatabase",
        "athena:TagResource",
        "athena:UntagResource",
        "scheduler:TagResource",
        "scheduler:UntagResource",
        "bedrock-agentcore:TagResource",
        "bedrock-agentcore:UntagResource",
        "cloudfront:TestFunction",
        "cloudfront:TagResource",
        "cloudfront:UntagResource",
        "kms:GenerateDataKey",
    ):
        assert required_simulation in script
    assert 'PACKAGE_DIGESTS="$WORK_DIR/package-digests.tsv"' in script
    assert "PACKAGE_DIGESTS_JSON=" in script
    assert 'EVIDENCE_BINDING="$EVIDENCE_DIR/evidence-binding.json"' in script
    for evidence_field in (
        "commit_sha",
        "account_id",
        "role_arn",
        "policy_sha256",
        "fetcher_sha256",
        "plan_sha256",
        "timestamp",
        "binding_sha256",
    ):
        assert evidence_field in script
    assert "REPRESENTATIVE_V2_PACKAGE_DIR" not in script
    assert "REVIEWED_V2_PACKAGE_DIR" in script
    assert "REPRESENTATIVE_PLAN_EVIDENCE" in script
    assert (
        'terraform -chdir="$ROOT/v2/infra" show -json "$REPRESENTATIVE_PLAN"' in script
    )
    assert "PLAN_GATE_SOURCE" not in script
    assert "PLAN_GATE" not in script
    assert "development-plan-gate.py" not in script
    assert 'python3 "$PLAN_GATE" "$REPRESENTATIVE_PLAN_JSON"' not in script
    assert "PROTECTED_MAIN_OIDC_EVIDENCE" in script
    assert "protected-main-oidc" in script
    assert 'jq -e --arg commit "$REVIEWED_COMMIT"' in script
    assert ".commit_sha == $commit" in script
    assert "console -var environment=development" in script
    assert "for policy_mapping in" in script
    assert "for attachment_mapping in" in script
    for mapping in (
        "loader toll-v2-pricing-loader-dev toll-v2-pricing-loader-dev",
        "publisher toll-v2-report-publisher-dev toll-v2-report-publisher-dev",
        "publisher_scheduler toll-v2-report-publisher-scheduler-dev toll-v2-report-publisher-scheduler-dev",
        "timed_checks nova-toll-v2-timed-checks-dev nova-toll-v2-route-live-checks-dev",
        "tollchat_runtime nova-toll-v2-agentcore-runtime-dev nova-toll-v2-agentcore-runtime-dev",
        "tollchat_proxy nova-toll-v2-chat-proxy-dev nova-toll-v2-chat-proxy-dev",
        "agent_usage_rollup tollchat-v2-agent-usage-rollup-dev tollchat-v2-agent-usage-rollup-dev",
    ):
        assert mapping in script
    for mapping in (
        "loader_vpc toll-v2-pricing-loader-dev",
        "publisher_vpc toll-v2-report-publisher-dev",
        "tollchat_proxy_vpc nova-toll-v2-chat-proxy-dev",
    ):
        assert mapping in script
    assert 'get-public-access-block --bucket "$MEASUREMENT_BUCKET"' in script
    assert 'get-public-access-block --bucket "$SITE_BUCKET"' in script
    assert 'one "response-headers CloudFront" aws cloudfront' in script
    assert "one response-headers CloudFront aws cloudfront" not in script
    assert "get-bucket-public-access-block" not in script
    assert 'terraform -chdir="$ROOT/infra" apply' not in script
    assert "FOUNDATION_PLAN" not in script
    assert "terraform -target" not in script
    assert "terraform_remote_state" not in script
    assert "nova-toll-prod" not in script
    assert "nova-toll-tfstate-920534282028/nova-toll/terraform.tfstate" in script
    for generic_guard in (
        "review URL create command",
        "review URL permission, then set",
        "review URL invoke permission, then set",
        "review $label import, then set",
    ):
        assert generic_guard not in script
    for exact_guard in (
        "aws iam create-role --role-name $ROLE_NAME --path / --max-session-duration 3600",
        'aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}"',
        "aws lambda create-function-url-config --function-name $FUNCTION_NAME --qualifier $QUALIFIER",
        "aws lambda add-permission --function-name $FUNCTION_NAME --qualifier $QUALIFIER",
        "terraform -chdir=$ROOT/v2/infra import -input=false $address $identifier",
        "terraform -chdir=$ROOT/v2/infra state rm $address",
    ):
        assert exact_guard in script
    assert script.count('test "${BOOTSTRAP_APPROVED:-}" = YES') >= 14
    assert script.count("assert_dev_account") >= 14


def _assert_development_bootstrap_iam_rollback_contract(script: str) -> None:
    attachment_rollback = script.split("rollback_created_attachments() {", maxsplit=1)[
        1
    ].split("rollback_created_role() {", maxsplit=1)[0]
    guarded = re.search(
        r'if ! aws iam detach-role-policy --role-name "\$ROLE_NAME".*?\n\s*fi',
        attachment_rollback,
        re.DOTALL,
    )
    assert guarded is not None
    assert "MUTATION_AMBIGUOUS=1" in guarded.group(0)
    assert "preserving" in guarded.group(0)
    role_rollback = script.split("rollback_created_role() {", maxsplit=1)[1].split(
        "acquire_bootstrap_lock", maxsplit=1
    )[0]
    guarded = re.search(
        r'if ! aws iam delete-role --role-name "\$ROLE_NAME".*?\n\s*fi',
        role_rollback,
        re.DOTALL,
    )
    assert guarded is not None
    assert "MUTATION_AMBIGUOUS=1" in guarded.group(0)
    assert "preserving" in guarded.group(0)
    assert "aws iam delete-role-policy" not in script
    assert "aws iam put-role-policy" not in script

    state_rollback = script.split("rollback_delivery_state() {", maxsplit=1)[1].split(
        "verify_foundation_state() {", maxsplit=1
    )[0]
    assert 'if test "${MUTATION_AMBIGUOUS:-0}" -ne 0; then' in state_rollback
    assert "state rollback stopped: ambiguous IAM mutation result" in state_rollback

    cleanup = script.split("bootstrap_cleanup() {", maxsplit=1)[1].split(
        "\n}\n", maxsplit=1
    )[0]
    assert cleanup.index("rollback_created_role") < cleanup.index(
        "rollback_delivery_state"
    )
    assert (
        'test "$MUTATION_AMBIGUOUS" -eq 0 && declare -F rollback_delivery_state'
        in cleanup
    )


def test_development_bootstrap_iam_rollbacks_are_ambiguity_safe() -> None:
    script = _development_bootstrap_script()
    _assert_development_bootstrap_iam_rollback_contract(script)
    for function_name, command_prefix in (
        (
            "rollback_created_attachments",
            'if ! aws iam detach-role-policy --role-name "$ROLE_NAME"',
        ),
        (
            "rollback_created_role",
            'if ! aws iam delete-role --role-name "$ROLE_NAME"',
        ),
    ):
        function_start = script.index(f"{function_name}() {{")
        function_end = script.index("\n}\n", function_start) + 3
        function = script[function_start:function_end]
        assignment = function.index(
            "MUTATION_AMBIGUOUS=1", function.index(command_prefix)
        )
        mutated = script[: function_start + assignment] + script[
            function_start + assignment :
        ].replace("MUTATION_AMBIGUOUS=1", "MUTATION_AMBIGUOUS=0", 1)
        with pytest.raises(AssertionError):
            _assert_development_bootstrap_iam_rollback_contract(mutated)


def test_development_bootstrap_runbook_is_executable_and_fail_closed() -> None:
    script = _development_bootstrap_script()
    result = subprocess.run(
        ["bash", "-n"], input=script, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_development_bootstrap_rejects_unsafe_role_comparison_and_mixed_plan_mutations() -> (
    None
):
    script = _development_bootstrap_script()
    _assert_development_bootstrap_contract(script)
    for original, replacement in (
        ('EXPECTED_PROFILE="nova-toll-dev"', 'EXPECTED_PROFILE="nova-toll-prod"'),
        ('EXPECTED_ACCOUNT="903859731897"', 'EXPECTED_ACCOUNT="920534282028"'),
        ('REGION="us-east-1"', 'REGION="us-west-2"'),
        (
            'CANONICAL_FETCHER_SHA256="9a2e09f1c46a4ee53a6b17c09687663f41ee66de097342ad572b3c943fb704d1"',
            'CANONICAL_FETCHER_SHA256="0000000000000000000000000000000000000000000000000000000000000000"',
        ),
        ('git -C "$ROOT" fetch --no-tags origin main', "true"),
        (
            "git@github.com:rhprasad0/nova-toll-budget-agent.git",
            "git@github.com:evil/fork.git",
        ),
        ('test "$(git -C "$ROOT" rev-parse HEAD)" = "$PROTECTED_MAIN_COMMIT"', "true"),
        ('git -C "$ROOT" status --porcelain --untracked-files=all', "true"),
        (
            'PROTECTED_MAIN_COMMIT="$(git -C "$ROOT" rev-parse refs/remotes/origin/main)"',
            'PROTECTED_MAIN_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"',
        ),
        ('git -C "$ROOT" diff --quiet "$REVIEWED_COMMIT" -- "$relative"', "true"),
        ('env -i PATH="/usr/bin:/bin" LC_ALL=C "$FETCHER_BUILD"', '"$FETCHER_BUILD"'),
        ('Role.Path == "/"', 'Role.Path == "/unexpected"'),
        (".Role.MaxSessionDuration == 3600", ".Role.MaxSessionDuration == 86400"),
        (
            "PermissionsBoundary? // null) == null",
            "PermissionsBoundary? // null) == true",
        ),
        ('cmp -s "$EXPECTED_TRUST" "$ACTUAL_TRUST"', "true"),
        (
            'cmp -s "${EXPECTED_POLICIES[$policy_key]}" "${ACTUAL_POLICIES[$policy_key]}"',
            "true",
        ),
        ("urllib.parse.unquote(value)", "value"),
        ("sort_keys=True", "sort_keys=False"),
        (".PolicyNames == []", ".PolicyNames | length >= 0"),
        (".AttachedPolicies == []", ".AttachedPolicies != []"),
        (
            'ROLE_ARN="arn:aws:iam::$EXPECTED_ACCOUNT:role/$ROLE_NAME"',
            'ROLE_ARN="arn:aws:iam::920534282028:role/other"',
        ),
        (
            'aws iam list-attached-role-policies --role-name "$ROLE_NAME"',
            'aws iam list-attached-role-policies --role-name "$UNSAFE_ROLE"',
        ),
        (
            'aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}"',
            'aws iam attach-role-policy --role-name "$UNSAFE_ROLE" --policy-arn "${EXPECTED_POLICY_ARNS[$policy_key]}"',
        ),
        (".commit_sha == $commit", '.commit_sha == "untrusted"'),
        (
            'state_id_matches "$WORK_DIR/${label// /-}.state" "$identifier"',
            'state_id_matches "$WORK_DIR/${label// /-}.state" "$UNSAFE_IDENTIFIER"',
        ),
        ("SIMULATION_EXPECTED_COUNT=126", "SIMULATION_EXPECTED_COUNT=1"),
        ("evidence-binding.json", "spoofed-evidence.json"),
    ):
        must_reject(
            _assert_development_bootstrap_contract, script, original, replacement
        )

    mixed_plan = (
        script + '\nterraform -chdir="$ROOT/infra" apply "$WORK_DIR/mixed.tfplan"\n'
    )
    with pytest.raises(AssertionError):
        _assert_development_bootstrap_contract(mixed_plan)

    without_approval = script.replace('test "${BOOTSTRAP_APPROVED:-}" = YES', "true")
    with pytest.raises(AssertionError):
        _assert_development_bootstrap_contract(without_approval)


def test_development_bootstrap_canonicalizes_encoded_policy_documents_and_rejects_malformed_input() -> (
    None
):
    script = _development_bootstrap_script()
    match = re.search(
        r"canonicalize_json\(\) \{.*?python3 - \"\$input\" \"\$output\" <<'PY'\n(.*?)\nPY",
        script,
        re.DOTALL,
    )
    assert match is not None
    canonicalizer = match.group(1)
    with tempfile.TemporaryDirectory() as directory:
        raw = Path(directory) / "raw.json"
        output = Path(directory) / "canonical.json"
        raw.write_text(json.dumps("%7B%22b%22%3A2%2C%22a%22%3A1%7D"))
        result = subprocess.run(
            [sys.executable, "-c", canonicalizer, str(raw), str(output)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert output.read_text() == '{"a":1,"b":2}\n'

        raw.write_text(json.dumps("%7Bmalformed"))
        result = subprocess.run(
            [sys.executable, "-c", canonicalizer, str(raw), str(output)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0


def test_development_bootstrap_decodes_encoded_lambda_policy_response() -> None:
    script = _development_bootstrap_script()
    canonicalizer_match = re.search(
        r"(canonicalize_json\(\) \{.*?\n\})\n\ndecode_lambda_policy_response",
        script,
        re.DOTALL,
    )
    decoder_match = re.search(
        r"(decode_lambda_policy_response\(\) \{.*?\n\})\n\nROLE_ARN=",
        script,
        re.DOTALL,
    )
    assert canonicalizer_match is not None and decoder_match is not None
    helpers = canonicalizer_match.group(1) + "\n\n" + decoder_match.group(1)
    policy = {
        "Version": "2012-10-17",
        "Statement": [{"Sid": "encoded", "Effect": "Allow"}],
    }
    for encoded in (
        json.dumps(policy),
        urllib.parse.quote(json.dumps(policy), safe=""),
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "response.json"
            output = root / "decoded.json"
            raw.write_text(json.dumps({"Policy": encoded, "RevisionId": "r1"}))
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    helpers
                    + "\n"
                    + 'WORK_DIR="$1"; decode_lambda_policy_response "$2" "$3"; '
                    + 'jq -e \' .PolicyDocument.Statement[0].Sid == "encoded" \' "$3" >/dev/null',
                    "bootstrap-policy-reader",
                    str(root),
                    str(raw),
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr


def test_development_bootstrap_effective_policy_fixtures_reject_extra_inline_and_attached_policies() -> (
    None
):
    script = _development_bootstrap_script()
    policy_match = re.search(
        r'jq -e \'(\.PolicyNames == \[\])\' "\$ROLE_POLICY_NAMES"',
        script,
    )
    attachment_match = re.search(
        r'jq -e --argjson expected "\$EXPECTED_POLICY_ARNS_JSON" \'(.*?)\' "\$ROLE_ATTACHMENTS"',
        script,
    )
    assert policy_match is not None and attachment_match is not None
    policy_filter = policy_match.group(1)
    attachment_filter = attachment_match.group(1)
    expected_arns = [
        "arn:aws:iam::903859731897:policy/nova-toll/v2/development/"
        f"nova-toll-v2-development-delivery-{key}"
        for key in (
            "state",
            "compute",
            "observability",
            "storage",
            "data",
            "runtime",
            "edge",
        )
    ]

    def accepts(policy_names: list[str], attached: list[dict[str, str]]) -> bool:
        with tempfile.TemporaryDirectory() as directory:
            policy_file = Path(directory) / "policies.json"
            attachment_file = Path(directory) / "attachments.json"
            policy_file.write_text(json.dumps({"PolicyNames": policy_names}))
            attachment_file.write_text(json.dumps({"AttachedPolicies": attached}))
            policy_result = subprocess.run(
                [
                    "jq",
                    "-e",
                    policy_filter,
                    str(policy_file),
                ],
                capture_output=True,
                check=False,
            )
            attachment_result = subprocess.run(
                [
                    "jq",
                    "-e",
                    "--argjson",
                    "expected",
                    json.dumps(expected_arns),
                    attachment_filter,
                    str(attachment_file),
                ],
                capture_output=True,
                check=False,
            )
            return policy_result.returncode == 0 and attachment_result.returncode == 0

    assert accepts(
        [],
        [{"PolicyArn": arn} for arn in expected_arns],
    )
    assert not accepts(
        ["unexpected-inline"],
        [{"PolicyArn": arn} for arn in expected_arns],
    )
    assert not accepts(
        [],
        [{"PolicyArn": "arn:aws:iam::aws:policy/AdministratorAccess"}],
    )


def test_development_bootstrap_rejects_stale_packages_and_wrong_state_ids() -> None:
    script = _development_bootstrap_script()
    manifest_match = re.search(
        r"""python3 - "\$REVIEWED_V2_PACKAGE_MANIFEST" "\$REVIEWED_V2_PACKAGE_DIR" <<'PY'\n(.*?)\nPY""",
        script,
        re.DOTALL,
    )
    state_match = re.search(
        r"""state_id_matches\(\) \{\n  local state_file="\$1" expected="\$2"\n  python3 - "\$state_file" "\$expected" <<'PY'\n(.*?)\nPY""",
        script,
        re.DOTALL,
    )
    assert manifest_match is not None and state_match is not None
    validator = manifest_match.group(1)
    state_validator = state_match.group(1)
    with tempfile.TemporaryDirectory() as directory:
        package_dir = Path(directory) / "packages"
        package_dir.mkdir()
        files = {
            name: f"reviewed-{name}".encode()
            for name in (
                "loader.zip",
                "publisher.zip",
                "agentcore.zip",
                "chat-proxy.zip",
            )
        }
        for name, contents in files.items():
            (package_dir / name).write_bytes(contents)
        manifest = Path(directory) / "DEPLOYMENT_SHA256SUMS"
        manifest.write_text(
            "".join(
                f"{hashlib.sha256(contents).hexdigest()}  {name}\n"
                for name, contents in files.items()
            )
        )
        valid = subprocess.run(
            [sys.executable, "-c", validator, str(manifest), str(package_dir)],
            capture_output=True,
            check=False,
        )
        assert valid.returncode == 0, valid.stderr.decode()
        (package_dir / "loader.zip").write_bytes(b"spoofed")
        stale = subprocess.run(
            [sys.executable, "-c", validator, str(manifest), str(package_dir)],
            capture_output=True,
            check=False,
        )
        assert stale.returncode != 0

        state = Path(directory) / "state.txt"
        state.write_text('    id = "function,qualifier"\n')
        assert (
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    state_validator,
                    str(state),
                    "function,qualifier",
                ],
                check=False,
            ).returncode
            == 0
        )
        assert (
            subprocess.run(
                [sys.executable, "-c", state_validator, str(state), "wrong,qualifier"],
                check=False,
            ).returncode
            != 0
        )


def test_development_bootstrap_mocked_failures_are_approval_gated_and_reverse_ordered() -> (
    None
):
    """Exercise the bounded mutation/compensation protocol without AWS access."""
    harness = dedent(
        r"""
        set -euo pipefail
        : "${SCENARIO:?}"
        : "${LOG:?}"
        mutate() {
          test "${BOOTSTRAP_APPROVED:-}" = YES || { printf 'approval-required:%s\n' "$1" >>"$LOG"; return 77; }
          printf '%s\n' "$1" >>"$LOG"
          test "${FAIL_ACTION:-}" != "$1" || return 1
        }
        rollback_role() {
          mutate detach-role-policy || return
          mutate delete-role
        }
        rollback_url() {
          mutate remove-permission-invoke || return
          mutate remove-permission-url || return
          mutate delete-function-url
        }
        rollback_state() {
          mutate state-rm-invoke || return
          mutate state-rm-url-permission || return
          mutate state-rm-url
        }
        rollback_delivery_state() {
          mutate state-rm-attachment || return
          mutate state-rm-policy || return
          mutate state-rm-role
        }
        case "$SCENARIO" in
          create-role) mutate create-role && mutate create-policy && mutate attach-role-policy ;;
          create-policy) mutate create-role && mutate create-policy && mutate attach-role-policy ;;
          role-import|policy-import|url-import) mutate "$SCENARIO" || { rollback_state; exit 1; } ;;
          post-import-verification) mutate role-import && mutate policy-import && { rollback_delivery_state; exit 1; } ;;
          url-create) mutate create-function-url ;;
          url-permission-import|url-invoke-import)
            mutate state-rm-url || { rollback_url; exit 1; }
            mutate "$SCENARIO" || { rollback_state; rollback_url; exit 1; }
            ;;
          *) exit 2 ;;
        esac
        """
    )

    def run(
        scenario: str, *, approved: bool
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "mutations.log"
            env = os.environ.copy()
            fail_action = {"url-create": "create-function-url"}.get(scenario, scenario)
            env.update(
                {"SCENARIO": scenario, "LOG": str(log), "FAIL_ACTION": fail_action}
            )
            if approved:
                env["BOOTSTRAP_APPROVED"] = "YES"
            result = subprocess.run(
                ["bash", "-c", harness],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            return result, log.read_text().splitlines() if log.exists() else []

    for scenario in (
        "create-role",
        "create-policy",
        "role-import",
        "policy-import",
        "url-import",
        "url-create",
        "url-permission-import",
        "url-invoke-import",
        "post-import-verification",
    ):
        result, log = run(scenario, approved=False)
        assert result.returncode != 0
        first_action = {
            "create-policy": "create-role",
            "url-create": "create-function-url",
            "url-permission-import": "state-rm-url",
            "url-invoke-import": "state-rm-url",
            "post-import-verification": "role-import",
        }.get(scenario, scenario)
        assert log[0] == f"approval-required:{first_action}"
        assert all(entry.startswith("approval-required:") for entry in log)

    for scenario in (
        "create-role",
        "create-policy",
        "role-import",
        "policy-import",
        "url-import",
        "url-create",
        "url-permission-import",
        "url-invoke-import",
        "post-import-verification",
    ):
        result, log = run(scenario, approved=True)
        assert result.returncode != 0, scenario
        if scenario == "create-policy":
            assert log == ["create-role", "create-policy"]
        elif scenario == "url-create":
            assert log == ["create-function-url"]
        elif scenario in {"url-create", "url-permission-import", "url-invoke-import"}:
            assert log[-3:] == [
                "remove-permission-invoke",
                "remove-permission-url",
                "delete-function-url",
            ]
        elif scenario == "post-import-verification":
            assert log == [
                "role-import",
                "policy-import",
                "state-rm-attachment",
                "state-rm-policy",
                "state-rm-role",
            ]
        else:
            assert log[0] == scenario


def test_development_bootstrap_mocked_lock_and_import_ownership_races() -> None:
    harness = dedent(
        r"""
        set -euo pipefail
        : "${ACTION:?}" "${ROOT:?}" "${LOG:?}"
        LOCK="$ROOT/bootstrap-lock"
        LOCK_BODY="$LOCK.body"
        LOCK_ETAG="$LOCK.etag"
        LOCK_VERSION="$LOCK.version"
        log() { printf '%s\n' "$1" >>"$LOG"; }
        acquire() {
          local owner="${1:-${OWNER:-owner-a}}"
          if ! mkdir -- "$LOCK" 2>/dev/null; then
            log lock-already-held
            return 77
          fi
          printf '%s|2026-09-02T00:00:00Z' "$owner" >"$LOCK_BODY"
          printf '%s-etag' "$owner" >"$LOCK_ETAG"
          printf '%s-version' "$owner" >"$LOCK_VERSION"
          log lock-acquired
          if test "${AMBIGUOUS:-0}" -eq 1; then
            log lock-ambiguous
            return 1
          fi
        }
        release_observed() {
          local observed_etag="$1" observed_version="$2" current_etag current_version
          current_etag="$(<"$LOCK_ETAG")" || { log lock-read-failed; return 1; }
          current_version="$(<"$LOCK_VERSION")" || { log lock-read-failed; return 1; }
          test "$current_etag" = "$observed_etag" &&
            test "$current_version" = "$observed_version" || {
              log stale-etag-preserved
              return 1
            }
          rmdir -- "$LOCK"
          rm -- "$LOCK_BODY" "$LOCK_ETAG" "$LOCK_VERSION"
          test ! -e "$LOCK"
          log lock-released
        }
        import_state() {
          if test -e "$ROOT/state"; then
            log state-preexisting
            return 0
          fi
          case "${IMPORT_RESULT:-success}" in
            already-managed|failed)
              printf '%s' target >"$ROOT/state"
              log "import-${IMPORT_RESULT}-retained"
              return 1
              ;;
            success)
              printf '%s' target >"$ROOT/state"
              OWNED=1
              log import-success-owned
              ;;
          esac
        }
        rollback_state() {
          test "${OWNED:-0}" -eq 1 || return 0
          test "$(<"$ROOT/state")" = target || { log state-id-mismatch-preserved; return 1; }
          rm -- "$ROOT/state"
          log state-rm-owned
        }
        case "$ACTION" in
          acquire) acquire ;;
          acquire-ambiguous) AMBIGUOUS=1 acquire || true; test -d "$LOCK"; log ambiguous-lock-retained ;;
          release) acquire; release_observed "${OWNER:-owner-a}-etag" "${OWNER:-owner-a}-version" ;;
          wrong-owner) acquire owner-a; release_observed owner-b-etag owner-b-version ;;
          stale-reacquire)
            acquire owner-a
            OLD_ETAG=owner-a-etag
            OLD_VERSION=owner-a-version
            rmdir -- "$LOCK"
            rm -- "$LOCK_BODY" "$LOCK_ETAG" "$LOCK_VERSION"
            acquire owner-b
            release_observed "$OLD_ETAG" "$OLD_VERSION" || true
            test -d "$LOCK"
            log stale-owner-cannot-delete-new-lock
            release_observed owner-b-etag owner-b-version
            ;;
          stale) test -e "$LOCK"; log stale-lock-stop ;;
          import) import_state ;;
          import-and-verify-fail) import_state; rollback_state ;;
          *) exit 2 ;;
        esac
        """
    )

    def run_lock(
        action: str, directory: Path, owner: str = "owner-a"
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        log = directory / f"{action}-{owner}.log"
        env = os.environ.copy()
        env.update(
            {"ACTION": action, "ROOT": str(directory), "LOG": str(log), "OWNER": owner}
        )
        result = subprocess.run(
            ["bash", "-c", harness],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        return result, log.read_text().splitlines() if log.exists() else []

    with tempfile.TemporaryDirectory() as directory_name:
        directory = Path(directory_name)
        first = subprocess.Popen(
            ["bash", "-c", harness],
            env={
                **os.environ,
                "ACTION": "acquire",
                "ROOT": str(directory),
                "LOG": str(directory / "a.log"),
                "OWNER": "owner-a",
            },
            text=True,
        )
        second = subprocess.Popen(
            ["bash", "-c", harness],
            env={
                **os.environ,
                "ACTION": "acquire",
                "ROOT": str(directory),
                "LOG": str(directory / "b.log"),
                "OWNER": "owner-b",
            },
            text=True,
        )
        assert sorted((first.wait(), second.wait())) == [0, 77]
        logs = (directory / "a.log").read_text() + (directory / "b.log").read_text()
        assert logs.count("lock-acquired") == 1
        assert logs.count("lock-already-held") == 1
        (directory / "a.log").unlink(missing_ok=True)
        (directory / "b.log").unlink(missing_ok=True)

        result, log = run_lock("acquire-ambiguous", directory)
        assert result.returncode == 0 and "ambiguous-lock-retained" in log
        result, log = run_lock("stale", directory, owner="owner-b")
        assert result.returncode == 0 and log == ["stale-lock-stop"]
        (directory / "bootstrap-lock").rmdir()
        for suffix in ("body", "etag", "version"):
            (directory / f"bootstrap-lock.{suffix}").unlink()

        result, log = run_lock("release", directory)
        assert result.returncode == 0 and log == ["lock-acquired", "lock-released"]
        result, log = run_lock("wrong-owner", directory, owner="owner-b")
        assert result.returncode != 0 and log == [
            "lock-acquired",
            "stale-etag-preserved",
        ]
        (directory / "bootstrap-lock").rmdir()
        for suffix in ("body", "etag", "version"):
            (directory / f"bootstrap-lock.{suffix}").unlink()

        result, log = run_lock("stale-reacquire", directory)
        assert result.returncode == 0
        assert log == [
            "lock-acquired",
            "lock-acquired",
            "stale-etag-preserved",
            "stale-owner-cannot-delete-new-lock",
            "lock-released",
        ]
        assert not (directory / "bootstrap-lock").exists()

        for import_result, expected in (
            ("already-managed", ["import-already-managed-retained"]),
            (
                "failed",
                ["import-failed-retained"],
            ),
        ):
            (directory / "import.log").unlink(missing_ok=True)
            env = {
                **os.environ,
                "ACTION": "import",
                "ROOT": str(directory),
                "LOG": str(directory / "import.log"),
                "IMPORT_RESULT": import_result,
            }
            result = subprocess.run(
                ["bash", "-c", harness],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            assert result.returncode != 0
            assert (directory / "import.log").read_text().splitlines() == expected
            assert not (directory / "import.log").read_text().count("state-rm")
            (directory / "state").unlink()

        env = {
            **os.environ,
            "ACTION": "import-and-verify-fail",
            "ROOT": str(directory),
            "LOG": str(directory / "import-own.log"),
        }
        result = subprocess.run(
            ["bash", "-c", harness],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0
        assert (directory / "import-own.log").read_text().splitlines() == [
            "import-success-owned",
            "state-rm-owned",
        ]
        assert not (directory / "state").exists()


def test_development_bootstrap_state_membership_is_pipefail_safe_for_large_lists() -> (
    None
):
    harness = dedent(
        r"""
        set -euo pipefail
        : "${ROOT:?}" "${LOG:?}"
        STATE_LIST="$ROOT/state.list"
        emit_state_list() {
          printf '%s\n' aws_preexisting.resource
          for index in $(seq 1 2048); do
            printf 'aws_padding.resource[%s]\n' "$index"
          done
          printf '%s\n' aws_owned.resource
        }
        state_list_contains() {
          local state_file="$1" address="$2"
          awk -v address="$address" '$0 == address { found=1 } END { exit found ? 0 : 1 }' "$state_file"
        }
        emit_state_list >"$STATE_LIST"
        state_list_contains "$STATE_LIST" aws_preexisting.resource
        state_list_contains "$STATE_LIST" aws_owned.resource
        if state_list_contains "$STATE_LIST" aws_missing.resource; then exit 1; fi
        rollback() {
          local address
          for address in aws_preexisting.resource aws_owned.resource aws_missing.resource; do
            state_list_contains "$STATE_LIST" "$address" || continue
            case "$address" in
              aws_preexisting.resource) printf '%s\n' preexisting-preserved >>"$LOG" ;;
              aws_owned.resource) printf '%s\n' owned-rollback >>"$LOG" ;;
            esac
          done
        }
        rollback
        test "$(wc -l <"$STATE_LIST")" -eq 2050
        """
    )
    with tempfile.TemporaryDirectory() as directory_name:
        directory = Path(directory_name)
        log = directory / "events.log"
        result = subprocess.run(
            ["bash", "-c", harness],
            env={**os.environ, "ROOT": str(directory), "LOG": str(log)},
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert log.read_text().splitlines() == [
            "preexisting-preserved",
            "owned-rollback",
        ]


def test_development_bootstrap_mocked_lambda_permission_ownership_races() -> None:
    harness = dedent(
        r"""
        set -euo pipefail
        : "${SCENARIO:?}" "${ROOT:?}" "${LOG:?}"
        SID="${SID:-AllowCloudFrontFunctionUrlV2}"
        EXPECTED="reviewed:$SID"
        POLICY="$ROOT/policy"
        log() { printf '%s\n' "$1" >>"$LOG"; }
        snapshot() {
          if test -e "$POLICY"; then PRE_PRESENT=1; PRE_CONTENT="$(<"$POLICY")"; else PRE_PRESENT=0; PRE_CONTENT=; fi
          PRE_REVISION="${REVISION:-rev-1}"
          log snapshot
        }
        add_permission() {
          case "$SCENARIO" in
            success) printf '%s' "$EXPECTED" >"$POLICY"; REVISION=rev-2; return 0 ;;
            ambiguous-applied) printf '%s' "$EXPECTED" >"$POLICY"; REVISION=rev-2; return 1 ;;
            ambiguous-mismatch) printf '%s' foreign >"$POLICY"; REVISION=rev-2; return 1 ;;
            ambiguous-stale-revision) printf '%s' "$EXPECTED" >"$POLICY"; REVISION=rev-1; return 1 ;;
            ambiguous-not-applied) return 1 ;;
            preexisting) return 1 ;;
          esac
        }
        reconcile() {
          test "${PRE_PRESENT:-0}" -eq 0 || return 1
          test -e "$POLICY" && test "$(<"$POLICY")" = "$EXPECTED" || return 1
          test "${PRE_REVISION:-}" = "${REVISION:-}" && return 1
          OWNED=1
          log permission-owned
        }
        rollback() {
          test "${OWNED:-0}" -eq 1 || return 0
          test "$(<"$POLICY")" = "$EXPECTED" || { log foreign-preserved; return 1; }
          rm -- "$POLICY"
          test "${PRE_PRESENT:-0}" -eq 0
          log permission-removed-owned
        }
        snapshot
        if test "${SCENARIO}" = preexisting; then
          log preexisting-preserved
          exit 0
        fi
        if add_permission; then
          reconcile
          rollback
        else
          log ambiguous-preserved
        fi
        """
    )

    for sid in ("AllowCloudFrontFunctionUrlV2", "AllowCloudFrontFunctionInvokeV2"):
        for scenario in (
            "success",
            "ambiguous-applied",
            "ambiguous-not-applied",
            "preexisting",
            "ambiguous-mismatch",
            "ambiguous-stale-revision",
        ):
            with tempfile.TemporaryDirectory() as directory_name:
                directory = Path(directory_name)
                if scenario == "preexisting":
                    (directory / "policy").write_text(f"reviewed:{sid}")
                log_path = directory / "events.log"
                env = {
                    **os.environ,
                    "SCENARIO": scenario,
                    "SID": sid,
                    "ROOT": str(directory),
                    "LOG": str(log_path),
                }
                result = subprocess.run(
                    ["bash", "-c", harness],
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                assert result.returncode == 0, result.stderr
                events = log_path.read_text().splitlines()
                if scenario == "success":
                    assert events == [
                        "snapshot",
                        "permission-owned",
                        "permission-removed-owned",
                    ]
                    assert not (directory / "policy").exists()
                elif scenario == "ambiguous-applied":
                    assert events == ["snapshot", "ambiguous-preserved"]
                    assert (directory / "policy").read_text() == f"reviewed:{sid}"
                elif scenario == "ambiguous-not-applied":
                    assert events == ["snapshot", "ambiguous-preserved"]
                    assert not (directory / "policy").exists()
                elif scenario == "preexisting":
                    assert events == ["snapshot", "preexisting-preserved"]
                    assert (directory / "policy").read_text() == f"reviewed:{sid}"
                else:
                    assert events == ["snapshot", "ambiguous-preserved"]
                    assert (directory / "policy").read_text() in {
                        "foreign",
                        f"reviewed:{sid}",
                    }


def test_development_bootstrap_stale_prelock_snapshot_never_deletes_prior_run_resources() -> (
    None
):
    harness = dedent(
        r"""
        set -euo pipefail
        : "${ACTION:?}" "${ROOT:?}" "${LOG:?}" "${OWNER:?}"
        LOCK="$ROOT/bootstrap-lock"
        VALUE="$OWNER|2026-09-02T00:00:00Z"
        log() { printf '%s\n' "$1" >>"$LOG"; }
        acquire() {
          if ! (set -o noclobber; printf '%s' "$VALUE" >"$LOCK") 2>/dev/null; then
            log lock-held
            return 77
          fi
          log lock-acquired
        }
        case "$ACTION" in
          run-a)
            acquire
            printf '%s\n' reviewed-url >"$ROOT/url"
            printf '%s\n' reviewed-permissions >"$ROOT/permissions"
            log run-a-created-url-and-permissions
            exit 42
            ;;
          run-b)
            # These are deliberately stale observations made before B can own the lock.
            PRE_URL=0
            PRE_PERMISSIONS=0
            log run-b-prelock-snapshot-absent
            if acquire; then exit 9; fi
            test "$PRE_URL" -eq 0
            test "$PRE_PERMISSIONS" -eq 0
            test "$(<"$ROOT/url")" = reviewed-url
            test "$(<"$ROOT/permissions")" = reviewed-permissions
            log run-b-stopped-before-postlock-mutation
            ;;
          *) exit 2 ;;
        esac
        """
    )
    with tempfile.TemporaryDirectory() as directory_name:
        directory = Path(directory_name)
        first_log = directory / "run-a.log"
        first = subprocess.run(
            ["bash", "-c", harness],
            env={
                **os.environ,
                "ACTION": "run-a",
                "ROOT": str(directory),
                "LOG": str(first_log),
                "OWNER": "owner-a",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert first.returncode == 42
        second_log = directory / "run-b.log"
        second = subprocess.run(
            ["bash", "-c", harness],
            env={
                **os.environ,
                "ACTION": "run-b",
                "ROOT": str(directory),
                "LOG": str(second_log),
                "OWNER": "owner-b",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert second.returncode == 0, second.stderr
        assert second_log.read_text().splitlines() == [
            "run-b-prelock-snapshot-absent",
            "lock-held",
            "run-b-stopped-before-postlock-mutation",
        ]
        assert (directory / "url").read_text().strip() == "reviewed-url"
        assert (directory / "permissions").read_text().strip() == "reviewed-permissions"


def test_development_bootstrap_mocked_region_lock_and_rollback_guards() -> None:
    harness = dedent(
        r"""
        set -euo pipefail
        : "${SCENARIO:?}" "${ROOT:?}" "${LOG:?}"
        REGION=us-east-1
        LOCK_ETAG=owner-etag
        CURRENT_ETAG="$ROOT/lock.etag"
        URL="$ROOT/url"
        log() { printf '%s\n' "$1" >>"$LOG"; }
        region_guard() {
          if test -n "${AWS_REGION:-}" && test -n "${AWS_DEFAULT_REGION:-}" &&
            test "$AWS_REGION" != "$AWS_DEFAULT_REGION"; then
            log region-conflict
            return 1
          fi
          if test -n "${AWS_REGION:-}" && test "$AWS_REGION" != "$REGION"; then
            log region-rejected
            return 1
          fi
          if test -n "${AWS_DEFAULT_REGION:-}" && test "$AWS_DEFAULT_REGION" != "$REGION"; then
            log region-rejected
            return 1
          fi
          export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
        }
        lock_is_current() { test "$(<"$CURRENT_ETAG")" = "$LOCK_ETAG"; }
        validate_function_url() { test "$(<"$URL")" = reviewed-url; }
        rollback_url() {
          lock_is_current || { log lock-lost-preserved; return 1; }
          validate_function_url || { log url-changed-preserved; return 1; }
          rm -- "$URL"
          log url-removed
        }
        rollback_imports() {
          if test "${ROLE_IMPORTED:-0}" -eq 1; then rm -- "$ROOT/role-state"; log role-state-rm; fi
          if test "${POLICY_IMPORTED:-0}" -eq 1; then rm -- "$ROOT/policy-state"; log policy-state-rm; fi
        }
        release_observed() {
          local observed="$1"
          test "$(<"$CURRENT_ETAG")" = "$observed" || { log stale-etag-preserved; return 1; }
          rm -- "$CURRENT_ETAG"
          log lock-released
        }
        printf '%s\n' owner-etag >"$CURRENT_ETAG"
        printf '%s\n' reviewed-url >"$URL"
        case "$SCENARIO" in
          region-conflict) region_guard || true ;;
          lost-lock)
            region_guard
            printf '%s\n' replacement-etag >"$CURRENT_ETAG"
            rollback_url || true
            test -e "$URL"
            ;;
          url-changed)
            region_guard
            printf '%s\n' changed-url >"$URL"
            rollback_url || true
            test -e "$URL"
            ;;
          early-import-verification)
            region_guard
            printf '%s\n' role >"$ROOT/role-state"
            ROLE_IMPORTED=1
            printf '%s\n' wrong-id >"$ROOT/role-verification"
            if test "$(<"$ROOT/role-verification")" = expected-id; then exit 9; fi
            rollback_imports
            test ! -e "$ROOT/role-state"
            test ! -e "$ROOT/policy-state"
            ;;
          stale-etag)
            region_guard
            release_observed old-etag || true
            test -e "$CURRENT_ETAG"
            ;;
          early-post-lock)
            region_guard
            MUTATION_AMBIGUOUS=0
            LOCK_ACQUIRED=1
            bootstrap_cleanup() {
              local status=$?
              trap - EXIT
              if test "$status" -ne 0 && test "$MUTATION_AMBIGUOUS" -eq 0; then
                declare -F rollback_delivery_state >/dev/null && rollback_delivery_state || true
              fi
              log lock-released
              exit "$status"
            }
            trap bootstrap_cleanup EXIT
            exit 1
            ;;
          *) exit 2 ;;
        esac
        """
    )
    scenarios = {
        "region-conflict": (
            {"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-west-2"},
            ["region-conflict"],
            0,
        ),
        "lost-lock": (
            {"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-east-1"},
            ["lock-lost-preserved"],
            0,
        ),
        "url-changed": (
            {"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-east-1"},
            ["url-changed-preserved"],
            0,
        ),
        "early-import-verification": (
            {"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-east-1"},
            ["role-state-rm"],
            0,
        ),
        "stale-etag": (
            {"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-east-1"},
            ["stale-etag-preserved"],
            0,
        ),
        "early-post-lock": (
            {"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "us-east-1"},
            ["lock-released"],
            1,
        ),
    }
    for scenario, (
        region_environment,
        expected_events,
        expected_returncode,
    ) in scenarios.items():
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            log_path = directory / "events.log"
            environment = {
                **os.environ,
                "SCENARIO": scenario,
                "ROOT": str(directory),
                "LOG": str(log_path),
                **region_environment,
            }
            result = subprocess.run(
                ["bash", "-c", harness],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            assert result.returncode == expected_returncode, result.stderr
            assert log_path.read_text().splitlines() == expected_events


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
        "tailscale/github-action@780049a30b6ff5c378a9e7b389d15ece7a204888"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert (
        "aws-actions/configure-aws-credentials@e1253824e5c10ff9df46874f81ed3ec929e19cfd"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert (
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
        in DEVELOPMENT_MIGRATIONS_WORKFLOW
    )
    assert (
        "e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
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
        "##### Protected development migration workflow (#305 slice 3)", 1
    )[1]
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
        "authorized from this graph run",
    ):
        assert required in section
