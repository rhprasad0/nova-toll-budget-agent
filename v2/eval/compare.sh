#!/usr/bin/env bash
set -euo pipefail
exec python3 "$(dirname "$(realpath "$0")")/graph_checks.py" compare "$@"
