# SPDX-License-Identifier: MPL-2.0
"""Loopback-only client for real IRIS verification, without provider requests."""
import base64
import http.cookiejar
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from local_config import read_env


class IrisCheckError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        raise IrisCheckError("IRIS redirected the request; credentials were not forwarded.")


class IrisClient:
    def __init__(self, expected_build=109, port=52773):
        if expected_build not in {154, 109}:
            raise ValueError("Supported verification targets are build 154 or 109.")
        self.expected_build = expected_build
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Choose a valid loopback port.")
        self.base_url = f"http://127.0.0.1:{port}/recall-guard/api/"
        self.expected_version = "2026.3" if expected_build == 154 else "2027.1"
        path = Path(__file__).resolve().parents[1] / ".env"
        try:
            password = read_env(path).get("IRIS_PASSWORD", "")
        except OSError:
            raise IrisCheckError("Run python scripts/init_env.py first.") from None
        if len(password) < 12:
            raise IrisCheckError("Configure IRIS_PASSWORD with python scripts/init_env.py first.")
        self.authorization = "Basic " + base64.b64encode(("SuperUser:" + password).encode()).decode()
        # Bypass proxy environment variables and never forward local credentials
        # to a redirect target. Remote Codespaces checks run inside the VM/SSH.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedirect())

    def request(self, action, payload=None):
        if action not in {"state", "seed", "load_recorded_demo", "transact", "preview_inventory", "import_inventory", "discovery_plan", "discover", "select_candidates"}:
            raise IrisCheckError("This verifier does not invoke agents or refresh sources.")
        request = urllib.request.Request(
            self.base_url + action,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Authorization": self.authorization, "Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(2_000_001)
        except urllib.error.HTTPError as exc:
            raise IrisCheckError(f"IRIS returned HTTP {exc.code} for {action}; inspect the local Production.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise IrisCheckError("Cannot reach local IRIS. Start the container and Production first.") from None
        if len(raw) > 2_000_000:
            raise IrisCheckError("IRIS response exceeded the verifier's size limit.")
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError):
            raise IrisCheckError("IRIS did not return a JSON response.") from None
        if isinstance(data, dict) and data.get("ok") is True and data.get("accepted") is True:
            return data
        if not isinstance(data, dict) or data.get("ok") is not True or not isinstance(data.get("result"), dict):
            raise IrisCheckError(f"IRIS rejected {action}; inspect the local Production for details.")
        return data["result"]

    def state(self):
        state = self.request("state")
        if state.get("backend") != "intersystems-iris":
            raise IrisCheckError("A real IRIS backend was not confirmed.")
        if state.get("ai_hub_agent_class_present") is not True:
            raise IrisCheckError("AI Hub %AI.Agent is unavailable.")
        version = state.get("iris_version", "")
        build_pattern = rf"\bBuild\s+{self.expected_build}U?(?=[.\s)]|$)"
        if not isinstance(version, str) or self.expected_version not in version or not re.search(build_pattern, version):
            raise IrisCheckError(f"Expected IRIS AI Hub {self.expected_version} build {self.expected_build}.")
        return state
