# SPDX-License-Identifier: MPL-2.0
"""Start an isolated no-key first visit, or stop it while retaining its data."""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from iris_client import IrisClient
from local_config import read_env

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop"))
    parser.add_argument("--build", action="store_true", help="Rebuild after changing or updating application source.")
    parser.add_argument("--iris-build", type=int, choices=(154, 109), default=109,
                        help="Current target is build 109; select 154 explicitly for historical compatibility work.")
    parser.add_argument("--project",
                        help="Separate Compose project/data volume; existing data is never reset.")
    args = parser.parse_args()
    if not args.project:
        args.project = "recall-to-inventory-bridge-judge" + ("-109" if args.iris_build == 109 else "")
    if not re.fullmatch(r"recall-to-inventory-bridge-judge(?:-[a-z0-9-]+)?", args.project):
        parser.error("Use the judge project prefix; the live project is not accepted.")
    version = "2026.3.0AI.154.0" if args.iris_build == 154 else "2027.1.0AI.109.0"
    base_image = "recall-guard-aihub:" + version
    image = "recall-to-inventory-bridge-judge" + ("-109" if args.iris_build == 109 else "") + ":local"
    env = {**os.environ, "COMPOSE_PROJECT_NAME": args.project, "IRIS_IMAGE": base_image, "JUDGE_IMAGE": image,
           "COMPOSE_FILE": os.pathsep.join(str(ROOT / p) for p in ("compose.yaml", "compose.judge.yaml"))}
    try:
        if args.action == "stop":
            return subprocess.run([sys.executable, "scripts/stop_iris.py"], cwd=ROOT, env=env, timeout=150).returncode
        disk = subprocess.run(["docker", "run", "--rm", "--pull", "never", "--entrypoint", "/bin/df",
                               base_image, "-Pk", "/usr/irissys/mgr"],
                              cwd=ROOT, env=env, capture_output=True, text=True, timeout=35)
        if disk.returncode:
            raise RuntimeError("Cannot inspect Docker storage. Load the selected private AI Hub image and start Docker first.")
        image_exists = subprocess.run(["docker", "image", "inspect", image],
                                      capture_output=True, env=env, timeout=20).returncode == 0
        must_build = args.build or not image_exists
        required_bytes = 2 * 1024 ** 3
        if must_build:
            size = subprocess.run(["docker", "image", "inspect", base_image, "--format", "{{.Size}}"],
                                  cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
            if size.returncode or not size.stdout.strip().isdigit():
                raise RuntimeError("Cannot inspect the selected base image's storage requirement.")
            # BuildKit may unpack another complete copy of an imported EAP image.
            # Keep runtime headroom instead of relying on shared-cache savings.
            required_bytes += int(size.stdout.strip())
        if int(disk.stdout.strip().splitlines()[-1].split()[3]) * 1024 < required_bytes:
            raise RuntimeError(f"Docker needs at least {required_bytes / 1024 ** 3:.1f} GiB free for "
                               + ("this conservative fresh-build estimate. " if must_build else "startup. ")
                               + "Inspect docker system df or use the documented IPM route; no automatic deletion was performed.")
        subprocess.run([sys.executable, "scripts/init_env.py"], cwd=ROOT, env=env, check=True, timeout=20)
        build = "--build" if must_build else "--no-build"
        subprocess.run(["docker", "compose", "up", "-d", build, "--pull", "never", "iris"],
                       cwd=ROOT, env=env, check=True, timeout=600)
        subprocess.run([sys.executable, "scripts/wait_iris.py"], cwd=ROOT, env=env, check=True, timeout=210)
        console = ('try { set sc=1 if \'##class(Ens.Director).IsProductionRunning() { set sc=##class(RecallGuard.Setup).Start() } '
                   'if $SYSTEM.Status.IsError(sc) { '
                   'if $find($SYSTEM.Status.GetErrorText(sc),"ErrProductionNotShutdownCleanly") { '
                   'set sc=##class(Ens.Director).RecoverProduction() '
                   'if \'$SYSTEM.Status.IsError(sc) { '
                   'if \'##class(Ens.Director).IsProductionRunning() { set sc=##class(RecallGuard.Setup).Start() } } } } '
                   'if $SYSTEM.Status.IsError(sc) { do $SYSTEM.Status.DisplayError(sc) do $SYSTEM.Process.Terminate(,1) } '
                   'write "BRIDGE_JUDGE_READY",! } catch ex { write ex.DisplayString(),! do $SYSTEM.Process.Terminate(,1) }\n'
                   'do $SYSTEM.Process.Terminate(,0)\n')
        result = subprocess.run(["docker", "compose", "exec", "-T", "iris", "iris", "session", "IRIS", "-U", "RECALLGUARD"],
                                cwd=ROOT, env=env, input=console, capture_output=True, text=True, timeout=100)
        if result.returncode or "BRIDGE_JUDGE_READY" not in result.stdout:
            diagnostic = result.stdout + result.stderr
            for key in ("GEMINI_API_KEY", "IRIS_PASSWORD"):
                value = read_env(ROOT / ".env").get(key)
                if value:
                    diagnostic = diagnostic.replace(value, "[REDACTED]")
            path = ROOT / ".artifacts" / (args.project + "-startup.log")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(diagnostic, encoding="utf-8")
            raise RuntimeError("Production startup was not confirmed. Inspect the redacted .artifacts/" + path.name + "; no data was reset.")
        state = IrisClient(expected_build=args.iris_build).state()
        if (not state["production_running"] or state["configuration"]["api_key_present"]
                or state["configuration"]["agent_mode"] != "disabled"):
            raise RuntimeError("The actual no-key Production configuration was not confirmed.")
        print("No-key judge instance ready. The live project's image, volume and .env settings were preserved.")
        print("http://localhost:52773/recall-guard/auth/RecallGuard.Home.cls")
        print("Sign in with your local IRIS_PASSWORD; import a snapshot, or choose the separate recorded AI course.")
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(str(error) if isinstance(error, RuntimeError) else
              "Judge setup failed. Inspect the separate project; existing data was retained.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
