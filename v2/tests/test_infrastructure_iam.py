import hashlib
import json
import os
import re
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from textwrap import dedent
from typing import cast

import pytest

from tests.infrastructure_support import (
    DEPLOYMENT,
    DEVELOPMENT_CONNECTIVITY_WORKFLOW,
    FOUNDATION_IAM,
    FOUNDATION_ROOT,
    FOUNDATION_TAILSCALE,
    MAIN_TF,
    MEASUREMENT_INFRA,
    SLICE_2A_POLICY,
    TIMED_CHECKS_TF,
    V2_ROOT,
    hcl_attribute,
    hcl_named_blocks,
    hcl_scalar,
    hcl_strings,
    must_reject,
    must_reject_after_marker,
    parsed_policy_document,
    parsed_policy_tuple_map,
    policy_by_sid,
    terraform_block,
    top_level_terraform_block,
)


@pytest.fixture(scope="module")
def rendered_development_delivery_policies() -> tuple[
    dict[str, dict[str, object]], list[dict[str, object]], dict[str, object]
]:
    """Render the policy locals in a backend-free, credential-free Terraform root."""
    first_locals = top_level_terraform_block(FOUNDATION_IAM, "locals", 0)
    first_locals += "\nlocals { green_trace_log_arns = [] }\n"
    policy_locals = top_level_terraform_block(FOUNDATION_IAM, "locals", 1)
    policy_data = top_level_terraform_block(
        FOUNDATION_IAM,
        'data "aws_iam_policy_document" "development_delivery"',
    )
    foundation_data = "\n".join(
        top_level_terraform_block(
            FOUNDATION_IAM, f'data "aws_iam_policy_document" "{name}"'
        )
        for name in (
            "development_agentcore_trace_logs_assume",
            "development_agentcore_trace_logs",
            "development_agentcore_trace_firehose_assume",
            "development_agentcore_trace_firehose",
        )
    )
    policy_data = (
        policy_data.replace(
            "aws_s3_bucket.tfstate.arn", "local.test_tfstate_bucket_arn"
        )
        .replace("aws_kms_key.tfstate.arn", "local.test_tfstate_kms_key_arn")
        .replace("aws_kms_key.alerts.arn", "local.test_alerts_kms_key_arn")
    )
    telemetry_locals = (
        top_level_terraform_block(
            (FOUNDATION_ROOT / "telemetry.tf").read_text(), "locals", 0
        )
        + '\nlocals {\n production_delivery_account_id = "920534282028"\n production_delivery_application_policy_json = jsonencode({Statement = []})\n development_delivery_trace_statement_sids = []\n}\n'
    )
    configuration = dedent(
        f"""
        terraform {{
          required_providers {{
            aws = {{
              source  = "hashicorp/aws"
              version = "~> 6.47"
            }}
          }}
        }}

        variable "environment" {{
          type    = string
          default = "development"
        }}

        provider "aws" {{
          region                         = "us-east-1"
          access_key                     = "test"
          secret_key                     = "test"
          skip_credentials_validation   = true
          skip_requesting_account_id    = true
          skip_metadata_api_check       = true
        }}

        locals {{
          test_tfstate_bucket_arn = "arn:aws:s3:::nova-toll-tfstate-903859731897"
          test_tfstate_kms_key_arn = "arn:aws:kms:us-east-1:903859731897:key/00000000-0000-0000-0000-000000000000"
          test_alerts_kms_key_arn = "arn:aws:kms:us-east-1:903859731897:key/11111111-1111-1111-1111-111111111111"
        }}

        {first_locals}
        {telemetry_locals}
        {policy_data}
        {foundation_data}
        {policy_locals}

        output "development_delivery_policy_documents" {{
          value = local.development_delivery_policy_documents
        }}

        output "development_delivery_aggregate" {{
          value = data.aws_iam_policy_document.development_delivery.json
        }}

        output "development_agentcore_trace_foundation_documents" {{
          value = {{
            logs_assume     = data.aws_iam_policy_document.development_agentcore_trace_logs_assume[0].json
            logs            = data.aws_iam_policy_document.development_agentcore_trace_logs[0].json
            firehose_assume = data.aws_iam_policy_document.development_agentcore_trace_firehose_assume[0].json
            firehose        = data.aws_iam_policy_document.development_agentcore_trace_firehose[0].json
          }}
        }}
        """
    )
    with tempfile.TemporaryDirectory(prefix="nova-toll-iam-render-") as directory:
        root = Path(directory)
        (root / "main.tf").write_text(configuration, encoding="utf-8")
        # Only AWS is required here; unrelated entries make readonly init fail.
        (root / ".terraform.lock.hcl").write_text(
            top_level_terraform_block(
                (FOUNDATION_ROOT / ".terraform.lock.hcl").read_text(),
                'provider "registry.terraform.io/hashicorp/aws"',
            )
            + "\n",
            encoding="utf-8",
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("AWS_")
        }
        assert not any(key.startswith("AWS_") for key in environment)
        environment["HOME"] = str(root)
        environment["TF_DATA_DIR"] = str(root / ".terraform-data")
        provider_mirror = FOUNDATION_ROOT / ".terraform" / "providers"
        if provider_mirror.is_dir():
            # Installed providers may link into the cache; never cache a mirror into itself.
            environment.pop("TF_PLUGIN_CACHE_DIR", None)
            cli_config = root / "terraform.tfrc"
            cli_config.write_text(
                dedent(
                    f"""
                    provider_installation {{
                      filesystem_mirror {{
                        path = {json.dumps(str(provider_mirror))}
                      }}
                      direct {{
                        exclude = ["hashicorp/aws"]
                      }}
                    }}
                    """
                ),
                encoding="utf-8",
            )
            environment["TF_CLI_CONFIG_FILE"] = str(cli_config)
        init = subprocess.run(
            [
                "terraform",
                "init",
                "-backend=false",
                "-input=false",
                "-no-color",
                "-lockfile=readonly",
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert init.returncode == 0, init.stdout + init.stderr
        plan_path = root / "development-delivery.tfplan"
        plan = subprocess.run(
            [
                "terraform",
                "plan",
                "-refresh=false",
                "-input=false",
                "-no-color",
                f"-out={plan_path}",
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert plan.returncode == 0, plan.stdout + plan.stderr
        rendered = subprocess.run(
            ["terraform", "show", "-json", str(plan_path)],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr
        values = json.loads(rendered.stdout)["planned_values"]["outputs"]
        documents = values["development_delivery_policy_documents"]["value"]
        aggregate = values["development_delivery_aggregate"]["value"]
        foundation = values["development_agentcore_trace_foundation_documents"]["value"]
        assert isinstance(documents, dict)
        assert isinstance(aggregate, str)
        return (
            {
                key: json.loads(value)
                for key, value in cast(dict[str, str], documents).items()
            },
            cast(list[dict[str, object]], json.loads(aggregate)["Statement"]),
            {
                key: json.loads(value)
                for key, value in cast(dict[str, str], foundation).items()
            },
        )


def _terraform_rendered_development_plan_policies() -> tuple[
    dict[str, dict[str, object]], list[dict[str, object]]
]:
    """Render the development plan policies in a backend-free Terraform root."""
    first_locals = top_level_terraform_block(FOUNDATION_IAM, "locals", 0)
    first_locals += "\nlocals { green_trace_log_arns = [] }\n"
    policy_data = top_level_terraform_block(
        FOUNDATION_IAM,
        'data "aws_iam_policy_document" "development_plan"',
    )
    plan_locals = next(
        top_level_terraform_block(FOUNDATION_IAM, "locals", occurrence)
        for occurrence in range(5)
        if "development_plan_policy_documents"
        in top_level_terraform_block(FOUNDATION_IAM, "locals", occurrence)
    )
    policy_data = (
        policy_data.replace(
            "aws_s3_bucket.tfstate.arn", "local.test_tfstate_bucket_arn"
        )
        .replace("aws_kms_key.tfstate.arn", "local.test_tfstate_kms_key_arn")
        .replace("aws_kms_key.alerts.arn", "local.test_alerts_kms_key_arn")
    )
    telemetry_locals = (
        top_level_terraform_block(
            (FOUNDATION_ROOT / "telemetry.tf").read_text(), "locals", 0
        )
        + '\nlocals {\n production_delivery_account_id = "920534282028"\n production_delivery_application_policy_json = jsonencode({Statement = []})\n development_delivery_trace_statement_sids = []\n}\n'
    )
    configuration = dedent(
        f"""
        terraform {{
          required_providers {{
            aws = {{
              source  = "hashicorp/aws"
              version = "~> 6.47"
            }}
          }}
        }}

        variable "environment" {{
          type    = string
          default = "development"
        }}

        provider "aws" {{
          region                       = "us-east-1"
          access_key                   = "test"
          secret_key                   = "test"
          skip_credentials_validation = true
          skip_requesting_account_id  = true
          skip_metadata_api_check     = true
        }}

        locals {{
          test_tfstate_bucket_arn = "arn:aws:s3:::nova-toll-tfstate-903859731897"
          test_tfstate_kms_key_arn = "arn:aws:kms:us-east-1:903859731897:key/00000000-0000-0000-0000-000000000000"
          test_alerts_kms_key_arn = "arn:aws:kms:us-east-1:903859731897:key/11111111-1111-1111-1111-111111111111"
        }}

        {first_locals}
        {telemetry_locals}
        {policy_data}
        {plan_locals}

        output "development_plan_policy_documents" {{
          value = local.development_plan_policy_documents
        }}

        output "development_plan_aggregate" {{
          value = data.aws_iam_policy_document.development_plan.json
        }}
        """
    )
    with tempfile.TemporaryDirectory(prefix="nova-toll-iam-plan-render-") as directory:
        root = Path(directory)
        (root / "main.tf").write_text(configuration, encoding="utf-8")
        # Only AWS is required here; unrelated entries make readonly init fail.
        (root / ".terraform.lock.hcl").write_text(
            top_level_terraform_block(
                (FOUNDATION_ROOT / ".terraform.lock.hcl").read_text(),
                'provider "registry.terraform.io/hashicorp/aws"',
            )
            + "\n",
            encoding="utf-8",
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("AWS_")
        }
        environment["HOME"] = str(root)
        environment["TF_DATA_DIR"] = str(root / ".terraform-data")
        provider_mirror = FOUNDATION_ROOT / ".terraform" / "providers"
        if provider_mirror.is_dir():
            environment.pop("TF_PLUGIN_CACHE_DIR", None)
            cli_config = root / "terraform.tfrc"
            cli_config.write_text(
                dedent(
                    f"""
                    provider_installation {{
                      filesystem_mirror {{
                        path = {json.dumps(str(provider_mirror))}
                      }}
                      direct {{
                        exclude = ["hashicorp/aws"]
                      }}
                    }}
                    """
                ),
                encoding="utf-8",
            )
            environment["TF_CLI_CONFIG_FILE"] = str(cli_config)
        init = subprocess.run(
            [
                "terraform",
                "init",
                "-backend=false",
                "-input=false",
                "-no-color",
                "-lockfile=readonly",
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert init.returncode == 0, init.stdout + init.stderr
        plan_path = root / "development-plan.tfplan"
        plan = subprocess.run(
            [
                "terraform",
                "plan",
                "-refresh=false",
                "-input=false",
                "-no-color",
                f"-out={plan_path}",
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert plan.returncode == 0, plan.stdout + plan.stderr
        rendered = subprocess.run(
            ["terraform", "show", "-json", str(plan_path)],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr
        outputs = json.loads(rendered.stdout)["planned_values"]["outputs"]
        documents = outputs["development_plan_policy_documents"]["value"]
        aggregate = outputs["development_plan_aggregate"]["value"]
        return (
            {
                key: json.loads(value)
                for key, value in cast(dict[str, str], documents).items()
            },
            cast(list[dict[str, object]], json.loads(aggregate)["Statement"]),
        )


def test_iam_provider_lock_rejects_unverified_mirror_bytes(tmp_path: Path) -> None:
    lock = (
        top_level_terraform_block(
            (FOUNDATION_ROOT / ".terraform.lock.hcl").read_text(),
            'provider "registry.terraform.io/hashicorp/aws"',
        )
        + "\n"
    )
    version = re.search(r'version\s*=\s*"([^"]+)"', lock)
    assert version
    platform = json.loads(subprocess.check_output(["terraform", "version", "-json"]))[
        "platform"
    ]
    provider = (
        tmp_path / "mirror/registry.terraform.io/hashicorp/aws" / version[1] / platform
    )
    provider.mkdir(parents=True)
    (provider / f"terraform-provider-aws_v{version[1]}").write_text(
        "unverified provider bytes"
    )
    (tmp_path / ".terraform.lock.hcl").write_text(lock)
    (tmp_path / "main.tf").write_text(
        'terraform {\n required_providers {\n aws = { source = "hashicorp/aws" }\n }\n }\n'
    )
    config = tmp_path / "terraform.tfrc"
    config.write_text(
        "provider_installation {\n filesystem_mirror {\n path = "
        + json.dumps(str(tmp_path / "mirror"))
        + "\n }\n }\n"
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("AWS_", "TF_"))
    }
    environment.update(
        HOME=str(tmp_path),
        TF_CLI_CONFIG_FILE=str(config),
        TF_DATA_DIR=str(tmp_path / "data"),
    )
    result = subprocess.run(
        [
            "terraform",
            "init",
            "-backend=false",
            "-input=false",
            "-lockfile=readonly",
            "-no-color",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "checksum" in result.stderr.lower()
    assert (tmp_path / ".terraform.lock.hcl").read_text() == lock


def _assert_development_delivery_trust(source: str) -> None:
    trust = parsed_policy_document(source, "development_delivery_assume")
    assert len(trust) == 1
    statement = trust[0]
    assert statement["actions"] == ["sts:AssumeRoleWithWebIdentity"]
    principal_blocks = hcl_named_blocks(
        terraform_block(
            source, 'data "aws_iam_policy_document" "development_delivery_assume"'
        ),
        "principals",
    )
    assert len(principal_blocks) == 1
    assert hcl_scalar(principal_blocks[0], "type") == "Federated"
    assert hcl_attribute(principal_blocks[0], "identifiers") == (
        "aws_iam_openid_connect_provider.github.arn"
    )
    assert statement["conditions"] == [
        {
            "test": "StringEquals",
            "variable": "token.actions.githubusercontent.com:aud",
            "values": ["sts.amazonaws.com"],
        },
        {
            "test": "StringEquals",
            "variable": "token.actions.githubusercontent.com:sub",
            "values": [
                "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"
            ],
        },
        {
            "test": "StringEquals",
            "variable": "token.actions.githubusercontent.com:ref",
            "values": ["refs/heads/main"],
        },
        {
            "test": "StringEquals",
            "variable": "token.actions.githubusercontent.com:job_workflow_ref",
            "values": [
                "rhprasad0/nova-toll-budget-agent/.github/workflows/v2-development-delivery-privileged.yml@refs/heads/main"
            ],
        },
    ]


def _assert_development_delivery_state_and_application_policy(source: str) -> None:
    delivery_role = terraform_block(
        source, 'resource "aws_iam_role" "development_delivery"'
    )
    assert re.search(r"(?m)^\s*max_session_duration\s*=\s*3600\s*$", delivery_role)
    statements = parsed_policy_document(source, "development_delivery")
    by_sid = policy_by_sid(statements)
    assert {
        "ListDevelopmentState",
        "ReadDevelopmentFoundationState",
        "ManageDevelopmentApplicationState",
        "ManageDevelopmentApplicationLock",
        "DecryptDevelopmentState",
        "WriteDevelopmentStateDataKeys",
    } <= by_sid.keys()
    assert by_sid["ListDevelopmentState"]["actions"] == ["s3:ListBucket"]
    assert by_sid["ListDevelopmentState"]["resources"] == ["aws_s3_bucket.tfstate.arn"]
    assert by_sid["ListDevelopmentState"]["conditions"] == [
        {
            "test": "StringEquals",
            "variable": "s3:prefix",
            "values": [
                "nova-toll/development/terraform.tfstate",
                "nova-toll/v2/development/terraform.tfstate",
            ],
        }
    ]
    assert by_sid["ReadDevelopmentFoundationState"]["actions"] == ["s3:GetObject"]
    assert by_sid["ReadDevelopmentFoundationState"]["resources"] == [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/development/terraform.tfstate"
    ]
    assert by_sid["ManageDevelopmentApplicationState"]["actions"] == [
        "s3:GetObject",
        "s3:PutObject",
    ]
    assert by_sid["ManageDevelopmentApplicationState"]["resources"] == [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate"
    ]
    assert by_sid["ManageDevelopmentApplicationLock"]["actions"] == [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
    ]
    assert by_sid["ManageDevelopmentApplicationLock"]["resources"] == [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate.tflock"
    ]
    assert by_sid["DecryptDevelopmentState"]["actions"] == ["kms:Decrypt"]
    assert by_sid["WriteDevelopmentStateDataKeys"]["actions"] == ["kms:GenerateDataKey"]
    assert by_sid["PassTimedChecksSchedulerRole"]["actions"] == ["iam:PassRole"]
    assert by_sid["PassTimedChecksSchedulerRole"]["resources"] == [
        "arn:aws:iam::${local.development_delivery_account_id}:role/nova-toll-v2-timed-checks-scheduler-dev"
    ]
    assert by_sid["PassTimedChecksSchedulerRole"]["conditions"] == [
        {
            "test": "StringEquals",
            "variable": "iam:PassedToService",
            "values": ["scheduler.amazonaws.com"],
        }
    ]
    for sid in ("DecryptDevelopmentState", "WriteDevelopmentStateDataKeys"):
        assert by_sid[sid]["resources"] == ["aws_kms_key.tfstate.arn"]
        conditions = cast(list[dict[str, object]], by_sid[sid]["conditions"])
        assert conditions[0]["variable"] == "kms:EncryptionContext:aws:s3:arn"
    write_state_conditions = cast(
        list[dict[str, object]], by_sid["WriteDevelopmentStateDataKeys"]["conditions"]
    )
    assert write_state_conditions[0]["values"] == [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate",
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate.tflock",
    ]

    all_actions = [
        action
        for statement in statements
        for action in cast(list[str], statement["actions"])
    ]
    assert all("*" not in action for action in all_actions)
    assert not any(
        action.startswith(("sts:", "organizations:")) for action in all_actions
    )
    assert not any(
        action.startswith("iam:") and action.endswith(":*") for action in all_actions
    )
    assert not {
        "iam:CreateRole",
        "iam:PutRolePermissionsBoundary",
        "iam:DeleteRolePermissionsBoundary",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:UpdateAssumeRolePolicy",
    } & set(all_actions)
    assert {
        cast(str, statement["sid"]): cast(list[str], statement["actions"])
        for statement in statements
        if any(
            action.startswith("iam:")
            for action in cast(list[str], statement["actions"])
        )
    } == {
        "ReadPreprovisionedApplicationRoles": [
            "iam:GetRole",
            "iam:GetRolePolicy",
            "iam:ListAttachedRolePolicies",
            "iam:ListRolePolicies",
            "iam:ListRoleTags",
        ],
        "ReadRetiredUsagePublisherIam": [
            "iam:GetRole",
            "iam:GetRolePolicy",
            "iam:ListAttachedRolePolicies",
            "iam:ListRolePolicies",
            "iam:ListRoleTags",
        ],
        "ReadAgentCoreTraceRoles": [
            "iam:GetRole",
            "iam:GetRolePolicy",
            "iam:ListAttachedRolePolicies",
            "iam:ListRolePolicies",
            "iam:ListRoleTags",
        ],
        "PassExistingAgentCoreRuntimeRole": ["iam:PassRole"],
        "PassTimedChecksSchedulerRole": ["iam:PassRole"],
        "UpdateReportPublisherInlinePolicy": ["iam:PutRolePolicy"],
        "PassAgentCoreTraceLogsRole": ["iam:PassRole"],
        "PassAgentCoreTraceFirehoseRole": ["iam:PassRole"],
        "ManageAgentCoreTraceRuntimePolicy": ["iam:PutRolePolicy"],
    }
    assert by_sid["UpdateReportPublisherInlinePolicy"]["resources"] == [
        "arn:aws:iam::${local.development_delivery_account_id}:role/toll-v2-report-publisher-dev"
    ]
    assert by_sid["UpdateReportPublisherInlinePolicy"]["conditions"] == []
    assert by_sid["ManageAgentCoreTraceRuntimePolicy"] == {
        "sid": "ManageAgentCoreTraceRuntimePolicy",
        "actions": ["iam:PutRolePolicy"],
        "resources": [
            "arn:aws:iam::${local.development_delivery_account_id}:role/nova-toll-v2-agentcore-runtime-dev"
        ],
        "conditions": [],
    }
    assert by_sid["UpdateReportGenerationFreshnessAlarm"] == {
        "sid": "UpdateReportGenerationFreshnessAlarm",
        "actions": ["cloudwatch:PutMetricAlarm"],
        "resources": [
            "arn:aws:cloudwatch:${local.development_delivery_region}:${local.development_delivery_account_id}:alarm:toll-v2-report-generation-freshness-dev"
        ],
        "conditions": [],
    }
    temporary_sids = {
        "RetireUsagePublisherIam",
        "RetireUsagePublisherLambda",
        "RetireUsagePublisherEvents",
        "RetireUsagePublisherAlarms",
        "RetireAgentUsageRollupIam",
        "RetireAgentUsageRollupLambda",
        "RetireAgentUsageRollupEvents",
        "RetireAgentUsageRollupAlarms",
        "RetireAgentReportsWafLogging",
    }
    assert not temporary_sids & by_sid.keys()
    assert not {
        "iam:DeleteRole",
        "iam:DeleteRolePolicy",
        "lambda:RemovePermission",
        "events:DeleteRule",
        "events:RemoveTargets",
        "cloudwatch:DeleteAlarms",
        "wafv2:DeleteLoggingConfiguration",
    } & set(all_actions)
    assert by_sid["ReadRetiredUsagePublisherLambda"]["actions"] == [
        "lambda:GetAlias",
        "lambda:GetFunction",
        "lambda:GetFunctionCodeSigningConfig",
        "lambda:GetFunctionConfiguration",
        "lambda:GetFunctionEventInvokeConfig",
        "lambda:GetFunctionUrlConfig",
        "lambda:GetPolicy",
        "lambda:GetProvisionedConcurrencyConfig",
        "lambda:ListAliases",
        "lambda:ListProvisionedConcurrencyConfigs",
        "lambda:ListTags",
        "lambda:ListVersionsByFunction",
    ]
    assert by_sid["ReadRetiredUsagePublisherEvents"]["actions"] == [
        "events:DescribeRule",
        "events:ListTagsForResource",
        "events:ListTargetsByRule",
    ]
    assert by_sid["ReadRetiredUsagePublisherAlarms"]["actions"] == [
        "cloudwatch:DescribeAlarms",
        "cloudwatch:ListTagsForResource",
    ]
    assert by_sid["ManageApplicationAlarms"]["actions"] == [
        "cloudwatch:DescribeAlarms",
        "cloudwatch:ListTagsForResource",
        "cloudwatch:TagResource",
        "cloudwatch:UntagResource",
    ]
    assert by_sid["ReadRetiredUsagePublisherIam"]["resources"] == [
        "local.development_delivery_usage_publisher_role_arn"
    ]
    assert by_sid["ReadRetiredUsagePublisherLambda"]["resources"] == [
        "local.development_delivery_usage_publisher_lambda_arn"
    ]
    assert by_sid["ReadRetiredUsagePublisherEvents"]["resources"] == [
        "local.development_delivery_usage_publisher_rule_arn"
    ]
    assert by_sid["ReadRetiredUsagePublisherAlarms"]["resources"] == [
        "local.development_delivery_usage_publisher_alarm_arns"
    ]
    assert by_sid["ReadPreprovisionedApplicationRoles"]["actions"] == [
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:ListRolePolicies",
        "iam:ListRoleTags",
    ]
    assert by_sid["ReadPreprovisionedApplicationRoles"]["resources"] == [
        "local.development_delivery_role_arns"
    ]
    assert by_sid["ManageApplicationQueues"]["actions"] == [
        "sqs:GetQueueAttributes",
        "sqs:ListQueueTags",
    ]
    assert not {
        "sqs:SetQueueAttributes",
        "sqs:AddPermission",
        "sqs:RemovePermission",
        "sqs:TagQueue",
        "sqs:UntagQueue",
    } & set(all_actions)
    assert "ManageApplicationIamRoles" not in by_sid
    assert "CreateBoundedApplicationRoles" not in by_sid
    assert "bedrock:ListTagsForResource" in cast(
        list[str], by_sid["ManageApplicationGuardrail"]["actions"]
    )
    assert "AttachOnlyLambdaVpcPolicy" not in by_sid
    assert not {"iam:AttachRolePolicy", "iam:DetachRolePolicy"} & set(all_actions)
    assert by_sid["PassExistingAgentCoreRuntimeRole"]["resources"] == [
        "arn:aws:iam::${local.development_delivery_account_id}:role/nova-toll-v2-agentcore-runtime-dev"
    ]
    assert by_sid["PassExistingAgentCoreRuntimeRole"]["conditions"] == [
        {
            "test": "StringEquals",
            "variable": "iam:PassedToService",
            "values": ["bedrock-agentcore.amazonaws.com"],
        }
    ]
    assert by_sid["UpdateApplicationLambdaFunctions"]["actions"] == [
        "lambda:TagResource",
        "lambda:UntagResource",
        "lambda:UpdateAlias",
        "lambda:UpdateFunctionCode",
    ]
    assert by_sid["UpdateApplicationLambdaFunctions"]["resources"] == [
        "local.development_delivery_lambda_resources"
    ]
    assert not {
        "lambda:UpdateFunctionConfiguration",
        "lambda:PutFunctionConcurrency",
        "lambda:PutFunctionEventInvokeConfig",
        "lambda:PutProvisionedConcurrencyConfig",
        "lambda:UpdateFunctionEventInvokeConfig",
    } & set(all_actions)
    for statement in statements:
        for resource in cast(list[str], statement["resources"]):
            assert "920534282028" not in resource
            assert "production" not in resource.lower()
    assert re.search(
        r'(?m)^\s*development_delivery_account_id\s*=\s*"903859731897"\s*$', source
    )
    assert re.search(
        r'(?m)^\s*development_delivery_region\s*=\s*"us-east-1"\s*$', source
    )
    parsed_policy = json.dumps(statements).lower()
    assert "920534282028" not in parsed_policy
    assert "production" not in parsed_policy
    assert "ssm:" not in parsed_policy
    assert "secretsmanager" not in parsed_policy

    wildcard_statements = {
        cast(str, statement["sid"])
        for statement in statements
        if cast(list[str], statement["resources"]) == ["*"]
    }
    assert wildcard_statements <= {
        "DescribeApplicationLogPolicies",
        "DescribeApplicationLogGroups",
        "DescribeApplicationNetworking",
        "ListApplicationAthenaWorkGroups",
        "ReadManagedCloudFrontPolicies",
        "ReadApplicationKmsAliases",
    }
    for sid in wildcard_statements:
        conditions = cast(list[dict[str, object]], by_sid[sid]["conditions"])
        assert any(
            condition["variable"] == "aws:RequestedRegion" for condition in conditions
        )

    assert "events:ListTagsForResource" in cast(
        list[str], by_sid["ManageApplicationEventRules"]["actions"]
    )
    assert "events:RemoveTargets" not in cast(
        list[str], by_sid["ManageApplicationEventRules"]["actions"]
    )
    assert hcl_strings(
        hcl_attribute(source, "development_delivery_log_group_arns")
    ) == [
        "arn:aws:logs:${local.development_delivery_region}:${local.development_delivery_account_id}:log-group:"
        + name
        for name in (
            "/aws/lambda/toll-v2-pricing-loader-dev",
            "/aws/lambda/toll-v2-report-publisher-dev",
            "/aws/lambda/tollchat-v2-chat-proxy-dev",
            "/aws/lambda/tollchat-v2-usage-publisher-dev",
            "/aws/lambda/nova-toll-v2-timed-checks-dev",
            "/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-DEFAULT",
            "/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-preview",
        )
    ]
    assert by_sid["ManageApplicationMeasurementBucket"]["actions"] == [
        "s3:GetAccelerateConfiguration",
        "s3:GetBucketAcl",
        "s3:GetBucketCORS",
        "s3:GetBucketLocation",
        "s3:GetBucketLogging",
        "s3:GetBucketObjectLockConfiguration",
        "s3:GetBucketOwnershipControls",
        "s3:GetBucketPolicy",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketRequestPayment",
        "s3:GetBucketTagging",
        "s3:GetBucketVersioning",
        "s3:GetBucketWebsite",
        "s3:GetEncryptionConfiguration",
        "s3:GetLifecycleConfiguration",
        "s3:GetReplicationConfiguration",
        "s3:ListBucket",
        "s3:ListBucketMultipartUploads",
        "s3:ListBucketVersions",
    ]
    assert by_sid["ReadRetainedApplicationAthenaNamedQueries"]["actions"] == [
        "athena:GetNamedQuery",
        "athena:ListTagsForResource",
    ]
    assert by_sid["ReadRetainedApplicationAthenaNamedQueries"]["resources"] == [
        "local.development_delivery_athena_workgroup_arn"
    ]
    assert by_sid["ReadRetainedApplicationAthenaWorkGroup"]["actions"] == [
        "athena:GetWorkGroup",
        "athena:ListNamedQueries",
        "athena:ListTagsForResource",
    ]
    assert by_sid["ReadRetainedApplicationAthenaWorkGroup"]["resources"] == [
        "local.development_delivery_athena_workgroup_arn"
    ]

    assert by_sid["UseApplicationKmsKeys"]["actions"] == [
        "kms:Decrypt",
        "kms:DescribeKey",
        "kms:Encrypt",
        "kms:GenerateDataKey",
        "kms:GetKeyPolicy",
        "kms:GetKeyRotationStatus",
        "kms:ListResourceTags",
    ]
    kms_conditions = cast(
        list[dict[str, object]], by_sid["UseApplicationKmsKeys"]["conditions"]
    )
    assert {
        (condition["variable"], tuple(cast(list[str], condition["values"])))
        for condition in kms_conditions
    } == {
        ("aws:ResourceTag/environment", ("development",)),
        ("aws:ResourceTag/version", ("v2",)),
    }
    assert "ManageApplicationKmsAliases" not in by_sid
    assert "CreateApplicationKmsKeys" not in by_sid
    assert "ManageNewApplicationKmsKeys" not in by_sid
    assert by_sid["ReadApplicationKmsAliases"]["actions"] == ["kms:ListAliases"]
    assert by_sid["ReadApplicationKmsAliases"]["resources"] == ["*"]
    assert by_sid["ReadAlertsKeyForTimedChecks"] == {
        "sid": "ReadAlertsKeyForTimedChecks",
        "actions": ["kms:DescribeKey"],
        "resources": ["aws_kms_key.alerts.arn"],
        "conditions": [],
    }
    assert by_sid["ReadRetainedMeasurementKey"]["actions"] == [
        "kms:Decrypt",
        "kms:DescribeKey",
        "kms:GetKeyPolicy",
        "kms:GetKeyRotationStatus",
        "kms:ListResourceTags",
    ]
    assert by_sid["ReadRetainedMeasurementKey"]["resources"] == [
        "local.development_delivery_measurement_key_arn"
    ]
    assert {
        (condition["variable"], tuple(cast(list[str], condition["values"])))
        for condition in cast(
            list[dict[str, object]], by_sid["ReadRetainedMeasurementKey"]["conditions"]
        )
    } == {
        ("aws:ResourceTag/environment", ("development",)),
        ("aws:ResourceTag/version", ("v2",)),
    }
    assert re.search(
        r'sid\s*=\s*"ReadApplicationKmsAliases".*?test\s*=\s*"StringEquals"'
        r'.*?variable\s*=\s*"aws:RequestedRegion"'
        r".*?values\s*=\s*\[local\.development_delivery_region\]",
        source,
        re.DOTALL,
    )
    bucket_reads = {
        "s3:GetAccelerateConfiguration",
        "s3:GetBucketCORS",
        "s3:GetBucketLogging",
        "s3:GetBucketObjectLockConfiguration",
        "s3:GetBucketRequestPayment",
        "s3:GetBucketWebsite",
        "s3:GetReplicationConfiguration",
    }
    for sid in ("ManageApplicationSiteBuckets", "ManageApplicationMeasurementBucket"):
        assert bucket_reads <= set(cast(list[str], by_sid[sid]["actions"]))
    assert not {
        "s3:DeleteObject",
        "s3:PutBucketVersioning",
        "s3:PutLifecycleConfiguration",
    } & set(cast(list[str], by_sid["ManageApplicationSiteBuckets"]["actions"]))
    object_scopes = {
        "ManageApplicationSiteBuckets": [
            "local.development_delivery_site_bucket_arn",
            "${local.development_delivery_site_bucket_arn}/*",
        ],
        "ReadRetainedApplicationMeasurementRegistry": [
            "${local.development_delivery_measurement_bucket_arn}/registry/agent_registry.ndjson",
        ],
        "PublishApplicationArtifacts": [
            "${local.development_delivery_artifact_bucket_arn}/runtime/v2/*",
            "${local.development_delivery_artifact_bucket_arn}/lambda/v2/*",
        ],
    }
    for sid, resources in object_scopes.items():
        if sid == "ReadRetainedApplicationMeasurementRegistry":
            assert set(cast(list[str], by_sid[sid]["actions"])) == {
                "s3:GetObject",
                "s3:GetObjectAttributes",
                "s3:GetObjectTagging",
                "s3:GetObjectVersion",
            }
        else:
            assert {"s3:GetObjectTagging", "s3:PutObjectTagging"} <= set(
                cast(list[str], by_sid[sid]["actions"])
            )
        assert by_sid[sid]["resources"] == resources
    assert "lambda:GetFunctionCodeSigningConfig" in cast(
        list[str], by_sid["ReadApplicationLambdaFunctions"]["actions"]
    )
    assert by_sid["ReadManagedCloudFrontPolicy"]["resources"] == [
        "arn:aws:cloudfront::${local.development_delivery_account_id}:cache-policy/4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
        "arn:aws:cloudfront::${local.development_delivery_account_id}:origin-request-policy/b689b0a8-53d0-40ab-baf2-68738e2966ac",
    ]
    assert by_sid["PublishApplicationApiGatewayDeployments"]["resources"] == [
        "local.development_delivery_api_deployment_arns"
    ]
    assert "UpdateApplicationApiGateway" not in by_sid
    assert by_sid["ReadApplicationApiGateway"]["resources"] == [
        "arn:aws:apigateway:${local.development_delivery_region}::/restapis/${local.development_delivery_api_id}",
        "arn:aws:apigateway:${local.development_delivery_region}::/restapis/${local.development_delivery_api_id}/*",
    ]
    assert by_sid["PublishApplicationLambdaVersions"]["actions"] == [
        "lambda:PublishVersion"
    ]
    assert by_sid["RetireApplicationLambdaVersions"]["actions"] == [
        "lambda:DeleteFunction"
    ]
    assert by_sid["PublishApplicationLambdaVersions"]["resources"] == [
        "local.development_delivery_lambda_arns"
    ]
    assert by_sid["RetireApplicationLambdaVersions"]["resources"] == [
        'for function_arn in local.development_delivery_lambda_arns : "${function_arn}:*"'
    ]
    assert by_sid["PublishApplicationGuardrailVersions"]["actions"] == [
        "bedrock:CreateGuardrailVersion",
    ]
    assert by_sid["PublishApplicationGuardrailVersions"]["resources"] == [
        "local.development_delivery_guardrail_arn"
    ]
    assert by_sid["ReadApplicationCloudFront"]["actions"] == [
        "cloudfront:GetDistribution",
        "cloudfront:GetDistributionConfig",
        "cloudfront:GetOriginAccessControl",
        "cloudfront:GetResponseHeadersPolicy",
        "cloudfront:ListTagsForResource",
    ]
    assert by_sid["ReadApplicationCloudFront"]["resources"] == [
        "local.development_delivery_distribution_arn",
        "arn:aws:cloudfront::${local.development_delivery_account_id}:origin-access-control/*",
        "arn:aws:cloudfront::${local.development_delivery_account_id}:response-headers-policy/*",
    ]
    assert by_sid["ManageApplicationAgentCore"]["actions"] == [
        "bedrock-agentcore:GetAgentRuntime",
        "bedrock-agentcore:GetAgentRuntimeEndpoint",
        "bedrock-agentcore:GetResourcePolicy",
        "bedrock-agentcore:ListTagsForResource",
        "bedrock-agentcore:TagResource",
        "bedrock-agentcore:UntagResource",
        "bedrock-agentcore:UpdateAgentRuntime",
        "bedrock-agentcore:UpdateAgentRuntimeEndpoint",
    ]
    assert by_sid["ManageApplicationAgentCore"]["resources"] == [
        "local.development_delivery_agentcore_runtime_arn",
        "local.development_delivery_agentcore_endpoint_arn",
    ]
    assert by_sid["ManageApplicationCloudFront"]["resources"] == [
        "arn:aws:cloudfront::${local.development_delivery_account_id}:function/tollchat-v2-public-chat-routes-dev",
        "arn:aws:cloudfront::${local.development_delivery_account_id}:function/tollchat-v2-public-report-routes-dev",
    ]
    assert by_sid["ManageApplicationWaf"]["actions"] == [
        "wafv2:GetLoggingConfiguration",
        "wafv2:GetWebACL",
        "wafv2:ListTagsForResource",
    ]
    assert "ManageApplicationNetworking" not in by_sid
    assert by_sid["ManageAgentCoreTraceNamedQuery"]["actions"] == [
        "athena:CreateNamedQuery",
        "athena:DeleteNamedQuery",
    ]
    assert "athena:UpdateNamedQuery" not in all_actions
    assert re.search(r'development_delivery_api_id\s*=\s*"ocw8sg0wlb"', source)
    assert re.search(r"guardrail/vdyqrh31xgca", source)
    assert re.search(r"runtime/nova_toll_v2_development-Y69XBf88Bl", source)
    assert "local.development_delivery_application_key_arns" in source
    assert "development_delivery_athena_workgroup_arn" in source
    assert "development_delivery_waf_acl_arn" not in source
    assert (
        "global/webacl/tollchat-v2-public-chat-dev/250c4d9a-abcd-4bdf-861c-b2b10549a770"
        not in source
    )
    assert "security-group/*" not in source
    assert "security-group-rule/*" not in source
    assert "vpc/*" not in source
    forbidden_mutations = {
        "iam:CreateRole",
        "iam:PutRolePermissionsBoundary",
        "iam:DeleteRolePermissionsBoundary",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:UpdateAssumeRolePolicy",
        "bedrock-agentcore:CreateAgentRuntime",
        "bedrock-agentcore:CreateAgentRuntimeEndpoint",
        "bedrock-agentcore:DeleteAgentRuntime",
        "bedrock-agentcore:DeleteAgentRuntimeEndpoint",
        "bedrock-agentcore:PutResourcePolicy",
        "bedrock-agentcore:DeleteResourcePolicy",
        "lambda:AddPermission",
        "lambda:CreateFunctionUrlConfig",
        "lambda:UpdateFunctionUrlConfig",
        "lambda:DeleteFunctionUrlConfig",
        "s3:PutBucketPolicy",
        "s3:PutBucketPublicAccessBlock",
        "wafv2:UpdateWebACL",
        "kms:CreateAlias",
        "kms:UpdateAlias",
        "kms:DeleteAlias",
        "kms:CreateKey",
        "kms:PutKeyPolicy",
        "events:PutRule",
        "logs:PutMetricFilter",
        "wafv2:PutLoggingConfiguration",
    }
    assert not forbidden_mutations & set(all_actions)


def _assert_application_roles_are_bootstrap_owned() -> None:
    role_sources = {
        "main.tf": MAIN_TF,
        "agentcore.tf": (V2_ROOT / "infra" / "agentcore.tf").read_text(),
        "site.tf": (V2_ROOT / "infra" / "site.tf").read_text(),
        "agent_measurement.tf": (
            V2_ROOT / "infra" / "agent_measurement.tf"
        ).read_text(),
        "timed_checks.tf": TIMED_CHECKS_TF,
    }
    role_names = {
        "main.tf": ("loader", "timed_checks", "publisher", "publisher_scheduler"),
        "agentcore.tf": ("tollchat_runtime", "tollchat_proxy"),
        "site.tf": (),
        "agent_measurement.tf": (),
        "timed_checks.tf": ("timed_checks_lambda", "timed_checks_scheduler"),
    }
    for filename, names in role_names.items():
        for name in names:
            role = terraform_block(
                role_sources[filename], f'resource "aws_iam_role" "{name}"'
            )
            assert hcl_scalar(role, "permissions_boundary") in (None, "")


def test_development_agentcore_execution_trust_is_exact_and_confused_deputy_bound() -> (
    None
):
    source = (V2_ROOT / "infra" / "agentcore.tf").read_text()
    policy = terraform_block(
        source, 'data "aws_iam_policy_document" "agentcore_assume"'
    )
    conditions = hcl_named_blocks(policy, "condition")
    assert any(
        hcl_scalar(condition, "test") == "StringEquals"
        and hcl_scalar(condition, "variable") == "aws:SourceAccount"
        and hcl_attribute(condition, "values")
        == "data.aws_caller_identity.current.account_id"
        for condition in conditions
    )
    assert any(
        hcl_scalar(condition, "test") == "ArnEquals"
        and hcl_scalar(condition, "variable") == "aws:SourceArn"
        and hcl_attribute(condition, "values") == "local.agentcore_runtime_source_arns"
        for condition in conditions
    )
    assert re.search(
        r"agentcore_runtime_source_arns\s*=\s*values\(local.slot_runtime_arns\)",
        source,
        re.DOTALL,
    )
    assert (
        'name => "arn:aws:bedrock-agentcore:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:runtime/${slot.runtime_id}"'
        in (V2_ROOT / "infra/releases.tf").read_text()
    )


def test_development_delivery_iam_is_parsed_and_adversarial_mutations_fail() -> None:
    _assert_development_delivery_trust(FOUNDATION_IAM)
    _assert_development_delivery_state_and_application_policy(FOUNDATION_IAM)
    _assert_application_roles_are_bootstrap_owned()
    for original, replacement in (
        (
            "role/nova-toll-v2-agentcore-runtime-dev",
            "role/nova-toll-v2-development-delivery",
        ),
        ("role/nova-toll-v2-agentcore-runtime-dev", "role/unrelated-runtime-dev"),
        ("bedrock-agentcore.amazonaws.com", "lambda.amazonaws.com"),
        ("iam:PassedToService", "aws:RequestedRegion"),
    ):
        must_reject_after_marker(
            _assert_development_delivery_state_and_application_policy,
            FOUNDATION_IAM,
            'sid = "PassExistingAgentCoreRuntimeRole"',
            original,
            replacement,
        )

    for original, replacement in (
        (
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:production",
        ),
        (
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main",
        ),
        ("refs/heads/main", "refs/heads/release"),
        (
            "v2-development-delivery-privileged.yml@refs/heads/main",
            "v2-development-connectivity-verification.yml@refs/heads/main",
        ),
        (
            "token.actions.githubusercontent.com:aud",
            "token.actions.githubusercontent.com:evil",
        ),
        (
            "aws_iam_openid_connect_provider.github.arn",
            '"arn:aws:iam::903859731897:oidc-provider/evil.example"',
        ),
        (
            "nova-toll/v2/development/terraform.tfstate",
            "nova-toll/v2/production/terraform.tfstate",
        ),
        ("bedrock:ListTagsForResource", "bedrock:ListResources"),
        ("events:ListTagsForResource", "events:ListRules"),
        ("iam:GetRole", "iam:DeleteRole"),
        ("iam:GetRolePolicy", "iam:PutRolePolicy"),
        ("lambda:GetFunctionConfiguration", "lambda:UpdateFunctionConfiguration"),
        (
            'variable = "aws:ResourceTag/version"\n      values   = ["v2"]',
            'variable = "aws:ResourceTag/version"\n      values   = ["production"]',
        ),
        ("sts:AssumeRoleWithWebIdentity", "sts:AssumeRole"),
    ):
        assertion = (
            _assert_development_delivery_trust
            if (
                "repo:" in original
                or original.startswith("sts:")
                or "token.actions" in original
                or "openid_connect_provider" in original
                or original == "refs/heads/main"
                or original == "v2-development-delivery-privileged.yml@refs/heads/main"
            )
            else _assert_development_delivery_state_and_application_policy
        )
        must_reject(assertion, FOUNDATION_IAM, original, replacement)
    must_reject_after_marker(
        _assert_development_delivery_state_and_application_policy,
        FOUNDATION_IAM,
        'sid       = "ManageApplicationMeasurementBucket"',
        "s3:GetBucketPolicy",
        "s3:PutBucketPolicy",
    )
    must_reject_after_marker(
        _assert_development_delivery_state_and_application_policy,
        FOUNDATION_IAM,
        'sid       = "UseApplicationKmsKeys"',
        'variable = "aws:ResourceTag/environment"',
        'variable = "kms:ResourceAliases"',
    )
    must_reject_after_marker(
        _assert_development_delivery_state_and_application_policy,
        FOUNDATION_IAM,
        'sid     = "ManageApplicationAgentCore"',
        "local.development_delivery_agentcore_runtime_arn",
        '"arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/*"',
    )
    must_reject_after_marker(
        _assert_development_delivery_state_and_application_policy,
        FOUNDATION_IAM,
        'sid       = "PublishApplicationGuardrailVersions"',
        "local.development_delivery_guardrail_arn",
        '"arn:aws:bedrock:us-east-1:903859731897:guardrail/*"',
    )
    must_reject_after_marker(
        _assert_development_delivery_state_and_application_policy,
        FOUNDATION_IAM,
        'sid       = "PublishApplicationApiGatewayDeployments"',
        "local.development_delivery_api_deployment_arns",
        '["arn:aws:apigateway:${local.development_delivery_region}::/restapis/*/deployments"]',
    )
    for marker, original, replacement in (
        (
            'sid       = "ManageApplicationEventRules"',
            "events:DescribeRule",
            "events:PutRule",
        ),
        (
            'sid       = "ManageApplicationLogs"',
            "logs:DescribeMetricFilters",
            "logs:PutMetricFilter",
        ),
        (
            'sid       = "ManageApplicationAlarms"',
            "cloudwatch:DescribeAlarms",
            "cloudwatch:PutMetricAlarm",
        ),
        (
            'sid       = "ManageApplicationWaf"',
            "wafv2:GetLoggingConfiguration",
            "wafv2:PutLoggingConfiguration",
        ),
        (
            'sid = "ReadRetainedApplicationAthenaNamedQueries"',
            "local.development_delivery_athena_workgroup_arn",
            '"arn:aws:athena:${local.development_delivery_region}:${local.development_delivery_account_id}:workgroup/*"',
        ),
    ):
        must_reject_after_marker(
            _assert_development_delivery_state_and_application_policy,
            FOUNDATION_IAM,
            marker,
            original,
            replacement,
        )


DEVELOPMENT_PLAN_SIDS = [
    "ListDevelopmentState",
    "ReadDevelopmentState",
    "DecryptDevelopmentState",
    "ReadPreprovisionedApplicationRoles",
    "ReadApplicationLambdaFunctions",
    "ReadApplicationQueues",
    "ReadApplicationQueueUrls",
    "ReadApplicationEventRules",
    "ReadRetainedRollupEventRule",
    "ReadApplicationLogs",
    "ReadRetainedRollupLogGroup",
    "DescribeApplicationLogPolicies",
    "DescribeApplicationLogGroups",
    "ReadAgentCoreTraceSubscription",
    "ReadAgentCoreTraceRoles",
    "ReadAgentCoreTraceFirehose",
    "ReadApplicationAlarms",
    "ReadRetainedRollupAlarms",
    "DescribeApplicationNetworking",
    "ReadApplicationSiteBucket",
    "ReadApplicationMeasurementBucket",
    "ReadRetainedApplicationMeasurementRegistry",
    "ReadApplicationArtifacts",
    "ReadApplicationArtifactBucket",
    "ReadApplicationKmsKeys",
    "ReadRetainedMeasurementKey",
    "ReadApplicationKmsAliases",
    "ReadApplicationSessions",
    "ReadRetainedApplicationCatalog",
    "ReadRetainedApplicationAthenaNamedQueries",
    "ReadRetainedApplicationAthenaWorkGroup",
    "ListApplicationAthenaWorkGroups",
    "ReadApplicationSchedules",
    "ReadRetiredUsagePublisherIam",
    "ReadRetiredUsagePublisherLambda",
    "ReadRetiredUsagePublisherEvents",
    "ReadRetiredUsagePublisherAlarms",
    "ReadApplicationGuardrail",
    "ReadApplicationAgentCore",
    "ReadApplicationApiGateway",
    "ReadApplicationCloudFrontFunctions",
    "ReadApplicationCloudFront",
    "ReadManagedCloudFrontPolicies",
    "ReadManagedCloudFrontPolicy",
    "ReadApplicationWaf",
    "ReadDevelopmentCertificate",
    "ReadAlertsKeyForTimedChecks",
]


_NO_PLAN_CONDITIONS = ()


_REGIONAL_PLAN_CONDITIONS = (("StringEquals", "aws:RequestedRegion", ("us-east-1",)),)


_KMS_PLAN_CONDITIONS = (
    ("StringEquals", "aws:ResourceTag/environment", ("development",)),
    ("StringEquals", "aws:ResourceTag/version", ("v2",)),
)


_LAMBDA_READ_ACTIONS = (
    "lambda:GetAlias",
    "lambda:GetFunction",
    "lambda:GetFunctionCodeSigningConfig",
    "lambda:GetFunctionConfiguration",
    "lambda:GetFunctionEventInvokeConfig",
    "lambda:GetFunctionUrlConfig",
    "lambda:GetPolicy",
    "lambda:GetProvisionedConcurrencyConfig",
    "lambda:ListAliases",
    "lambda:ListProvisionedConcurrencyConfigs",
    "lambda:ListTags",
    "lambda:ListVersionsByFunction",
)


_EVENT_READ_ACTIONS = (
    "events:DescribeRule",
    "events:ListTagsForResource",
    "events:ListTargetsByRule",
)


_ALARM_READ_ACTIONS = ("cloudwatch:DescribeAlarms", "cloudwatch:ListTagsForResource")


_IAM_READ_ACTIONS = (
    "iam:GetRole",
    "iam:GetRolePolicy",
    "iam:ListAttachedRolePolicies",
    "iam:ListInstanceProfilesForRole",
    "iam:ListRolePolicies",
    "iam:ListRoleTags",
)


DEVELOPMENT_PLAN_REFRESH_TUPLES = {
    "ReadPreprovisionedApplicationRoles": (
        _IAM_READ_ACTIONS,
        ("local.development_delivery_role_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationLambdaFunctions": (
        _LAMBDA_READ_ACTIONS,
        (
            "concat(local.development_delivery_lambda_resources, local.development_delivery_legacy_rollup_lambda_resources)",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationQueues": (
        ("sqs:GetQueueAttributes", "sqs:ListQueueTags"),
        ("local.development_delivery_queue_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationQueueUrls": (
        ("sqs:GetQueueUrl",),
        ("local.development_delivery_queue_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationEventRules": (
        _EVENT_READ_ACTIONS,
        ("local.development_delivery_event_rule_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetainedRollupEventRule": (
        _EVENT_READ_ACTIONS,
        ("local.development_delivery_legacy_rollup_event_rule_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationLogs": (
        ("logs:DescribeMetricFilters", "logs:ListTagsForResource"),
        ("local.development_delivery_log_group_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetainedRollupLogGroup": (
        ("logs:DescribeMetricFilters", "logs:ListTagsForResource"),
        ("local.development_delivery_legacy_rollup_log_group_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "DescribeApplicationLogPolicies": (
        ("logs:DescribeResourcePolicies",),
        ("*",),
        _REGIONAL_PLAN_CONDITIONS,
    ),
    "DescribeApplicationLogGroups": (
        ("logs:DescribeLogGroups",),
        ("*",),
        _REGIONAL_PLAN_CONDITIONS,
    ),
    "ReadAgentCoreTraceSubscription": (
        ("logs:DescribeSubscriptionFilters",),
        (
            "for",
            "arn",
            "in",
            "local.development_delivery_agentcore_trace_log_group_arns",
            "${arn}:*",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadAgentCoreTraceRoles": (
        _IAM_READ_ACTIONS,
        (
            "local.development_delivery_agentcore_trace_logs_role_arn",
            "local.development_delivery_agentcore_trace_firehose_role_arn",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadAgentCoreTraceFirehose": (
        (
            "firehose:DescribeDeliveryStream",
            "firehose:ListTagsForDeliveryStream",
        ),
        ("local.development_delivery_agentcore_trace_firehose_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationAlarms": (
        _ALARM_READ_ACTIONS,
        ("local.development_delivery_alarm_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetainedRollupAlarms": (
        _ALARM_READ_ACTIONS,
        ("local.development_delivery_legacy_rollup_alarm_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "DescribeApplicationNetworking": (
        (
            "ec2:DescribePrefixLists",
            "ec2:DescribeSecurityGroupRules",
            "ec2:DescribeSecurityGroups",
            "ec2:DescribeSubnets",
            "ec2:DescribeVpcs",
        ),
        ("*",),
        _REGIONAL_PLAN_CONDITIONS,
    ),
    "ReadApplicationSiteBucket": (
        (
            "s3:GetAccelerateConfiguration",
            "s3:GetBucketAcl",
            "s3:GetBucketCORS",
            "s3:GetBucketLocation",
            "s3:GetBucketLogging",
            "s3:GetBucketObjectLockConfiguration",
            "s3:GetBucketOwnershipControls",
            "s3:GetBucketPolicy",
            "s3:GetBucketPublicAccessBlock",
            "s3:GetBucketRequestPayment",
            "s3:GetBucketTagging",
            "s3:GetBucketVersioning",
            "s3:GetBucketWebsite",
            "s3:GetEncryptionConfiguration",
            "s3:GetLifecycleConfiguration",
            "s3:GetObject",
            "s3:GetObjectAttributes",
            "s3:GetObjectTagging",
            "s3:GetObjectVersion",
            "s3:GetReplicationConfiguration",
            "s3:ListBucket",
            "s3:ListBucketMultipartUploads",
            "s3:ListBucketVersions",
        ),
        (
            "local.development_delivery_site_bucket_arn",
            "${local.development_delivery_site_bucket_arn}/*",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationMeasurementBucket": (
        (
            "s3:GetAccelerateConfiguration",
            "s3:GetBucketAcl",
            "s3:GetBucketCORS",
            "s3:GetBucketLocation",
            "s3:GetBucketLogging",
            "s3:GetBucketObjectLockConfiguration",
            "s3:GetBucketOwnershipControls",
            "s3:GetBucketPolicy",
            "s3:GetBucketPublicAccessBlock",
            "s3:GetBucketRequestPayment",
            "s3:GetBucketTagging",
            "s3:GetBucketVersioning",
            "s3:GetBucketWebsite",
            "s3:GetEncryptionConfiguration",
            "s3:GetLifecycleConfiguration",
            "s3:GetReplicationConfiguration",
            "s3:ListBucket",
            "s3:ListBucketMultipartUploads",
            "s3:ListBucketVersions",
        ),
        ("local.development_delivery_measurement_bucket_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetainedApplicationMeasurementRegistry": (
        (
            "s3:GetObject",
            "s3:GetObjectAttributes",
            "s3:GetObjectTagging",
            "s3:GetObjectVersion",
        ),
        (
            "${local.development_delivery_measurement_bucket_arn}/registry/agent_registry.ndjson",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationArtifacts": (
        (
            "s3:GetObject",
            "s3:GetObjectAttributes",
            "s3:GetObjectTagging",
            "s3:GetObjectVersion",
            "s3:ListBucketMultipartUploads",
            "s3:ListMultipartUploadParts",
        ),
        (
            "${local.development_delivery_artifact_bucket_arn}/runtime/v2/*",
            "${local.development_delivery_artifact_bucket_arn}/lambda/v2/*",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationArtifactBucket": (
        ("s3:GetBucketLocation",),
        ("local.development_delivery_artifact_bucket_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationKmsKeys": (
        (
            "kms:DescribeKey",
            "kms:GetKeyPolicy",
            "kms:GetKeyRotationStatus",
            "kms:ListResourceTags",
        ),
        ("local.development_delivery_application_key_arns",),
        _KMS_PLAN_CONDITIONS,
    ),
    "ReadRetainedMeasurementKey": (
        (
            "kms:DescribeKey",
            "kms:GetKeyPolicy",
            "kms:GetKeyRotationStatus",
            "kms:ListResourceTags",
        ),
        ("local.development_delivery_measurement_key_arn",),
        _KMS_PLAN_CONDITIONS,
    ),
    "ReadApplicationKmsAliases": (
        ("kms:ListAliases",),
        ("*",),
        _REGIONAL_PLAN_CONDITIONS,
    ),
    "ReadApplicationSessions": (
        (
            "dynamodb:DescribeContinuousBackups",
            "dynamodb:DescribeTable",
            "dynamodb:DescribeTimeToLive",
            "dynamodb:ListTagsOfResource",
        ),
        (
            "arn:aws:dynamodb:${local.development_delivery_region}:${local.development_delivery_account_id}:table/tollchat-v2-anonymous-sessions-dev",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetainedApplicationCatalog": (
        (
            "glue:GetDatabase",
            "glue:GetDatabases",
            "glue:GetTable",
            "glue:GetTables",
            "glue:GetTags",
        ),
        (
            "arn:aws:glue:${local.development_delivery_region}:${local.development_delivery_account_id}:catalog",
            "arn:aws:glue:${local.development_delivery_region}:${local.development_delivery_account_id}:database/tollchat_agent_reports_development",
            "arn:aws:glue:${local.development_delivery_region}:${local.development_delivery_account_id}:table/tollchat_agent_reports_development/*",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetainedApplicationAthenaNamedQueries": (
        ("athena:GetNamedQuery", "athena:ListTagsForResource"),
        ("local.development_delivery_athena_workgroup_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetainedApplicationAthenaWorkGroup": (
        (
            "athena:GetWorkGroup",
            "athena:ListNamedQueries",
            "athena:ListTagsForResource",
        ),
        ("local.development_delivery_athena_workgroup_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ListApplicationAthenaWorkGroups": (
        ("athena:ListWorkGroups",),
        ("*",),
        _REGIONAL_PLAN_CONDITIONS,
    ),
    "ReadApplicationSchedules": (
        ("scheduler:GetSchedule", "scheduler:ListTagsForResource"),
        (
            'concat([ "arn:aws:scheduler:${local.development_delivery_region}:${local.development_delivery_account_id}:schedule/*/toll-v2-report-publisher-dev", "arn:aws:scheduler:${local.development_delivery_region}:${local.development_delivery_account_id}:schedule-group/default", ], local.development_delivery_timed_schedule_arns)',
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetiredUsagePublisherIam": (
        _IAM_READ_ACTIONS,
        ("local.development_delivery_usage_publisher_role_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetiredUsagePublisherLambda": (
        _LAMBDA_READ_ACTIONS,
        ("local.development_delivery_usage_publisher_lambda_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetiredUsagePublisherEvents": (
        _EVENT_READ_ACTIONS,
        ("local.development_delivery_usage_publisher_rule_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadRetiredUsagePublisherAlarms": (
        _ALARM_READ_ACTIONS,
        ("local.development_delivery_usage_publisher_alarm_arns",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationGuardrail": (
        ("bedrock:GetGuardrail", "bedrock:ListTagsForResource"),
        ("local.development_delivery_guardrail_arn",),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationAgentCore": (
        (
            "bedrock-agentcore:GetAgentRuntime",
            "bedrock-agentcore:GetAgentRuntimeEndpoint",
            "bedrock-agentcore:GetResourcePolicy",
            "bedrock-agentcore:ListTagsForResource",
        ),
        (
            "local.development_delivery_agentcore_runtime_arn",
            "local.development_delivery_agentcore_endpoint_arn",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationApiGateway": (
        ("apigateway:GET",),
        (
            "arn:aws:apigateway:${local.development_delivery_region}::/restapis/${local.development_delivery_api_id}",
            "arn:aws:apigateway:${local.development_delivery_region}::/restapis/${local.development_delivery_api_id}/*",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationCloudFrontFunctions": (
        (
            "cloudfront:DescribeFunction",
            "cloudfront:GetFunction",
            "cloudfront:ListTagsForResource",
        ),
        (
            "arn:aws:cloudfront::${local.development_delivery_account_id}:function/tollchat-v2-public-chat-routes-dev",
            "arn:aws:cloudfront::${local.development_delivery_account_id}:function/tollchat-v2-public-report-routes-dev",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationCloudFront": (
        (
            "cloudfront:GetDistribution",
            "cloudfront:GetDistributionConfig",
            "cloudfront:GetOriginAccessControl",
            "cloudfront:GetResponseHeadersPolicy",
            "cloudfront:ListTagsForResource",
        ),
        (
            "local.development_delivery_distribution_arn",
            "arn:aws:cloudfront::${local.development_delivery_account_id}:origin-access-control/*",
            "arn:aws:cloudfront::${local.development_delivery_account_id}:response-headers-policy/*",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadManagedCloudFrontPolicies": (
        ("cloudfront:ListCachePolicies", "cloudfront:ListOriginRequestPolicies"),
        ("*",),
        _REGIONAL_PLAN_CONDITIONS,
    ),
    "ReadManagedCloudFrontPolicy": (
        ("cloudfront:GetCachePolicy", "cloudfront:GetOriginRequestPolicy"),
        (
            "arn:aws:cloudfront::${local.development_delivery_account_id}:cache-policy/4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
            "arn:aws:cloudfront::${local.development_delivery_account_id}:origin-request-policy/b689b0a8-53d0-40ab-baf2-68738e2966ac",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadApplicationWaf": (
        (
            "wafv2:GetLoggingConfiguration",
            "wafv2:GetWebACL",
            "wafv2:ListTagsForResource",
        ),
        (
            "arn:aws:wafv2:${local.development_delivery_region}:${local.development_delivery_account_id}:global/webacl/tollchat-v2-public-chat-dev/*",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadDevelopmentCertificate": (
        ("acm:DescribeCertificate", "acm:ListTagsForCertificate"),
        (
            "arn:aws:acm:${local.development_delivery_region}:${local.development_delivery_account_id}:certificate/0c2c3578-fee5-41b3-9985-ea7465c16a20",
        ),
        _NO_PLAN_CONDITIONS,
    ),
    "ReadAlertsKeyForTimedChecks": (
        ("kms:DescribeKey",),
        ("aws_kms_key.alerts.arn",),
        _NO_PLAN_CONDITIONS,
    ),
}


def _assert_development_plan_trust(source: str) -> None:
    statements = parsed_policy_document(source, "development_plan_assume")
    assert len(statements) == 1
    assert statements[0] == {
        "sid": "GitHubDevelopmentPlanWorkflow",
        "actions": ["sts:AssumeRoleWithWebIdentity"],
        "resources": [],
        "conditions": [
            {
                "test": "StringEquals",
                "variable": "token.actions.githubusercontent.com:aud",
                "values": ["sts.amazonaws.com"],
            },
            {
                "test": "StringEquals",
                "variable": "token.actions.githubusercontent.com:sub",
                "values": [
                    "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development-plan"
                ],
            },
            {
                "test": "StringEquals",
                "variable": "token.actions.githubusercontent.com:repository",
                "values": ["rhprasad0/nova-toll-budget-agent"],
            },
            {
                "test": "StringEquals",
                "variable": "token.actions.githubusercontent.com:job_workflow_ref",
                "values": [
                    "rhprasad0/nova-toll-budget-agent/.github/workflows/v2-development-plan.yml@refs/heads/main"
                ],
            },
        ],
    }
    principal = hcl_named_blocks(
        terraform_block(
            source, 'data "aws_iam_policy_document" "development_plan_assume"'
        ),
        "principals",
    )
    assert len(principal) == 1
    assert hcl_scalar(principal[0], "type") == "Federated"
    assert hcl_attribute(principal[0], "identifiers") == (
        "aws_iam_openid_connect_provider.github.arn"
    )
    assert "StringLike" not in terraform_block(
        source, 'data "aws_iam_policy_document" "development_plan_assume"'
    )


def _assert_development_plan_policy(source: str) -> None:
    policy_block = terraform_block(
        source, 'data "aws_iam_policy_document" "development_plan"'
    )
    statements = parsed_policy_document(source, "development_plan")
    assert [statement["sid"] for statement in statements] == DEVELOPMENT_PLAN_SIDS
    assert len(statements) == 47
    by_sid = policy_by_sid(statements)
    parsed_tuples = parsed_policy_tuple_map(source, "development_plan")
    assert set(parsed_tuples) == set(DEVELOPMENT_PLAN_SIDS)
    for sid in DEVELOPMENT_PLAN_SIDS[3:]:
        assert parsed_tuples[sid] == DEVELOPMENT_PLAN_REFRESH_TUPLES[sid]

    assert by_sid["ListDevelopmentState"] == {
        "sid": "ListDevelopmentState",
        "actions": ["s3:ListBucket"],
        "resources": ["aws_s3_bucket.tfstate.arn"],
        "conditions": [
            {
                "test": "StringEquals",
                "variable": "s3:prefix",
                "values": [
                    "nova-toll/development/terraform.tfstate",
                    "nova-toll/v2/development/terraform.tfstate",
                ],
            }
        ],
    }
    assert by_sid["ReadDevelopmentState"]["actions"] == ["s3:GetObject"]
    assert by_sid["ReadDevelopmentState"]["resources"] == [
        "${aws_s3_bucket.tfstate.arn}/nova-toll/development/terraform.tfstate",
        "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate",
    ]
    assert by_sid["DecryptDevelopmentState"]["actions"] == ["kms:Decrypt"]
    assert by_sid["DecryptDevelopmentState"]["resources"] == ["aws_kms_key.tfstate.arn"]
    assert by_sid["DecryptDevelopmentState"]["conditions"] == [
        {
            "test": "StringEquals",
            "variable": "kms:ViaService",
            "values": ["s3.us-east-1.amazonaws.com"],
        },
        {
            "test": "StringEquals",
            "variable": "kms:EncryptionContext:aws:s3:arn",
            "values": [
                "${aws_s3_bucket.tfstate.arn}/nova-toll/development/terraform.tfstate",
                "${aws_s3_bucket.tfstate.arn}/nova-toll/v2/development/terraform.tfstate",
            ],
        },
    ]
    assert set(
        cast(list[str], by_sid["ReadPreprovisionedApplicationRoles"]["actions"])
    ) == {
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListAttachedRolePolicies",
        "iam:ListInstanceProfilesForRole",
        "iam:ListRolePolicies",
        "iam:ListRoleTags",
    }
    assert "iam:ListInstanceProfilesForRole" in cast(
        list[str], by_sid["ReadRetiredUsagePublisherIam"]["actions"]
    )
    assert by_sid["ReadPreprovisionedApplicationRoles"]["resources"] == [
        "local.development_delivery_role_arns"
    ]
    assert by_sid["ReadRetiredUsagePublisherIam"]["resources"] == [
        "local.development_delivery_usage_publisher_role_arn"
    ]

    wildcard_sids = {
        cast(str, statement["sid"])
        for statement in statements
        if cast(list[str], statement["resources"]) == ["*"]
    }
    assert wildcard_sids == {
        "DescribeApplicationLogPolicies",
        "DescribeApplicationLogGroups",
        "DescribeApplicationNetworking",
        "ReadApplicationKmsAliases",
        "ListApplicationAthenaWorkGroups",
        "ReadManagedCloudFrontPolicies",
    }
    for sid in wildcard_sids:
        assert by_sid[sid]["conditions"] == [
            {
                "test": "StringEquals",
                "variable": "aws:RequestedRegion",
                "values": [],
            }
        ]

    all_actions = {
        action
        for statement in statements
        for action in cast(list[str], statement["actions"])
    }
    assert not any(action.endswith(":*") or action == "*" for action in all_actions)
    assert (
        not {
            "s3:PutObject",
            "s3:DeleteObject",
            "kms:GenerateDataKey",
            "iam:PassRole",
            "iam:SimulatePrincipalPolicy",
        }
        & all_actions
    )
    assert not any(
        action.startswith(("ssm:", "secretsmanager:")) for action in all_actions
    )
    assert ".tflock" not in policy_block
    assert "920534282028" not in policy_block
    assert "production" not in policy_block.lower()

    role = terraform_block(source, 'resource "aws_iam_role" "development_plan"')
    assert re.search(
        r'(?m)^\s*count\s*=\s*var.environment == "development" \? 1 : 0\s*$', role
    )
    assert re.search(r"(?m)^\s*max_session_duration\s*=\s*3600\s*$", role)
    for resource_type in (
        'resource "aws_iam_policy" "development_plan"',
        'resource "aws_iam_role_policy_attachment" "development_plan"',
    ):
        resource = terraform_block(source, resource_type)
        assert 'var.environment == "development" ?' in resource
        assert "local.development_plan_policy_documents" in resource


def test_development_plan_iam_is_exact_and_adversarial_mutations_fail() -> None:
    _assert_development_plan_trust(FOUNDATION_IAM)
    _assert_development_plan_policy(FOUNDATION_IAM)
    for original, replacement in (
        (
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development-plan",
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
        ),
        ("rhprasad0/nova-toll-budget-agent", "evil/fork"),
        (
            "v2-development-plan.yml@refs/heads/main",
            "v2-development-plan.yml@refs/heads/release",
        ),
        ("s3.us-east-1.amazonaws.com", "s3.us-west-2.amazonaws.com"),
        ("s3:ListBucket", "s3:PutObject"),
        ("kms:Decrypt", "kms:GenerateDataKey"),
        ("iam:ListInstanceProfilesForRole", "iam:ListRoles"),
    ):
        assertion = (
            _assert_development_plan_trust
            if original
            in {
                "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development-plan",
                "rhprasad0/nova-toll-budget-agent",
                "v2-development-plan.yml@refs/heads/main",
            }
            else _assert_development_plan_policy
        )
        marker = (
            'data "aws_iam_policy_document" "development_plan_assume"'
            if assertion is _assert_development_plan_trust
            else 'data "aws_iam_policy_document" "development_plan"'
        )
        must_reject_after_marker(
            assertion, FOUNDATION_IAM, marker, original, replacement
        )
    for original, replacement in (
        ("apigateway:GET", "apigateway:POST"),
        (
            "arn:aws:apigateway:${local.development_delivery_region}::/restapis/${local.development_delivery_api_id}",
            "arn:aws:apigateway:${local.development_delivery_region}::/restapis/*",
        ),
    ):
        must_reject_after_marker(
            _assert_development_plan_policy,
            FOUNDATION_IAM,
            'data "aws_iam_policy_document" "development_plan"',
            original,
            replacement,
        )


def test_development_plan_policy_set_is_deterministic_and_bounded() -> None:
    documents, aggregate = _terraform_rendered_development_plan_policies()
    assert set(documents) == {
        "state",
        "compute",
        "observability",
        "storage",
        "data",
        "runtime",
        "edge",
        "telemetry",
    }
    assert len(aggregate) == 47
    assert [
        statement
        for statement in aggregate
        if statement["Sid"] == "ReadAlertsKeyForTimedChecks"
    ] == [
        {
            "Action": "kms:DescribeKey",
            "Effect": "Allow",
            "Resource": "arn:aws:kms:us-east-1:903859731897:key/11111111-1111-1111-1111-111111111111",
            "Sid": "ReadAlertsKeyForTimedChecks",
        }
    ]
    rendered_statements: list[dict[str, object]] = []
    for key in (
        "state",
        "compute",
        "observability",
        "storage",
        "data",
        "runtime",
        "edge",
    ):
        policy = documents[key]
        statements = policy.get("Statement")
        assert isinstance(statements, list)
        rendered_statements.extend(cast(list[dict[str, object]], statements))
        assert len(json.dumps(policy, separators=(",", ":")).encode("utf-8")) <= 6_144
    assert rendered_statements == aggregate
    assert [statement["Sid"] for statement in aggregate] == DEVELOPMENT_PLAN_SIDS
    assert len({statement["Sid"] for statement in aggregate}) == len(aggregate)


def _statement_allows(statement: dict[str, object], action: str, resource: str) -> bool:
    return action in cast(list[str], statement["actions"]) and resource in cast(
        list[str], statement["resources"]
    )


def _assert_agentcore_trace_foundation_source(source: str) -> None:
    logs_trust = parsed_policy_document(
        source, "development_agentcore_trace_logs_assume"
    )
    logs_policy = parsed_policy_document(source, "development_agentcore_trace_logs")
    firehose_trust = parsed_policy_document(
        source, "development_agentcore_trace_firehose_assume"
    )
    firehose_policy = parsed_policy_document(
        source, "development_agentcore_trace_firehose"
    )
    assert logs_trust == [
        {
            "sid": "",
            "actions": ["sts:AssumeRole"],
            "resources": [],
            "conditions": [
                {
                    "test": "StringLike",
                    "variable": "aws:SourceArn",
                    "values": [],
                },
                {
                    "test": "StringEquals",
                    "variable": "aws:SourceAccount",
                    "values": [],
                },
            ],
        }
    ]
    logs_source = terraform_block(
        source,
        'data "aws_iam_policy_document" "development_agentcore_trace_logs_assume"',
    )
    assert (
        "values=concat(local.development_delivery_agentcore_trace_log_group_arns,"
        '[forarninlocal.development_delivery_agentcore_trace_log_group_arns:"${arn}:*"],)'
    ) in "".join(logs_source.split())
    assert logs_policy == [
        {
            "sid": "",
            "actions": ["firehose:PutRecord"],
            "resources": ["local.development_delivery_agentcore_trace_firehose_arn"],
            "conditions": [],
        }
    ]
    assert firehose_trust == [
        {
            "sid": "",
            "actions": ["sts:AssumeRole"],
            "resources": [],
            "conditions": [
                {"test": "StringEquals", "variable": "sts:ExternalId", "values": []}
            ],
        }
    ]
    assert firehose_policy == [
        {
            "sid": "",
            "actions": [
                "s3:GetBucketLocation",
                "s3:ListBucket",
                "s3:ListBucketMultipartUploads",
            ],
            "resources": ["local.development_delivery_measurement_bucket_arn"],
            "conditions": [],
        },
        {
            "sid": "",
            "actions": ["s3:AbortMultipartUpload", "s3:GetObject", "s3:PutObject"],
            "resources": [
                "${local.development_delivery_measurement_bucket_arn}/agentcore-traces/*"
            ],
            "conditions": [],
        },
        {
            "sid": "",
            "actions": ["kms:Decrypt", "kms:GenerateDataKey"],
            "resources": ["local.development_delivery_measurement_key_arn"],
            "conditions": [
                {
                    "test": "StringEquals",
                    "variable": "kms:ViaService",
                    "values": ["s3.${local.development_delivery_region}.amazonaws.com"],
                },
                {
                    "test": "StringEquals",
                    "variable": "kms:EncryptionContext:aws:s3:arn",
                    "values": [],
                },
            ],
        },
    ]
    for name, service in (
        (
            "development_agentcore_trace_logs_assume",
            "logs.amazonaws.com",
        ),
        ("development_agentcore_trace_firehose_assume", "firehose.amazonaws.com"),
    ):
        principals = hcl_named_blocks(
            terraform_block(source, f'data "aws_iam_policy_document" "{name}"'),
            "principals",
        )
        assert len(principals) == 1
        assert hcl_scalar(principals[0], "type") == "Service"
        assert hcl_strings(hcl_attribute(principals[0], "identifiers")) == [service]


def _assert_agentcore_trace_bucket_key_contract(iam: str, measurement: str) -> None:
    encryption = terraform_block(
        measurement,
        'resource "aws_s3_bucket_server_side_encryption_configuration" "agent_measurement"',
    )
    assert "bucket_key_enabled = true" in encryption
    firehose = policy_by_sid(
        parsed_policy_document(iam, "development_agentcore_trace_firehose")
    )[""]
    firehose_source = terraform_block(
        iam, 'data "aws_iam_policy_document" "development_agentcore_trace_firehose"'
    )
    assert (
        "values   = [local.development_delivery_measurement_bucket_arn]"
        in firehose_source
    )
    assert firehose["resources"] == ["local.development_delivery_measurement_key_arn"]
    assert firehose["conditions"] == [
        {
            "test": "StringEquals",
            "variable": "kms:ViaService",
            "values": ["s3.${local.development_delivery_region}.amazonaws.com"],
        },
        {
            "test": "StringEquals",
            "variable": "kms:EncryptionContext:aws:s3:arn",
            "values": [],
        },
    ]


def _assert_agentcore_trace_resource_headers(source: str) -> None:
    headers = sorted(
        set(
            re.findall(
                r'(?m)^resource "(aws_[^"]+)" "([^"]+)" \{',
                source,
            )
        )
    )
    assert len(headers) == 28
    assert (
        hashlib.sha256(
            json.dumps(headers, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        == "a00621201c851c38b78ec4f9cb75cd723c8bcf06145f6b9092a48a97f2c59824"
    )
    trace_headers = {
        ("aws_iam_role", "development_agentcore_trace_logs"),
        ("aws_iam_role_policy", "development_agentcore_trace_logs"),
        ("aws_iam_role", "development_agentcore_trace_firehose"),
        ("aws_iam_role_policy", "development_agentcore_trace_firehose"),
    }
    assert trace_headers <= set(headers)
    for resource_type, name in trace_headers:
        assert "count" in terraform_block(
            source, f'resource "{resource_type}" "{name}"'
        )
        assert 'var.environment == "development" ? 1 : 0' in terraform_block(
            source, f'resource "{resource_type}" "{name}"'
        )


def _assert_agentcore_trace_identity_reads(source: str) -> None:
    expected: dict[
        str, tuple[list[str], list[str], list[dict[str, str | list[str]]]]
    ] = {
        "ReadAgentCoreTraceSubscription": (
            ["logs:DescribeSubscriptionFilters"],
            [
                'for arn in local.development_delivery_agentcore_trace_log_group_arns : "${arn}:*"'
            ],
            [],
        ),
        "ReadAgentCoreTraceRoles": (
            [
                "iam:GetRole",
                "iam:GetRolePolicy",
                "iam:ListAttachedRolePolicies",
                "iam:ListRolePolicies",
                "iam:ListRoleTags",
            ],
            [
                "local.development_delivery_agentcore_trace_logs_role_arn",
                "local.development_delivery_agentcore_trace_firehose_role_arn",
            ],
            [],
        ),
        "ReadAgentCoreTraceFirehose": (
            [
                "firehose:DescribeDeliveryStream",
                "firehose:ListTagsForDeliveryStream",
            ],
            ["local.development_delivery_agentcore_trace_firehose_arn"],
            [],
        ),
    }
    for document in ("development_delivery", "development_plan"):
        statements = policy_by_sid(parsed_policy_document(source, document))
        document_expected = deepcopy(expected)
        if document == "development_plan":
            document_expected["ReadAgentCoreTraceRoles"] = (
                [
                    "iam:GetRole",
                    "iam:GetRolePolicy",
                    "iam:ListAttachedRolePolicies",
                    "iam:ListInstanceProfilesForRole",
                    "iam:ListRolePolicies",
                    "iam:ListRoleTags",
                ],
                [
                    "local.development_delivery_agentcore_trace_logs_role_arn",
                    "local.development_delivery_agentcore_trace_firehose_role_arn",
                ],
                [],
            )
        assert {
            sid: (
                statements[sid]["actions"],
                statements[sid]["resources"],
                statements[sid]["conditions"],
            )
            for sid in document_expected
        } == document_expected


def test_development_delivery_direct_api_denials_are_resource_scoped() -> None:
    by_sid = policy_by_sid(
        parsed_policy_document(FOUNDATION_IAM, "development_delivery")
    )
    assert _statement_allows(
        by_sid["ManageApplicationAgentCore"],
        "bedrock-agentcore:UpdateAgentRuntime",
        "local.development_delivery_agentcore_runtime_arn",
    )
    assert not _statement_allows(
        by_sid["ManageApplicationAgentCore"],
        "bedrock-agentcore:UpdateAgentRuntime",
        "arn:aws:bedrock-agentcore:us-east-1:903859731897:runtime/unrelated",
    )
    assert _statement_allows(
        by_sid["PublishApplicationGuardrailVersions"],
        "bedrock:CreateGuardrailVersion",
        "local.development_delivery_guardrail_arn",
    )
    assert not _statement_allows(
        by_sid["PublishApplicationGuardrailVersions"],
        "bedrock:CreateGuardrailVersion",
        "arn:aws:bedrock:us-east-1:903859731897:guardrail/unrelated",
    )
    all_actions = {
        action
        for statement in by_sid.values()
        for action in cast(list[str], statement["actions"])
    }
    pass_role = by_sid["PassExistingAgentCoreRuntimeRole"]
    assert pass_role["actions"] == ["iam:PassRole"]
    assert pass_role["resources"] == [
        "arn:aws:iam::${local.development_delivery_account_id}:role/nova-toll-v2-agentcore-runtime-dev"
    ]
    assert "lambda:UpdateFunctionConfiguration" not in all_actions
    assert by_sid["ManageAgentCoreTraceNamedQuery"]["resources"] == [
        "local.development_delivery_athena_workgroup_arn"
    ]
    assert by_sid["PassAgentCoreTraceLogsRole"]["conditions"] == [
        {
            "test": "StringEquals",
            "variable": "iam:PassedToService",
            "values": ["logs.amazonaws.com"],
        }
    ]
    assert by_sid["PassAgentCoreTraceFirehoseRole"]["conditions"] == [
        {
            "test": "StringEquals",
            "variable": "iam:PassedToService",
            "values": ["firehose.amazonaws.com"],
        }
    ]
    assert "athena:UpdateNamedQuery" not in all_actions
    temporary_sids = {
        "RetireUsagePublisherIam",
        "RetireUsagePublisherLambda",
        "RetireUsagePublisherEvents",
        "RetireUsagePublisherAlarms",
        "RetireAgentUsageRollupIam",
        "RetireAgentUsageRollupLambda",
        "RetireAgentUsageRollupEvents",
        "RetireAgentUsageRollupAlarms",
        "RetireAgentReportsWafLogging",
    }
    assert not temporary_sids & by_sid.keys()
    assert (
        not {
            "iam:DeleteRole",
            "iam:DeleteRolePolicy",
            "lambda:RemovePermission",
            "events:DeleteRule",
            "events:RemoveTargets",
            "cloudwatch:DeleteAlarms",
            "wafv2:DeleteLoggingConfiguration",
        }
        & all_actions
    )
    assert (
        not {
            "sqs:SetQueueAttributes",
            "sqs:AddPermission",
            "sqs:RemovePermission",
            "sqs:TagQueue",
            "sqs:UntagQueue",
        }
        & all_actions
    )
    assert (
        not {
            "ec2:AuthorizeSecurityGroupIngress",
            "ec2:AuthorizeSecurityGroupEgress",
            "ec2:RevokeSecurityGroupIngress",
            "ec2:RevokeSecurityGroupEgress",
        }
        & all_actions
    )
    assert (
        not {
            "events:PutRule",
            "logs:PutMetricFilter",
            "wafv2:PutLoggingConfiguration",
        }
        & all_actions
    )
    assert _statement_allows(
        by_sid["UpdateReportPublisherInlinePolicy"],
        "iam:PutRolePolicy",
        "arn:aws:iam::${local.development_delivery_account_id}:role/toll-v2-report-publisher-dev",
    )
    assert not _statement_allows(
        by_sid["UpdateReportPublisherInlinePolicy"],
        "iam:PutRolePolicy",
        "arn:aws:iam::903859731897:role/unrelated-dev",
    )
    assert _statement_allows(
        by_sid["UpdateReportGenerationFreshnessAlarm"],
        "cloudwatch:PutMetricAlarm",
        "arn:aws:cloudwatch:${local.development_delivery_region}:${local.development_delivery_account_id}:alarm:toll-v2-report-generation-freshness-dev",
    )
    assert not _statement_allows(
        by_sid["UpdateReportGenerationFreshnessAlarm"],
        "cloudwatch:PutMetricAlarm",
        "arn:aws:cloudwatch:us-east-1:903859731897:alarm:unrelated-dev",
    )
    assert _statement_allows(
        by_sid["UpdateApplicationLambdaFunctions"],
        "lambda:UpdateFunctionCode",
        "local.development_delivery_lambda_resources",
    )
    assert not _statement_allows(
        by_sid["UpdateApplicationLambdaFunctions"],
        "lambda:UpdateFunctionCode",
        "arn:aws:lambda:us-east-1:903859731897:function:unrelated-dev",
    )
    assert _statement_allows(
        by_sid["ManageApplicationCloudFront"],
        "cloudfront:UpdateFunction",
        "arn:aws:cloudfront::${local.development_delivery_account_id}:function/tollchat-v2-public-chat-routes-dev",
    )
    assert not _statement_allows(
        by_sid["ManageApplicationCloudFront"],
        "cloudfront:UpdateFunction",
        "arn:aws:cloudfront::903859731897:function/unrelated-dev",
    )
    assert _statement_allows(
        by_sid["ManageApplicationSiteBuckets"],
        "s3:PutObject",
        "${local.development_delivery_site_bucket_arn}/*",
    )
    for action in (
        "s3:DeleteObject",
        "s3:PutBucketVersioning",
        "s3:PutLifecycleConfiguration",
    ):
        assert not _statement_allows(
            by_sid["ManageApplicationSiteBuckets"],
            action,
            "${local.development_delivery_site_bucket_arn}/*",
        )
    assert not _statement_allows(
        by_sid["ManageApplicationSiteBuckets"],
        "s3:PutObject",
        "arn:aws:s3:::unrelated-development-site/*",
    )
    assert not any(
        resource.endswith("/key/*")
        for statement in by_sid.values()
        for resource in cast(list[str], statement["resources"])
    )


def test_agentcore_trace_iam_is_exact_scoped_and_production_excluded(
    rendered_development_delivery_policies: tuple[
        dict[str, dict[str, object]], list[dict[str, object]], dict[str, object]
    ],
) -> None:
    delivery = policy_by_sid(
        parsed_policy_document(FOUNDATION_IAM, "development_delivery")
    )
    assert {
        sid: (
            delivery[sid]["actions"],
            delivery[sid]["resources"],
            delivery[sid]["conditions"],
        )
        for sid in (
            "ReadAgentCoreTraceSubscription",
            "ReadAgentCoreTraceRoles",
            "ReadAgentCoreTraceFirehose",
        )
    } == {
        "ReadAgentCoreTraceSubscription": (
            ["logs:DescribeSubscriptionFilters"],
            [
                'for arn in local.development_delivery_agentcore_trace_log_group_arns : "${arn}:*"'
            ],
            [],
        ),
        "ReadAgentCoreTraceRoles": (
            [
                "iam:GetRole",
                "iam:GetRolePolicy",
                "iam:ListAttachedRolePolicies",
                "iam:ListRolePolicies",
                "iam:ListRoleTags",
            ],
            [
                "local.development_delivery_agentcore_trace_logs_role_arn",
                "local.development_delivery_agentcore_trace_firehose_role_arn",
            ],
            [],
        ),
        "ReadAgentCoreTraceFirehose": (
            [
                "firehose:DescribeDeliveryStream",
                "firehose:ListTagsForDeliveryStream",
            ],
            ["local.development_delivery_agentcore_trace_firehose_arn"],
            [],
        ),
    }
    _assert_agentcore_trace_identity_reads(FOUNDATION_IAM)
    trace_actions = {
        action
        for sid in {
            "ReadAgentCoreTraceSubscription",
            "ReadAgentCoreTraceRoles",
            "ReadAgentCoreTraceFirehose",
            "ManageAgentCoreTraceSubscriptions",
            "ManageAgentCoreTraceFirehose",
            "ManageAgentCoreTraceRuntimePolicy",
            "PassAgentCoreTraceLogsRole",
            "PassAgentCoreTraceFirehoseRole",
            "ManageAgentCoreTraceRetention",
            "ManageAgentCoreTraceCatalog",
            "ManageAgentCoreTraceNamedQuery",
        }
        for action in cast(list[str], delivery[sid]["actions"])
    }
    assert {
        "logs:PutSubscriptionFilter",
        "logs:DeleteSubscriptionFilter",
        "firehose:CreateDeliveryStream",
        "firehose:DeleteDeliveryStream",
        "firehose:TagDeliveryStream",
        "firehose:UpdateDestination",
        "s3:PutLifecycleConfiguration",
        "glue:CreateTable",
        "glue:DeleteTable",
        "glue:UpdateTable",
        "athena:CreateNamedQuery",
        "athena:DeleteNamedQuery",
        "iam:PassRole",
    } <= trace_actions
    assert "logs:PutResourcePolicy" not in trace_actions
    production = top_level_terraform_block(FOUNDATION_IAM, "locals", 3)
    assert "development_delivery_trace_statement_sids = toset" in production
    for sid in {
        "ReadAgentCoreTraceSubscription",
        "ReadAgentCoreTraceRoles",
        "ReadAgentCoreTraceFirehose",
        "ManageAgentCoreTraceSubscriptions",
        "ManageAgentCoreTraceFirehose",
        "ManageAgentCoreTraceRuntimePolicy",
        "PassAgentCoreTraceLogsRole",
        "PassAgentCoreTraceFirehoseRole",
        "ManageAgentCoreTraceRetention",
        "ManageAgentCoreTraceCatalog",
        "ManageAgentCoreTraceNamedQuery",
    }:
        assert f'"{sid}"' in production
    assert "production_delivery_trace_role_arns" not in production
    role_discovery = hcl_attribute(
        top_level_terraform_block(FOUNDATION_IAM, "locals", 0),
        "development_delivery_role_names",
    )
    assert "nova-toll-v2-agentcore-traces-logs-dev" not in role_discovery
    assert "nova-toll-v2-agentcore-traces-firehose-dev" not in role_discovery
    _, rendered_delivery, foundation = rendered_development_delivery_policies
    _assert_agentcore_trace_foundation_source(FOUNDATION_IAM)
    _assert_agentcore_trace_bucket_key_contract(FOUNDATION_IAM, MEASUREMENT_INFRA)
    _assert_agentcore_trace_resource_headers(FOUNDATION_IAM)
    assert foundation["logs_assume"] == {
        "Statement": [
            {
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringLike": {
                        "aws:SourceArn": [
                            "arn:aws:logs:us-east-1:903859731897:log-group:/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-DEFAULT",
                            "arn:aws:logs:us-east-1:903859731897:log-group:/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-preview",
                            "arn:aws:logs:us-east-1:903859731897:log-group:/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-DEFAULT:*",
                            "arn:aws:logs:us-east-1:903859731897:log-group:/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-preview:*",
                        ]
                    },
                    "StringEquals": {"aws:SourceAccount": "903859731897"},
                },
                "Effect": "Allow",
                "Principal": {"Service": "logs.amazonaws.com"},
            }
        ],
        "Version": "2012-10-17",
    }
    assert foundation["logs"] == {
        "Statement": [
            {
                "Action": "firehose:PutRecord",
                "Effect": "Allow",
                "Resource": "arn:aws:firehose:us-east-1:903859731897:deliverystream/nova-toll-v2-agentcore-traces-dev",
            }
        ],
        "Version": "2012-10-17",
    }
    assert foundation["firehose_assume"] == {
        "Statement": [
            {
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"sts:ExternalId": "903859731897"}},
                "Effect": "Allow",
                "Principal": {"Service": "firehose.amazonaws.com"},
            }
        ],
        "Version": "2012-10-17",
    }
    assert foundation["firehose"] == {
        "Statement": [
            {
                "Action": [
                    "s3:ListBucketMultipartUploads",
                    "s3:ListBucket",
                    "s3:GetBucketLocation",
                ],
                "Effect": "Allow",
                "Resource": "arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-903859731897-dev",
            },
            {
                "Action": ["s3:PutObject", "s3:GetObject", "s3:AbortMultipartUpload"],
                "Effect": "Allow",
                "Resource": "arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-903859731897-dev/agentcore-traces/*",
            },
            {
                "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
                "Condition": {
                    "StringEquals": {
                        "kms:EncryptionContext:aws:s3:arn": "arn:aws:s3:::aws-waf-logs-tollchat-agent-reports-903859731897-dev",
                        "kms:ViaService": "s3.us-east-1.amazonaws.com",
                    },
                },
                "Effect": "Allow",
                "Resource": "arn:aws:kms:us-east-1:903859731897:key/076e8341-894b-405c-96e9-2b037f96e2a6",
            },
        ],
        "Version": "2012-10-17",
    }
    for name in (
        "development_agentcore_trace_logs",
        "development_agentcore_trace_firehose",
    ):
        role = terraform_block(FOUNDATION_IAM, f'resource "aws_iam_role" "{name}"')
        policy = terraform_block(
            FOUNDATION_IAM, f'resource "aws_iam_role_policy" "{name}"'
        )
        assert 'count                = var.environment == "development" ? 1 : 0' in role
        assert 'count  = var.environment == "development" ? 1 : 0' in policy
    assert (
        FOUNDATION_IAM.count('resource "aws_iam_role" "development_agentcore_trace_')
        == 2
    )
    assert (
        FOUNDATION_IAM.count(
            'resource "aws_iam_role_policy" "development_agentcore_trace_'
        )
        == 2
    )
    rendered_delivery_by_sid = {
        statement["Sid"]: statement for statement in rendered_delivery
    }
    assert {
        sid: {
            key: rendered_delivery_by_sid[sid].get(key)
            for key in ("Action", "Resource", "Condition")
        }
        for sid in (
            "ReadAgentCoreTraceSubscription",
            "ReadAgentCoreTraceFirehose",
        )
    } == {
        "ReadAgentCoreTraceSubscription": {
            "Action": "logs:DescribeSubscriptionFilters",
            "Resource": [
                "arn:aws:logs:us-east-1:903859731897:log-group:/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-preview:*",
                "arn:aws:logs:us-east-1:903859731897:log-group:/aws/bedrock-agentcore/runtimes/nova_toll_v2_development-Y69XBf88Bl-DEFAULT:*",
            ],
            "Condition": None,
        },
        "ReadAgentCoreTraceFirehose": {
            "Action": [
                "firehose:ListTagsForDeliveryStream",
                "firehose:DescribeDeliveryStream",
            ],
            "Resource": "arn:aws:firehose:us-east-1:903859731897:deliverystream/nova-toll-v2-agentcore-traces-dev",
            "Condition": None,
        },
    }
    for marker, original, replacement in (
        (
            'data "aws_iam_policy_document" "development_agentcore_trace_logs_assume"',
            "logs.amazonaws.com",
            "lambda.amazonaws.com",
        ),
        (
            'data "aws_iam_policy_document" "development_agentcore_trace_logs_assume"',
            '[for arn in local.development_delivery_agentcore_trace_log_group_arns : "${arn}:*"]',
            '["*"]',
        ),
        (
            'data "aws_iam_policy_document" "development_agentcore_trace_logs_assume"',
            "local.development_delivery_account_id",
            '"000000000000"',
        ),
        (
            'data "aws_iam_policy_document" "development_agentcore_trace_firehose_assume"',
            "local.development_delivery_account_id",
            '"000000000000"',
        ),
        (
            'data "aws_iam_policy_document" "development_agentcore_trace_logs"',
            "local.development_delivery_agentcore_trace_firehose_arn",
            '"arn:aws:firehose:us-east-1:903859731897:deliverystream/unrelated"',
        ),
        (
            'data "aws_iam_policy_document" "development_agentcore_trace_firehose"',
            "/agentcore-traces/*",
            "/*",
        ),
        (
            'data "aws_iam_policy_document" "development_agentcore_trace_firehose"',
            "local.development_delivery_measurement_key_arn",
            '"arn:aws:kms:us-east-1:903859731897:key/unrelated"',
        ),
        (
            'data "aws_iam_policy_document" "development_agentcore_trace_firehose"',
            "kms:ViaService",
            "kms:EncryptionContext:wrong",
        ),
        (
            'data "aws_iam_policy_document" "development_agentcore_trace_firehose"',
            "StringEquals",
            "StringLike",
        ),
        (
            'data "aws_iam_policy_document" "development_agentcore_trace_firehose"',
            "local.development_delivery_measurement_bucket_arn",
            '"arn:aws:s3:::wrong-bucket"',
        ),
        (
            'data "aws_iam_policy_document" "development_agentcore_trace_firehose"',
            "s3:GetObject",
            "s3:DeleteObject",
        ),
    ):
        must_reject_after_marker(
            _assert_agentcore_trace_foundation_source,
            FOUNDATION_IAM,
            marker,
            original,
            replacement,
        )
    must_reject_after_marker(
        lambda source: _assert_agentcore_trace_bucket_key_contract(
            source, MEASUREMENT_INFRA
        ),
        FOUNDATION_IAM,
        'data "aws_iam_policy_document" "development_agentcore_trace_firehose"',
        "kms:EncryptionContext:aws:s3:arn",
        "kms:EncryptionContext:wrong",
    )
    must_reject(
        lambda source: _assert_agentcore_trace_bucket_key_contract(
            FOUNDATION_IAM, source
        ),
        MEASUREMENT_INFRA,
        "bucket_key_enabled = true",
        "bucket_key_enabled = false",
    )
    must_reject(
        lambda source: _assert_agentcore_trace_bucket_key_contract(
            FOUNDATION_IAM, source
        ),
        MEASUREMENT_INFRA,
        "bucket_key_enabled = true",
        "",
    )
    must_reject_after_marker(
        _assert_agentcore_trace_foundation_source,
        FOUNDATION_IAM,
        'data "aws_iam_policy_document" "development_agentcore_trace_logs_assume"',
        '["logs.amazonaws.com"]',
        '["logs.amazonaws.com", "lambda.amazonaws.com"]',
    )
    must_reject_after_marker(
        _assert_agentcore_trace_resource_headers,
        FOUNDATION_IAM,
        'resource "aws_iam_role" "development_agentcore_trace_logs"',
        'var.environment == "development"',
        "true",
    )
    for resource_type, label in (
        ("aws_iam_role", "arbitrary_role"),
        ("aws_iam_role_policy", "arbitrary_policy"),
        ("aws_kms_key", "arbitrary_key"),
    ):
        with pytest.raises(AssertionError):
            _assert_agentcore_trace_resource_headers(
                FOUNDATION_IAM + f'\nresource "{resource_type}" "{label}" {{}}\n'
            )
    with pytest.raises(AssertionError):
        _assert_agentcore_trace_resource_headers(
            FOUNDATION_IAM
            + '\nresource "aws_glue_catalog_table" "agentcore_traces" {}\n'
        )
    for resource_type in (
        "aws_cloudwatch_log_subscription_filter",
        "aws_cloudwatch_log_resource_policy",
        "aws_kinesis_firehose_delivery_stream",
        "aws_athena_named_query",
        "aws_s3_bucket_lifecycle_configuration",
    ):
        with pytest.raises(AssertionError):
            _assert_agentcore_trace_resource_headers(
                FOUNDATION_IAM
                + f'\nresource "{resource_type}" "arbitrary_label" {{}}\n'
            )
    for document in ("development_delivery", "development_plan"):
        must_reject_after_marker(
            _assert_agentcore_trace_identity_reads,
            FOUNDATION_IAM,
            f'data "aws_iam_policy_document" "{document}"',
            "logs:DescribeSubscriptionFilters",
            "logs:PutSubscriptionFilter",
        )


def test_development_delivery_policy_set_is_deterministic_and_bounded(
    rendered_development_delivery_policies: tuple[
        dict[str, dict[str, object]], list[dict[str, object]], dict[str, object]
    ],
) -> None:
    statements = parsed_policy_document(FOUNDATION_IAM, "development_delivery")
    assert len(statements) == 67
    expected_groups = {
        "state": (
            0,
            7,
            [
                "ListDevelopmentState",
                "ReadDevelopmentFoundationState",
                "ManageDevelopmentApplicationState",
                "ManageDevelopmentApplicationLock",
                "DecryptDevelopmentState",
                "WriteDevelopmentStateDataKeys",
                "ReadPreprovisionedApplicationRoles",
            ],
        ),
        "compute": (
            7,
            13,
            [
                "ReadApplicationLambdaFunctions",
                "UpdateApplicationLambdaFunctions",
                "PublishApplicationLambdaVersions",
                "RetireApplicationLambdaVersions",
                "ManageApplicationQueues",
                "ResolveApplicationQueueUrls",
            ],
        ),
        "observability": (
            13,
            19,
            [
                "ManageApplicationEventRules",
                "ReadRetainedRollupEventRule",
                "ManageApplicationLogs",
                "ReadRetainedRollupLogGroup",
                "DescribeApplicationLogPolicies",
                "DescribeApplicationLogGroups",
            ],
        ),
        "trace": (
            19,
            30,
            [
                "ReadAgentCoreTraceSubscription",
                "ReadAgentCoreTraceRoles",
                "ReadAgentCoreTraceFirehose",
                "ManageAgentCoreTraceSubscriptions",
                "ManageAgentCoreTraceFirehose",
                "ManageAgentCoreTraceRuntimePolicy",
                "PassAgentCoreTraceLogsRole",
                "PassAgentCoreTraceFirehoseRole",
                "ManageApplicationAlarms",
                "ReadRetainedRollupAlarms",
                "DescribeApplicationNetworking",
            ],
        ),
        "storage": (
            30,
            36,
            [
                "ManageApplicationSiteBuckets",
                "ManageApplicationMeasurementBucket",
                "ManageAgentCoreTraceRetention",
                "ReadRetainedApplicationMeasurementRegistry",
                "PublishApplicationArtifacts",
                "ReadApplicationArtifactBucket",
            ],
        ),
        "data": (
            36,
            46,
            [
                "UseApplicationKmsKeys",
                "ReadRetainedMeasurementKey",
                "ReadApplicationKmsAliases",
                "ManageApplicationSessions",
                "ReadRetainedApplicationCatalog",
                "ManageAgentCoreTraceCatalog",
                "ManageAgentCoreTraceNamedQuery",
                "ReadRetainedApplicationAthenaNamedQueries",
                "ReadRetainedApplicationAthenaWorkGroup",
                "ListApplicationAthenaWorkGroups",
            ],
        ),
        "runtime": (
            46,
            56,
            [
                "ManageApplicationSchedules",
                "PassTimedChecksSchedulerRole",
                "ReadRetiredUsagePublisherIam",
                "ReadRetiredUsagePublisherLambda",
                "ReadRetiredUsagePublisherEvents",
                "ReadRetiredUsagePublisherAlarms",
                "ManageApplicationGuardrail",
                "PublishApplicationGuardrailVersions",
                "ManageApplicationAgentCore",
                "PassExistingAgentCoreRuntimeRole",
            ],
        ),
        "edge": (
            56,
            67,
            [
                "ReadApplicationApiGateway",
                "PublishApplicationApiGatewayDeployments",
                "ManageApplicationCloudFront",
                "ReadApplicationCloudFront",
                "ReadManagedCloudFrontPolicies",
                "ReadManagedCloudFrontPolicy",
                "ManageApplicationWaf",
                "ReadDevelopmentCertificate",
                "UpdateReportPublisherInlinePolicy",
                "UpdateReportGenerationFreshnessAlarm",
                "ReadAlertsKeyForTimedChecks",
            ],
        ),
    }
    rendered_documents, rendered_aggregate, _ = rendered_development_delivery_policies
    assert len(rendered_documents) <= 10
    assert set(rendered_documents) == set(expected_groups) | {"telemetry"}
    assert len(rendered_aggregate) == len(statements) == 67
    rendered_by_sid = {statement["Sid"]: statement for statement in rendered_aggregate}
    assert rendered_by_sid["ReadApplicationKmsAliases"]["Condition"] == {
        "StringEquals": {"aws:RequestedRegion": "us-east-1"}
    }
    assert rendered_by_sid["ReadAlertsKeyForTimedChecks"] == {
        "Action": "kms:DescribeKey",
        "Effect": "Allow",
        "Resource": "arn:aws:kms:us-east-1:903859731897:key/11111111-1111-1111-1111-111111111111",
        "Sid": "ReadAlertsKeyForTimedChecks",
    }
    assert rendered_by_sid["PassExistingAgentCoreRuntimeRole"]["Condition"] == {
        "StringEquals": {"iam:PassedToService": "bedrock-agentcore.amazonaws.com"}
    }
    assert rendered_by_sid["PassTimedChecksSchedulerRole"]["Action"] == "iam:PassRole"
    assert rendered_by_sid["PassTimedChecksSchedulerRole"]["Resource"] == (
        "arn:aws:iam::903859731897:role/nova-toll-v2-timed-checks-scheduler-dev"
    )
    assert rendered_by_sid["PassTimedChecksSchedulerRole"]["Condition"] == {
        "StringEquals": {"iam:PassedToService": "scheduler.amazonaws.com"}
    }
    assert rendered_by_sid["UpdateReportPublisherInlinePolicy"] == {
        "Action": "iam:PutRolePolicy",
        "Effect": "Allow",
        "Resource": "arn:aws:iam::903859731897:role/toll-v2-report-publisher-dev",
        "Sid": "UpdateReportPublisherInlinePolicy",
    }
    assert rendered_by_sid["UpdateReportGenerationFreshnessAlarm"] == {
        "Action": "cloudwatch:PutMetricAlarm",
        "Effect": "Allow",
        "Resource": "arn:aws:cloudwatch:us-east-1:903859731897:alarm:toll-v2-report-generation-freshness-dev",
        "Sid": "UpdateReportGenerationFreshnessAlarm",
    }
    temporary_sids = {
        "RetireUsagePublisherIam",
        "RetireUsagePublisherLambda",
        "RetireUsagePublisherEvents",
        "RetireUsagePublisherAlarms",
        "RetireAgentUsageRollupIam",
        "RetireAgentUsageRollupLambda",
        "RetireAgentUsageRollupEvents",
        "RetireAgentUsageRollupAlarms",
        "RetireAgentReportsWafLogging",
    }
    assert not temporary_sids & rendered_by_sid.keys()
    rendered_actions = {
        action
        for statement in rendered_aggregate
        for action in cast(
            list[str],
            statement["Action"]
            if isinstance(statement["Action"], list)
            else [cast(str, statement["Action"])],
        )
    }
    assert (
        not {
            "iam:DeleteRole",
            "iam:DeleteRolePolicy",
            "lambda:RemovePermission",
            "events:DeleteRule",
            "events:RemoveTargets",
            "cloudwatch:DeleteAlarms",
            "wafv2:DeleteLoggingConfiguration",
        }
        & rendered_actions
    )
    rendered_statements: list[dict[str, object]] = []
    for key, (start, end, expected_sids) in expected_groups.items():
        policy = rendered_documents[key]
        policy_statements = policy.get("Statement")
        assert isinstance(policy_statements, list)
        policy_statements = cast(list[dict[str, object]], policy_statements)
        assert len(policy_statements) == end - start
        rendered_statements.extend(policy_statements)
        assert [
            statement.get("Sid") for statement in policy_statements
        ] == expected_sids
        rendered = json.dumps(policy, separators=(",", ":"))
        assert len(re.sub(r"\s+", "", rendered)) <= 6_144
        assert (
            f"Statement = slice(local.development_delivery_policy_statements, {start}, {end})"
            in FOUNDATION_IAM
        )

    assert rendered_statements == rendered_aggregate
    assert [statement["Sid"] for statement in rendered_statements] == [
        statement["sid"] for statement in statements
    ]
    assert [
        statement["sid"]
        for _, (start, end, _) in expected_groups.items()
        for statement in statements[start:end]
    ] == [statement["sid"] for statement in statements]
    policy_resource = terraform_block(
        FOUNDATION_IAM, 'resource "aws_iam_policy" "development_delivery"'
    )
    assert (
        'for_each = var.environment == "development" ? local.development_delivery_policy_documents : {}'
        in policy_resource
    )
    assert (
        'name     = "nova-toll-v2-development-delivery-${each.key}"' in policy_resource
    )
    assert 'path     = "/nova-toll/v2/development/"' in policy_resource
    assert 'resource "aws_iam_role_policy" "development_delivery"' not in FOUNDATION_IAM
    attachment_resource = terraform_block(
        FOUNDATION_IAM,
        'resource "aws_iam_role_policy_attachment" "development_delivery"',
    )
    assert (
        'for_each   = var.environment == "development" ? local.development_delivery_policy_documents : {}'
        in attachment_resource
    )
    assert (
        "role       = aws_iam_role.development_delivery[0].name" in attachment_resource
    )
    assert (
        "policy_arn = aws_iam_policy.development_delivery[each.key].arn"
        in attachment_resource
    )


def test_production_ci_private_api_grant_preserves_environment_isolation() -> None:
    source = re.sub(r"//[^\n]*", "", SLICE_2A_POLICY)
    policy = json.loads(re.sub(r",\s*([}\]])", r"\1", source))
    assert policy["hosts"]["tollchat-api-production"] == "172.31.225.174"
    grants = [grant for grant in policy["grants"] if grant["src"] == ["tag:ci"]]
    assert grants == [
        {"src": ["tag:ci"], "dst": ["172.31.0.0/16"], "ip": ["tcp:5432"]},
        {"src": ["tag:ci"], "dst": ["tollchat-api-production"], "ip": ["tcp:443"]},
    ]
    tests = {test["src"]: test for test in policy["tests"]}
    assert "tollchat-api-production:443" in tests["tag:ci"]["accept"]
    assert {
        "tollchat-api-production:22",
        "tollchat-api-production:80",
        "nova-toll-rds:443",
        "tollchat-api-development:443",
        "nova-toll-rds-development:5432",
        "tollchat-preview-test:443",
        "8.8.8.8:443",
    } <= set(tests["tag:ci"]["deny"])
    assert "tollchat-api-production:443" in tests["tag:ci-development"]["deny"]


def _slice_2a_policy_sections(source: str) -> tuple[str, str, str]:
    tag_owners = re.search(r'"tagOwners"\s*:\s*\{(.*?)\n\s*\},', source, re.DOTALL)
    auto_approvers = re.search(
        r'"autoApprovers"\s*:\s*\{(.*?)\n\s*\},', source, re.DOTALL
    )
    grants = re.search(r'"grants"\s*:\s*\[(.*?)\n\s*\],', source, re.DOTALL)
    assert tag_owners and auto_approvers and grants
    return tag_owners.group(1), auto_approvers.group(1), grants.group(1)


def _assert_slice_2a_policy(source: str) -> None:
    tag_owners, auto_approvers, grants = _slice_2a_policy_sections(source)
    assert tag_owners.count('"tag:nova-toll-development-router"') == 1
    assert tag_owners.count('"tag:ci-development"') == 1
    assert '"tag:nova-toll-development-router": ["rhprasad0@github"]' in tag_owners
    assert '"tag:ci-development": ["rhprasad0@github"]' in tag_owners
    assert '"tag:nova-toll-router": ["rhprasad0@github"]' in tag_owners
    assert '"tag:ci": ["rhprasad0@github"]' in tag_owners

    assert (
        '"fd7a:115c:a1e0:b1a:0:1:ac1f:0/112": [\n'
        '                "tag:nova-toll-development-router"\n'
        "            ]" in auto_approvers
    )
    assert auto_approvers.count('"fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"') == 1
    assert '"172.31.0.0/16": ["tag:nova-toll-router"]' in auto_approvers
    assert '"exitNode": ["tag:nova-toll-router"]' in source
    assert '"exitNode": ["tag:nova-toll-development-router"]' not in source

    dev_grant = re.search(
        r'\{\s*"src": \["tag:ci-development"\],\s*'
        r'"dst": \["fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"\],\s*'
        r'"ip":  \["tcp:5432"\],\s*\}',
        grants,
        re.DOTALL,
    )
    assert dev_grant is not None
    dev_grant_text = dev_grant.group(0)
    assert "172.31.0.0/16" not in dev_grant_text
    assert "exitNode" not in dev_grant_text
    assert '"src": ["tag:ci"]' in grants
    assert '"dst": ["172.31.0.0/16"]' in grants
    assert '"dst": ["fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"]' in grants
    assert '"ip":  ["tcp:5432"]' in grants
    assert (
        '"nova-toll-rds-development": "fd7a:115c:a1e0:b1a:0:1:ac1f:e1a2/128"' in source
    )
    assert '"nova-toll-rds": "172.31.83.200"' in source


def test_slice_2a_policy_is_scoped_and_preserves_production_entries() -> None:
    _assert_slice_2a_policy(SLICE_2A_POLICY)
    baseline = subprocess.run(
        ["git", "show", "HEAD:infra/policy.hujson"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for production_entry in (
        '"tag:nova-toll-router": ["rhprasad0@github"]',
        '"tag:ci": ["rhprasad0@github"]',
        '"172.31.0.0/16": ["tag:nova-toll-router"]',
        '"exitNode": ["tag:nova-toll-router"]',
        '"src": ["tag:ci"]',
        '"dst": ["172.31.0.0/16"]',
        '"ip":  ["tcp:5432"]',
    ):
        assert production_entry in baseline
        assert production_entry in SLICE_2A_POLICY
    for original, replacement in (
        (
            '"tag:nova-toll-development-router": ["rhprasad0@github"]',
            '"tag:nova-toll-development-router": ["tag:ci-development"]',
        ),
        (
            '"fd7a:115c:a1e0:b1a:0:1:ac1f:0/112": [\n'
            '                "tag:nova-toll-development-router"\n'
            "            ]",
            '"172.31.0.0/16": ["tag:nova-toll-development-router"]',
        ),
        (
            '"src": ["tag:ci-development"]',
            '"src": ["tag:ci"]',
        ),
    ):
        must_reject(_assert_slice_2a_policy, SLICE_2A_POLICY, original, replacement)


def test_slice_3b3a_route_control_contract_is_fixed_and_least_privilege() -> None:
    helper = (
        V2_ROOT / "scripts" / "approve_development_tailscale_route.py"
    ).read_text()
    assert 'SSM_DOCUMENT = "nova-toll-v2-route-control-status-dev"' in helper
    assert "AWS-RunShellScript" not in helper
    assert "--parameters" not in helper
    assert "TS_DEVELOPMENT_ROUTE_OAUTH_CLIENT_ID" in helper
    assert "TS_DEVELOPMENT_ROUTE_OAUTH_SECRET" in helper
    assert "TS_DEVELOPMENT_OAUTH_CLIENT_ID" not in helper
    assert "TS_DEVELOPMENT_OAUTH_SECRET" not in helper
    assert "type(response_code) is not int" in helper
    assert 'scope": OAUTH_SCOPE' in helper
    assert "len(scope_tokens) != len(REQUIRED_SCOPES)" in helper
    assert "route != EXPECTED_ROUTE" in helper
    assert "current.selected != initial.selected" in helper
    assert "expected_enabled_routes = frozenset" in helper
    assert "post_self_id = read_router_node_id" in helper
    assert "expected_enabled_after" in helper
    assert '"devices:routes:read"' in helper

    for declaration in (
        'data "aws_iam_policy_document" "route_control_assume"',
        'resource "aws_ssm_document" "route_control"',
        'resource "aws_iam_role" "route_control"',
        'data "aws_iam_policy_document" "route_control"',
        'resource "aws_iam_role_policy" "route_control"',
    ):
        assert declaration not in MAIN_TF
        assert declaration in FOUNDATION_TAILSCALE

    trust = FOUNDATION_TAILSCALE.split(
        'data "aws_iam_policy_document" "route_control_assume"', maxsplit=1
    )[1].split('resource "aws_ssm_document" "route_control"', maxsplit=1)[0]
    assert "token.actions.githubusercontent.com:aud" in trust
    assert "token.actions.githubusercontent.com:sub" in trust
    assert (
        'values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"]'
        in trust
    )
    assert "token.actions.githubusercontent.com:job_workflow_ref" not in trust

    document = FOUNDATION_TAILSCALE.split(
        'resource "aws_ssm_document" "route_control"', maxsplit=1
    )[1].split('resource "aws_iam_role" "route_control"', maxsplit=1)[0]
    assert 'count           = var.environment == "development" ? 1 : 0' in document
    assert 'name            = "nova-toll-v2-route-control-status-dev"' in document
    assert "tailscale status --json" in document
    assert "set -eu" in document
    assert "parameters" not in document

    role = FOUNDATION_TAILSCALE.split(
        'resource "aws_iam_role" "route_control"', maxsplit=1
    )[1].split('data "aws_iam_policy_document" "route_control"', maxsplit=1)[0]
    assert 'name               = "nova-toll-v2-route-control-dev"' in role
    assert (
        "assume_role_policy = data.aws_iam_policy_document.route_control_assume[0].json"
        in role
    )

    policy = FOUNDATION_TAILSCALE.split(
        'data "aws_iam_policy_document" "route_control"', maxsplit=1
    )[1].split('resource "aws_iam_role_policy" "route_control"', maxsplit=1)[0]
    assert "ssm:SendCommand" in policy
    assert "ssm:GetCommandInvocation" in policy
    assert "nova-toll-v2-route-control-status-dev" in policy
    assert "i-0d33b9a9c15db93fc" in policy
    assert "aws:RequestedRegion" in policy
    assert "ssm:GetParameter" not in policy
    assert "rds:" not in policy
    role_policy = FOUNDATION_TAILSCALE.split(
        'resource "aws_iam_role_policy" "route_control"', maxsplit=1
    )[1]
    assert 'name   = "nova-toll-v2-route-control-dev"' in role_policy
    assert "role   = aws_iam_role.route_control[0].id" in role_policy

    assert "TS_DEVELOPMENT_OAUTH_CLIENT_ID" in DEVELOPMENT_CONNECTIVITY_WORKFLOW
    assert "TS_DEVELOPMENT_OAUTH_SECRET" in DEVELOPMENT_CONNECTIVITY_WORKFLOW
    assert "TS_DEVELOPMENT_ROUTE_OAUTH_CLIENT_ID" in DEVELOPMENT_CONNECTIVITY_WORKFLOW
    assert "TS_DEVELOPMENT_ROUTE_OAUTH_SECRET" in DEVELOPMENT_CONNECTIVITY_WORKFLOW
    assert "nova-toll-v2-route-control-dev" in DEVELOPMENT_CONNECTIVITY_WORKFLOW
    assert DEVELOPMENT_CONNECTIVITY_WORKFLOW.index(
        "TS_DEVELOPMENT_ROUTE_OAUTH_CLIENT_ID"
    ) < DEVELOPMENT_CONNECTIVITY_WORKFLOW.index("nova-toll-v2-timed-checks-dev")
    route_step = DEVELOPMENT_CONNECTIVITY_WORKFLOW.split(
        "- name: Approve development Tailscale route", maxsplit=1
    )[1].split("- uses: aws-actions/configure-aws-credentials", maxsplit=1)[0]
    assert "TS_DEVELOPMENT_OAUTH_" not in route_step
    assert "TS_DEVELOPMENT_ROUTE_OAUTH_" in route_step
    assert "devices:core:read" in DEPLOYMENT
    assert "devices:routes:read" in DEPLOYMENT
    assert "devices:routes" in DEPLOYMENT
    assert "GET /api/v2/tailnet/rhprasad0.github/devices" in DEPLOYMENT
    assert "GET /api/v2/device/<nodeId>/routes" in DEPLOYMENT
    assert "list-supplied route fields are not trusted" in DEPLOYMENT
    assert "irreducible multi-GET sub-request TOCTOU window" in DEPLOYMENT
    assert "devices?fields=all" not in DEPLOYMENT
    assert "auth_keys`-only" in DEPLOYMENT
    assert "list-plus-per-device route reads are not an atomic snapshot" in DEPLOYMENT


def _assert_timed_role_trust_is_environment_conditional(source: str) -> None:
    trust = source.split(
        'data "aws_iam_policy_document" "timed_checks_assume"', maxsplit=1
    )[1].split('resource "aws_iam_role" "timed_checks"', maxsplit=1)[0]
    assert 'variable = "token.actions.githubusercontent.com:aud"' in trust
    assert 'values   = ["sts.amazonaws.com"]' in trust
    assert 'values = var.environment == "development" ? [' in trust
    development_values, production_values = trust.split(
        'values = var.environment == "development" ? [', maxsplit=1
    )[1].split("] : [", maxsplit=1)
    development_subject = "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"
    production_subject = (
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main"
    )
    assert development_values.count(development_subject) == 1
    assert production_subject not in development_values
    assert production_values.count(production_subject) == 1
    assert development_subject not in production_values
    assert "environment:production" not in trust
    assert 'sts:AssumeRole"' not in trust


def test_slice_2b_timed_role_trust_is_environment_conditional_and_adversarial_safe() -> (
    None
):
    _assert_timed_role_trust_is_environment_conditional(MAIN_TF)
    for original, replacement in (
        ('values = var.environment == "development" ? [', "values = ["),
        (
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main",
        ),
        (
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main",
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:production",
        ),
        ('var.environment == "development"', "true"),
    ):
        must_reject(
            _assert_timed_role_trust_is_environment_conditional,
            MAIN_TF,
            original,
            replacement,
        )


def test_slice_2b_timed_role_trust_adds_only_the_development_environment_subject() -> (
    None
):
    trust = MAIN_TF.split(
        'data "aws_iam_policy_document" "timed_checks_assume"', maxsplit=1
    )[1].split('resource "aws_iam_role" "timed_checks"', maxsplit=1)[0]
    assert 'variable = "token.actions.githubusercontent.com:aud"' in trust
    assert 'values   = ["sts.amazonaws.com"]' in trust
    assert 'var.environment == "development"' in trust
    assert (
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main"
        in trust
    )
    assert (
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"
        in trust
    )
    assert "environment:production" not in trust
    assert 'sts:AssumeRole"' not in trust
