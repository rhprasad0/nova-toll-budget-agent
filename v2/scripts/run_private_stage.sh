#!/usr/bin/env bash

_run_private_stage_emit() {
  local event="$1"
  printf '%s\n' "$event" >&2
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    if ! (printf '%s\n' "$event" >>"$GITHUB_STEP_SUMMARY") 2>/dev/null; then
      PRIVATE_STAGE_SUMMARY_FAILED=1
    fi
  fi
}

run_private_stage() {
  local stage="${1-}"
  local stdout_log="${2-}"
  local stderr_log="${3-}"
  shift 3 2>/dev/null || true

  case "$stage" in
    foundation-init|foundation-output|foundation-output-validation|foundation-vars|release-init|plan|show|validator|apply|readiness-state|readiness-check|cleanup) ;;
    *)
      _run_private_stage_emit 'stage=invalid status=fail elapsed=0 exit=64 reason=unclassified'
      return 64
      ;;
  esac
  if [[ -z "$stdout_log" || -z "$stderr_log" || "$#" -eq 0 ]]; then
    _run_private_stage_emit "stage=$stage status=fail elapsed=0 exit=64 reason=diagnostic_unavailable"
    return 64
  fi

  local started finished elapsed status reason
  PRIVATE_STAGE_REPORTED=0
  PRIVATE_STAGE_SUMMARY_FAILED=0
  started="$(date +%s 2>/dev/null)" || {
    _run_private_stage_emit "stage=$stage status=fail elapsed=0 exit=125 reason=unclassified"
    return 125
  }
  [[ "$started" =~ ^[0-9]+$ ]] || {
    _run_private_stage_emit "stage=$stage status=fail elapsed=0 exit=125 reason=unclassified"
    return 125
  }
  _run_private_stage_emit "stage=$stage status=start elapsed=0 exit=0 reason=unclassified"
  if (( PRIVATE_STAGE_SUMMARY_FAILED )); then
    _run_private_stage_emit "stage=$stage status=fail elapsed=0 exit=125 reason=unclassified"
    PRIVATE_STAGE_REPORTED=1
    return 125
  fi

  local errexit_was_set=0
  case "$-" in *e*) errexit_was_set=1 ;; esac
  set +e
  umask 077
  (
    if [[ "$stdout_log" == "$stderr_log" ]]; then
      "$@" >"$stdout_log" 2>&1
    else
      "$@" >"$stdout_log" 2>"$stderr_log"
    fi
  ) 2>/dev/null
  status=$?
  if (( errexit_was_set )); then set -e; else set +e; fi

  if finished="$(date +%s 2>/dev/null)"; then :; else finished="$started"; fi
  if [[ "$finished" =~ ^[0-9]+$ && "$finished" -ge "$started" ]]; then
    elapsed=$((finished - started))
  else
    elapsed=0
  fi
  if (( status == 0 )); then
    _run_private_stage_emit "stage=$stage status=pass elapsed=$elapsed exit=0 reason=unclassified"
    if (( PRIVATE_STAGE_SUMMARY_FAILED )); then
      _run_private_stage_emit "stage=$stage status=fail elapsed=$elapsed exit=125 reason=unclassified"
      PRIVATE_STAGE_REPORTED=1
      return 125
    fi
    return 0
  fi

  reason="diagnostic_unavailable"
  if [[ -r "$stdout_log" && -r "$stderr_log" ]]; then
    if reason="$(python3 "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/classify_deployment_error.py" "$stdout_log" "$stderr_log" 2>/dev/null)"; then :; else reason=diagnostic_unavailable; fi
    case "$reason" in
      access_denied|expired_credentials|network|dns|tls|backend_config|state_lock|provider_installation|checksum|malformed_input|unclassified|diagnostic_unavailable) ;;
      *) reason=unclassified ;;
    esac
  fi
  _run_private_stage_emit "stage=$stage status=fail elapsed=$elapsed exit=$status reason=$reason"
  PRIVATE_STAGE_REPORTED=1
  return "$status"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -euo pipefail
  run_private_stage "$@"
fi
