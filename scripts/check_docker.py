# SPDX-License-Identifier: MPL-2.0
"""Bounded, read-only engine check; never starts the Docker dashboard."""
import argparse
import json
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-path", default="docker")
    args = parser.parse_args()
    try:
        result = subprocess.run([args.docker_path, "version", "--format", "{{json .Server}}"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
    except subprocess.TimeoutExpired:
        raise SystemExit("Docker did not respond within 15 seconds. Check WSL2 and `docker desktop status` before retrying.")
    except OSError:
        raise SystemExit("Docker CLI is unavailable. Complete local Docker setup before starting Recall-to-Inventory Bridge.")
    if result.returncode:
        raise SystemExit("Docker engine is unavailable. Check `docker desktop status`; after host setup, use `docker desktop start`.")
    try:
        server = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise SystemExit("Docker did not return a valid engine response.")
    if not isinstance(server, dict) or server.get("Os") != "linux":
        raise SystemExit("A running Linux Docker engine is required for the private AI Hub image.")
    print(json.dumps({"engine": "linux", "version": server.get("Version"), "ready": True}))


if __name__ == "__main__":
    main()
