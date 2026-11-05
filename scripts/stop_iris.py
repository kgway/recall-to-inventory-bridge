# SPDX-License-Identifier: MPL-2.0
"""Stop the Production before its container; never restarts the host or deletes data."""
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    console = ('try { set sc=##class(Ens.Director).StopProduction(30,0) '
               'if $SYSTEM.Status.IsError(sc) { do $SYSTEM.Process.Terminate(,1) } '
               'write "BRIDGE_PRODUCTION_STOPPED",! '
               '} catch ex { do $SYSTEM.Process.Terminate(,1) }\n'
               'do $SYSTEM.Process.Terminate(,0)\n')
    try:
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "iris", "iris", "session", "IRIS", "-U", "RECALLGUARD"],
            cwd=root, input=console, capture_output=True, text=True, timeout=50,
        )
        if result.returncode or "BRIDGE_PRODUCTION_STOPPED" not in result.stdout:
            print("Production stop was not confirmed. Inspect the local IRIS logs before stopping the container.", file=sys.stderr)
            return 1
        result = subprocess.run(["docker", "compose", "stop", "iris"], cwd=root, timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        print("Shutdown did not complete; inspect the local IRIS/container state.", file=sys.stderr)
        return 1
    if result.returncode:
        return result.returncode
    print("Recall-to-Inventory Bridge Production and container stopped; persistent data retained.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
