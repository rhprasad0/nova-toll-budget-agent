#!/usr/bin/env bash
# Runs inside the sandbox: clone the base bundle and run the required checks.
# Inputs in /work/in: base.bundle and verify.sh, both from the dispatcher's
# checkout of main, so a work order cannot change which checks run.
set -euo pipefail

git clone --quiet --branch "${FACTORY_BRANCH:-main}" /work/in/base.bundle /work/repo
cd /work/repo
install -m 755 /work/in/verify.sh .github/scripts/verify.sh
exec .github/scripts/verify.sh "$@"
