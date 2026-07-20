#!/usr/bin/env bash
# SessionStart setup: install the package so the `articlegen` CLI and the
# offline tests run immediately in a fresh session. Safe to re-run; never fails
# the session (exits 0 even if install hiccups).
set -u
cd "$(dirname "$0")/.." || exit 0

pip install -e . -q 2>/dev/null \
  || pip install -r requirements.txt -q 2>/dev/null \
  || true

echo "articlegen ready. Offline tests: python tests/test_offline.py"
exit 0
