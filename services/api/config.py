"""Local configuration loading for the API.

The app is documented as reading ``.env``, so load it before any module reads
configuration at import time. Explicit process environment variables always
win. No shell expansion is performed: values are data, not code.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"'}


def _value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
        if raw.strip()[0] == '"':
            value = re.sub(r"\\(.)", lambda match: _ESCAPES.get(match.group(1), "\\" + match.group(1)), value)
        return value
    # A comment starts only after whitespace, so URLs and other values can
    # contain '#' without being truncated.
    return re.split(r"\s+#", value, maxsplit=1)[0].rstrip()


def load_env_file(path: str | Path | None = None) -> int:
    """Load KEY=value pairs from ``path`` and return how many were applied.

    The default location is the repository-level ``.env``. Missing or invalid
    files are ignored so a bad local config cannot prevent startup; malformed
    lines are skipped individually.
    """
    env_path = Path(path) if path is not None else Path(__file__).resolve().parents[2] / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        return 0

    loaded = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not _ENV_KEY.fullmatch(key) or key in os.environ:
            continue
        os.environ[key] = _value(raw_value)
        loaded += 1
    return loaded
