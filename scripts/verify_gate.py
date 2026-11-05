# SPDX-License-Identifier: MPL-2.0
"""Exercise blocked sale/shipment requests through the real Production, without an LLM."""
import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from iris_client import IrisCheckError, IrisClient


def require(condition, message):
    if not condition:
        raise IrisCheckError(message)


def verify(client, evidence, seed):
    state = client.state()
    evidence.update(backend=state["backend"], iris_version=state["iris_version"],
                    ai_hub_agent_class_present=True)
    if seed:
        require(not state["meta"]["initialized"] and not any(state[key] for key in
                ("lots", "notices", "runs", "assessments", "transactions", "reviews")),
                "--seed requires an empty demo data volume. Existing data was not replaced.")
        client.request("seed", {})
        state = client.state()
        evidence["seeded_synthetic_inventory"] = True
    require(state["meta"]["initialized"] and state["notices"] and state["lots"],
            "Load demo inventory first, or use --seed on a new empty data volume.")
    require(not state["runs"] and not state["assessments"] and not state["reviews"],
            "Run this check before any agent investigation or human review. Existing data was preserved.")
    require(all(item.get("synthetic") is True and item["status"] == "PENDING_EVALUATION"
                for item in state["lots"]), "Expected explicitly synthetic, unassessed inventory.")
    lot = next((item for item in state["lots"] if item["quantity"] >= 2), None)
    require(lot is not None, "This check requires a synthetic lot with at least two units.")
    balances = {item["lot_id"]: item["quantity"] for item in state["lots"]}
    evidence.update(lot_id=lot["lot_id"], quantity_before=lot["quantity"],
                    notice_versions={item["notice_id"]: item["version"] for item in state["notices"]},
                    fixture_notice_ids=[item["notice_id"] for item in state["notices"] if item.get("fixture")],
                    inventory_version=lot["version"])
    requests = []
    for kind in ("sale", "shipment"):
        payload = {"idempotency_key": "gate-check-" + uuid.uuid4().hex, "kind": kind,
                   "lines": [{"lot_id": lot["lot_id"], "quantity": 1}]}
        result = client.request("transact", payload)
        evidence["retailer_results"].append(result)
        require(result.get("allowed") is False and result.get("replayed") is False,
                f"Unassessed {kind} was not rejected as a new transaction.")
        require(any(item.get("lot_id") == lot["lot_id"] and item.get("status") == "PENDING_EVALUATION"
                    for item in result.get("blocked", [])),
                f"The {kind} response did not identify the missing evaluation.")
        requests.append(payload)
    retry = client.request("transact", requests[0])
    evidence["idempotent_retry"] = retry
    require(retry.get("replayed") is True and retry.get("allowed") is False,
            "The repeated blocked sale did not return its stored rejection.")
    require(all(retry.get(key) == evidence["retailer_results"][0].get(key)
                for key in ("idempotency_key", "fingerprint", "blocked", "at")),
            "The retry changed the stored transaction result.")
    after = client.state()
    after_balances = {item["lot_id"]: item["quantity"] for item in after["lots"]}
    require(after_balances == balances,
            "Inventory quantities changed during rejected requests.")
    require(not after["runs"] and not after["assessments"],
            "An agent ran during this no-LLM check; inspect concurrent activity.")
    stored = {item["idempotency_key"]: item for item in after["transactions"]}
    require(len(stored) == len(state["transactions"]) + 2,
            "Expected exactly two new transaction records, with no extra record for the retry.")
    for result in evidence["retailer_results"]:
        require(stored.get(result["idempotency_key"]) == result,
                "The Production response was not persisted as the same transaction.")
    evidence.update(success=True, quantity_after=after_balances[lot["lot_id"]],
                    quantities_unchanged=True, retailer_requests_exercised=True,
                    new_transaction_records=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New evidence JSON file; never overwritten.")
    parser.add_argument("--seed", action="store_true", help="Load fixtures only into an empty demo data volume.")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output = args.output.open("x", encoding="utf-8")
    except FileExistsError:
        parser.error("Use a new evidence file; existing evidence was not overwritten.")
    evidence = {"purpose": "Real IRIS Production gate check before agent investigation",
                "at_utc": datetime.now(timezone.utc).isoformat(), "success": False,
                "llm_called_by_this_check": False, "ai_hub_agent_executed": False,
                "retailer_results": []}
    try:
        verify(IrisClient(), evidence, args.seed)
    except (IrisCheckError, KeyError, TypeError, ValueError) as exc:
        evidence["error"] = str(exc)
    finally:
        evidence["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        with output:
            json.dump(evidence, output, ensure_ascii=False, indent=2)
            output.write("\n")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
