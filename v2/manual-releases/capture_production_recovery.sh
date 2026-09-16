#!/usr/bin/env bash
# Capture fixed production routing versions; reads AWS and creates a private record.
(
  set -euo pipefail
  set +x
  umask 077
  EXPECTED_ACCOUNT=920534282028
  EXPECTED_REGION=us-east-1
  LAMBDA_FUNCTION=tollchat-v2-chat-proxy
  LAMBDA_ALIAS=live
  AGENTCORE_RUNTIME=nova_toll_v2-W6989LEw44
  AGENTCORE_ENDPOINT=preview
  export AWS_IGNORE_CONFIGURED_ENDPOINT_URLS=true
  CURRENT_STAGE=record-path
  FAILURE_REPORTED=0
  finish() {
    local status=$?
    trap - EXIT
    if (( status != 0 && FAILURE_REPORTED == 0 )); then
      printf 'stage=%s status=fail exit=%s reason=unclassified\n' "$CURRENT_STAGE" "$status" >&2 || :
      FAILURE_REPORTED=1
    fi
    exit "$status"
  }
  trap finish EXIT
  trap 'exit 130' HUP INT TERM
  CURRENT_STAGE=record-path
  test -n "${RELEASE_EVIDENCE-}"
  CURRENT_STAGE=account-identity
  set +e
  AWS_PROFILE=nova-toll-prod aws --region "$EXPECTED_REGION" \
    sts get-caller-identity --query Account --output text 2>&1 | cmp -s - <(printf '%s\n' "$EXPECTED_ACCOUNT") 2>/dev/null
  statuses=("${PIPESTATUS[@]}")
  set -e
  (( statuses[0] == 0 )) || exit "${statuses[0]}"
  (( statuses[1] == 0 )) || exit "${statuses[1]}"
  CURRENT_STAGE=lambda-validate
  LAMBDA_LIVE_FUNCTION_VERSION="$(
    set +e
    AWS_PROFILE=nova-toll-prod aws --region "$EXPECTED_REGION" lambda get-alias \
      --function-name "$LAMBDA_FUNCTION" --name "$LAMBDA_ALIAS" --output json 2>&1 | jq -ser '
    select(length == 1) | .[0] | select(.AliasArn == "arn:aws:lambda:us-east-1:920534282028:function:tollchat-v2-chat-proxy:live" and .Name == "live" and
      (.FunctionVersion | type == "string" and test("^[0-9]+$")) and
      (.FunctionVersion | tonumber > 0) and
      (if has("RoutingConfig") then
        .RoutingConfig as $routing |
        if ($routing | type) != "object" then false
        elif ($routing | has("AdditionalVersionWeights")) then
          ($routing.AdditionalVersionWeights | type == "object" and length == 0)
        else true
        end
      else true
      end))
    | .FunctionVersion
    ' 2>/dev/null
    statuses=("${PIPESTATUS[@]}")
    set -e
    (( statuses[0] == 0 )) || exit "${statuses[0]}"
    exit "${statuses[1]}"
  )"
  CURRENT_STAGE=agentcore-validate
  AGENTCORE_ENDPOINT_LIVE_VERSION="$(
    set +e
    AWS_PROFILE=nova-toll-prod aws --region "$EXPECTED_REGION" bedrock-agentcore-control get-agent-runtime-endpoint \
      --agent-runtime-id "$AGENTCORE_RUNTIME" --endpoint-name "$AGENTCORE_ENDPOINT" --output json 2>&1 | jq -ser '
    select(length == 1) | .[0] | select(.agentRuntimeArn == "arn:aws:bedrock-agentcore:us-east-1:920534282028:runtime/nova_toll_v2-W6989LEw44" and
      .name == "preview" and .status == "READY" and
      (.liveVersion | type == "string" and test("^[1-9][0-9]*$")) and
      (if has("targetVersion") then .targetVersion == .liveVersion else true end))
    | .liveVersion
    ' 2>/dev/null
    statuses=("${PIPESTATUS[@]}")
    set -e
    (( statuses[0] == 0 )) || exit "${statuses[0]}"
    exit "${statuses[1]}"
  )"
  CURRENT_STAGE=record-write
  if CAPTURE_WRITE_STAGE="$(
    set +e
    python3 -I -S - "$RELEASE_EVIDENCE" "$LAMBDA_LIVE_FUNCTION_VERSION" "$AGENTCORE_ENDPOINT_LIVE_VERSION" 2>/dev/null <<'PY' | jq -Rser '
    select(. == "" or . == "record-path")
    ' 2>/dev/null
import os
import stat
import sys

try:
    path, lambda_version, agentcore_version = sys.argv[1:]
    record = (
        f"lambda_live_function_version={lambda_version}\n"
        f"agentcore_endpoint_live_version={agentcore_version}\n"
    ).encode("ascii")
    if len(record) > 256:
        raise ValueError
    parent, basename = os.path.split(path)
    if not basename:
        raise ValueError
    directory = os.open(
        parent or ".", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    try:
        parent_info = os.fstat(directory)
        if parent_info.st_uid != os.geteuid() or parent_info.st_mode & 0o022:
            sys.stdout.write("record-path")
            raise SystemExit(1)
        fd = os.open(
            basename,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid()
            ):
                raise ValueError
            offset = 0
            while offset < len(record):
                written = os.write(fd, record[offset:])
                if written <= 0:
                    raise OSError
                offset += written
            named = os.stat(basename, dir_fd=directory, follow_symlinks=False)
            if (
                named.st_dev != info.st_dev
                or named.st_ino != info.st_ino
                or named.st_uid != os.geteuid()
                or not stat.S_ISREG(named.st_mode)
                or stat.S_IMODE(named.st_mode) != 0o600
            ):
                raise ValueError
            if os.fstat(fd).st_nlink != 1:
                raise ValueError
        finally:
            os.close(fd)
    finally:
        os.close(directory)
except FileExistsError:
    sys.stdout.write("record-path")
    raise SystemExit(1)
except (OSError, ValueError):
    raise SystemExit(1)
PY
    statuses=("${PIPESTATUS[@]}")
    set -e
    (( statuses[0] == 0 )) || exit "${statuses[0]}"
    exit "${statuses[1]}"
  )"; then
    :
  else
    CAPTURE_WRITE_STATUS=$?
    if test "$CAPTURE_WRITE_STAGE" = record-path; then CURRENT_STAGE=record-path; fi
    exit "$CAPTURE_WRITE_STATUS"
  fi
  unset LAMBDA_LIVE_FUNCTION_VERSION AGENTCORE_ENDPOINT_LIVE_VERSION
)
