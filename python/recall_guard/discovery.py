# SPDX-License-Identifier: MPL-2.0
"""Bounded inventory-driven CPSC candidate retrieval, separate from assessment."""
from __future__ import annotations

import json
import re
import urllib.parse

from .engine import digest, now
from .inventory import MODE
from .sources import API, fetch, fetch_notice, normalize_cpsc

MAX_QUERIES = 8
MAX_CANDIDATES = 40
FIELDS = {"UPC", "RecallTitle", "RecallDescription", "Manufacturer", "ProductName"}


def plan(lots):
    groups, skipped = {}, []
    for lot in lots:
        terms = []
        for field, attribute in (("UPC", "upc"), ("RecallTitle", "brand"),
                                 ("RecallDescription", "model"), ("Manufacturer", "manufacturer")):
            term = lot.get(attribute)
            if isinstance(term, str) and 2 <= len(term.strip()) <= 100:
                terms.append((field, term.strip()))
        if not terms:
            term = lot.get("product_type") or lot.get("name")
            if isinstance(term, str) and 3 <= len(term.strip()) <= 100:
                terms.append(("ProductName", term.strip()))
        if not terms:
            skipped.append(lot["lot_id"])
        for position, (field, term) in enumerate(terms):
            filters = {field: term}
            # A model such as "Rest" by itself also matches restrictions,
            # restaurants, etc. Combine it with the known brand; retain a
            # separate broad brand query so model omissions remain visible.
            brand = lot.get("brand")
            if field == "RecallDescription" and isinstance(brand, str) and 2 <= len(brand.strip()) <= 100:
                filters["RecallTitle"] = brand.strip()
            key = tuple(sorted((k, v.casefold()) for k, v in filters.items()))
            group = groups.setdefault(key, {"field": field, "term": term, "filters": filters, "lot_ids": [], "priority": position})
            group["lot_ids"].append(lot["lot_id"])
    queries = sorted(groups.values(), key=lambda g: (g["priority"], g["field"], g["term"].casefold()))
    selected = [{k: v for k, v in q.items() if k != "priority"} for q in queries[:MAX_QUERIES]]
    searched = {lot for q in selected for lot in q["lot_ids"]}
    return {"queries": selected, "omitted_queries": max(0, len(queries)-MAX_QUERIES),
            "unsearched_lot_ids": sorted({lot["lot_id"] for lot in lots} - searched),
            "skipped_lot_ids": skipped, "complete_recall_coverage": False,
            "disclosure": "These exact product terms will go to the public CPSC API; no SKU, external ID, location, quantity or serial.",
            "meaning": "Substring search yields candidates. No results never establishes safety or clearance."}


def require_workspace(engine):
    if engine._meta().get("experience_mode") != MODE or not engine.store.scan("lot"):
        raise ValueError("Import inventory snapshots in a separate bridge workspace first.")


def inventory_versions(engine):
    return {lot["lot_id"]: lot["version"] for lot in engine.store.scan("lot")}


def search_plan(engine):
    require_workspace(engine)
    result = plan(engine.store.scan("lot"))
    return {**result, "plan_hash": digest([result, inventory_versions(engine)])}


def discover(engine, request):
    require_workspace(engine)
    with engine.store.atomic():
        current = search_plan(engine)
        if request.get("plan_hash") != current["plan_hash"]:
            raise ValueError("Review the current CPSC search plan before starting retrieval.")
        # Queue serialization plus idempotency prevents accidental repeated network batches.
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
            raise ValueError("Provide a discovery request_id.")
        key = digest(request_id)
        prior = engine.store.get("discovery", key)
        if prior:
            if prior["plan_hash"] != current["plan_hash"]:
                raise ValueError("Discovery request_id was reused with a different plan.")
            return prior
        record = {"discovery_id": key, "request_id": request_id, "at": now(), "status": "RUNNING",
                  "plan_hash": current["plan_hash"], "plan": current, "inventory_versions": inventory_versions(engine),
                  "candidates": [], "query_results": [], "complete_recall_coverage": False,
                  "new_inferences": 0}
        engine.store.put("discovery", key, record)
    candidates = {}
    for query in current["queries"]:
        field, term = query["field"], query["term"]
        if field not in FIELDS:
            raise ValueError("Unsupported CPSC search field.")
        filters = query["filters"]
        if set(filters) - FIELDS:
            raise ValueError("Unsupported CPSC search filters.")
        url = API + "?" + urllib.parse.urlencode({"format": "json", **filters})
        result = {"field": field, "term": term, "filters": filters, "url": url}
        try:
            records = json.loads(fetch(url, max_bytes=2_000_000))
            if not isinstance(records, list):
                raise ValueError("CPSC did not return a record array.")
            result.update(status="RETRIEVED", returned_records=len(records),
                          limited=len(records) > MAX_CANDIDATES)
            rejected = 0
            for raw in records[:MAX_CANDIDATES]:
                try:
                    note = normalize_cpsc(raw, url)
                except (ValueError, KeyError, TypeError):
                    rejected += 1
                    continue
                # Guard against an ignored parameter returning unrelated records.
                search_text = {"RecallTitle": raw.get("Title", ""), "RecallDescription": raw.get("Description", ""),
                    "Manufacturer": " ".join(x.get("Name", "") for x in raw.get("Manufacturers", [])),
                    "ProductName": " ".join(x.get("Name", "") for x in raw.get("Products", [])),
                    "UPC": " ".join(x.get("UPC", "") for x in raw.get("ProductUPCs", []))}
                if any(value.casefold() not in search_text[key].casefold() for key, value in filters.items()):
                    rejected += 1
                    continue
                if note["notice_id"] not in candidates and len(candidates) >= MAX_CANDIDATES:
                    result["limited"] = True
                    continue
                candidate = candidates.setdefault(note["notice_id"], {"notice_id": note["notice_id"],
                    "title": note["title"], "url": note["url"], "recall_number": note["recall_number"],
                    "last_publish_date": note["last_publish_date"], "matched_queries": [], "lot_ids": [],
                    "classification": "CANDIDATE_ONLY", "api_snapshot": note["snapshots"][0]})
                candidate["matched_queries"].append({"field": field, "term": term, "filters": filters, "url": url})
                candidate["lot_ids"] = sorted(set(candidate["lot_ids"]) | set(query["lot_ids"]))
            result["rejected_records"] = rejected
        except (OSError, ValueError, TypeError, KeyError) as exc:
            result.update(status="FAILED", error_type=type(exc).__name__)
        record["query_results"].append(result)
    record.update(status="COMPLETED_WITH_LIMITS" if current["omitted_queries"] or current["unsearched_lot_ids"]
                  or any(q["status"] == "FAILED" or q.get("limited") or q.get("rejected_records") for q in record["query_results"])
                  else "COMPLETED", candidates=list(candidates.values()), finished_at=now())
    with engine.store.atomic():
        record["inventory_changed_during_search"] = inventory_versions(engine) != record["inventory_versions"]
        engine.store.put("discovery", key, record)
        engine._event("cpsc_candidates_discovered", {"discovery_id": key, "candidates": len(candidates),
                                                    "complete_recall_coverage": False})
    return record


def select_candidates(engine, request):
    require_workspace(engine)
    record = engine.store.get("discovery", request.get("discovery_id", ""))
    ids = request.get("notice_ids")
    if (not record or record["status"] == "RUNNING" or not isinstance(ids, list)
            or not 1 <= len(ids) <= 5 or any(not isinstance(key, str) for key in ids) or len(set(ids)) != len(ids)):
        raise ValueError("Select 1–5 distinct notices from a completed discovery.")
    candidates = {x["notice_id"]: x for x in record["candidates"]}
    if any(not isinstance(key, str) or key not in candidates for key in ids):
        raise ValueError("Notice is outside this captured candidate set.")
    if inventory_versions(engine) != record["inventory_versions"]:
        raise ValueError("Inventory identity changed; search again before selecting these candidates.")
    notes = []
    for key in ids:
        note = fetch_notice(int(key.split(":")[1]))
        note["inventory_candidate_ids"] = candidates[key]["lot_ids"]
        note["discovery_id"] = record["discovery_id"]
        notes.append(note)
    with engine.store.atomic():
        if inventory_versions(engine) != record["inventory_versions"]:
            raise ValueError("Inventory identity changed while obtaining evidence; no notice was activated.")
        if len({n["notice_id"] for n in engine.store.scan("notice")} | set(ids)) > 40:
            raise ValueError("Select at most 40 notices in this bounded workspace.")
        result = engine.import_notices(notes)
        # Association is retrieval metadata, not a change to official recall content.
        for note in notes:
            saved = engine.store.get("notice", note["notice_id"])
            saved.update(inventory_candidate_ids=note["inventory_candidate_ids"], discovery_id=record["discovery_id"])
            engine.store.put("notice", note["notice_id"], saved)
        return {**result, "selected": ids, "new_inferences": 0, "external_inventory_updated": False}
