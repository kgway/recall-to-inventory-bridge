# SPDX-License-Identifier: MPL-2.0
"""Prepare local-only credentials without printing or replacing existing keys."""
import secrets
from pathlib import Path

from local_config import read_env

root = Path(__file__).resolve().parents[1]
path = root / ".env"
if not path.exists():
    path.write_text((root / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
settings = read_env(path)
if len(settings.get("IRIS_PASSWORD", "")) < 12:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    replacement = "IRIS_PASSWORD=" + secrets.token_urlsafe(24)
    found = False
    for i, line in enumerate(lines):
        if line.startswith("IRIS_PASSWORD="):
            lines[i] = replacement
            found = True
    if not found:
        lines.append(replacement)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Created a local IRIS demo password in .env. Existing Gemini settings were preserved.")
else:
    print("Local IRIS password already configured. No settings were changed.")
