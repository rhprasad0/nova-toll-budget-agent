#!/usr/bin/env bash
set -euo pipefail

git clone --quiet /work/in/base.bundle /work/repo
cd /work/repo
git checkout --quiet -b "$1"
git config user.name factory-worker
git config user.email factory-worker@localhost
v2/scripts/setup.sh
