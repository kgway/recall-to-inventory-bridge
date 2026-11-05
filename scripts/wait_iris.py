# SPDX-License-Identifier: MPL-2.0
"""Wait for the real IRIS instance before attempting application setup."""
import argparse
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker-path', default='docker')
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 600:
        parser.error('--timeout must be between 1 and 600 seconds')
    deadline = time.monotonic() + args.timeout
    command = [args.docker_path, 'compose', 'exec', '-T', 'iris', 'iris', 'qlist', 'IRIS']
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1],
                                    capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and result.returncode == 0:
            for line in result.stdout.splitlines():
                fields = line.split('^')
                if (len(fields) > 8 and fields[0] == 'IRIS' and fields[3].lower().startswith('running')
                        and fields[8] in {'ok', 'warn', 'alert'}):
                    # qlist can say running while logons remain inhibited during
                    # startup. A real native session must also succeed.
                    try:
                        probe = subprocess.run(
                            [args.docker_path, 'compose', 'exec', '-T', 'iris',
                             'iris', 'session', 'IRIS', '-U', 'RECALLGUARD'],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                            text=True, timeout=15,
                            input='write "RECALL_GUARD_SESSION_READY",!\ndo $SYSTEM.Process.Terminate(,0)\n')
                    except (OSError, subprocess.TimeoutExpired):
                        probe = None
                    if probe is not None and probe.returncode == 0 and 'RECALL_GUARD_SESSION_READY' in probe.stdout:
                        print('IRIS accepts sessions; instance health: ' + fields[8])
                        return 0
        time.sleep(2)
    print('IRIS did not become ready. Inspect docker compose logs iris before retrying.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
