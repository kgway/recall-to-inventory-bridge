# SPDX-License-Identifier: MPL-2.0
"""Example receiving workflow: create a local review worklist, never mutate stock."""
import argparse
import json
from pathlib import Path


def worklist(document):
    if (document.get("schema") != "recall-to-inventory-bridge.advisories.v1"
            or document.get("authority") != "ADVISORY_ONLY" or document.get("external_inventory_updated") is not False):
        raise ValueError("An advisory-only v1 feed is required.")
    reasons = {"CANDIDATES_FOUND": "Review retrieved CPSC candidates against product labels.",
               "RECALL_MATCH": "Route the evidence to the existing recall response process.",
               "REVIEW_REQUIRED": "Collect missing identifiers or reconcile source evidence.",
               "NOT_EVALUATED": "Complete the assessment; no clearance was provided."}
    tasks=[]
    for item in document["items"]:
        if item["advisory"] not in reasons:
            if item["advisory"] != "NO_MATCH_IN_SELECTED_NOTICES":raise ValueError("Unknown advisory code.")
            if not item.get("audit_attention"):continue
        tasks.append({"source_system":item["source_system"],"external_id":item["external_id"],
                      "sku":item["sku"],"inventory_version":item["version"],
                      "task":reasons.get(item["advisory"], "Review incomplete recurring audit coverage before using a stored exclusion."),"advisory":item["advisory"],
                      "audit_attention":item.get("audit_attention", False),"audit_cycle_id":item.get("audit_cycle_id"),
                      "candidate_notices":item["candidate_notices"],"assessments":item["assessments"],
                      "stock_action_performed":False})
    return {"example_receiver":"local review worklist, not an ERP/WMS connector",
            "stock_action_performed":False,"tasks":tasks,"source_scope":document["scope"]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--advisories",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=worklist(json.loads(args.advisories.read_text(encoding="utf-8")))
    with args.output.open("x",encoding="utf-8") as out:json.dump(result,out,ensure_ascii=False,indent=2)
    print(str(len(result["tasks"]))+" local review tasks written. No inventory system was contacted or changed.")


if __name__=="__main__":main()
