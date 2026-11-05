# SPDX-License-Identifier: MPL-2.0
"""Export real Interoperability message correlation for a stored run; no inference."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--container", help="Explicit local container for an isolated verification instance.")
    parser.add_argument("--scan-limit", type=int, default=2000, help="Bounded recent-header window (1–20000).")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{32}", args.run_id):
        parser.error("run_id must be a stored 32-character hexadecimal ID")
    if args.container and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,200}", args.container):
        parser.error("Choose a valid local container name")
    if not 1 <= args.scan_limit <= 20000:
        parser.error("scan-limit must be between 1 and 20000")
    if args.output.exists():
        parser.error("Choose a new evidence file; existing evidence is preserved")
    # Read only native message headers and application message bodies. The
    # bounded scan includes failed runs rather than silently filtering them out.
    console = '''try {
 set stmt=##class(%SQL.Statement).%New()
 set sc=stmt.%Prepare("SELECT TOP 2000 ID,SessionId,SourceConfigName,TargetConfigName,MessageBodyClassName,MessageBodyId,TimeCreated,TimeProcessed,Type FROM Ens.MessageHeader ORDER BY ID DESC")
 if $SYSTEM.Status.IsError(sc) { do $SYSTEM.Status.DisplayError(sc) do $SYSTEM.Process.Terminate(,1) }
 set rs=stmt.%Execute(), rows=[]
 while rs.%Next() {
  set cls=rs.%Get("MessageBodyClassName")
  if (cls="RecallGuard.Message.Request")!(cls="RecallGuard.Message.Response") {
   set body=$classmethod(cls,"%OpenId",rs.%Get("MessageBodyId"))
   if $isobject(body) {
    set row={}
    for key="ID","SessionId","SourceConfigName","TargetConfigName","MessageBodyClassName","MessageBodyId","TimeCreated","TimeProcessed","Type" { do row.%Set(key,rs.%Get(key)) }
    set row.payload=body.Payload
    if cls="RecallGuard.Message.Request" { set row.action=body.Action }
    do rows.%Push(row)
   }
  }
 }
 if rs.%SQLCODE<0 { write "Trace query failed",! do $SYSTEM.Process.Terminate(,1) }
 write "RECALL_TRACE=",rows.%ToJSON(),!
} catch ex { write "Trace query failed",! do $SYSTEM.Process.Terminate(,1) }
do $SYSTEM.Process.Terminate(,0)
'''
    # The native interactive console accepts a compound Try block on one line.
    lines = console.strip().splitlines()
    console = " ".join(line.strip() for line in lines[:-1]) + "\n" + lines[-1] + "\n"
    console = console.replace("TOP 2000", "TOP " + str(args.scan_limit))
    root = Path(__file__).resolve().parents[1]
    try:
        command = (["docker", "exec", "-i", args.container] if args.container else
                   ["docker", "compose", "exec", "-T", "iris"])
        process = subprocess.run(
            command + ["iris", "session", "IRIS", "-U", "RECALLGUARD"],
            cwd=root, input=console, capture_output=True, text=True, timeout=60,
        )
        line = next(line for line in process.stdout.splitlines() if line.startswith("RECALL_TRACE="))
        rows = json.loads(line.removeprefix("RECALL_TRACE="))
        if process.returncode:
            raise ValueError("Console failed")
    except (OSError, subprocess.TimeoutExpired, StopIteration, ValueError):
        print("Could not read native messages. Start IRIS and inspect its local logs.", file=sys.stderr)
        return 1
    sessions = {row["SessionId"] for row in rows if args.run_id in row["payload"]}
    if not sessions:
        print(f"No matching run in the most recent {args.scan_limit} message headers; evidence was not created.", file=sys.stderr)
        return 1
    messages = []
    completed = None
    for row in reversed(rows):
        if row["SessionId"] not in sessions:
            continue
        payload = row.pop("payload")
        row["payload_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
        row["contains_run_id"] = args.run_id in payload
        try:
            body = json.loads(payload)
        except ValueError:
            body = {}
        if isinstance(body, dict):
            row["payload_keys"] = sorted(body)
            candidate = body.get("result", body)
            if isinstance(candidate, dict) and candidate.get("run_id") == args.run_id and candidate.get("finished_at"):
                # Only safe application metadata, not full tool/source payloads.
                completed = {key: candidate[key] for key in (
                    "run_id", "notice_id", "notice_version", "status", "mode", "provider", "model",
                    "prompt_version", "policy_version", "created_at", "finished_at", "tool_calls", "usage", "audit_cycle_id"
                ) if key in candidate}
        messages.append(row)
    record = {"at_utc": datetime.now(timezone.utc).isoformat(), "success": bool(completed),
              "purpose": "Native Interoperability trace of a previously executed AI Hub investigation",
              "run_id": args.run_id, "llm_called_by_this_check": False,
              "scan_limit_headers": args.scan_limit, "session_ids": sorted(sessions),
              "messages": messages, "run_metadata_from_message": completed,
              "scope": "Agent execution and application tool messages; not per-provider HTTP spans or hidden reasoning"}
    if not completed:
        print("Messages were found, but completed run metadata was absent; evidence was not created.", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(record, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"success": True, "run_id": args.run_id, "session_ids": sorted(sessions),
                      "message_count": len(messages), "llm_called": False}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
