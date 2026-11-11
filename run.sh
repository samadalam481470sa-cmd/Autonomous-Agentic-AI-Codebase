#!/usr/bin/env bash
# Aetherion OmniForge - local bootstrap for Linux and macOS.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3.11+ is required. Install it, then run this script again." >&2
  exit 1
fi
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11+ is required (found $("$PYTHON" -V 2>&1))." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating local virtual environment in .venv ..."
  "$PYTHON" -m venv .venv
fi

# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --disable-pip-version-check --quiet -e .
exec python aetherion.py "$@"
