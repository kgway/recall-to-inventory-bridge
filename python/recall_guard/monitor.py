# SPDX-License-Identifier: MPL-2.0
"""Bounded recurring audits. Search/evidence/AI advice only; no inventory actions."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

from .engine import PROMPT_VERSION, digest, now
from .policy import POLICY_VERSION
from .discovery import discover, inventory_versions, require_workspace, search_plan
from .sources import fetch_notice

TERMINAL = {"COMPLETED", "PARTIAL", "FAILED", "TIMED_OUT"}
LEASE_SECONDS = 600
MAX_REFRESH = 5


def config(engine):
    return engine.store.get("monitor", "config") or {
        "enabled": False, "auto_ai": False, "interval_seconds": 3600,
        "generation": 0, "next_due_at": None, "active_cycle_id": None,
        "refresh_cursor": 0, "last_finished_at": None}


def configure(engine, request, provider_ready=False):
    require_workspace(engine)
    if any(type(request.get(k)) is not bool for k in ("enabled", "auto_ai")):
        raise ValueError("Set enabled and auto_ai explicitly to true or false.")
    interval = request.get("interval_seconds", 3600)
    if type(interval) is not int or not 60 <= interval <= 86400:
        raise ValueError("Audit interval must be 60–86400 seconds.")
    if request["auto_ai"] and not provider_ready:
        raise ValueError("Automatic AI requires live mode, a key and confirmed Free Tier; no paid fallback.")
    with engine.store.atomic():
        if request["enabled"] and request.get("plan_hash") != search_plan(engine)["plan_hash"]:
            raise ValueError("Review current public product search terms before enabling monitoring.")
        saved = config(engine)
        saved.update(enabled=request["enabled"], auto_ai=request["auto_ai"], interval_seconds=interval,
                     generation=saved["generation"] + 1, updated_at=now(),
                     next_due_at=(datetime.fromisoformat(now()) + timedelta(seconds=interval)).isoformat()
                     if request["enabled"] else None)
        engine.store.put("monitor", "config", saved)
        engine._event("audit_policy_changed", {"enabled": saved["enabled"], "auto_ai": saved["auto_ai"],
                                               "interval_seconds": interval})
        return saved


def inventory_updated(engine):
    """Called inside the import transaction, including quantity-only captures."""
    saved = config(engine)
    if saved["enabled"]:
        saved.update(next_due_at=now(), inventory_update_pending=True)
        engine.store.put("monitor", "config", saved)


def due(engine):
    saved = config(engine)
    # Recovery is also needed for a manually requested audit with periodic work off.
    if saved.get("active_cycle_id"):
        with engine.store.atomic():
            saved = config(engine)
            active = engine.store.get("audit_cycle", saved.get("active_cycle_id") or "")
            if active and active["status"] not in TERMINAL and active["lease_until"] <= now():
                active.update(status="TIMED_OUT", finished_at=now())
                active["errors"].append("AUDIT_DEADLINE_EXCEEDED")
                engine.store.put("audit_cycle", active["cycle_id"], active)
                saved["active_cycle_id"] = None
                engine.store.put("monitor", "config", saved)
                engine._event("audit_timed_out", {"cycle_id": active["cycle_id"]})
    if not saved["enabled"] or engine._meta().get("experience_mode") != "inventory-bridge":
        return False
    if saved.get("active_cycle_id"):
        cycle = engine.store.get("audit_cycle", saved["active_cycle_id"])
        if cycle and cycle["status"] not in TERMINAL and cycle["lease_until"] > now():
            return False
    return bool(saved.get("next_due_at") and saved["next_due_at"] <= now())


def view(engine):
    saved = config(engine)
    history = sorted(engine.store.scan("audit_cycle"), key=lambda x: x["started_at"], reverse=True)[:10]
    # Baselines are internal comparison data, not another full inventory export.
    public = []
    for cycle in history:
        item = {k: v for k, v in cycle.items() if k not in {"baseline", "inventory_versions", "ai_task"}}
        item["pending_evaluations"] = [{k: t[k] for k in ("notice_id", "pending_records", "automatic_retry_blocked")}
                                        for t in cycle.get("pending_evaluations", [])]
        public.append(item)
    return {"config": saved, "cycles": public,
            "authority": "ADVISORY_ONLY", "complete_recall_coverage": False,
            "running_requires": "IRIS Production and its host must remain running; this is not an external scheduler."}


def claim_tick(engine):
    """Reserve before async delivery, not after the source worker eventually runs."""
    with engine.store.atomic():
        if not due(engine):
            return False
        saved = config(engine)
        if saved.get("queued_until") and saved["queued_until"] > now():
            return False
        saved["queued_until"] = (datetime.fromisoformat(now()) + timedelta(seconds=60)).isoformat()
        engine.store.put("monitor", "config", saved)
        return True


def capture(engine):
    from .advisories import feed
    document = feed(engine)
    return {item["lot_id"]: {"advisory": item["advisory"], "inventory_version": item["version"],
            "decisions": {a["notice_id"]: [a["decision"], a["notice_version"]] for a in item["assessments"]}}
            for item in document["items"]}


def pending(engine, notice_ids=None):
    tasks = []
    lots = engine.store.scan("lot")
    for note in sorted(engine.store.scan("notice"), key=lambda n: n["notice_id"]):
        if notice_ids is not None and note["notice_id"] not in notice_ids:
            continue
        scoped = set(note.get("inventory_candidate_ids", [x["lot_id"] for x in lots]))
        missing = {}
        for lot in lots:
            if lot["lot_id"] not in scoped:
                continue
            a = engine.store.get("assessment", digest([note["notice_id"], lot["lot_id"]]))
            run = engine.store.get("run", a["run_id"]) if a else None
            if (not a or a["inventory_version"] != lot["version"] or a["notice_version"] != note["version"]
                    or a.get("policy_version") != POLICY_VERSION or not run or run["status"] != "COMPLETED"):
                missing[lot["lot_id"]] = lot["version"]
        if missing:
            versions = dict(sorted(missing.items())[:20])
            fingerprint = digest([note["notice_id"], note["version"], versions, PROMPT_VERSION, POLICY_VERSION])
            attempted = engine.store.get("audit_attempt", fingerprint)
            tasks.append({"notice_id": note["notice_id"], "notice_version": note["version"],
                          "lot_versions": versions, "pending_records": len(missing), "fingerprint": fingerprint,
                          "automatic_retry_blocked": bool(attempted)})
    return tasks


def finish(engine, cycle_id, error=None):
    with engine.store.atomic():
        cycle = engine.store.get("audit_cycle", cycle_id)
        if not cycle or cycle["status"] in TERMINAL:
            return cycle
        current = capture(engine)
        baseline = cycle["baseline"]
        cycle["advisory_changes"] = [{"lot_id": key, "before": baseline.get(key), "after": current.get(key)}
            for key in sorted(set(baseline) | set(current)) if baseline.get(key) != current.get(key)]
        cycle["pending_evaluations"] = pending(engine)
        cycle["remaining_evaluation_notices"] = len(cycle["pending_evaluations"])
        cycle["needs_attention"] = sum(item["advisory"] != "NO_MATCH_IN_SELECTED_NOTICES" for item in current.values())
        if error:
            cycle["errors"].append(str(error)[:500])
        cycle.update(status="PARTIAL" if cycle["errors"] or cycle.get("limitations") or cycle.get("ai_deferred_reason")
                     else "COMPLETED", finished_at=now(), external_inventory_updated=False)
        engine.store.put("audit_cycle", cycle_id, cycle)
        saved = config(engine)
        if saved.get("active_cycle_id") == cycle_id:
            saved.update(active_cycle_id=None, last_finished_at=cycle["finished_at"])
            engine.store.put("monitor", "config", saved)
        engine._event("audit_finished", {"cycle_id": cycle_id, "status": cycle["status"],
                                         "new_candidates": len(cycle.get("new_candidate_ids", [])),
                                         "advisory_changes": len(cycle["advisory_changes"])})
        return cycle


def run_cycle(engine, request, timer=False, provider_ready=False):
    require_workspace(engine)
    request_id = request.get("request_id") if not timer else "timer-" + uuid.uuid4().hex
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
        raise ValueError("Provide an audit request_id.")
    cycle_id = digest(request_id)
    with engine.store.atomic():
        prior = engine.store.get("audit_cycle", cycle_id)
        if prior:
            return {"cycle_id": cycle_id, "status": prior["status"], "replayed": True}
        saved = config(engine)
        if timer and not due(engine):
            return {"skipped": True, "reason": "NOT_DUE"}
        active = engine.store.get("audit_cycle", saved.get("active_cycle_id") or "")
        if active and active["status"] not in TERMINAL:
            if active["lease_until"] > now():
                return {"skipped": True, "reason": "AUDIT_ALREADY_RUNNING", "cycle_id": active["cycle_id"]}
            active.update(status="TIMED_OUT", finished_at=now())
            engine.store.put("audit_cycle", active["cycle_id"], active)
        if saved.get("last_finished_at") and (datetime.fromisoformat(now()) - datetime.fromisoformat(saved["last_finished_at"])).total_seconds() < 60:
            return {"skipped": True, "reason": "AUDIT_COOLDOWN_60_SECONDS"}
        previous = sorted(engine.store.scan("discovery"), key=lambda x: x["at"])
        old_ids = {c["notice_id"] for c in previous[-1]["candidates"]} if previous else set()
        cycle = {"cycle_id": cycle_id, "request_id": request_id, "trigger": "timer" if timer else "manual",
                 "status": "RUNNING", "started_at": now(),
                 "lease_until": (datetime.fromisoformat(now()) + timedelta(seconds=LEASE_SECONDS)).isoformat(),
                 "config_generation": saved["generation"], "inventory_versions": inventory_versions(engine),
                 "baseline": capture(engine), "errors": [], "limitations": [], "refreshed_notice_ids": [],
                 "changed_notice_ids": [], "new_candidate_ids": [], "max_ai_runs": 1,
                 "complete_recall_coverage": False, "external_inventory_updated": False}
        saved.update(active_cycle_id=cycle_id, inventory_update_pending=False, queued_until=None,
                     next_due_at=(datetime.fromisoformat(now()) + timedelta(seconds=saved["interval_seconds"])).isoformat()
                     if saved["enabled"] else None)
        engine.store.put("monitor", "config", saved)
        engine.store.put("audit_cycle", cycle_id, cycle)
    try:
        record = discover(engine, {"request_id": "audit-" + cycle_id, "plan_hash": search_plan(engine)["plan_hash"]})
        cycle.update(discovery_id=record["discovery_id"], query_count=len(record["query_results"]),
                     new_candidate_ids=sorted({c["notice_id"] for c in record["candidates"]} - old_ids))
        if record["status"] != "COMPLETED":
            cycle["limitations"].append("CANDIDATE_SEARCH_FAILED_OR_LIMITED")
        notes = sorted(engine.store.scan("notice"), key=lambda n: n["notice_id"])
        cursor = saved["refresh_cursor"] % max(1, len(notes))
        selected = (notes[cursor:] + notes[:cursor])[:MAX_REFRESH]
        if len(notes) > MAX_REFRESH:
            cycle["limitations"].append("SELECTED_NOTICE_REFRESH_BATCH_LIMIT")
        cycle["deferred_refresh_notice_ids"] = [n["notice_id"] for n in notes if n not in selected]
        for note in selected:
            try:
                fresh = fetch_notice(int(note["notice_id"].split(":")[1]))
                matches = next((c["lot_ids"] for c in record["candidates"] if c["notice_id"] == note["notice_id"]), [])
                fresh["inventory_candidate_ids"] = sorted(set(note.get("inventory_candidate_ids", [])) | set(matches))
                fresh["discovery_id"] = record["discovery_id"]
                with engine.store.atomic():
                    result = engine.import_notices([fresh])
                    stored = engine.store.get("notice", note["notice_id"])
                    stored.update(inventory_candidate_ids=fresh["inventory_candidate_ids"], discovery_id=record["discovery_id"])
                    engine.store.put("notice", note["notice_id"], stored)
                cycle["changed_notice_ids"].extend(result["changed"])
                cycle["refreshed_notice_ids"].append(note["notice_id"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                cycle["errors"].append("NOTICE_REFRESH_FAILED:" + note["notice_id"] + ":" + type(exc).__name__)
        with engine.store.atomic():
            current = config(engine)
            current["refresh_cursor"] = cursor + len(selected)
            engine.store.put("monitor", "config", current)
            if inventory_versions(engine) != cycle["inventory_versions"]:
                cycle["limitations"].append("INVENTORY_CHANGED_DURING_AUDIT")
            tasks = pending(engine, cycle["refreshed_notice_ids"])
            eligible = [t for t in tasks if not t["automatic_retry_blocked"]]
            cycle["pending_evaluations"] = tasks
            can_ai = saved["auto_ai"] and provider_ready and saved["generation"] == current["generation"] and not cycle["limitations"]
            if tasks and not can_ai:
                cycle["ai_deferred_reason"] = "AUTOMATIC_AI_DISABLED_OR_UNAVAILABLE" if not saved["auto_ai"] or not provider_ready else "AUDIT_SCOPE_CHANGED_OR_LIMITED"
            elif tasks and not eligible:
                cycle["ai_deferred_reason"] = "UNCHANGED_INPUT_REQUIRES_MANUAL_RETRY"
            if can_ai and eligible:
                cycle.update(status="AWAITING_AI", ai_task=eligible[0])
            engine.store.put("audit_cycle", cycle_id, cycle)
        if cycle["status"] == "AWAITING_AI":
            return {"cycle_id": cycle_id, "status": cycle["status"], "ai_notice_id": cycle["ai_task"]["notice_id"]}
        completed = finish(engine, cycle_id)
        return {"cycle_id": cycle_id, "status": completed["status"]}
    except Exception:
        with engine.store.atomic():
            engine.store.put("audit_cycle", cycle_id, cycle)
        finish(engine, cycle_id, "AUDIT_SOURCE_OPERATION_FAILED")
        raise


def prepare_auto_run(engine, request, model, limit, provider_ready):
    """Second gate in the AI worker: policy/input/attempt changes cannot race dispatch."""
    cycle_id = request["audit_cycle_id"]
    with engine.store.atomic():
        cycle = engine.store.get("audit_cycle", cycle_id)
        saved = config(engine)
        if (not cycle or cycle["status"] != "AWAITING_AI" or saved.get("active_cycle_id") != cycle_id
                or cycle.get("run_id")):
            return {"allowed": False, "reason": "AUDIT_NOT_AWAITING_AI"}
        task = cycle["ai_task"]
        current = pending(engine, [request["notice_id"]])
        valid = (provider_ready and saved["auto_ai"] and saved["generation"] == cycle["config_generation"]
                 and inventory_versions(engine) == cycle["inventory_versions"]
                 and request["notice_id"] == task["notice_id"] and current
                 and current[0]["fingerprint"] == task["fingerprint"] and not current[0]["automatic_retry_blocked"])
        result = engine.prepare_run(request["notice_id"], model=model, limit=min(limit, 5)) if valid else {"allowed": False, "reason": "AUDIT_INPUT_OR_POLICY_CHANGED"}
        if result["allowed"]:
            run = engine.store.get("run", result["run_id"])
            run["audit_cycle_id"] = cycle_id
            engine.store.put("run", run["run_id"], run)
            cycle["run_id"] = run["run_id"]
            engine.store.put("audit_attempt", task["fingerprint"], {"run_id": run["run_id"], "at": now()})
            engine.store.put("audit_cycle", cycle_id, cycle)
        else:
            cycle["ai_deferred_reason"] = result["reason"]
            engine.store.put("audit_cycle", cycle_id, cycle)
            finish(engine, cycle_id)
        return result


def complete_auto_run(engine, run):
    cycle_id = run.get("audit_cycle_id")
    if cycle_id:
        return finish(engine, cycle_id, "AI_INVESTIGATION_FAILED" if run["status"] != "COMPLETED" else None)
