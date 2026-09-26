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
    AGENTS,
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
    VERSIONS_TF,
    must_reject,
    workflow_run_source,
    workflow_trigger,
)


def test_ci_installs_proxy_dependencies_once_before_testing() -> None:
    steps = yaml.safe_load(CI_WORKFLOW)["jobs"]["v2-loader"]["steps"]
    node = next(
        step for step in steps if step.get("uses", "").startswith("actions/setup-node@")
    )
    assert node["with"]["cache-dependency-path"].splitlines() == [
        "v2/package-lock.json",
        "v2/lambdas/chat_proxy/package-lock.json",
    ]
    install = next(
        step
        for step in steps
        if step.get("run") == "npm ci --prefix lambdas/chat_proxy"
    )
    build = next(
        step for step in steps if step.get("run") == "./scripts/build_agentcore_zips.sh"
    )
    test = next(
        step
        for step in steps
        if step.get("run") == "npm test --prefix lambdas/chat_proxy"
    )
    assert install["if"] == "github.event_name != 'pull_request'"
    assert build["if"] == "github.event_name == 'pull_request'"
    assert "if" not in test
    assert steps.index(install) < steps.index(test)
    assert steps.index(build) < steps.index(test)
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
    workflow = (REPO_ROOT / ".github" / "workflows" / "terraform.yml").read_text()

    assert 'backend "s3" {}' in (FOUNDATION_ROOT / "versions.tf").read_text()
    assert 'backend "s3" {}' in VERSIONS_TF
    assert (FOUNDATION_ROOT / "backend.production.hcl").read_text().find(
        'key          = "nova-toll/terraform.tfstate"'
    ) >= 0
    assert (V2_ROOT / "infra" / "backend.production.hcl").read_text().find(
        'key          = "nova-toll/v2/terraform.tfstate"'
    ) >= 0
    assert "postgis/postgis" in CI_WORKFLOW
    assert "python3 v2/scripts/check_schema_versions.py" in CI_WORKFLOW
    assert "v2/scripts/run_db_tests.sh" in CI_WORKFLOW
    ci_jobs = cast(dict[str, dict[str, object]], yaml.safe_load(CI_WORKFLOW)["jobs"])
    database_setup_uv = [
        step
        for step in cast(list[dict[str, object]], ci_jobs["v2-database"]["steps"])
        if cast(str, step.get("uses", "")).startswith("astral-sh/setup-uv@")
    ]
    assert database_setup_uv == [
        {
            "uses": "astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4",
            "with": {"python-version": "3.13"},
        }
    ]
    for forbidden in (
        "terraform plan",
        "terraform apply",
        "configure-aws-credentials",
        "id-token: write",
    ):
        assert forbidden not in workflow
    for text in (
        "PRs use disposable migration validation only",
        "checks are credential-free",
        "never mutate deployed databases or schemas",
        "protected `development` migration workflow",
        "refs/heads/main",
        "reviewed protected fixed-target",
        "v2-production-migrations.yml",
        "manually authorized production migration",
        "Generic or future manual migrations are not authorized.",
    ):
        assert text in AGENTS
    guarded = RUNBOOK.split("### Guarded production release", maxsplit=1)[1].split(
        "The legacy development inventory", maxsplit=1
    )[0]
    for text in (
        "verified\ndevelopment candidate/bundle",
        "stable published `vX.Y.Z` event",
        "listener has no AWS credentials",
        "one durable claim",
        "before planner OIDC credentials",
        "encrypted,\nversioned, checksummed candidate/state-bound saved plan valid for 24 hours",
        "Reviewer approval of the protected `production` job occurs after that plan is\nsaved",
        "before the reusable job can access environment secrets or credentials",
        "before migration credentials and fixed migration",
        "re-assumes the deploy role",
        "before applying that same plan",
        "separate `production-cutover` approval",
        "new routing-only plan",
        "Two consecutive failures",
        "direct, arbitrary, stale, or caller-selected plan/apply",
        "sanitized",
    ):
        assert text in guarded
    assert "terraform plan" not in guarded
    assert "terraform apply" not in guarded
    handoff = RUNBOOK.split("## Account-local foundation handoff", maxsplit=1)[1].split(
        "Application/database bootstrap", maxsplit=1
    )[0]
    for text in (
        "guarded\nproduction planner",
        "current foundation output",
        "validates its approved non-secret shape",
        "planner-owned production handoff",
    ):
        assert text in handoff
    assert "planned-output" not in handoff
    assert "foundation-plan path" not in handoff

    assert "Historical pre-bootstrap recovery capture" in RUNBOOK
    assert "**Historical pre-bootstrap procedure only.**" in RUNBOOK
    assert "v2-production-recovery.yml" in RUNBOOK

    capture = RUNBOOK.split(
        "Before approving or deploying a production release", maxsplit=1
    )[1].split("Historical `usage.json`", maxsplit=1)[0]
    rollback = RUNBOOK.split(
        "### Production canary failure: human stop and manual routing restore",
        maxsplit=1,
    )[1].split("Deterministic builds", maxsplit=1)[0]
    capture_shells = re.findall(r"```sh\n(.*?)\n```", capture, flags=re.DOTALL)
    restore_shells = re.findall(r"```sh\n(.*?)\n```", rollback, flags=re.DOTALL)
    assert len(capture_shells) == len(restore_shells) == 1
    assert capture_shells == ["bash v2/manual-releases/capture_production_recovery.sh"]
    capture = (
        V2_ROOT / "manual-releases" / "capture_production_recovery.sh"
    ).read_text()
    capture_shells.append(capture)
    for shell in [*capture_shells, *restore_shells]:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as script:
            script.write(shell)
            script.flush()
            assert (
                subprocess.run(["bash", "-n", script.name], check=False).returncode == 0
            )

    for text in (
        "set -euo pipefail",
        "set +x",
        "umask 077",
        "920534282028",
        "EXPECTED_REGION=us-east-1",
        "tollchat-v2-chat-proxy",
        "nova_toll_v2-W6989LEw44",
        "os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW",
        "stat.S_ISREG(info.st_mode)",
        "stat.S_IMODE(info.st_mode) != 0o600",
        "if os.fstat(fd).st_nlink != 1:",
        "lambda_live_function_version",
        "agentcore_endpoint_live_version",
        "AdditionalVersionWeights",
    ):
        assert text in capture
    for text in (
        "set -euo pipefail",
        "set +x",
        "umask 077",
        "920534282028",
        "EXPECTED_REGION=us-east-1",
        'python3 -I -S - "$RELEASE_EVIDENCE" "$RECOVERY_RECORD_MAX_BYTES"',
        "os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,",
        "info = os.fstat(fd)",
        "stat.S_ISREG(info.st_mode)",
        "stat.S_IMODE(info.st_mode) != 0o600",
        "snapshot = os.read(fd, limit + 1)",
        "snapshot.splitlines(keepends=True)",
        '--revision-id "$LAMBDA_ALIAS_REVISION"',
        '--client-token "$AGENTCORE_RESTORE_TOKEN"',
        "for ((attempt = 1; attempt <= 60; attempt++))",
        "UPDATE_FAILED",
        "human stop",
        "do not roll back automatically",
        "distinct from the\nforward update token",
        "WAF/rate-limit response",
        "HTTP 429",
        "currently configured WAF rate-based quiet/evaluation window",
        "production exactly unchanged",
        "two-session/reset verification",
    ):
        assert text in rollback
    for shell in (capture, rollback):
        assert "CURRENT_STAGE=" in shell
        assert "FAILURE_REPORTED=0" in shell
        assert "status=fail exit=%s reason=unclassified" in shell
        assert ".FunctionName" not in shell
        assert 'if has("RoutingConfig") then' in shell
        assert '($routing | type) != "object" then false' in shell
        assert "AdditionalVersionWeights? // {}" not in shell
        assert (
            'AliasArn == "arn:aws:lambda:us-east-1:920534282028:function:tollchat-v2-chat-proxy:live"'
            in shell
        )
        assert "PRIVATE_SINK" not in shell
        assert "$(mktemp" not in shell
        assert "2>&1 |" in shell
        assert "cmp -s - <(printf '%s\\n' \"$EXPECTED_ACCOUNT\") 2>/dev/null" in shell
        assert 'test "${statuses[1]}" -eq 0' not in shell
        assert 'aws --region "$EXPECTED_REGION"' in shell
        assert "export AWS_IGNORE_CONFIGURED_ENDPOINT_URLS=true" in shell
        assert 'test -n "${RELEASE_EVIDENCE-}"' in shell
        assert "${RELEASE_EVIDENCE:?" not in shell
    for stage in (
        "record-path",
        "account-identity",
        "lambda-validate",
        "agentcore-validate",
        "record-write",
    ):
        assert f"CURRENT_STAGE={stage}" in capture
    for stage in (
        "record-snapshot",
        "record-validate",
        "lambda-update",
        "agentcore-token",
        "agentcore-update",
        "agentcore-poll",
        "agentcore-retry",
    ):
        assert f"CURRENT_STAGE={stage}" in rollback
    assert rollback.count('"$RELEASE_EVIDENCE"') == 1
    assert rollback.count('$(<"$RELEASE_EVIDENCE")') == 0
    assert "stat -c " not in rollback
    assert "grep -qx" not in rollback
    assert "sed -n" not in rollback
    assert "^[1-9][0-9]*$" in capture
    assert "^[1-9][0-9]*$" in rollback
    assert "jq -ser" in capture
    assert capture.count("jq -Rser") == 1
    assert "select(length == 1) | .[0]" in capture
    assert '.status == "READY"' in capture
    assert "then .targetVersion == .liveVersion else true end" in capture
    assert 'python3 -I -S - "$RELEASE_EVIDENCE"' in capture
    assert 'if CAPTURE_WRITE_STAGE="$(' in capture
    assert "os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW" in capture
    assert "os.O_DIRECTORY | os.O_NOFOLLOW" in capture
    assert "dir_fd=directory" in capture
    assert "named.st_dev != info.st_dev" in capture
    assert 'chmod 600 "$RELEASE_EVIDENCE"' not in capture
    assert 'test ! -e "$RELEASE_EVIDENCE"' not in capture
    assert "jq -ser" in rollback
    assert rollback.count("jq -Rser") == 2
    assert "jq -se --arg version" in rollback
    assert "explode | all(. >= 32 and (. < 127 or . >= 160))" in rollback
    assert 'python3 -I -S - "$RELEASE_EVIDENCE"' in rollback
    assert "os.O_DIRECTORY | os.O_NOFOLLOW" in rollback
    assert "info.st_uid != os.geteuid()" in rollback
    assert rollback.count("select(length == 1) | .[0]") >= 3
    assert 'AGENTCORE_RESTORE_TOKEN="$(' in rollback
    assert (
        "python3 -I -S -c 'import uuid; print(uuid.uuid4())' 2>/dev/null | jq -Rser"
        in rollback
    )
    assert rollback.index("AGENTCORE_RESTORE_TOKEN") < rollback.index(
        "update_agentcore()"
    )
    assert "AGENTCORE_UPDATE_AMBIGUOUS=1" in rollback
    assert "AGENTCORE_UPDATE_STATUS=$?" in rollback
    assert 'exit "$AGENTCORE_UPDATE_STATUS"' in rollback
    assert "AGENTCORE_RETRY_USED=1" in rollback
    assert (
        'if (( AGENTCORE_RETRY_USED == 1 )); then exit "$AGENTCORE_UPDATE_STATUS"; fi'
        in rollback
    )
    agent_identity = rollback.index('.agentRuntimeArn == "arn:aws:bedrock-agentcore')
    agent_branch = rollback.index('case "$AGENTCORE_STATUS"')
    assert agent_identity < agent_branch
    assert 'test "$AGENTCORE_TARGET_VERSION" = "$AGENTCORE_LIVE_VERSION"' in rollback
    assert (
        'test "$AGENTCORE_TARGET_VERSION" = "$AGENTCORE_ENDPOINT_LIVE_VERSION"'
        in rollback
    )
    assert "check_development_release.py --profile production" not in rollback
    assert "fixed production readiness checker" not in rollback
    assert "300 seconds" not in rollback
    assert "5 minutes" not in rollback
    assert "QUIET_WINDOW" not in rollback
    assert 'sleep "$' not in rollback
    assert rollback.index("lambda get-alias") < rollback.index("lambda update-alias")
    lambda_update = rollback.index("lambda update-alias")
    assert (
        rollback.find(
            'AWS_PROFILE=nova-toll-prod aws --region "$EXPECTED_REGION" lambda get-alias',
            lambda_update,
        )
        > lambda_update
    )
    assert rollback.index("update-agent-runtime-endpoint") < rollback.index(
        "get-agent-runtime-endpoint"
    )
    assert "immediate Lambda alias read-back and finite AgentCore" in rollback
    assert "Terraform-state-bound production checker" in rollback
    fixed_targets = {
        "EXPECTED_ACCOUNT": "920534282028",
        "EXPECTED_REGION": "us-east-1",
        "LAMBDA_FUNCTION": "tollchat-v2-chat-proxy",
        "LAMBDA_ALIAS": "live",
        "AGENTCORE_RUNTIME": "nova_toll_v2-W6989LEw44",
        "AGENTCORE_ENDPOINT": "preview",
    }
    for shell in (capture, rollback):
        for name, value in fixed_targets.items():
            assert re.search(rf"(?m)^\s*{name}={re.escape(value)}$", shell)
            assert not re.search(rf"(?m)^\s*{name}=.*(?:\$|`)", shell)

    readme = (V2_ROOT / "README.md").read_text()
    for text in (
        "verified development bundle",
        "admission\nand claim",
        "saved plan",
        "reviewer approval",
        "Guards fail closed",
        "separate `production-cutover` approval",
        "routing-only promotion plan",
        "Two consecutive post-cutover observation failures",
        "v2-production-recovery.yml",
        "sanitized",
    ):
        assert text in readme


def test_manual_routing_restore_documentation_shells_are_bounded(
    tmp_path: Path,
) -> None:
    capture = RUNBOOK.split(
        "Before approving or deploying a production release", maxsplit=1
    )[1].split("Historical `usage.json`", maxsplit=1)[0]
    rollback = RUNBOOK.split(
        "### Production canary failure: human stop and manual routing restore",
        maxsplit=1,
    )[1].split("Deterministic builds", maxsplit=1)[0]
    capture_shell = re.findall(r"```sh\n(.*?)\n```", capture, flags=re.DOTALL)[0]
    restore_shell = re.findall(r"```sh\n(.*?)\n```", rollback, flags=re.DOTALL)[0]
    binary = tmp_path / "bin"
    state = tmp_path / "state"
    log = tmp_path / "commands.log"
    binary.mkdir()
    state.mkdir()
    aws = binary / "aws"
    aws.write_text(
        dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            printf '%s\\n' "$*" >>"$LOG"
            test "${AWS_IGNORE_CONFIGURED_ENDPOINT_URLS:-}" = true || exit 71
            if [[ "$*" == *"sts get-caller-identity"* ]]; then
              if [[ "${FAIL_ACCOUNT:-}" == 1 ]]; then
                if [[ "${NUL_FAILURE:-}" == 1 ]]; then
                  printf 'RAW\0SENTINEL\n'
                  printf 'RAW\0SENTINEL\n' >&2
                elif [[ "${SENTINEL_FAILURE:-}" == capture ]]; then
                  printf '%s\\n' RAW_PROVIDER_STDOUT
                  printf '%s\\n' RAW_PROVIDER_STDERR >&2
                fi
                exit 17
              fi
              if [[ -n "${MUTATE_RECORD:-}" ]]; then
                printf 'lambda_live_function_version=999\\nagentcore_endpoint_live_version=998\\n' >"$MUTATE_RECORD"
              fi
              printf '%s\\n' 920534282028
            elif [[ "$*" == *"lambda get-alias"* ]]; then
              count_file="$STATE/lambda-get"
              count=0; test -f "$count_file" && count="$(<"$count_file")"
              count=$((count + 1)); printf '%s' "$count" >"$count_file"
              if [[ "${MODE:-}" == restore && "${LAMBDA_MALFORMED_READBACK:-}" == 1 && "$count" -gt 1 ]]; then
                printf '{\\n'
                exit 0
              fi
              version=11; revision=revision-capture
              if [[ "${MODE:-}" == restore ]]; then
                version=9; revision=revision-current
                if (( count > 1 )); then version=7; revision=revision-readback; fi
              fi
              if [[ "${LAMBDA_REVISION_NUL:-}" == 1 ]]; then revision='revision\\u0000'; fi
              routing="${LAMBDA_ROUTING:-}"
              if [[ -z "$routing" ]]; then routing='{"AdditionalVersionWeights":{}}'; fi
              if [[ "$routing" == absent ]]; then
                printf '{"AliasArn":"arn:aws:lambda:us-east-1:920534282028:function:tollchat-v2-chat-proxy:live","Name":"live","FunctionVersion":"%s","RevisionId":"%s"}\\n' "$version" "$revision"
              else
                printf '{"AliasArn":"arn:aws:lambda:us-east-1:920534282028:function:tollchat-v2-chat-proxy:live","Name":"live","FunctionVersion":"%s","RevisionId":"%s","RoutingConfig":%s}\\n' "$version" "$revision" "$routing"
              fi
              duplicate=0
              if [[ "${MULTI_DOCUMENT:-}" == lambda ]] || [[ "${MODE:-}" == restore && "${MULTI_DOCUMENT:-}" == restore-initial && "$count" -eq 1 ]] || [[ "${MODE:-}" == restore && "${MULTI_DOCUMENT:-}" == restore-readback && "$count" -gt 1 ]]; then duplicate=1; fi
              if (( duplicate )); then
                printf '{"AliasArn":"arn:aws:lambda:us-east-1:920534282028:function:tollchat-v2-chat-proxy:live","Name":"live","FunctionVersion":"%s","RevisionId":"%s","RoutingConfig":{"AdditionalVersionWeights":{}}}\\n' "$version" "$revision"
              fi
            elif [[ "$*" == *"lambda update-alias"* ]]; then
              if [[ "${FAIL_LAMBDA:-}" == 1 ]]; then
                if [[ "${SENTINEL_FAILURE:-}" == restore ]]; then
                  printf '%s\\n' RAW_PROVIDER_STDOUT
                  printf '%s\\n' RAW_PROVIDER_STDERR >&2
                fi
                exit 19
              fi
            elif [[ "$*" == *"bedrock-agentcore-control get-agent-runtime-endpoint"* ]]; then
              count_file="$STATE/agent-get"
              count=0; test -f "$count_file" && count="$(<"$count_file")"
              count=$((count + 1)); printf '%s' "$count" >"$count_file"
              version=8
              if [[ "${MODE:-}" == restore && ( "${AGENT_MODE:-}" == unresolved || ( "${AGENT_MODE:-}" == ambiguous && "$count" -eq 1 ) ) ]]; then version=1; fi
              runtime_arn=arn:aws:bedrock-agentcore:us-east-1:920534282028:runtime/nova_toll_v2-W6989LEw44
              endpoint_name=preview
              status=READY
              target_version="$version"
              case "${AGENT_BAD:-}" in
                arn) runtime_arn=arn:aws:bedrock-agentcore:us-east-1:920534282028:runtime/wrong ;;
                name) endpoint_name=wrong ;;
                target) status=UPDATING; target_version=1 ;;
                transition) status=UPDATING ;;
                mismatch) target_version=9 ;;
              esac
              if [[ "${MODE:-}" == restore && "${MULTI_DOCUMENT:-}" == agent-restore-split ]]; then
                printf '{"agentRuntimeArn":"%s","name":"%s","status":"%s"}\\n' "$runtime_arn" "$endpoint_name" "$status"
                printf '{"liveVersion":"%s","targetVersion":"%s"}\\n' "$version" "$target_version"
              else
                printf '{"agentRuntimeArn":"%s","name":"%s","status":"%s","liveVersion":"%s","targetVersion":"%s"}\\n' "$runtime_arn" "$endpoint_name" "$status" "$version" "$target_version"
              fi
              if [[ "${MULTI_DOCUMENT:-}" == agent ]]; then
                printf '{"agentRuntimeArn":"arn:aws:bedrock-agentcore:us-east-1:920534282028:runtime/nova_toll_v2-W6989LEw44","name":"preview","status":"READY","liveVersion":"8","targetVersion":"8"}\\n'
              fi
            elif [[ "$*" == *"bedrock-agentcore-control update-agent-runtime-endpoint"* ]]; then
              count_file="$STATE/agent-update"
              count=0; test -f "$count_file" && count="$(<"$count_file")"
              count=$((count + 1)); printf '%s' "$count" >"$count_file"
              if [[ "${AGENT_MODE:-}" == unresolved || ( "${AGENT_MODE:-}" == ambiguous && "$count" -eq 1 ) ]]; then exit 23; fi
            else
              exit 99
            fi
            """
        ),
        encoding="utf-8",
    )
    python = binary / "python3"
    python.write_text(
        dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            python_is_code=0
            for argument in "$@"; do
              [[ "$argument" == -c ]] && python_is_code=1
            done
            if [[ "${PYTHON_BROKEN_NUL:-}" == stream && "$python_is_code" == 0 ]] || [[ "${PYTHON_BROKEN_NUL:-}" == token && "$python_is_code" == 1 ]]; then
              printf 'RAW\\000PYTHON_SENTINEL\\n'
              exit 43
            fi
            if [[ "$python_is_code" == 1 ]]; then
              printf '%s\\n' 00000000-0000-4000-8000-000000000000
              exit 0
            fi
            if [[ -n "${CAPTURE_REPLACE_AFTER_OPEN:-}${CUSTODY_REPLACE_SOURCE:-}${REPLACE_AFTER_OPEN:-}" ]]; then
              while [[ "${1:-}" == -I || "${1:-}" == -S ]]; do shift; done
              test "${1:-}" = -; shift
              exec "$REAL_PYTHON" -I -S -c '
            import os
            import sys

            capture_source = os.environ.get("CAPTURE_REPLACE_AFTER_OPEN")
            capture_replacement = os.environ.get("CAPTURE_REPLACEMENT")
            capture_moved = os.environ.get("CAPTURE_MOVED_RECORD")
            if capture_source and capture_replacement:
                original_write = os.write
                replaced = False

                def write(fd, data):
                    global replaced
                    if not replaced:
                        replaced = True
                        if capture_moved:
                            os.replace(capture_source, capture_moved)
                        os.replace(capture_replacement, capture_source)
                    return original_write(fd, data)

                os.write = write

            custody_source = os.environ.get("CUSTODY_REPLACE_SOURCE")
            custody_replacement = os.environ.get("CUSTODY_REPLACEMENT")
            if custody_source and custody_replacement:
                original_stat = os.stat
                replaced = False

                def stat(path, *args, **kwargs):
                    global replaced
                    if (
                        not replaced
                        and path == os.path.basename(custody_source)
                        and kwargs.get("dir_fd") is not None
                    ):
                        replaced = True
                        os.replace(custody_replacement, custody_source)
                    return original_stat(path, *args, **kwargs)

                os.stat = stat

            snapshot_source = os.environ.get("REPLACE_AFTER_OPEN")
            snapshot_replacement = os.environ.get("REPLACEMENT")
            if snapshot_source and snapshot_replacement:
                original_read = os.read
                replaced = False

                def read(fd, count):
                    global replaced
                    if not replaced:
                        replaced = True
                        os.replace(snapshot_replacement, snapshot_source)
                    return original_read(fd, count)

                os.read = read

            exec(compile(sys.stdin.read(), "<stdin>", "exec"))
            ' "$@"
            fi
            exec "$REAL_PYTHON" "$@"
            """
        ),
        encoding="utf-8",
    )
    sleep = binary / "sleep"
    sleep.write_text("#!/usr/bin/env bash\nexit 0\n")
    mktemp = binary / "mktemp"
    mktemp.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' mktemp >>\"$LOG\"\n"
        "printf '%s/victim\\n' \"$TMPDIR\"\n"
    )
    cmp = binary / "cmp"
    cmp.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${COMPARE_FAILURE:-}" == 1 ]]; then\n'
        "  cat >/dev/null\n"
        "  printf '%s\\n' RAW_COMPARATOR_SENTINEL >&2\n"
        "  exit 43\n"
        "fi\n"
        'exec /usr/bin/cmp "$@"\n'
    )
    for command in (aws, python, sleep, mktemp, cmp):
        command.chmod(0o700)

    def run(shell: str, **environment: str) -> subprocess.CompletedProcess[str]:
        environment = dict(environment)
        unset_release_evidence = environment.pop("UNSET_RELEASE_EVIDENCE", "") == "1"
        child_environment = {
            **os.environ,
            "PATH": str(binary) + os.pathsep + os.defpath,
            "LOG": str(log),
            "STATE": str(state),
            "REAL_PYTHON": sys.executable,
            **environment,
        }
        if unset_release_evidence:
            child_environment.pop("RELEASE_EVIDENCE", None)
        return subprocess.run(
            ["bash", "-c", shell],
            cwd=REPO_ROOT,
            env=child_environment,
            text=True,
            capture_output=True,
            check=False,
        )

    record = tmp_path / "recovery-record"
    captured = run(
        capture_shell, MODE="capture", RELEASE_EVIDENCE=str(record), LOG=str(log)
    )
    assert captured.returncode == 0, captured.stderr
    assert record.read_text() == (
        "lambda_live_function_version=11\nagentcore_endpoint_live_version=8\n"
    )
    assert record.stat().st_mode & 0o777 == 0o600

    startup_hook = tmp_path / "startup-hook"
    startup_hook.mkdir()
    startup_sentinel = tmp_path / "startup-hook-ran"
    (startup_hook / "sitecustomize.py").write_text(
        'open(__import__("os").environ["STARTUP_HOOK_SENTINEL"], "w").write("ran")\n'
    )
    isolated_capture_record = tmp_path / "isolated-capture-record"
    isolated_capture = run(
        capture_shell,
        MODE="capture",
        RELEASE_EVIDENCE=str(isolated_capture_record),
        PYTHONPATH=str(startup_hook),
        STARTUP_HOOK_SENTINEL=str(startup_sentinel),
    )
    assert isolated_capture.returncode == 0, isolated_capture.stderr
    assert not startup_sentinel.exists()
    isolated_record = tmp_path / "isolated-recovery-record"
    isolated_record.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    isolated_record.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    isolated_restore = run(
        restore_shell,
        MODE="restore",
        RELEASE_EVIDENCE=str(isolated_record),
        PYTHONPATH=str(startup_hook),
        STARTUP_HOOK_SENTINEL=str(startup_sentinel),
    )
    assert isolated_restore.returncode == 0, isolated_restore.stderr
    assert not startup_sentinel.exists()

    for shell, mode in ((capture_shell, "capture"), (restore_shell, "restore")):
        unset_path = run(shell, MODE=mode, UNSET_RELEASE_EVIDENCE="1")
        empty_path = run(shell, MODE=mode, RELEASE_EVIDENCE="")
        for failed in (unset_path, empty_path):
            assert failed.returncode == 1
            assert failed.stdout == ""
            assert failed.stderr == (
                "stage=record-path status=fail exit=1 reason=unclassified\n"
            )

    existing_record = tmp_path / "existing-record"
    existing_record.write_text("do not overwrite", encoding="utf-8")
    existing = run(capture_shell, MODE="capture", RELEASE_EVIDENCE=str(existing_record))
    assert existing.returncode == 1
    assert existing.stdout == ""
    assert (
        existing.stderr == "stage=record-path status=fail exit=1 reason=unclassified\n"
    )
    assert existing_record.read_text(encoding="utf-8") == "do not overwrite"

    unwritable_record = tmp_path / "missing-parent" / "recovery-record"
    unwritable = run(
        capture_shell, MODE="capture", RELEASE_EVIDENCE=str(unwritable_record)
    )
    assert unwritable.returncode == 1
    assert unwritable.stdout == ""
    assert (
        unwritable.stderr
        == "stage=record-write status=fail exit=1 reason=unclassified\n"
    )
    assert not unwritable_record.exists()

    capture_target = tmp_path / "capture-race-record"
    capture_replacement = tmp_path / "capture-race-fifo"
    os.mkfifo(capture_replacement, 0o644)
    capture_replacement.chmod(0o644)
    raced_capture = run(
        capture_shell,
        MODE="capture",
        RELEASE_EVIDENCE=str(capture_target),
        CAPTURE_REPLACE_AFTER_OPEN=str(capture_target),
        CAPTURE_REPLACEMENT=str(capture_replacement),
    )
    assert raced_capture.returncode == 1
    assert raced_capture.stdout == ""
    assert (
        raced_capture.stderr
        == "stage=record-write status=fail exit=1 reason=unclassified\n"
    )
    assert capture_target.is_fifo()
    assert capture_target.stat().st_mode & 0o777 == 0o644

    planted_capture = tmp_path / "planted-capture-record"
    planted_replacement = tmp_path / "planted-capture-replacement"
    planted_replacement.write_text(
        "lambda_live_function_version=999\nagentcore_endpoint_live_version=998\n"
    )
    planted_replacement.chmod(0o600)
    moved_capture = tmp_path / "moved-capture-record"
    planted = run(
        capture_shell,
        MODE="capture",
        RELEASE_EVIDENCE=str(planted_capture),
        CAPTURE_REPLACE_AFTER_OPEN=str(planted_capture),
        CAPTURE_REPLACEMENT=str(planted_replacement),
        CAPTURE_MOVED_RECORD=str(moved_capture),
    )
    assert planted.returncode == 1
    assert planted.stdout == ""
    assert planted.stderr == (
        "stage=record-write status=fail exit=1 reason=unclassified\n"
    )
    assert planted_capture.read_text() == (
        "lambda_live_function_version=999\nagentcore_endpoint_live_version=998\n"
    )
    assert moved_capture.read_text() == (
        "lambda_live_function_version=11\nagentcore_endpoint_live_version=8\n"
    )

    for document, stage in (
        ("lambda", "lambda-validate"),
        ("agent", "agentcore-validate"),
    ):
        multi_record = tmp_path / f"multi-{document}-record"
        multi = run(
            capture_shell,
            MODE="capture",
            MULTI_DOCUMENT=document,
            RELEASE_EVIDENCE=str(multi_record),
        )
        assert multi.returncode != 0
        assert multi.stdout == ""
        assert re.fullmatch(
            rf"stage={stage} status=fail exit=[1-9][0-9]* reason=unclassified\n",
            multi.stderr,
        )
        assert not multi_record.exists()

    for invalid_endpoint in ("transition", "mismatch"):
        failed_record = tmp_path / f"capture-{invalid_endpoint}-record"
        failed = run(
            capture_shell,
            MODE="capture",
            AGENT_BAD=invalid_endpoint,
            RELEASE_EVIDENCE=str(failed_record),
        )
        assert failed.returncode != 0
        assert failed.stdout == ""
        assert re.fullmatch(
            r"stage=agentcore-validate status=fail exit=[1-9][0-9]* reason=unclassified\n",
            failed.stderr,
        )
        assert not failed_record.exists()

    capture_failure = run(
        capture_shell,
        MODE="capture",
        FAIL_ACCOUNT="1",
        RELEASE_EVIDENCE=str(tmp_path / "failed-record"),
    )
    assert capture_failure.returncode == 17
    assert capture_failure.stderr.splitlines() == [
        "stage=account-identity status=fail exit=17 reason=unclassified"
    ]
    broken_capture = run(
        capture_shell,
        MODE="capture",
        PYTHON_BROKEN_NUL="stream",
        RELEASE_EVIDENCE=str(tmp_path / "broken-python-capture-record"),
    )
    assert broken_capture.returncode == 43
    assert broken_capture.stdout == ""
    assert broken_capture.stderr == (
        "stage=record-write status=fail exit=43 reason=unclassified\n"
    )
    assert "RAW" not in broken_capture.stderr
    assert not (tmp_path / "broken-python-capture-record").exists()
    for shell, mode, evidence in (
        (capture_shell, "capture", tmp_path / "comparator-capture-record"),
        (restore_shell, "restore", record),
    ):
        log.write_text("")
        comparator_failure = run(
            shell,
            MODE=mode,
            COMPARE_FAILURE="1",
            RELEASE_EVIDENCE=str(evidence),
        )
        assert comparator_failure.returncode == 43
        assert comparator_failure.stdout == ""
        assert comparator_failure.stderr == (
            "stage=account-identity status=fail exit=43 reason=unclassified\n"
        )
        assert "RAW_COMPARATOR_SENTINEL" not in comparator_failure.stderr
        assert "lambda get-alias" not in log.read_text()
    assert not (tmp_path / "comparator-capture-record").exists()
    sentinel_capture = run(
        capture_shell,
        MODE="capture",
        FAIL_ACCOUNT="1",
        SENTINEL_FAILURE="capture",
        RELEASE_EVIDENCE=str(tmp_path / "sentinel-capture-record"),
    )
    assert sentinel_capture.returncode == 17
    assert sentinel_capture.stdout == ""
    assert sentinel_capture.stderr == (
        "stage=account-identity status=fail exit=17 reason=unclassified\n"
    )

    nul_capture = run(
        capture_shell,
        MODE="capture",
        FAIL_ACCOUNT="1",
        NUL_FAILURE="1",
        RELEASE_EVIDENCE=str(tmp_path / "nul-capture-record"),
    )
    assert nul_capture.returncode == 17
    assert nul_capture.stdout == ""
    assert nul_capture.stderr == (
        "stage=account-identity status=fail exit=17 reason=unclassified\n"
    )

    hostile_tmp = tmp_path / "hostile-tmp"
    hostile_tmp.mkdir()
    victim = hostile_tmp / "victim"
    victim.write_text("do not clobber")
    log.write_text("")
    hostile_capture = run(
        capture_shell,
        MODE="capture",
        FAIL_ACCOUNT="1",
        SENTINEL_FAILURE="capture",
        RELEASE_EVIDENCE=str(tmp_path / "hostile-tmp-capture-record"),
        TMPDIR=str(hostile_tmp),
    )
    assert hostile_capture.returncode == 17
    assert hostile_capture.stdout == ""
    assert hostile_capture.stderr == (
        "stage=account-identity status=fail exit=17 reason=unclassified\n"
    )
    assert victim.read_text() == "do not clobber"
    assert "mktemp" not in log.read_text()

    hostile_restore_record = tmp_path / "hostile-tmp-restore-record"
    hostile_restore_record.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    hostile_restore_record.chmod(0o600)
    nul_restore = run(
        restore_shell,
        MODE="restore",
        FAIL_ACCOUNT="1",
        NUL_FAILURE="1",
        RELEASE_EVIDENCE=str(hostile_restore_record),
        TMPDIR=str(hostile_tmp),
    )
    assert nul_restore.returncode == 17
    assert nul_restore.stdout == ""
    assert nul_restore.stderr == (
        "stage=account-identity status=fail exit=17 reason=unclassified\n"
    )
    assert victim.read_text() == "do not clobber"

    hostile_restore_record = tmp_path / "hostile-tmp-restore-record"
    hostile_restore_record.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    hostile_restore_record.chmod(0o600)
    log.write_text("")
    hostile_restore = run(
        restore_shell,
        MODE="restore",
        FAIL_LAMBDA="1",
        SENTINEL_FAILURE="restore",
        RELEASE_EVIDENCE=str(hostile_restore_record),
        TMPDIR=str(hostile_tmp),
    )
    assert hostile_restore.returncode == 19
    assert hostile_restore.stdout == ""
    assert hostile_restore.stderr == (
        "stage=lambda-update status=fail exit=19 reason=unclassified\n"
    )
    assert victim.read_text() == "do not clobber"
    assert "mktemp" not in log.read_text()

    routing_failures = (
        "null",
        '"not-an-object"',
        "[]",
        '{"AdditionalVersionWeights":null}',
        '{"AdditionalVersionWeights":[]}',
        '{"AdditionalVersionWeights":{"9":1}}',
    )
    for index, routing in enumerate(routing_failures):
        failed_record = tmp_path / f"bad-routing-capture-{index}"
        failed = run(
            capture_shell,
            MODE="capture",
            LAMBDA_ROUTING=routing,
            RELEASE_EVIDENCE=str(failed_record),
        )
        assert failed.returncode != 0
        assert re.fullmatch(
            r"stage=lambda-validate status=fail exit=[1-9][0-9]* reason=unclassified\n",
            failed.stderr,
        )
        assert not failed_record.exists()

    def invalid_record(name: str, contents: str | None = None) -> Path:
        path = tmp_path / name
        if contents is None:
            os.mkfifo(path, 0o600)
        else:
            path.write_text(contents)
            path.chmod(0o600)
        return path

    for name, contents in (
        (
            "zero",
            "lambda_live_function_version=0\nagentcore_endpoint_live_version=8\n",
        ),
        ("missing", "lambda_live_function_version=7\n"),
        (
            "malformed",
            "lambda_live_function_version=seven\nagentcore_endpoint_live_version=8\n",
        ),
        (
            "duplicate",
            "lambda_live_function_version=7\nlambda_live_function_version=7\nagentcore_endpoint_live_version=8\n",
        ),
        (
            "extra",
            "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\nextra=1\n",
        ),
        (
            "oversized",
            "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
            + "x" * 256,
        ),
        (
            "trailing-blank",
            "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n\n",
        ),
        ("fifo", None),
    ):
        path = invalid_record(name, contents)
        log.write_text("")
        failed = run(restore_shell, MODE="restore", RELEASE_EVIDENCE=str(path))
        assert failed.returncode != 0
        assert failed.stderr.count("status=fail") == 1
        assert "lambda update-alias" not in log.read_text()

    log.write_text("")
    absent = run(
        restore_shell,
        MODE="restore",
        RELEASE_EVIDENCE=str(tmp_path / "absent-record"),
    )
    assert absent.returncode != 0
    assert absent.stderr.count("status=fail") == 1
    assert "lambda update-alias" not in log.read_text()

    target = invalid_record(
        "target",
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n",
    )
    link = tmp_path / "record-link"
    link.symlink_to(target)
    log.write_text("")
    linked = run(restore_shell, MODE="restore", RELEASE_EVIDENCE=str(link))
    assert linked.returncode != 0
    assert "lambda update-alias" not in log.read_text()

    log.write_text("")
    broken_snapshot = run(
        restore_shell,
        MODE="restore",
        PYTHON_BROKEN_NUL="stream",
        RELEASE_EVIDENCE=str(target),
    )
    assert broken_snapshot.returncode == 43
    assert broken_snapshot.stdout == ""
    assert broken_snapshot.stderr == (
        "stage=record-snapshot status=fail exit=43 reason=unclassified\n"
    )
    assert "RAW" not in broken_snapshot.stderr
    assert "lambda update-alias" not in log.read_text()

    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    nul_revision = run(
        restore_shell,
        MODE="restore",
        LAMBDA_REVISION_NUL="1",
        RELEASE_EVIDENCE=str(target),
    )
    assert nul_revision.returncode != 0
    assert nul_revision.stdout == ""
    assert re.fullmatch(
        r"stage=lambda-validate status=fail exit=[1-9][0-9]* reason=unclassified\n",
        nul_revision.stderr,
    )
    assert "lambda update-alias" not in log.read_text()

    for document, stage, lambda_update_expected in (
        ("restore-initial", "lambda-validate", False),
        ("restore-readback", "lambda-readback-validate", True),
    ):
        target.write_text(
            "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
        )
        target.chmod(0o600)
        log.write_text("")
        for path in state.iterdir():
            path.unlink()
        malformed_restore = run(
            restore_shell,
            MODE="restore",
            MULTI_DOCUMENT=document,
            RELEASE_EVIDENCE=str(target),
        )
        assert malformed_restore.returncode != 0
        assert malformed_restore.stdout == ""
        assert re.fullmatch(
            rf"stage={stage} status=fail exit=[1-9][0-9]* reason=unclassified\n",
            malformed_restore.stderr,
        )
        commands = log.read_text()
        assert ("lambda update-alias" in commands) is lambda_update_expected
        assert "update-agent-runtime-endpoint" not in commands

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    malformed_readback = run(
        restore_shell,
        MODE="restore",
        LAMBDA_MALFORMED_READBACK="1",
        RELEASE_EVIDENCE=str(target),
    )
    assert malformed_readback.returncode == 5
    assert malformed_readback.stdout == ""
    assert malformed_readback.stderr == (
        "stage=lambda-readback-validate status=fail exit=5 reason=unclassified\n"
    )
    commands = log.read_text()
    assert "lambda update-alias" in commands
    assert "update-agent-runtime-endpoint" not in commands

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    broken_token = run(
        restore_shell,
        MODE="restore",
        PYTHON_BROKEN_NUL="token",
        RELEASE_EVIDENCE=str(target),
    )
    assert broken_token.returncode == 43
    assert broken_token.stdout == ""
    assert broken_token.stderr == (
        "stage=agentcore-token status=fail exit=43 reason=unclassified\n"
    )
    assert "RAW" not in broken_token.stderr
    commands = log.read_text()
    assert "lambda update-alias" in commands
    assert "update-agent-runtime-endpoint" not in commands

    hostile_targets = {
        "EXPECTED_ACCOUNT": "111111111111",
        "EXPECTED_REGION": "eu-west-1",
        "LAMBDA_FUNCTION": "wrong-function",
        "LAMBDA_ALIAS": "wrong-alias",
        "AGENTCORE_RUNTIME": "wrong-runtime",
        "AGENTCORE_ENDPOINT": "wrong-endpoint",
        "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "false",
        "AWS_ENDPOINT_URL": "http://127.0.0.1:9",
        "AWS_ENDPOINT_URL_STS": "http://127.0.0.1:9/sts",
        "AWS_ENDPOINT_URL_LAMBDA": "http://127.0.0.1:9/lambda",
        "AWS_ENDPOINT_URL_BEDROCK_AGENTCORE_CONTROL": "http://127.0.0.1:9/agentcore",
    }
    log.write_text("")
    hostile_capture = run(
        capture_shell,
        MODE="capture",
        RELEASE_EVIDENCE=str(tmp_path / "hostile-capture-record"),
        **hostile_targets,
    )
    assert hostile_capture.returncode == 0, hostile_capture.stderr
    commands = log.read_text()
    for expected in (
        "--region us-east-1",
        "--function-name tollchat-v2-chat-proxy --name live",
        "--agent-runtime-id nova_toll_v2-W6989LEw44 --endpoint-name preview",
    ):
        assert expected in commands
    assert not any(value in commands for value in hostile_targets.values())

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    hostile_restore = run(
        restore_shell,
        MODE="restore",
        RELEASE_EVIDENCE=str(target),
        **hostile_targets,
    )
    assert hostile_restore.returncode == 0, hostile_restore.stderr
    commands = log.read_text()
    for expected in (
        "--region us-east-1",
        "--function-name tollchat-v2-chat-proxy --name live",
        "--agent-runtime-id nova_toll_v2-W6989LEw44 --endpoint-name preview",
    ):
        assert expected in commands
    assert not any(value in commands for value in hostile_targets.values())

    for routing in routing_failures:
        target.write_text(
            "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
        )
        target.chmod(0o600)
        log.write_text("")
        for path in state.iterdir():
            path.unlink()
        failed = run(
            restore_shell,
            MODE="restore",
            LAMBDA_ROUTING=routing,
            RELEASE_EVIDENCE=str(target),
        )
        assert failed.returncode != 0
        assert re.fullmatch(
            r"stage=lambda-readback-validate status=fail exit=[1-9][0-9]* reason=unclassified\n",
            failed.stderr,
        )
        commands = log.read_text()
        assert "lambda update-alias" in commands
        assert "update-agent-runtime-endpoint" not in commands

    log.write_text("")
    (state / "lambda-get").unlink(missing_ok=True)
    (state / "agent-get").unlink(missing_ok=True)
    snapshot = run(
        restore_shell,
        MODE="restore",
        LAMBDA_ROUTING="absent",
        RELEASE_EVIDENCE=str(target),
        MUTATE_RECORD=str(target),
    )
    assert snapshot.returncode == 0, snapshot.stderr
    assert "function-version 7" in log.read_text()
    assert "lambda_live_function_version=999" in target.read_text()

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    custody_replacement = invalid_record(
        "custody-replacement-record",
        "lambda_live_function_version=999\nagentcore_endpoint_live_version=998\n",
    )
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    custody_replaced = run(
        restore_shell,
        MODE="restore",
        RELEASE_EVIDENCE=str(target),
        CUSTODY_REPLACE_SOURCE=str(target),
        CUSTODY_REPLACEMENT=str(custody_replacement),
    )
    assert custody_replaced.returncode != 0
    assert custody_replaced.stdout == ""
    assert custody_replaced.stderr == (
        "stage=record-snapshot status=fail exit=1 reason=unclassified\n"
    )
    assert "lambda update-alias" not in log.read_text()

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    replacement = invalid_record(
        "replacement-record",
        "lambda_live_function_version=999\nagentcore_endpoint_live_version=998\n",
    )
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    replaced_path = run(
        restore_shell,
        MODE="restore",
        RELEASE_EVIDENCE=str(target),
        REPLACE_AFTER_OPEN=str(target),
        REPLACEMENT=str(replacement),
    )
    assert replaced_path.returncode == 0, replaced_path.stderr
    assert "function-version 7" in log.read_text()
    assert "lambda_live_function_version=999" in target.read_text()

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    ambiguous = run(
        restore_shell,
        MODE="restore",
        AGENT_MODE="ambiguous",
        RELEASE_EVIDENCE=str(target),
    )
    assert ambiguous.returncode == 0, ambiguous.stderr
    commands = log.read_text().splitlines()
    updates = [line for line in commands if "update-agent-runtime-endpoint" in line]
    assert len(updates) == 2 and updates[0] == updates[1]
    assert "--client-token 00000000-0000-4000-8000-000000000000" in updates[0]
    update_positions = [
        index
        for index, command in enumerate(commands)
        if "update-agent-runtime-endpoint" in command
    ]
    endpoint_position = next(
        index
        for index, command in enumerate(commands)
        if "get-agent-runtime-endpoint" in command
    )
    assert update_positions[0] < endpoint_position < update_positions[1]

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    unresolved = run(
        restore_shell,
        MODE="restore",
        AGENT_MODE="unresolved",
        RELEASE_EVIDENCE=str(target),
    )
    assert unresolved.returncode == 23
    assert unresolved.stdout == ""
    assert unresolved.stderr == (
        "stage=agentcore-validate status=fail exit=23 reason=unclassified\n"
    )
    commands = log.read_text().splitlines()
    updates = [line for line in commands if "update-agent-runtime-endpoint" in line]
    reads = [
        index
        for index, command in enumerate(commands)
        if "get-agent-runtime-endpoint" in command
    ]
    update_positions = [
        index
        for index, command in enumerate(commands)
        if "update-agent-runtime-endpoint" in command
    ]
    assert len(updates) == 2 and updates[0] == updates[1]
    assert update_positions[0] < reads[0] < update_positions[1] < reads[1]

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    split_readback = run(
        restore_shell,
        MODE="restore",
        AGENT_MODE="ambiguous",
        MULTI_DOCUMENT="agent-restore-split",
        RELEASE_EVIDENCE=str(target),
    )
    assert split_readback.returncode == 23
    assert split_readback.stdout == ""
    assert split_readback.stderr == (
        "stage=agentcore-validate status=fail exit=23 reason=unclassified\n"
    )
    commands = log.read_text().splitlines()
    assert sum("update-agent-runtime-endpoint" in command for command in commands) == 1
    assert any("get-agent-runtime-endpoint" in command for command in commands)

    for bad_response in ("arn", "name", "target"):
        target.write_text(
            "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
        )
        target.chmod(0o600)
        log.write_text("")
        for path in state.iterdir():
            path.unlink()
        rejected = run(
            restore_shell,
            MODE="restore",
            AGENT_MODE="ambiguous",
            AGENT_BAD=bad_response,
            RELEASE_EVIDENCE=str(target),
        )
        assert rejected.returncode != 0
        assert re.fullmatch(
            r"stage=agentcore-validate status=fail exit=[1-9][0-9]* reason=unclassified\n",
            rejected.stderr,
        )
        commands = log.read_text().splitlines()
        assert (
            sum("update-agent-runtime-endpoint" in command for command in commands) == 1
        )
        assert any("get-agent-runtime-endpoint" in command for command in commands)

    target.write_text(
        "lambda_live_function_version=7\nagentcore_endpoint_live_version=8\n"
    )
    target.chmod(0o600)
    log.write_text("")
    for path in state.iterdir():
        path.unlink()
    lambda_failure = run(
        restore_shell,
        MODE="restore",
        FAIL_LAMBDA="1",
        SENTINEL_FAILURE="restore",
        RELEASE_EVIDENCE=str(target),
    )
    assert lambda_failure.returncode == 19
    assert lambda_failure.stdout == ""
    assert lambda_failure.stderr.splitlines() == [
        "stage=lambda-update status=fail exit=19 reason=unclassified"
    ]


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


def test_development_plan_policy_requires_reservations_and_valid_default_edge() -> None:
    release = DEPLOYMENT.split(
        "### Development application release and database validation (#331)", maxsplit=1
    )[1].split("### Development handoff (non-operative)", maxsplit=1)[0]
    policy_match = re.search(
        r"if ! jq -e '(\n\s+def managed_changes\(\$address\):.*?\n\s+)' \"\$PLAN_JSON\"",
        release,
        flags=re.DOTALL,
    )
    assert policy_match is not None
    policy = policy_match.group(1)

    def change(address: str, after: object) -> dict[str, object]:
        return {
            "mode": "managed",
            "address": address,
            "change": {"actions": ["create"], "after": after, "after_unknown": {}},
        }

    edge = {
        "aliases": [],
        "viewer_certificate": [
            {
                "acm_certificate_arn": None,
                "cloudfront_default_certificate": True,
                "minimum_protocol_version": "TLSv1",
                "ssl_support_method": None,
            }
        ],
    }
    plan = {
        "resource_changes": [
            change(
                "aws_lambda_function.loader",
                {"reserved_concurrent_executions": 5},
            ),
            change(
                "aws_lambda_function.publisher",
                {"reserved_concurrent_executions": 1},
            ),
            change(
                "aws_lambda_function.tollchat_proxy",
                {"reserved_concurrent_executions": 5},
            ),
            change("aws_cloudfront_distribution.site", edge),
        ]
    }

    def passes(candidate: object) -> bool:
        return (
            subprocess.run(
                ["jq", "-e", policy],
                input=json.dumps(candidate),
                text=True,
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )

    assert passes(plan)
    empty_actions = json.loads(json.dumps(plan))
    for resource in empty_actions["resource_changes"]:
        resource["change"]["actions"] = []
    assert not passes(empty_actions)
    for address, key, value in (
        ("aws_lambda_function.loader", "reserved_concurrent_executions", None),
        ("aws_lambda_function.publisher", "reserved_concurrent_executions", 5),
        ("aws_lambda_function.tollchat_proxy", "reserved_concurrent_executions", -1),
        ("aws_cloudfront_distribution.site", "aliases", ["preview.example"]),
        (
            "aws_cloudfront_distribution.site",
            "minimum_protocol_version",
            "TLSv1.2_2021",
        ),
    ):
        candidate = json.loads(json.dumps(plan))
        after = next(
            resource
            for resource in candidate["resource_changes"]
            if resource["address"] == address
        )["change"]["after"]
        if address.endswith("distribution.site") and key != "aliases":
            after["viewer_certificate"][0][key] = value
        else:
            after[key] = value
        assert not passes(candidate)


def test_development_secret_fetch_keeps_arn_out_of_argv_and_evidence() -> None:
    release = DEPLOYMENT.split(
        "### Development application release and database validation (#331)", maxsplit=1
    )[1].split("### Development handoff (non-operative)", maxsplit=1)[0]
    assert "secret_json()" in release
    assert 'SECRET_ARN="$SECRET_ARN"' in release
    assert 'SecretId=os.environ["SECRET_ARN"]' in release
    assert 'get-secret-value --secret-id "$SECRET_ARN"' not in release
    assert "--only-matching" in release
    assert 'test "$reference" = "$ALLOWED_SSM_REFERENCE"' in release
    pattern = re.search(r"SSM_ARN_PATTERN='([^']+)'", release)
    assert pattern is not None
    allowed = "arn:aws:ssm:us-east-1:903859731897:parameter/nova-toll/openai_api_key"
    unexpected = "arn:aws:ssm:us-east-1:903859731897:parameter/unexpected"
    python_pattern = pattern.group(1).replace("[:alnum:]", "A-Za-z0-9")
    matches = re.findall(
        python_pattern, json.dumps({"allowed": allowed, "unexpected": unexpected})
    )
    assert matches == [allowed, unexpected]
    assert (
        'test -z "$(git -C "$ROOT" status --porcelain --untracked-files=all)"'
        in release
    )
    assert "source_tree_sha256=$SOURCE_TREE_SHA256" in release
    assert "source_diff_sha256=$SOURCE_DIFF_SHA256" in release
    assert release.index('SOURCE_TREE_SHA256="$(source_tree_digest)"') < release.index(
        'tf_dev -chdir="$ROOT/v2/infra" plan'
    )


def test_development_release_scans_before_apply_and_never_bootstraps_deployed_database() -> (
    None
):
    release = DEPLOYMENT.split(
        "### Development application release and database validation (#331)", maxsplit=1
    )[1].split("### Development handoff (non-operative)", maxsplit=1)[0]

    phase_one_apply = (
        'tf_dev -chdir="$ROOT/v2/infra" apply -input=false "$PHASE_ONE_PLAN"'
    )
    phase_two_apply = (
        'tf_dev -chdir="$ROOT/v2/infra" apply -input=false "$PHASE_TWO_PLAN"'
    )
    assert release.index('scan_package "$package"') < release.index(phase_one_apply)
    assert release.index('scan_release_file "$PHASE_ONE_PLAN"') < release.index(
        phase_one_apply
    )
    assert release.index('scan_release_file "$PHASE_TWO_PLAN"') < release.index(
        phase_two_apply
    )
    assert 'python3 "$ROOT/v2/scripts/bootstrap_development_database.py"' not in release
    assert "database_bootstrap=not-run" in release
    assert "psql --dbname nova_toll_development --file" in release


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
        "golden",
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
    assert workflow_trigger(workflow) == {"push": {"branches": ["main"]}}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "v2-development-delivery",
        "queue": "max",
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
    assert "id: package-mode" in source
    assert 'test ! -L "$MANIFEST"' in build_source
    assert "isinstance(value, dict)" in build_source
    assert 'isinstance(value.get("deployment_inputs"), dict)' in build_source
    assert (
        '"v2/scripts/build_timed_checks_zip.sh" in value["deployment_inputs"]'
        in build_source
    )
    assert (
        "PACKAGE_NAMES=(agentcore.zip chat-proxy.zip loader.zip publisher.zip)"
        in build_source
    )
    assert (
        "PACKAGE_NAMES=(agentcore.zip chat-proxy.zip loader.zip publisher.zip timed-checks.zip)"
        in build_source
    )
    for package in (
        "loader.zip",
        "publisher.zip",
        "agentcore.zip",
        "chat-proxy.zip",
        "timed-checks.zip",
    ):
        assert package in build_source
    assert "DEPLOYMENT_SHA256SUMS" in build_source
    assert 'sha256sum "${PACKAGE_NAMES[@]}" > DEPLOYMENT_SHA256SUMS' in build_source
    assert (
        "awk '{print $2}' DEPLOYMENT_SHA256SUMS | LC_ALL=C sort | tr '\\n' ' '"
        in build_source
    )
    assert 'if [[ "$PACKAGE_MODE" = timed ]]; then' in build_source
    assert "./scripts/build_timed_checks_zip.sh" in build_source
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
    assert "--repo-root" not in plan_source
    assert 'test ! -L "$MANIFEST"' in plan_source
    assert "isinstance(value, dict)" in plan_source
    assert 'isinstance(value.get("deployment_inputs"), dict)' in plan_source
    assert (
        '"v2/scripts/build_timed_checks_zip.sh" in value["deployment_inputs"]'
        in plan_source
    )
    assert (
        "PACKAGE_NAMES=(agentcore.zip chat-proxy.zip loader.zip publisher.zip)"
        in plan_source
    )
    assert (
        "PACKAGE_NAMES=(agentcore.zip chat-proxy.zip loader.zip publisher.zip timed-checks.zip)"
        in plan_source
    )
    assert "PACKAGE_COUNT=4" in plan_source
    assert "PACKAGE_COUNT=5" in plan_source
    assert (
        "find \"$STAGING\" -mindepth 1 -maxdepth 1 -name '*.zip' -printf" in plan_source
    )
    assert 'test "$(wc -l <"$CHECKSUMS")" -eq "$PACKAGE_COUNT"' in plan_source
    assert 'sha256sum --check "$(basename "$CHECKSUMS")"' in plan_source
    assert source.index(
        "Verify candidate release binding without credentials"
    ) < source.index("aws-actions/configure-aws-credentials@")
    plan_start = source.index("\n  plan:\n")
    credential_index = source.index(
        "aws-actions/configure-aws-credentials@", plan_start
    )
    for boundary in (
        'PACKAGE_MODE="$(python3 - "$MANIFEST"',
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
        "timed_checks_package_path",
    ):
        assert f"-var {package_variable}" in plan_source
    assert (
        'cp "$STAGING/"*.zip "$GITHUB_WORKSPACE/trusted/v2/infra/build/"' in plan_source
    )
    for variable, package in (
        ("loader", "loader"),
        ("publisher", "publisher"),
        ("timed_checks", "timed-checks"),
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


def test_development_plan_workflow_digest_matches_reviewed_manifest() -> None:
    manifest = json.loads(
        (REPO_ROOT / "infra" / "development-release-manifest.json").read_text()
    )
    assert (
        hashlib.sha256(DEVELOPMENT_PLAN_WORKFLOW.encode()).hexdigest()
        == manifest["deployment_inputs"][".github/workflows/v2-development-plan.yml"]
    )


def test_development_delivery_selected_input_digests_match_reviewed_manifest() -> None:
    manifest = json.loads(
        (REPO_ROOT / "infra" / "development-release-manifest.json").read_text()
    )
    for relative in (
        ".github/workflows/v2-development-delivery.yml",
        ".github/workflows/v2-development-delivery-privileged.yml",
        "infra/delivery_plan_validator.py",
        "infra/iam.tf",
        "infra/release_manifest.py",
        "v2/scripts/development_deployment_status.py",
        "v2/agent_tools/currency.py",
        "v2/eval/run_evaluation.py",
        "v2/scripts/build_timed_checks_zip.sh",
    ):
        assert (
            hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
            == manifest["deployment_inputs"][relative]
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
    for variable in (
        "TOOL_CONTRACT_BASE_REF",
        "AGENT_CONTRACT_BASE_REF",
        "SCHEMA_BASE_REF",
        "BASE_REF",
    ):
        assert f"{variable}: ${{{{ {base_expression} }}}}" in source
    assert source.count(base_expression) == 4

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
    assert "continue-on-error" not in source

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
        ("@main", "@feature"),
        (
            "development-plan:\n    if: always()",
            "development-plan:\n    if: success()",
        ),
        ('test "$PLAN_RESULT" = success', 'test "$PLAN_RESULT" = skipped'),
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
            "timed-checks.zip",
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
    assert workflow_trigger(caller) == {"push": {"branches": ["main"]}}
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
        ("push:\n    branches:", "pull_request:\n    branches:"),
        ("- main", "- release"),
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
        "- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        "- uses: aws-actions/configure-aws-credentials@e1253824e5c10ff9df46874f81ed3ec929e19cfd",
    )
