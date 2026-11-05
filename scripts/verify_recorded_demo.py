# SPDX-License-Identifier: MPL-2.0
"""Exercise the recorded-demo gate through real IRIS; no LLM or source fetch."""
import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from iris_client import IrisCheckError, IrisClient

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--load", action="store_true", help="Load the pinned package into an empty instance.")
    parser.add_argument("--iris-build", type=int, choices=(154, 109), default=109)
    parser.add_argument("--port", type=int, default=52773, help="Loopback port of the separate test instance.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new evidence path; existing records are not overwritten.")
    proof = {"at_utc": datetime.now(timezone.utc).isoformat(), "success": False,
             "verification_kind": "Actual IRIS Production with recorded genuine proposals",
             "llm_called": False, "fresh_ai_hub_execution": False}
    try:
        client = IrisClient(expected_build=args.iris_build, port=args.port)
        initial = client.state()
        if not initial["production_running"] or initial["configuration"]["api_key_present"]:
            raise ValueError("Use a running isolated IRIS instance without a model key.")
        if initial["configuration"]["agent_mode"] != "disabled":
            raise ValueError("AGENT_MODE must be disabled.")
        if args.load:
            proof["load_result"] = client.request("load_recorded_demo", {})
        before = client.state()
        if before["meta"].get("experience_mode") != "recorded-demo":
            raise ValueError("Load the recorded demo in an empty instance first.")
        expected = json.loads((ROOT / "fixtures/expected_decisions.json").read_text())
        observed = {(a["lot_id"], a["notice_id"]): a["decision"] for a in before["assessments"]}
        for case in expected["cases"]:
            for notice, decision in zip(expected["notice_order"], case["decisions"], strict=True):
                if observed.get((case["lot_id"], notice)) != decision:
                    raise ValueError("Revalidated decisions differ from the independent labels.")
        if len(before["runs"]) != 3 or any(r["mode"] != "recorded-demo" or r["tool_calls"] or r["usage"] for r in before["runs"]):
            raise ValueError("Expected only recorded validation runs, without new tools or usage.")
        prefix = "recorded-check-" + uuid.uuid4().hex
        def order(name, kind, lots):
            return client.request("transact", {"idempotency_key": prefix + "-" + name,
                                  "kind": kind, "lines": [{"lot_id": lot, "quantity": 1} for lot in lots]})
        results = {"recall_sale": order("recall-sale", "sale", ["DREO-start"]),
                   "recall_shipment": order("recall-ship", "shipment", ["DREO-start"]),
                   "unknown_date": order("unknown", "shipment", ["DREO-unknown"]),
                   "mixed_order": order("mixed", "shipment", ["DREO-before", "DREO-end"]),
                   "eligible_sale": order("eligible", "sale", ["DREO-before"])}
        results["eligible_retry"] = order("eligible", "sale", ["DREO-before"])
        if (any(results[k]["allowed"] for k in ("recall_sale", "recall_shipment", "unknown_date", "mixed_order"))
                or not results["eligible_sale"]["allowed"] or not results["eligible_retry"]["replayed"]):
            raise ValueError("Recorded-demo retailer gate did not give the expected results.")
        after = client.state()
        old = {lot["lot_id"]: lot["quantity"] for lot in before["lots"]}
        new = {lot["lot_id"]: lot["quantity"] for lot in after["lots"]}
        if any(new[key] != qty - (1 if key == "DREO-before" else 0) for key, qty in old.items()):
            raise ValueError("Stock changed beyond the single eligible sale.")
        if len(after["transactions"]) != len(before["transactions"]) + 5 or after["runs"] != before["runs"]:
            raise ValueError("Unexpected transaction or investigation records.")
        proof.update(success=True, iris_version=after["iris_version"], backend=after["backend"],
                     api_key_absent=True, agent_mode="disabled", expected_decisions_matched=36,
                     recorded_runs=3, new_inferences=0, results=results, stock_before=old, stock_after=new,
                     transaction_increase=5, package_sha256=after["meta"]["recorded_package_sha256"])
    except (IrisCheckError, ValueError, OSError, KeyError) as error:
        proof["error"] = str(error)
    proof["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(proof, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({k: v for k, v in proof.items() if k not in {"results", "stock_before", "stock_after"}}, indent=2))
    return 0 if proof["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
