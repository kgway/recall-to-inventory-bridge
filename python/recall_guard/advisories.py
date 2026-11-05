# SPDX-License-Identifier: MPL-2.0
"""Pull-based evidence feed; the receiving inventory system owns every action."""
import csv
import io
import json

from .engine import digest, now
from .policy import POLICY_VERSION

CODES = {"HOLD_RECALL": "RECALL_MATCH", "HOLD_REVIEW": "REVIEW_REQUIRED",
         "PENDING_EVALUATION": "NOT_EVALUATED", "ELIGIBLE_IN_DEMO_SCOPE": "NO_MATCH_IN_SELECTED_NOTICES"}


def feed(engine):
    with engine.store.atomic():
        state = engine.snapshot()
        notes = {n["notice_id"]: n for n in state["notices"]}
        discovery = state.get("discoveries", [])[-1] if state.get("discoveries") else None
        latest_audit = next((c for c in state.get("monitor", {}).get("cycles", [])
                             if c["status"] in {"COMPLETED", "PARTIAL", "FAILED", "TIMED_OUT"}), None)
        audit_attention = bool(latest_audit and (latest_audit["status"] != "COMPLETED"
                               or latest_audit.get("pending_evaluations")))
        items = []
        for lot in state["lots"]:
            assessments = []
            for note in notes.values():
                a = engine.store.get("assessment", digest([note["notice_id"], lot["lot_id"]]))
                run = engine.store.get("run", a["run_id"]) if a else None
                current = bool(a and a["inventory_version"] == lot["version"] and a["notice_version"] == note["version"]
                               and a.get("policy_version") == POLICY_VERSION and run and run["status"] == "COMPLETED")
                assessments.append({"notice_id": note["notice_id"], "notice_version": note["version"],
                    "official_url": note["url"], "decision": a["decision"] if current else "NOT_EVALUATED",
                    "reason": a["reason"] if current else "No current completed assessment.",
                    "run_id": a["run_id"] if current else None, "checks": a["checks"] if current else [],
                    "missing_fields": a["missing_fields"] if current else ["current_assessment"],
                    "mode": a.get("mode") if current else None})
            candidates = [{"notice_id": c["notice_id"], "title": c["title"], "official_url": c["url"],
                           "discovery_id": discovery["discovery_id"], "classification": "CANDIDATE_ONLY"}
                          for c in discovery["candidates"] if c["notice_id"] in lot.get("candidate_notice_ids", [])] if discovery else []
            code = CODES[lot["status"]]
            if code == "NOT_EVALUATED" and candidates:
                code = "CANDIDATES_FOUND"
            items.append({k: lot.get(k) for k in ("lot_id", "external_id", "source_system", "sku", "lot_number",
                         "location", "name", "quantity", "source_updated_at", "received_at", "version", "import_id", "synthetic", "data_classification")}
                         | {"advisory": code, "assessments": assessments, "candidate_notices": candidates,
                            "audit_attention": audit_attention,
                            "audit_cycle_id": latest_audit["cycle_id"] if latest_audit else None,
                            "external_inventory_updated": False})
        return {"schema": "recall-to-inventory-bridge.advisories.v1", "generated_at": now(),
                "authority": "ADVISORY_ONLY", "external_inventory_updated": False,
                "scope": {"notice_ids": sorted(notes), "complete_recall_coverage": False,
                          "meaning": "Only selected notices were assessed. No match or no search results never establishes product safety."},
                "latest_discovery": {k: discovery.get(k) for k in ("discovery_id", "status", "at", "complete_recall_coverage")} if discovery else None,
                "monitor": state.get("monitor"), "policy_version": POLICY_VERSION, "items": items}


def spreadsheet_text(value):
    text = "" if value is None else str(value).lower() if isinstance(value, bool) else str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text


def export(engine, format_="json"):
    document = feed(engine)
    if format_ == "json":
        content, mime = json.dumps(document, ensure_ascii=False, indent=2), "application/json"
    elif format_ == "csv":
        output = io.StringIO(newline="")
        fields = ["source_system", "external_id", "sku", "lot_number", "location", "reported_quantity",
                  "advisory", "notice_id", "decision", "reason", "official_url", "inventory_version",
                  "notice_version", "run_id", "candidate_notice_ids", "audit_attention", "audit_cycle_id",
                  "complete_recall_coverage", "external_inventory_updated"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for item in document["items"]:
            for a in item["assessments"] or [{}]:
                row = {k: item.get(k) for k in fields}
                row.update(reported_quantity=item["quantity"], inventory_version=item["version"],
                           complete_recall_coverage=False, external_inventory_updated=False,
                           candidate_notice_ids=";".join(c["notice_id"] for c in item["candidate_notices"]),
                           **{k: a.get(k) for k in ("notice_id", "decision", "reason", "official_url", "notice_version", "run_id")})
                if not a:
                    row.update(decision="NOT_EVALUATED", reason="No recall notices have been selected.")
                writer.writerow({k: spreadsheet_text(v) for k, v in row.items()})
        content, mime = output.getvalue(), "text/csv"
    else:
        raise ValueError("Export format must be json or csv.")
    return {"format": format_, "content": content, "content_type": mime,
            "filename": "recall-advisories." + format_, "external_inventory_updated": False}
