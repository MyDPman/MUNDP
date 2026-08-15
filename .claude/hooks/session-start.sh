#!/bin/bash
set -euo pipefail

# Set up the Python environment for Claude Code on the web sessions.
# Local machines manage their own .venv, so do nothing outside remote.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi

.venv/bin/pip install --quiet -r requirements.txt
