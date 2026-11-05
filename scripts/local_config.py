# SPDX-License-Identifier: MPL-2.0
"""Read local development settings without logging secrets."""
from pathlib import Path


def read_env(path=Path(".env")):
    result = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result
