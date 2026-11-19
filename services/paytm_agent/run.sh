#!/usr/bin/env bash
# Local run. PORT and ALLOWED_ORIGINS come from the environment, never from the code.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip -q install -r requirements.txt
exec .venv/bin/python -m uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8002}" "$@"
