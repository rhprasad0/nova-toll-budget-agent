import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from textwrap import dedent
from typing import Any, NoReturn, cast

import pytest
import yaml

from tests.infrastructure_support import (
    CI_WORKFLOW,
    DEPLOYMENT,
    DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW,
    DEVELOPMENT_DELIVERY_WORKFLOW,
    DEVELOPMENT_PLAN_WORKFLOW,
    FOUNDATION_ROOT,
    PRODUCTION_PLAN_WORKFLOW,
    REPO_ROOT,
    RUNBOOK,
    TERRAFORM_WORKFLOW,
    V2_ROOT,
    VERIFY_SCRIPT,
    VERSIONS_TF,
    must_reject,
    workflow_run_source,
    workflow_trigger,
)


def test_ci_installs_proxy_dependencies_once_before_testing() -> None:
    steps = yaml.safe_load(CI_WORKFLOW)["jobs"]["v2-loader"]["steps"]
    assert [step["run"] for step in steps if "verify.sh" in step.get("run", "")] == [
        '../.github/scripts/verify.sh loader "$BASE_REF"'
    ]
    loader = VERIFY_SCRIPT.split("\nloader() (\n", 1)[1].split("\n)\n", 1)[0]
    install = (
        '  if [[ "$event" != pull_request ]]; then\n'
        "    step npm ci --prefix lambdas/chat_proxy\n  fi\n"
    )
    build = "    step ./scripts/build_agentcore_zips.sh\n  fi\n"
    test = "\n  step npm test --prefix lambdas/chat_proxy\n"
    assert loader.index(install) < loader.index(test)
    assert loader.index(build) < loader.index(test)
    assert (
        'npm ci --omit=dev --prefix "$V2_ROOT/lambdas/chat_proxy"'
        in (V2_ROOT / "scripts/build_agentcore_zips.sh").read_text()
    )
    assert not json.loads(
        (V2_ROOT / "lambdas/chat_proxy/package.json").read_text()
    ).get("devDependencies")


def test_v2_pr_validation_has_no_aws_access_or_mutation_commands() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "terraform.yml").read_text()
    for forbidden in (
        "configure-aws-credentials",
        "id-token: write",
        "terraform plan",
        "terraform apply",
        "terraform import",
        "terraform state list",
        "aws sts",
        "ssm get-parameter",
    ):
        assert forbidden not in workflow


def test_delivery_contract_keeps_pr_checks_disposable_and_production_fixed() -> None:
    assert 'backend "s3" {}' in (FOUNDATION_ROOT / "versions.tf").read_text()
    assert 'backend "s3" {}' in VERSIONS_TF
    assert (FOUNDATION_ROOT / "backend.production.hcl").read_text().find(
        'key          = "nova-toll/terraform.tfstate"'
    ) >= 0
    assert (V2_ROOT / "infra" / "backend.production.hcl").read_text().find(
        'key          = "nova-toll/v2/terraform.tfstate"'
    ) >= 0
    assert "postgis/postgis" in CI_WORKFLOW
    assert '.github/scripts/verify.sh database "$SCHEMA_BASE_REF"' in CI_WORKFLOW
    assert "step python3 v2/scripts/check_schema_versions.py" in VERIFY_SCRIPT
    assert "v2/scripts/run_db_tests.sh" in VERIFY_SCRIPT


def test_pull_request_workflows_have_no_production_access() -> None:
    trusted_planner = (
        "rhprasad0/nova-toll-budget-agent/.github/workflows/"
        "v2-development-plan.yml@main"
    )

    def assert_safe_permissions(permissions: object, *, allow_id_token: bool) -> None:
        if isinstance(permissions, str):
            assert permissions != "write-all"
        elif isinstance(permissions, dict):
            permissions = cast(dict[str, object], permissions)
            if not allow_id_token:
                assert permissions.get("id-token") != "write"

    github_token = re.compile(
        r"secrets\s*(?:[.]\s*GITHUB_TOKEN\b|\[\s*['\"]GITHUB_TOKEN['\"]\s*\])"
    )
    assert "secrets" not in github_token.sub("", "${{ secrets [ 'GITHUB_TOKEN' ] }}")
    assert "secrets" in github_token.sub("", "${{ secrets [ 'AWS_KEY' ] }}")
    for workflow_path in (REPO_ROOT / ".github" / "workflows").glob("*.y*ml"):
        workflow = workflow_path.read_text()
        document = yaml.load(workflow, Loader=yaml.BaseLoader)
        assert isinstance(document, dict)
        document = cast(dict[str, object], document)
        triggers = document.get("on")
        if not isinstance(triggers, (str, list, dict)):
            continue
        assert "pull_request_target" not in triggers
        if "pull_request" not in triggers:
            continue
        assert_safe_permissions(document.get("permissions"), allow_id_token=False)
        jobs = document.get("jobs")
        if isinstance(jobs, dict):
            for job in cast(dict[str, object], jobs).values():
                if isinstance(job, dict):
                    job = cast(dict[str, object], job)
                    assert_safe_permissions(
                        job.get("permissions"),
                        allow_id_token=job.get("uses") == trusted_planner,
                    )
        assert not re.search(r"\bsecrets\b", github_token.sub("", workflow))
        for forbidden in (
            "configure-aws-credentials",
            "AWS_PROFILE",
            "environment:",
        ):
            assert forbidden not in workflow


def test_production_release_plan_workflows_keep_trust_before_credentials_and_apply_disabled() -> (
    None
):
    listener = cast(
        dict[str, object],
        yaml.safe_load(
            (
                REPO_ROOT / ".github" / "workflows" / "v2-production-release.yml"
            ).read_text()
        ),
    )
    planner = cast(dict[str, object], yaml.safe_load(PRODUCTION_PLAN_WORKFLOW))
    assert workflow_trigger(listener) == {"release": {"types": ["published"]}}
    assert workflow_trigger(planner) == {
        "workflow_run": {
            "workflows": ["v2-production-release"],
            "types": ["completed"],
        }
    }
    for workflow in (listener, planner):
        assert workflow["concurrency"] == {
            "group": "v2-production-release-delivery",
            "queue": "max",
        }

    listener_source = "\n".join(
        workflow_run_source(job)
        for job in cast(dict[str, dict[str, object]], listener["jobs"]).values()
    )
    assert "aws-actions/configure-aws-credentials@" not in listener_source
    assert "terraform" not in listener_source
    assert (
        "v2-production-release-${{ github.run_id }}-${{ github.run_attempt }}"
        in str(listener)
    )

    jobs = cast(dict[str, dict[str, object]], planner["jobs"])
    assert set(jobs) == {
        "admission",
        "claim",
        "planner",
        "prepare",
        "approve-cutover",
        "migrate",
        "release-result",
    }
    assert jobs["admission"]["permissions"] == {
        "contents": "read",
        "actions": "read",
        "deployments": "read",
    }
    assert jobs["claim"]["permissions"] == {"contents": "read", "deployments": "write"}
    assert jobs["planner"]["permissions"] == {
        "contents": "read",
        "actions": "read",
        "deployments": "read",
        "id-token": "write",
    }
    assert all(
        jobs[name].get("environment") is None
        for name in ("admission", "claim", "planner", "release-result")
    )
    assert str(jobs["migrate"]["uses"]).endswith("v2-production-migrations.yml@main")
    assert jobs["release-result"]["if"] == "${{ always() }}"

    admission_source = workflow_run_source(jobs["admission"])
    claim_source = workflow_run_source(jobs["claim"])
    planner_source = workflow_run_source(jobs["planner"])
    assert (
        "aws-actions/configure-aws-credentials@" not in admission_source + claim_source
    )
    assert "check_production_release.py admit" in admission_source
    assert "check_production_release.py claim" in claim_source
    assert "check_production_release.py revalidate" in planner_source
    planner_steps = cast(list[dict[str, object]], jobs["planner"]["steps"])
    bundle_index = next(
        index
        for index, step in enumerate(planner_steps)
        if step.get("name") == "Verify exact candidate bundle before OIDC"
    )
    revalidation_index = next(
        index
        for index, step in enumerate(planner_steps)
        if step.get("name") == "Revalidate mutable release evidence before OIDC"
    )
    credentials_index = next(
        index
        for index, step in enumerate(planner_steps)
        if str(step.get("uses", "")).startswith(
            "aws-actions/configure-aws-credentials@"
        )
    )
    assert bundle_index < revalidation_index < credentials_index
    assert "terraform apply" not in planner_source
    assert "nova-toll-production-deploy" not in planner_source
    assert "-target" not in planner_source

    for field in (
        "listener_run",
        "listener_attempt",
        "development_run",
        "development_attempt",
        "development_deployment",
        "evidence_artifact",
        "evidence_digest",
        "bundle_id",
        "bundle_digest",
        "schema_versions",
        "claim_id",
        "saved_plan",
        "VersionId",
        "ChecksumSHA256",
        "SSEKMSKeyId",
    ):
        assert field in planner_source


def _assert_development_build_setup_uv(build: dict[str, object]) -> None:
    setup_uv_steps = [
        step
        for step in cast(list[dict[str, object]], build["steps"])
        if cast(str, step.get("uses", "")).startswith("astral-sh/setup-uv@")
    ]
    assert len(setup_uv_steps) == 1
    assert cast(dict[str, str], setup_uv_steps[0]["with"]) == {
        "version": "0.12.5",
        "checksum": "68a509da24b06b4223a1c0175fb5eb5bc79342b76cbeff0cfe51ac3f5b17b6b2",
        "python-version": "3.13",
    }


def test_setup_uv_v10_pins_version_and_checksum() -> None:
    sources = (
        DEVELOPMENT_DELIVERY_WORKFLOW,
        DEVELOPMENT_PLAN_WORKFLOW,
        PRODUCTION_PLAN_WORKFLOW,
    )
    for source in sources:
        workflow = cast(dict[str, object], yaml.safe_load(source))
        jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
        setup_uv_steps = [
            step
            for job in jobs.values()
            for step in cast(list[dict[str, object]], job.get("steps", []))
            if cast(str, step.get("uses", "")).startswith("astral-sh/setup-uv@")
        ]
        assert setup_uv_steps
        for step in setup_uv_steps:
            with_values = cast(dict[str, str], step["with"])
            assert with_values["version"] == "0.12.5"
            assert (
                with_values["checksum"]
                == "68a509da24b06b4223a1c0175fb5eb5bc79342b76cbeff0cfe51ac3f5b17b6b2"
            )


def _assert_development_delivery_caller(source: str) -> None:
    workflow = cast(dict[str, object], yaml.safe_load(source))
    assert workflow_trigger(workflow) == {
        "push": {"branches": ["main"]},
        "workflow_dispatch": None,
    }
    assert workflow["permissions"] == {"contents": "read"}
    # Safe because admission no longer waits on an earlier run inside the lock.
    assert workflow["concurrency"] == {
        "group": "v2-development-delivery-${{ github.ref }}",
        "cancel-in-progress": False,
    }
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    assert set(jobs) == {
        "admission",
        "release-record",
        "build",
        "deploy",
        "release-result",
    }
    record = jobs["release-record"]
    assert record["needs"] == "admission"
    deploy = jobs["deploy"]
    assert (
        deploy["if"]
        == "vars.DEVELOPMENT_DELIVERY_ENABLED == 'true' && github.triggering_actor == github.actor"
    )
    assert (
        deploy["uses"] == "./.github/workflows/v2-development-delivery-privileged.yml"
    )
    assert deploy["needs"] == ["admission", "release-record", "build"]
    assert deploy["permissions"] == {
        "contents": "read",
        "actions": "read",
        "id-token": "write",
    }
    assert "runs-on" not in deploy and "steps" not in deploy
    assert deploy["with"] == {
        "release_artifact_id": "${{ needs.build.outputs.artifact_id }}",
        "release_artifact_digest": "${{ needs.build.outputs.artifact_digest }}",
        "expected_pricing_schema": "${{ needs.build.outputs.pricing_schema }}",
        "expected_oracle_schema": "${{ needs.build.outputs.oracle_schema }}",
        "deployment_id": "${{ needs.release-record.outputs.deployment_id }}",
    }
    assert deploy["secrets"] == {
        "TS_DEVELOPMENT_OAUTH_CLIENT_ID": "${{ secrets.TS_DEVELOPMENT_OAUTH_CLIENT_ID }}",
        "TS_DEVELOPMENT_OAUTH_SECRET": "${{ secrets.TS_DEVELOPMENT_OAUTH_SECRET }}",
    }
    assert jobs["release-result"]["needs"] == [
        "admission",
        "release-record",
        "build",
        "deploy",
    ]
    setup_uv = next(
        step
        for step in cast(list[dict[str, object]], jobs["build"]["steps"])
        if cast(str, step.get("uses", "")).startswith("astral-sh/setup-uv@")
    )
    assert setup_uv["with"] == {
        "version": "0.12.5",
        "checksum": "68a509da24b06b4223a1c0175fb5eb5bc79342b76cbeff0cfe51ac3f5b17b6b2",
        "python-version": "3.13",
    }


def _assert_development_delivery_privileged(source: str) -> None:
    workflow = cast(dict[str, object], yaml.safe_load(source))
    trigger = cast(dict[str, object], workflow_trigger(workflow))
    assert set(trigger) == {"workflow_call"}
    call = cast(dict[str, object], trigger["workflow_call"])
    assert call["inputs"] == {
        name: {"required": True, "type": "string"}
        for name in (
            "release_artifact_id",
            "release_artifact_digest",
            "expected_pricing_schema",
            "expected_oracle_schema",
            "deployment_id",
        )
    }
    assert call["secrets"] == {
        "TS_DEVELOPMENT_OAUTH_CLIENT_ID": {"required": True},
        "TS_DEVELOPMENT_OAUTH_SECRET": {"required": True},
    }
    assert call["outputs"] == {
        "diagnostics": {"value": "${{ jobs.deploy.outputs.diagnostics }}"},
        "verified": {"value": "${{ jobs.deploy.outputs.verified }}"},
        "canary": {"value": "${{ jobs.deploy.outputs.canary }}"},
        "verified_pricing_schema": {
            "value": "${{ jobs.deploy.outputs.verified_pricing_schema }}"
        },
        "verified_oracle_schema": {
            "value": "${{ jobs.deploy.outputs.verified_oracle_schema }}"
        },
    }
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    assert set(jobs) == {"oidc-proof", "deploy"}
    proof = jobs["oidc-proof"]
    assert proof["if"] == "github.ref == 'refs/heads/main'"
    assert proof["environment"] == "development"
    assert proof["permissions"] == {"contents": "read", "id-token": "write"}
    proof_source = workflow_run_source(proof)
    for required in (
        "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
        '"repository": "rhprasad0/nova-toll-budget-agent"',
        "job_workflow_ref",
        "set -euo pipefail",
        "oidc_failure_emitted=0",
        "oidc_fail",
        '"$DEPLOYMENT_ID"',
        "return 125",
        "oidc-cleanup",
    ):
        assert required in proof_source
    cleanup = next(
        step
        for step in cast(list[dict[str, object]], proof["steps"])
        if step.get("name") == "Cleanup OIDC proof diagnostics"
    )
    cleanup_source = cast(str, cleanup["run"])
    assert "if ! rm -f" in cleanup_source and "exit 125" in cleanup_source
    deploy = jobs["deploy"]
    assert deploy["needs"] == "oidc-proof"
    assert (
        deploy["if"]
        == "vars.DEVELOPMENT_DELIVERY_ENABLED == 'true' && vars.DEVELOPMENT_BLUE_GREEN_BOOTSTRAPPED == 'true' && github.triggering_actor == github.actor"
    )
    assert deploy["environment"] == "development"
    assert deploy["concurrency"] == {"group": "v2-development-apply", "queue": "max"}
    deploy_source = workflow_run_source(deploy)
    for required in (
        "backend.development.hcl",
        "build/loader.zip",
    ):
        assert required in deploy_source
    assert deploy_source.count("backend.development.hcl") == 3
    steps = cast(list[dict[str, object]], deploy["steps"])
    credential_indexes = [
        index
        for index, step in enumerate(steps)
        if cast(str, step.get("uses", "")).startswith(
            "aws-actions/configure-aws-credentials@"
        )
    ]
    proof_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Validate protected-main OIDC proof"
    )
    admission_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Recheck admission before credentials"
    )
    assert credential_indexes and admission_index < proof_index < credential_indexes[0]
    terraform = next(
        step
        for step in steps
        if cast(str, step.get("uses", "")).startswith("hashicorp/setup-terraform@")
    )
    assert terraform["with"] == {
        "terraform_wrapper": False,
        "terraform_version": "1.15.8",
    }
    proof_download = next(
        step
        for step in steps
        if step.get("name") == "Download protected-main OIDC proof"
    )
    assert proof_download["with"] == {
        "artifact-ids": "${{ needs.oidc-proof.outputs.artifact_id }}",
        "path": "${{ runner.temp }}",
        "merge-multiple": True,
    }
    assert all(
        "${{ inputs." not in cast(str, step.get("run", ""))
        for job in jobs.values()
        for step in cast(list[dict[str, object]], job.get("steps", []))
    )


def _assert_development_plan_workflow(source: str) -> None:
    workflow = cast(dict[str, object], yaml.safe_load(source))
    assert workflow_trigger(workflow) == {
        "workflow_call": {
            "inputs": {
                "candidate_sha": {
                    "description": "Event-derived lowercase candidate commit SHA.",
                    "required": True,
                    "type": "string",
                }
            },
            "outputs": {
                "plan_result": {
                    "description": "Result of the protected nested plan job.",
                    "value": "${{ jobs.plan.result }}",
                }
            },
        }
    }
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    assert set(jobs) == {"build", "plan"}
    build = jobs["build"]
    plan = jobs["plan"]
    assert build["permissions"] == {"contents": "read"}
    assert "environment" not in build
    _assert_development_build_setup_uv(build)
    build_source = workflow_run_source(build)
    assert "aws-actions/configure-aws-credentials@" not in build_source
    assert "id-token: write" not in build_source
    assert "role-to-assume" not in build_source
    assert "EVENT_SHA" in build_source
    assert "INPUT_SHA" in build_source
    assert "github.event.pull_request.head.sha" in source
    assert "github.event.merge_group.head_sha" in source
    assert "github.sha" in source
    assert "refs/pull/" in source
    assert "refs/heads/gh-readonly-queue/" in source
    assert "refs/heads/main" in source
    assert 'test "$INPUT_SHA" = "$EVENT_SHA"' in source
    assert "candidate_sha" in build_source
    assert "persist-credentials: false" in source
    assert (
        "PACKAGE_NAMES=(agentcore.zip chat-proxy.zip loader.zip publisher.zip)"
        in build_source
    )
    for package in (
        "loader.zip",
        "publisher.zip",
        "agentcore.zip",
        "chat-proxy.zip",
    ):
        assert package in build_source
    assert "DEPLOYMENT_SHA256SUMS" in build_source
    assert 'sha256sum "${PACKAGE_NAMES[@]}" > DEPLOYMENT_SHA256SUMS' in build_source
    assert (
        "awk '{print $2}' DEPLOYMENT_SHA256SUMS | LC_ALL=C sort | tr '\\n' ' '"
        in build_source
    )
    assert 'PACKAGE_STAGE="$RUNNER_TEMP/v2-development-packages"' in build_source
    assert 'mkdir -m 700 -- "$PACKAGE_STAGE"' in build_source
    assert 'cp -P -- "$source" "$PACKAGE_STAGE/$package"' in build_source
    assert 'find "$PACKAGE_STAGE" -mindepth 1 -maxdepth 1 -printf' in build_source
    assert (
        'sha256sum --check "$GITHUB_WORKSPACE/v2/infra/build/DEPLOYMENT_SHA256SUMS"'
        in build_source
    )
    assert "trusted-build/infra/release_manifest.py" in build_source
    assert '--repo-root "$GITHUB_WORKSPACE"' in build_source
    assert "--write-evidence" in build_source
    assert "development-release-manifest.json" in build_source
    assert "development-release-evidence.json" in build_source
    assert "path: trusted-build" in source
    assert (
        'git show "${CANDIDATE_SHA}:infra/development-release-manifest.json"'
        in build_source
    )
    assert (
        'git show "${CANDIDATE_SHA}:v2/scripts/shared-package-compatibility.json"'
        in build_source
    )
    assert '>"$EVIDENCE_DIR/shared-package-compatibility.json"' in build_source
    assert (
        'git show "${CANDIDATE_SHA}:v2/agent/public-report-routes.js"' in build_source
    )
    assert '--report-routes "$EVIDENCE_DIR/public-report-routes.js"' in build_source
    assert "cp -P -- v2/infra/build/DEPLOYMENT_SHA256SUMS" in build_source
    assert (
        source.index("Build reviewed deployment packages")
        < source.index("Checkout trusted manifest verifier after candidate build")
        < source.index("Verify reviewed manifest and write runtime evidence")
    )
    uploads = [
        step
        for step in cast(list[dict[str, object]], build["steps"])
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert {cast(dict[str, str], step["with"])["name"] for step in uploads} == {
        "v2-development-packages-${{ github.run_id }}-${{ steps.resolve.outputs.candidate_sha }}",
        "v2-development-checksums-${{ github.run_id }}-${{ steps.resolve.outputs.candidate_sha }}",
    }

    assert plan["needs"] == "build"
    assert plan["environment"] == "development-plan"
    assert plan["permissions"] == {"contents": "read", "id-token": "write"}
    plan_source = workflow_run_source(plan)
    assert "nova-toll-v2-development-plan" in source
    assert "903859731897" in plan_source
    assert "aws-region: us-east-1" in source
    assert "job.workflow_repository" in source
    assert "job.workflow_sha" in source
    assert "job.workflow_ref" in source
    assert "job.workflow_file_path" in source
    assert "path: trusted" in source
    assert source.count("repository: ${{ job.workflow_repository }}") == 2
    assert source.count("ref: ${{ job.workflow_sha }}") == 2
    assert (
        "v2-development-packages-${{ github.run_id }}-${{ needs.build.outputs.candidate_sha }}"
        in source
    )
    assert (
        "v2-development-checksums-${{ github.run_id }}-${{ needs.build.outputs.candidate_sha }}"
        in source
    )
    assert "artifact-ids:" not in plan_source
    assert "download-artifact" in source
    assert "trusted/infra/release_manifest.py" in plan_source
    assert "--evidence" in plan_source
    assert '--report-routes "$STAGING/public-report-routes.js"' in plan_source
    assert 'cp -P -- "$STAGING/public-report-routes.js"' in plan_source
    assert '"$GITHUB_WORKSPACE/trusted/v2/agent/public-report-routes.js"' in plan_source
    assert "--repo-root" not in plan_source
    assert 'test ! -L "$MANIFEST"' in plan_source
    assert (
        "PACKAGE_NAMES=(agentcore.zip chat-proxy.zip loader.zip publisher.zip)"
        in plan_source
    )
    assert (
        "find \"$STAGING\" -mindepth 1 -maxdepth 1 -name '*.zip' -printf" in plan_source
    )
    assert 'test "$(wc -l <"$CHECKSUMS")" -eq 4' in plan_source
    assert 'sha256sum --check "$(basename "$CHECKSUMS")"' in plan_source
    assert source.index(
        "Verify candidate release binding without credentials"
    ) < source.index("aws-actions/configure-aws-credentials@")
    assert (
        source.index('--report-routes "$STAGING/public-report-routes.js"')
        < source.index('cp -P -- "$STAGING/public-report-routes.js"')
        < source.index("aws-actions/configure-aws-credentials@")
    )
    plan_start = source.index("\n  plan:\n")
    credential_index = source.index(
        "aws-actions/configure-aws-credentials@", plan_start
    )
    for boundary in (
        "find \"$STAGING\" -mindepth 1 -maxdepth 1 -name '*.zip'",
        'sha256sum --check "$(basename "$CHECKSUMS")"',
        "python3 trusted/infra/release_manifest.py",
    ):
        boundary_index = source.index(boundary, plan_start)
        assert plan_start < boundary_index < credential_index
    assert 'terraform_version: "1.15.8"' in source
    assert plan_source.count("-lockfile=readonly") == 2
    assert "-lock=false" in plan_source
    assert (
        plan_source.count('terraform -chdir="$GITHUB_WORKSPACE/trusted/v2/infra" plan')
        == 1
    )
    assert (
        'terraform -chdir="$GITHUB_WORKSPACE/trusted/v2/infra" show -json "$PLAN"'
        in plan_source
    )
    assert (
        'terraform -chdir="$GITHUB_WORKSPACE/trusted/v2/infra" apply' not in plan_source
    )
    for package_variable in (
        "loader_package_path",
        "publisher_package_path",
    ):
        assert f"-var {package_variable}" in plan_source
    assert (
        'cp "$STAGING/"*.zip "$GITHUB_WORKSPACE/trusted/v2/infra/build/"' in plan_source
    )
    for variable, package in (
        ("loader", "loader"),
        ("publisher", "publisher"),
    ):
        assert f"-var {variable}_package_path=build/{package}.zip" in plan_source
    assert "development-release-manifest.json" in plan_source
    assert "delivery_plan_validator.py" in plan_source
    assert (
        '--compatibility-review "$STAGING/shared-package-compatibility.json"'
        in plan_source
    )
    assert '"$GITHUB_WORKSPACE/trusted/infra/delivery_plan_validator.py"' in plan_source
    assert "GITHUB_STEP_SUMMARY" in plan_source
    assert '"$VALIDATION" | tee -a "$GITHUB_STEP_SUMMARY"' in plan_source
    assert (
        'FOUNDATION_VALIDATE_LOG="$RUNNER_TEMP/development-foundation-validate.log"'
        in plan_source
    )
    assert '2>"$FOUNDATION_VALIDATE_LOG"' in plan_source
    assert 'type == "object"' in plan_source
    assert "trap cleanup EXIT" in plan_source
    assert (
        "unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN" in plan_source
    )
    assert '"$PLAN"' in plan_source
    for forbidden in (
        "-target",
        "backend.production.hcl",
        "terraform_remote_state",
        "cloudflare",
        "ssm",
        "secrets",
    ):
        assert forbidden not in plan_source.lower()
    for job in jobs.values():
        for step in cast(list[dict[str, object]], job["steps"]):
            if "uses" in step:
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", cast(str, step["uses"]))
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert (
                    cast(dict[str, object], step["with"])["persist-credentials"]
                    is False
                )


def test_development_plan_workflow_is_reusable_and_fail_closed() -> None:
    _assert_development_plan_workflow(DEVELOPMENT_PLAN_WORKFLOW)
    for original, replacement in (
        ("workflow_call:", "push:"),
        (
            "candidate_sha:\n        description:",
            "candidate_ref:\n        description:",
        ),
        ("environment: development-plan", "environment: development"),
        (
            "role/nova-toll-v2-development-plan",
            "role/nova-toll-v2-development-delivery",
        ),
        (
            "${{ github.run_id }}-${{ needs.build.outputs.candidate_sha }}",
            "${{ github.run_id }}",
        ),
        (
            "repository: ${{ job.workflow_repository }}",
            "repository: ${{ github.repository }}",
        ),
        ("ref: ${{ job.workflow_sha }}", "ref: ${{ github.sha }}"),
        ("-lockfile=readonly", "-lockfile=update"),
        ("-lock=false", "-lock=true"),
        ("trap cleanup EXIT", "trap cleanup RETURN"),
        ('python-version: "3.13"', ""),
        ('python-version: "3.13"', 'python-version: "3.12"'),
    ):
        must_reject(
            _assert_development_plan_workflow,
            DEVELOPMENT_PLAN_WORKFLOW,
            original,
            replacement,
        )


def _assert_required_event_callers(source: str) -> None:
    ci = cast(dict[str, object], yaml.safe_load(source))
    ci_trigger = cast(dict[str, object], workflow_trigger(ci))
    assert ci_trigger["pull_request"] is None
    assert ci_trigger["merge_group"] == {"types": ["checks_requested"]}
    ci_jobs = cast(dict[str, dict[str, object]], ci["jobs"])
    for job_name in ("v2-loader", "v2-database"):
        assert "if" not in ci_jobs[job_name]
    base_expression = (
        "github.event.pull_request.base.sha || "
        "github.event.merge_group.base_sha || github.event.before"
    )
    assert f"SCHEMA_BASE_REF: ${{{{ {base_expression} }}}}" in source
    loader = [
        step
        for step in cast(list[dict[str, object]], ci_jobs["v2-loader"]["steps"])
        if "verify.sh" in str(step.get("run", ""))
    ]
    assert [(step["run"], step["env"]) for step in loader] == [
        (
            '../.github/scripts/verify.sh loader "$BASE_REF"',
            {"BASE_REF": f"${{{{ {base_expression} }}}}"},
        )
    ]
    # v2-loader, frontend-browser and v2-database.
    assert source.count(base_expression) == 3

    caller = ci_jobs["trusted-development-plan"]
    assert (
        caller["uses"] == "rhprasad0/nova-toll-budget-agent/.github/workflows/"
        "v2-development-plan.yml@main"
    )
    assert caller["with"] == {
        "candidate_sha": "${{ github.event.pull_request.head.sha || github.event.merge_group.head_sha }}"
    }
    assert caller["permissions"] == {"contents": "read", "id-token": "write"}
    assert "pull_request" in str(caller["if"])
    assert "merge_group" in str(caller["if"])
    assert "vars.DEVELOPMENT_BLUE_GREEN_BOOTSTRAPPED == 'true'" in str(caller["if"])

    gate = ci_jobs["development-plan"]
    assert gate["if"] == "always()"
    assert gate["needs"] == "trusted-development-plan"
    gate_source = workflow_run_source(gate)
    assert "CALL_RESULT: ${{ needs.trusted-development-plan.result }}" in source
    assert (
        "PLAN_RESULT: ${{ needs.trusted-development-plan.outputs.plan_result }}"
        in source
    )
    assert 'test "$CALL_RESULT" = success' in gate_source
    assert 'test "$PLAN_RESULT" = success' in gate_source

    provenance = ci_jobs["trusted-toolchain-provenance"]
    assert (
        provenance["uses"] == "rhprasad0/nova-toll-budget-agent/.github/workflows/"
        "toolchain-provenance.yml@main"
    )
    assert provenance["permissions"] == {"contents": "read", "attestations": "read"}
    provenance_gate = ci_jobs["toolchain-provenance"]
    assert provenance_gate["if"] == "always()"
    assert provenance_gate["needs"] == "trusted-toolchain-provenance"
    assert 'test "$CALL_RESULT" = success' in workflow_run_source(provenance_gate)
    for job in ci_jobs.values():
        assert "continue-on-error" not in job
        for step in cast(list[dict[str, object]], job.get("steps", [])):
            assert "continue-on-error" not in step

    _assert_terraform_trigger(TERRAFORM_WORKFLOW)


def test_deployed_plan_gate_requires_success_after_bootstrap() -> None:
    workflow = yaml.safe_load(CI_WORKFLOW)
    source = workflow["jobs"]["development-plan"]["steps"][0]["run"]
    for bootstrapped, called, planned, accepted in (
        ("", "skipped", "", True),
        ("true", "skipped", "", False),
        ("true", "success", "failure", False),
        ("true", "success", "success", True),
        ("", "failure", "", False),
    ):
        result = subprocess.run(
            ["bash", "-c", source],
            env={
                **os.environ,
                "GITHUB_EVENT_NAME": "pull_request",
                "BOOTSTRAPPED": bootstrapped,
                "CALL_RESULT": called,
                "PLAN_RESULT": planned,
            },
            capture_output=True,
            check=False,
        )
        assert (result.returncode == 0) == accepted


def _assert_terraform_trigger(source: str) -> None:
    terraform = cast(dict[str, object], yaml.safe_load(source))
    terraform_trigger = cast(dict[str, object], workflow_trigger(terraform))
    assert terraform_trigger["pull_request"] is None
    assert terraform_trigger["merge_group"] == {"types": ["checks_requested"]}
    assert "paths" not in cast(dict[str, object], terraform_trigger["merge_group"])
    assert "paths-ignore" not in source


def test_required_event_callers_are_unfiltered_and_fail_closed() -> None:
    _assert_required_event_callers(CI_WORKFLOW)
    for original, replacement in (
        (
            "pull_request:\n  merge_group:",
            "pull_request:\n    types: [opened]\n  merge_group:",
        ),
        ("merge_group:\n    types: [checks_requested]", "merge_group:"),
        (
            "github.event.pull_request.base.sha || github.event.merge_group.base_sha || github.event.before",
            "github.event.pull_request.base.sha || github.event.before",
        ),
        ("v2-development-plan.yml@main", "v2-development-plan.yml@feature"),
        ("toolchain-provenance.yml@main", "toolchain-provenance.yml@feature"),
        (
            "toolchain-provenance:\n    if: always()",
            "toolchain-provenance:\n    if: success()",
        ),
        (
            "development-plan:\n    if: always()",
            "development-plan:\n    if: success()",
        ),
        ('test "$PLAN_RESULT" = success', 'test "$PLAN_RESULT" = skipped'),
        (
            "v2-loader:\n    runs-on: ubuntu-latest",
            "v2-loader:\n    continue-on-error: true\n    runs-on: ubuntu-latest",
        ),
        (
            "- name: Require successful trusted development plan",
            "- name: Require successful trusted development plan\n        continue-on-error: true",
        ),
    ):
        must_reject(
            _assert_required_event_callers,
            CI_WORKFLOW,
            original,
            replacement,
        )
    must_reject(
        _assert_development_plan_workflow,
        DEVELOPMENT_PLAN_WORKFLOW,
        "value: ${{ jobs.plan.result }}",
        "value: ${{ jobs.build.result }}",
    )
    must_reject(
        _assert_terraform_trigger,
        TERRAFORM_WORKFLOW,
        "pull_request:\n  merge_group:",
        "pull_request:\n    types: [opened]\n  merge_group:",
    )


def test_development_delivery_staging_snippet_accepts_only_verified_package_bytes() -> (
    None
):
    workflow = cast(
        dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW)
    )
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    steps = cast(list[dict[str, object]], jobs["deploy"]["steps"])
    verify_source = cast(
        str,
        next(
            step["run"]
            for step in steps
            if step.get("name")
            == "Verify immutable development release without credentials"
        ),
    )
    staging_start = verify_source.index('rm -rf -- "$STAGED_PACKAGE_DIR"')
    staging_end = verify_source.index(
        "python3 infra/release_manifest.py", staging_start
    )
    staging = verify_source[staging_start:staging_end]

    with tempfile.TemporaryDirectory() as directory_name:
        root = Path(directory_name)
        package_dir = root / "overlay" / "v2" / "infra" / "build"
        package_dir.mkdir(parents=True)
        checksums_dir = root / "checksums"
        checksums_dir.mkdir()
        checksums = checksums_dir / "DEPLOYMENT_SHA256SUMS"
        packages = (
            "loader.zip",
            "publisher.zip",
            "agentcore.zip",
            "chat-proxy.zip",
        )
        for package in packages:
            (package_dir / package).write_bytes(package.encode())
        checksums.write_text(
            "".join(
                f"{hashlib.sha256((package_dir / package).read_bytes()).hexdigest()}  {package}\n"
                for package in packages
            ),
            encoding="ascii",
        )

        mock_bin = root / "bin"
        mock_bin.mkdir()
        mock_cp = mock_bin / "cp"
        mock_cp.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            '/bin/cp "$@"\n'
            'dest="${@: -1}"\n'
            'case "${MODE:-success}" in\n'
            '  tamper) printf tampered >>"$dest" ;;\n'
            '  truncate) : >"$dest" ;;\n'
            '  missing) rm -f -- "$dest" ;;\n'
            '  extra) : >"${STAGED_PACKAGE_DIR}/extra.zip" ;;\n'
            '  staged-symlink) rm -f -- "$dest"; ln -s -- "${PACKAGE_DIR}/loader.zip" "$dest" ;;\n'
            "esac\n",
            encoding="utf-8",
        )
        mock_cp.chmod(0o700)

        def run_staging(mode: str = "success") -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["bash", "-c", "set -euo pipefail\n" + staging],
                env={
                    **os.environ,
                    "PATH": f"{mock_bin}:{os.environ['PATH']}",
                    "PACKAGE_DIR": str(package_dir),
                    "STAGED_PACKAGE_DIR": str(root / "staged"),
                    "EVIDENCE_DIR": str(checksums_dir),
                    "MODE": mode,
                },
                capture_output=True,
                text=True,
                check=False,
            )

        success = run_staging()
        assert success.returncode == 0, success.stderr
        assert sorted(path.name for path in (root / "staged").iterdir()) == sorted(
            packages
        )
        for package in packages:
            assert (root / "staged" / package).read_bytes() == (
                package_dir / package
            ).read_bytes()

        for mode in ("tamper", "truncate", "missing", "extra", "staged-symlink"):
            assert run_staging(mode).returncode != 0, mode
        source = package_dir / "loader.zip"
        source.unlink()
        source.symlink_to(package_dir / "publisher.zip")
        assert run_staging().returncode != 0


def test_development_delivery_private_stage_helper_sanitizes_mock_failures() -> None:
    workflow = cast(
        dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW)
    )
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    steps = cast(list[dict[str, object]], jobs["deploy"]["steps"])
    plan_source = cast(
        str,
        next(
            step["run"]
            for step in steps
            if step.get("name")
            == "Create and gate the saved development plan before migrations"
        ),
    )
    assert "source v2/scripts/run_private_stage.sh" in plan_source
    for stage in (
        "foundation-init",
        "foundation-output",
        "release-init",
        "plan",
        "show",
        "validator",
    ):
        script = (
            "set -euo pipefail\n"
            + "source v2/scripts/run_private_stage.sh\n"
            + '\nmkdir -m 700 -- "$RUNNER_TEMP/logs"\n'
            + f'run_private_stage "{stage}" "$RUNNER_TEMP/logs/stdout" "$RUNNER_TEMP/logs/stderr" bash -c \'printf raw-diagnostic >&2; exit 17\'\n'
        )
        with tempfile.TemporaryDirectory() as directory_name:
            result = subprocess.run(
                ["bash", "-c", script],
                cwd=REPO_ROOT,
                env={**os.environ, "RUNNER_TEMP": directory_name},
                capture_output=True,
                text=True,
                check=False,
            )
        assert result.returncode == 17
        assert result.stdout == ""
        assert result.stderr.splitlines()[0].startswith(
            f"stage={stage} status=start elapsed="
        )
        assert result.stderr.splitlines()[-1].startswith(
            f"stage={stage} status=fail elapsed="
        )
        assert "exit=17 reason=unclassified" in result.stderr
        assert "raw-diagnostic" not in result.stdout + result.stderr

    with tempfile.TemporaryDirectory() as directory_name:
        missing_log = Path(directory_name) / "missing" / "stage.log"
        result = subprocess.run(
            [
                "bash",
                "-c",
                "set -euo pipefail; source v2/scripts/run_private_stage.sh; "
                "set +e; run_private_stage apply $1 $1 bash -c 'printf secret >&2; exit 17'; "
                "status=$?; set -e; printf '%s\\n' \"$status\"",
                "bash",
                str(missing_log),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert result.stdout == "1\n"
        assert "status=fail" in result.stderr
        assert "reason=diagnostic_unavailable" in result.stderr
        assert "secret" not in result.stdout + result.stderr

        invalid = subprocess.run(
            [
                "bash",
                "-c",
                "set -euo pipefail; source v2/scripts/run_private_stage.sh; "
                "set +e; run_private_stage secret-stage /tmp/out /tmp/err true; "
                "status=$?; set -e; printf '%s\\n' \"$status\"",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert invalid.returncode == 0
        assert invalid.stdout == "64\n"
        assert "secret-stage" not in invalid.stdout + invalid.stderr

    with tempfile.TemporaryDirectory() as directory_name:
        root = Path(directory_name)
        (root / "logs").mkdir()
        result = subprocess.run(
            [
                "bash",
                "-c",
                "set -euo pipefail; source v2/scripts/run_private_stage.sh; "
                'run_private_stage plan "$RUNNER_TEMP/logs/out" "$RUNNER_TEMP/logs/err" true',
            ],
            cwd=REPO_ROOT,
            env={
                **os.environ,
                "RUNNER_TEMP": str(root),
                "GITHUB_STEP_SUMMARY": str(root / "missing" / "summary"),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 125
        assert "stage=plan status=fail" in result.stderr
        assert "exit=125 reason=unclassified" in result.stderr
        assert str(root) not in result.stdout + result.stderr


def test_development_delivery_classifier_is_bounded_and_allowlisted() -> None:
    classifier = REPO_ROOT / "v2" / "scripts" / "classify_deployment_error.py"
    cases = {
        "access_denied": "AccessDeniedException: forbidden",
        "expired_credentials": "The security token included in the request is expired",
        "network": "connection reset by peer",
        "dns": "could not resolve host",
        "tls": "x509: certificate verify failed",
        "backend_config": "Error configuring the backend",
        "state_lock": "Error acquiring the state lock",
        "provider_installation": "Failed to install provider",
        "checksum": "doesn't match any of the checksums",
        "malformed_input": "malformed JSON input",
        "unclassified": "a bounded arbitrary failure",
    }
    with tempfile.TemporaryDirectory() as directory_name:
        path = Path(directory_name) / "diagnostic.log"
        for expected, diagnostic in cases.items():
            path.write_text(diagnostic, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(classifier), str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0
            assert result.stdout == f"{expected}\n"
            assert result.stderr == ""

        path.write_text("access deniedish", encoding="utf-8")
        near_match = subprocess.run(
            [sys.executable, str(classifier), str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert near_match.stdout == "unclassified\n"

        path.write_bytes(b"x" * (64 * 1024) + b" AccessDeniedException")
        bounded = subprocess.run(
            [sys.executable, str(classifier), str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert bounded.stdout == "unclassified\n"

        missing = subprocess.run(
            [sys.executable, str(classifier), str(path) + ".missing"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert missing.stdout == "diagnostic_unavailable\n"

        path.write_bytes(b"\xff\xfe")
        unreadable = subprocess.run(
            [sys.executable, str(classifier), str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert unreadable.stdout == "diagnostic_unavailable\n"

        path.write_text(
            "secret-token=do-not-print AccessDeniedException", encoding="utf-8"
        )
        secret = subprocess.run(
            [sys.executable, str(classifier), str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert secret.stdout == "access_denied\n"
        assert "secret-token" not in secret.stdout + secret.stderr


def test_development_delivery_mocked_plan_failures_skip_downstream_and_cleanup(
    tmp_path: Path,
) -> None:
    from scripts import blue_green as gate
    from scripts import release_blue_green as release
    from tests.test_blue_green import previous, slot

    state = previous()
    called: list[Any] = []

    def rejected(*args: object) -> NoReturn:
        called.append(args[1])
        raise gate.Rejected("terraform_failed")

    def staged(_root: Path, _bundle: Path, _expected: dict[str, Any]) -> None:
        pass

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(release, "terraform", rejected)
        patch.setattr(release, "stage_packages", staged)
        with pytest.raises(gate.Rejected):
            release.plan(
                tmp_path,
                tmp_path,
                tmp_path / "foundation.json",
                tmp_path,
                "prepare",
                state,
                gate.desired(state, slot("green", "release2")),
                {},
            )
    assert called == ["plan"]
    assert not (tmp_path / "prepare.tfplan").exists()


def test_development_delivery_apply_readiness_and_cleanup_failures_are_bounded(
    tmp_path: Path,
) -> None:
    workflow = yaml.safe_load(DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW)
    steps = workflow["jobs"]["deploy"]["steps"]
    cleanup = next(
        step for step in steps if step.get("name") == "Cleanup private delivery files"
    )
    assert cleanup["if"] == "always()"
    private = tmp_path / "blue-green"
    private.mkdir()
    (private / "context.json").write_text("private-state")
    (tmp_path / "blue-green-result.json").write_text("private-result")
    result = subprocess.run(
        ["bash", "-c", cleanup["run"]],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_WORKSPACE": str(tmp_path),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not private.exists()
    assert not (tmp_path / "blue-green-result.json").exists()
    assert "private-state" not in result.stdout + result.stderr


def test_development_delivery_extracts_only_validated_migration_after_versions() -> (
    None
):
    workflow = cast(
        dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW)
    )
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    steps = cast(list[dict[str, object]], jobs["deploy"]["steps"])
    source = cast(
        str,
        next(
            step["run"]
            for step in steps
            if step.get("name") == "Extract verified installed schema versions"
        ),
    )
    evidence: dict[str, object] = {
        "account": "903859731897",
        "after": {"pricing": "1.2.3", "oracle": "1.14.0"},
        "applied": list[str](),
        "before": {"pricing": "1.2.3", "oracle": "1.14.0"},
        "commit_sha": "a" * 40,
        "database": "nova_toll_development",
        "github_run_attempt": "2",
        "github_run_id": "123",
        "role": "nova-toll-v2-development-migrations-dev",
        "route": "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112",
        "route_valid": True,
        "runner_run_id": "migration-run",
        "status": "ok",
        "transport_valid": True,
        "user": "schema_migrator_development",
    }

    def run(
        value: Mapping[str, object],
    ) -> tuple[subprocess.CompletedProcess[str], str, bool]:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            output = root / "output"
            summary = root / "summary"
            (root / "v2-development-migrations-evidence.json").write_text(
                json.dumps(value), encoding="utf-8"
            )
            result = subprocess.run(
                ["bash", "-c", source],
                cwd=REPO_ROOT,
                env={
                    **os.environ,
                    "RUNNER_TEMP": str(root),
                    "GITHUB_OUTPUT": str(output),
                    "GITHUB_STEP_SUMMARY": str(summary),
                    "GITHUB_SHA": "a" * 40,
                    "GITHUB_RUN_ID": "123",
                    "GITHUB_RUN_ATTEMPT": "2",
                    "EXPECTED_PRICING_VERSION": "1.2.3",
                    "EXPECTED_ORACLE_VERSION": "1.14.0",
                },
                capture_output=True,
                text=True,
                check=False,
            )
            return (
                result,
                output.read_text() if output.exists() else "",
                output.exists(),
            )

    result, output, exists = run(evidence)
    assert result.returncode == 0, result.stderr
    assert exists
    assert output == "verified_pricing_schema=1.2.3\nverified_oracle_schema=1.14.0\n"
    mutations: tuple[dict[str, object], ...] = (
        {**evidence, "commit_sha": "b" * 40},
        {**evidence, "after": {"pricing": "9.9.9", "oracle": "1.14.0"}},
        {**evidence, "after": "secret malformed evidence"},
    )
    for mutation in mutations:
        result, _, exists = run(mutation)
        assert result.returncode != 0
        assert not exists
        assert "secret malformed evidence" not in result.stdout + result.stderr


def test_slice2_delivery_diagnostics_keep_machine_outputs_and_fixed_labels() -> None:
    delivery = DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW
    migration = (
        REPO_ROOT / "v2/scripts/run_development_migrations_workflow.sh"
    ).read_text(encoding="utf-8")
    for label in (
        "admission-recheck",
        "artifact-download",
        "release-verification",
        "oidc-claims",
        "account-identity",
        "delivery-role",
        "rds-ca",
    ):
        assert label in delivery
    assert "Record deployment and recovery outcomes separately" in delivery
    assert (
        'MIGRATION_STDOUT_LOG="${RUNNER_TEMP}/development-migration-stage.stdout"'
        in migration
    )
    assert (
        'MIGRATION_STDERR_LOG="${RUNNER_TEMP}/development-migration-stage.stderr"'
        in migration
    )
    assert 'DB_TOKEN="$(<"$MIGRATION_STDOUT_LOG")"' not in migration
    assert 'RUNNER_JSON="$(<"$MIGRATION_STDOUT_LOG")"' in migration
    assert "migrations-workflow.yml" not in delivery


def test_retained_artifact_bootstrap_handles_jq_outcomes_without_public_errors(
    tmp_path: Path,
) -> None:
    workflow = cast(dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_WORKFLOW))
    build = cast(dict[str, object], workflow["jobs"])["build"]
    steps = cast(list[dict[str, object]], cast(dict[str, object], build)["steps"])
    source = cast(
        str,
        next(
            step["run"]
            for step in steps
            if step.get("name") == "Reject retained exact release artifact"
        ),
    )
    sha = "a" * 40

    def run_case(
        case: str, *, evaluation_error: bool = False
    ) -> subprocess.CompletedProcess[str]:
        root = tmp_path / case
        mock_bin = root / "bin"
        mock_bin.mkdir(parents=True)
        curl = mock_bin / "curl"
        curl.write_text(
            "#!/usr/bin/env bash\n"
            "if test \"$ARTIFACT_CASE\" = malformed; then printf 'not-json\\n';\n"
            'elif test "$ARTIFACT_CASE" = retained; then printf \'{"artifacts":[{"name":"v2-development-release-%s","expired":false}]}\\n\' "$GITHUB_SHA";\n'
            "else printf '{\"artifacts\":[]}\\n'; fi\n",
            encoding="utf-8",
        )
        curl.chmod(0o700)
        if evaluation_error:
            jq = mock_bin / "jq"
            jq.write_text(
                "#!/usr/bin/env bash\n"
                'count_file="$RUNNER_TEMP/jq-count"\n'
                'count=0; test -e "$count_file" && count="$(<"$count_file")"\n'
                'count=$((count + 1)); printf "%s" "$count" >"$count_file"\n'
                'if test "$count" -eq 2; then printf "private-evaluation-error\\n" >&2; exit 2; fi\n'
                "exit 0\n",
                encoding="utf-8",
            )
            jq.chmod(0o700)
        summary = root / "summary"
        result = subprocess.run(
            ["bash", "-c", source],
            cwd=REPO_ROOT,
            env={
                **os.environ,
                "PATH": f"{mock_bin}:{os.environ['PATH']}",
                "RUNNER_TEMP": str(root),
                "GITHUB_STEP_SUMMARY": str(summary),
                "GITHUB_REPOSITORY": "rhprasad0/nova-toll-budget-agent",
                "GITHUB_SHA": sha,
                "GH_TOKEN": "test-token",
                "ARTIFACT_CASE": case,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert not (root / "release-artifacts.json").exists()
        assert not (root / "release-artifacts.error").exists()
        return result

    no_match = run_case("no-match")
    assert no_match.returncode == 0
    assert "stage=retained-artifact status=pass" in no_match.stderr

    retained = run_case("retained")
    assert retained.returncode == 1
    assert "reason=retained_artifact" in retained.stderr

    malformed = run_case("malformed")
    assert malformed.returncode != 0
    assert "reason=malformed_evidence" in malformed.stderr
    assert "jq: parse error" not in malformed.stdout + malformed.stderr

    evaluation = run_case("evaluation", evaluation_error=True)
    assert evaluation.returncode == 2
    assert "reason=malformed_evidence" in evaluation.stderr
    assert "private-evaluation-error" not in evaluation.stdout + evaluation.stderr


def test_development_delivery_plan_preflight_uses_shared_validator_and_exact_plan() -> (
    None
):
    workflow = yaml.safe_load(DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW)
    steps = workflow["jobs"]["deploy"]["steps"]
    sources = [step.get("run", "") for step in steps]
    prepare = next(
        i
        for i, source in enumerate(sources)
        if "release_blue_green.py prepare-plan" in source
    )
    migrate = next(
        i
        for i, source in enumerate(sources)
        if "run_development_migrations_workflow.sh" in source
    )
    finish = next(
        i
        for i, source in enumerate(sources)
        if "release_blue_green.py finish" in source
    )
    assert prepare < migrate < finish
    roles = [
        step["with"]["role-to-assume"]
        for step in steps[prepare:finish]
        if str(step.get("uses", "")).startswith(
            "aws-actions/configure-aws-credentials@"
        )
    ]
    assert roles == [
        "arn:aws:iam::903859731897:role/nova-toll-v2-development-migrations-dev",
        "arn:aws:iam::903859731897:role/nova-toll-v2-development-delivery",
    ]
    assert 'run_private_stage "plan"' in sources[prepare]
    assert 'run_private_stage "apply"' in sources[finish]
    assert '--work-dir "$RUNNER_TEMP/blue-green"' in sources[prepare]
    assert '--work-dir "$RUNNER_TEMP/blue-green"' in sources[finish]


def test_development_oidc_validator_rejects_malformed_and_wrong_claim_fixtures() -> (
    None
):
    workflow = cast(
        dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW)
    )
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    proof_source = workflow_run_source(jobs["oidc-proof"])
    match = re.search(
        r'python3 - "\$GITHUB_SHA" "\$DEPLOYMENT_ID" <<\x27PY\x27\n(.*?)\nPY',
        proof_source,
        flags=re.DOTALL,
    )
    assert match is not None
    validator = dedent(match.group(1))
    expected_sha = "a" * 40
    claims = {
        "iss": "https://token.actions.githubusercontent.com",
        "aud": "sts.amazonaws.com",
        "sub": "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
        "environment": "development",
        "repository": "rhprasad0/nova-toll-budget-agent",
        "ref": "refs/heads/main",
        "sha": expected_sha,
        "job_workflow_ref": "rhprasad0/nova-toll-budget-agent/.github/workflows/v2-development-delivery-privileged.yml@refs/heads/main",
    }

    def segment(value: object) -> bytes:
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode()
        ).rstrip(b"=")

    def token_for(values: Mapping[str, object]) -> str:
        return b".".join(
            (segment({"alg": "RS256"}), segment(values), segment("signature"))
        ).decode()

    def run(
        token: str, sha: str = expected_sha, deployment_id: str = "7"
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["OIDC_TOKEN"] = token
        return subprocess.run(
            [sys.executable, "-", sha, deployment_id],
            input=validator,
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

    valid = run(token_for(claims))
    assert valid.returncode == 0, valid.stderr
    for name, value in (
        ("iss", "https://evil.example"),
        ("aud", "wrong-audience"),
        ("sub", "repo:evil/fork:ref:refs/heads/main"),
        ("environment", "production"),
        ("repository", "evil/fork"),
        ("ref", "refs/heads/release"),
        ("sha", "b" * 40),
        ("job_workflow_ref", "wrong"),
    ):
        invalid_token = token_for({**claims, name: value})
        invalid = run(invalid_token)
        assert invalid.returncode != 0
        assert invalid_token not in invalid.stdout + invalid.stderr
    for name in claims:
        for value in (None, 1, cast(list[object], []), cast(dict[str, object], {})):
            invalid = run(token_for({**claims, name: value}))
            assert invalid.returncode != 0, (name, value)
        without_claim = dict(claims)
        without_claim.pop(name)
        assert run(token_for(without_claim)).returncode != 0, name
    malformed_json = ".".join(
        (
            segment({"alg": "RS256"}).decode(),
            base64.urlsafe_b64encode(b"not JSON").rstrip(b"=").decode(),
            segment("signature").decode(),
        )
    )
    for malformed in (
        "not-a-jwt",
        "a!.e30.signature",
        "a.e30.signature",
        malformed_json,
    ):
        invalid = run(malformed)
        assert invalid.returncode != 0
        assert malformed not in invalid.stdout + invalid.stderr
    assert run(token_for(claims), "A" * 40).returncode != 0
    for deployment_id in ("0", "-1", "1.0", "seven", " 7", "7 "):
        assert run(token_for(claims), deployment_id=deployment_id).returncode != 0


def test_oidc_step_never_expands_workflow_inputs_as_shell_code(tmp_path: Path) -> None:
    workflow = cast(
        dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW)
    )
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    steps = cast(list[dict[str, object]], jobs["oidc-proof"]["steps"])
    proof = next(
        step for step in steps if step["name"] == "Validate runner OIDC claims"
    )
    source = cast(str, proof["run"])
    assert "${{ inputs." not in source
    assert proof["env"] == {"DEPLOYMENT_ID": "${{ inputs.deployment_id }}"}
    marker = tmp_path / "shell-expression-executed"
    environment = os.environ | {
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_SHA": "a" * 40,
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.invalid/token",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "test",
        "DEPLOYMENT_ID": f"$(touch {marker}; printf 7)",
    }
    result = subprocess.run(
        [
            "bash",
            "-c",
            "curl() { printf '%s' '{\"value\":\"not-a-jwt\"}'; }\n" + source,
        ],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    assert result.returncode != 0
    assert not marker.exists()
    assert "shell-expression-executed" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("mode", "expected_status"),
    (("success", 0), ("upstream", 17), ("summary", 125), ("combined", 17)),
)
def test_oidc_step_records_bounded_failures_once(
    tmp_path: Path, mode: str, expected_status: int
) -> None:
    workflow = cast(
        dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW)
    )
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    steps = cast(list[dict[str, object]], jobs["oidc-proof"]["steps"])
    source = cast(
        str,
        next(step for step in steps if step["name"] == "Validate runner OIDC claims")[
            "run"
        ],
    )

    def segment(value: object) -> bytes:
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":")).encode()
        ).rstrip(b"=")

    token = b".".join(
        (
            segment({"alg": "RS256"}),
            segment(
                {
                    "iss": "https://token.actions.githubusercontent.com",
                    "aud": "sts.amazonaws.com",
                    "sub": "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
                    "environment": "development",
                    "repository": "rhprasad0/nova-toll-budget-agent",
                    "ref": "refs/heads/main",
                    "sha": "a" * 40,
                    "job_workflow_ref": "rhprasad0/nova-toll-budget-agent/.github/workflows/v2-development-delivery-privileged.yml@refs/heads/main",
                }
            ),
            segment("signature"),
        )
    ).decode()
    summary = tmp_path / "summary"
    environment = os.environ | {
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_SHA": "a" * 40,
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.invalid/token",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "test",
        "DEPLOYMENT_ID": "7",
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    if mode == "success":
        prelude = f"curl() {{ printf '%s' '{{\"value\":\"{token}\"}}'; }}\n"
    elif mode == "upstream":
        prelude = "curl() { return 17; }\n"
    elif mode == "summary":
        summary.mkdir()
        prelude = "curl() { return 17; }\n"
    else:
        prelude = 'curl() { rm -f -- "$GITHUB_STEP_SUMMARY"; mkdir "$GITHUB_STEP_SUMMARY"; return 17; }\n'
    result = subprocess.run(
        ["bash", "-c", prelude + source],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == expected_status, output
    assert output.count("stage=oidc-claims status=fail") == (
        0 if mode == "success" else 1
    )
    assert "Is a directory" not in output


def test_oidc_cleanup_failure_is_bounded_and_nonzero(tmp_path: Path) -> None:
    workflow = cast(
        dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW)
    )
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    steps = cast(list[dict[str, object]], jobs["oidc-proof"]["steps"])
    cleanup = cast(
        str,
        next(
            step for step in steps if step["name"] == "Cleanup OIDC proof diagnostics"
        )["run"],
    )
    result = subprocess.run(
        ["bash", "-c", "rm() { return 17; }\n" + cleanup],
        text=True,
        capture_output=True,
        env=os.environ | {"RUNNER_TEMP": str(tmp_path)},
        check=False,
    )
    assert result.returncode == 125
    assert (result.stdout + result.stderr).count("stage=oidc-cleanup status=fail") == 1


def test_development_oidc_proof_schema_rejects_extra_fields_and_stale_sha() -> None:
    workflow = cast(
        dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW)
    )
    jobs = cast(dict[str, dict[str, object]], workflow["jobs"])
    deploy_source = workflow_run_source(jobs["deploy"])
    match = re.search(
        r'jq -e --arg commit "\$GITHUB_SHA" \'\n(.*?)\n\' "\$PROOF"',
        deploy_source,
        flags=re.DOTALL,
    )
    assert match is not None
    schema = match.group(1)
    sha = "a" * 40
    proof = {
        "account": "903859731897",
        "commit_sha": sha,
        "environment": "development",
        "job_workflow_ref": "rhprasad0/nova-toll-budget-agent/.github/workflows/v2-development-delivery-privileged.yml@refs/heads/main",
        "proof": "protected-main-oidc",
        "ref": "refs/heads/main",
        "repository": "rhprasad0/nova-toll-budget-agent",
    }

    def passes(value: Mapping[str, object], commit: str = sha) -> bool:
        result = subprocess.run(
            ["jq", "-e", "--arg", "commit", commit, schema],
            input=json.dumps(value),
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    assert passes(proof)
    assert not passes({**proof, "extra": "rejected"})
    assert not passes({**proof, "commit_sha": "b" * 40})
    assert not passes({**proof, "job_workflow_ref": "wrong"})
    assert not passes(proof, "b" * 40)


def test_development_delivery_workflow_is_parsed_and_split_before_oidc() -> None:
    _assert_development_delivery_caller(DEVELOPMENT_DELIVERY_WORKFLOW)
    _assert_development_delivery_privileged(DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW)
    caller = cast(dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_WORKFLOW))
    caller_jobs = cast(dict[str, dict[str, object]], caller["jobs"])
    assert set(caller_jobs) == {
        "admission",
        "release-record",
        "build",
        "deploy",
        "release-result",
    }
    deploy = caller_jobs["deploy"]
    assert (
        deploy["uses"] == "./.github/workflows/v2-development-delivery-privileged.yml"
    )
    assert deploy["needs"] == ["admission", "release-record", "build"]
    assert deploy["permissions"] == {
        "contents": "read",
        "actions": "read",
        "id-token": "write",
    }
    assert deploy["with"] == {
        "release_artifact_id": "${{ needs.build.outputs.artifact_id }}",
        "release_artifact_digest": "${{ needs.build.outputs.artifact_digest }}",
        "expected_pricing_schema": "${{ needs.build.outputs.pricing_schema }}",
        "expected_oracle_schema": "${{ needs.build.outputs.oracle_schema }}",
        "deployment_id": "${{ needs.release-record.outputs.deployment_id }}",
    }
    assert deploy["secrets"] == {
        "TS_DEVELOPMENT_OAUTH_CLIENT_ID": "${{ secrets.TS_DEVELOPMENT_OAUTH_CLIENT_ID }}",
        "TS_DEVELOPMENT_OAUTH_SECRET": "${{ secrets.TS_DEVELOPMENT_OAUTH_SECRET }}",
    }
    privileged = cast(
        dict[str, object], yaml.safe_load(DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW)
    )
    assert set(cast(dict[str, object], workflow_trigger(privileged))) == {
        "workflow_call"
    }
    callee_jobs = cast(dict[str, dict[str, object]], privileged["jobs"])
    assert set(callee_jobs) == {"oidc-proof", "deploy"}
    assert callee_jobs["deploy"]["environment"] == "development"
    assert callee_jobs["deploy"]["concurrency"] == {
        "group": "v2-development-apply",
        "queue": "max",
    }
    for original, replacement in (
        ("  workflow_dispatch:\n", '  schedule:\n    - cron: "17 8 * * *"\n'),
        ("      - main\n  workflow_dispatch:", '      - "**"\n  workflow_dispatch:'),
        ("cancel-in-progress: false", "cancel-in-progress: true"),
        ("environment: development", "environment: production"),
        (
            "if: github.ref == 'refs/heads/main'",
            "if: github.ref == 'refs/heads/release'",
        ),
        (
            "if: vars.DEVELOPMENT_DELIVERY_ENABLED == 'true' && vars.DEVELOPMENT_BLUE_GREEN_BOOTSTRAPPED == 'true' && github.triggering_actor == github.actor",
            "if: github.triggering_actor == github.actor",
        ),
        (
            "if: vars.DEVELOPMENT_DELIVERY_ENABLED == 'true' && vars.DEVELOPMENT_BLUE_GREEN_BOOTSTRAPPED == 'true' && github.triggering_actor == github.actor",
            "if: vars.DEVELOPMENT_DELIVERY_ENABLED == 'true'",
        ),
        (
            "&& github.triggering_actor == github.actor",
            "|| github.triggering_actor == github.actor",
        ),
        (
            "github.triggering_actor == github.actor",
            "github.triggering_actor == 'owner'",
        ),
        (
            "github.triggering_actor == github.actor",
            "github.triggering_actor == github.actor && github.actor_id == '91573985'",
        ),
        (
            "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development",
            "repo:evil/fork:environment:development",
        ),
        (
            '"repository": "rhprasad0/nova-toll-budget-agent"',
            '"repository": "evil/fork"',
        ),
        ("backend.development.hcl", "backend.production.hcl"),
        ("build/loader.zip", "build/placeholder.zip"),
        ('version: "0.12.5"', "version: latest"),
        ('terraform_version: "1.15.8"', "terraform_version: latest"),
        (
            "${{ needs.oidc-proof.outputs.artifact_id }}",
            "protected-main-oidc-proof",
        ),
        ('python-version: "3.13"', ""),
        ('python-version: "3.13"', 'python-version: "3.12"'),
    ):
        if original in DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW:
            source, assertion = (
                DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW,
                _assert_development_delivery_privileged,
            )
        else:
            source, assertion = (
                DEVELOPMENT_DELIVERY_WORKFLOW,
                _assert_development_delivery_caller,
            )
        assert original in source, original
        must_reject(assertion, source, original, replacement)
    for source, assertion in (
        (DEVELOPMENT_DELIVERY_WORKFLOW, _assert_development_delivery_caller),
        (
            DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW,
            _assert_development_delivery_privileged,
        ),
    ):
        must_reject(
            assertion,
            source,
            "if: " + str(yaml.safe_load(source)["jobs"]["deploy"]["if"]),
            "if: true",
        )
    must_reject(
        _assert_development_delivery_privileged,
        DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW,
        "deployment_id:\n        required: true",
        "deployment_id:\n        required: false",
    )
    must_reject(
        _assert_development_delivery_privileged,
        DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW,
        "- uses: actions/checkout@",
        "- uses: aws-actions/configure-aws-credentials@",
    )


def test_runbooks_never_direct_plan_apply_target_or_workspaces() -> None:
    guarded = RUNBOOK.split("### Guarded production release", maxsplit=1)[1].split(
        "## Public report launch", maxsplit=1
    )[0]
    assert "terraform plan" not in guarded
    assert "terraform apply" not in guarded
    assert "terraform -target" not in DEPLOYMENT
    assert "terraform workspace" not in DEPLOYMENT


def test_ci_jobs_run_verify() -> None:
    """CLAUDE.md: run what CI runs. A check added inline in ci.yml is one no one runs locally."""
    elsewhere = {
        "frontend-browser": "needs Playwright browsers and the deployed development AI",
        "trusted-development-plan": "needs AWS credentials",
        "development-plan": "reports trusted-development-plan",
        "trusted-toolchain-provenance": "runs toolchain-provenance.yml from main",
        "toolchain-provenance": "reports trusted-toolchain-provenance",
    }
    jobs = yaml.safe_load(CI_WORKFLOW)["jobs"]
    inline = sorted(
        name
        for name, job in jobs.items()
        if name not in elsewhere
        and not any("verify.sh" in step.get("run", "") for step in job.get("steps", []))
    )
    assert not inline, (
        f"Move the checks in ci.yml jobs {inline} into a .github/scripts/verify.sh "
        "job and call it from ci.yml, so a local run checks what CI checks."
    )
    assert sorted(elsewhere) == sorted(set(elsewhere) & set(jobs)), "Drop retired jobs."
