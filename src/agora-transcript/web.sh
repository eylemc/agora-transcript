#!/usr/bin/env bash
set -euo pipefail
transcript_app="$(cd -- "$(dirname -- "$0")" && pwd)"
exec "$transcript_app/.venv/bin/python" "$transcript_app/web.py" "$@"
