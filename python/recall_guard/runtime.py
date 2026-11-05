# SPDX-License-Identifier: MPL-2.0
"""Small JSON boundary between ObjectScript messaging and Embedded Python."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .engine import Engine
from .sources import CURATED_IDS, fetch_curated, normalize_cpsc
from .storage import IrisStore

# IPM keeps its assets beside its own Python package in IRIS's shared Python
# directory. Docker continues to use the repository layout, without a copy step.
_PACKAGE_ASSETS = Path(__file__).resolve().parent / "assets"
ROOT = _PACKAGE_ASSETS if (_PACKAGE_ASSETS / "web" / "index.html").is_file() else Path(__file__).resolve().parents[2]


def redact(message):
    text = str(message)
    for name in ("GEMINI_API_KEY", "IRIS_PASSWORD"):
        value = os.environ.get(name, "")
        if value:
            text = text.replace(value, "[REDACTED]")
    return text[:500]


def fixture_notices():
    records = []
    for filename in ("cpsc-hatch", "cpsc-anker", "cpsc-published-window"):
        folder = ROOT / "research" / "evidence" / filename
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        for record in json.loads((folder / "response.json").read_bytes()):
            if record["RecallID"] in CURATED_IDS:
                note = normalize_cpsc(record, manifest["requested_url"], manifest["requested_at_utc"])
                note["fixture"] = True
                # The current detail page has not been included in this snapshot.
                # Hatch's known discrepancy remains unresolved until live refresh.
                if record["RecallID"] == 9996:
                    note["source_conflict"] = True
                records.append(note)
    return records


def provider_ready():
    return (os.environ.get("FREE_TIER_CONFIRMED", "false").lower() == "true"
            and bool(os.environ.get("GEMINI_API_KEY")) and os.environ.get("AGENT_MODE", "disabled") == "live")


def dispatch(action, payload):
    engine = Engine(IrisStore())
    recorded = engine._meta().get("experience_mode") == "recorded-demo"
    if recorded and action in {"import_notices", "import_lots", "prepare_run"}:
        raise ValueError("Recorded demo evidence is fixed. Use a separate empty instance for live investigations or source changes.")
    if action == "state":
        result = engine.snapshot()
        result["configuration"] = {"provider": "gemini", "model": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
                                   "api_key_present": bool(os.environ.get("GEMINI_API_KEY")),
                                   "free_tier_confirmed": os.environ.get("FREE_TIER_CONFIRMED", "false").lower() == "true",
                                   "paid_fallback": False, "agent_mode": os.environ.get("AGENT_MODE", "disabled")}
        return result
    if action == "preview_inventory":
        from .inventory import preview
        return preview(engine, payload)
    if action == "import_inventory":
        from .inventory import import_snapshot
        return import_snapshot(engine, payload)
    if action == "audit_configure":
        from .monitor import configure
        return configure(engine, payload, provider_ready())
    if action == "audit_due":
        from .monitor import claim_tick
        return {"due": claim_tick(engine)}
    if action == "discovery_plan":
        from .discovery import search_plan
        return search_plan(engine)
    if action == "advisory_feed":
        from .advisories import export
        return export(engine, payload.get("format", "json"))
    if action == "source_action_failed":
        if engine._meta().get("experience_mode") != "inventory-bridge":
            return {"skipped": True, "reason": "NOT_AN_INVENTORY_BRIDGE_WORKSPACE"}
        with engine.store.atomic():
            meta = engine._meta()
            task = meta.get("source_task", {})
            task.update(status="FAILED", error=redact(payload.get("error", "CPSC retrieval failed.")))
            meta["source_task"] = task
            engine.store.put("meta", "state", meta)
            for record in engine.store.scan("discovery"):
                if record["status"] == "RUNNING" and record["request_id"] == task.get("request_id"):
                    record.update(status="FAILED", error=task["error"])
                    engine.store.put("discovery", record["discovery_id"], record)
            return task
    if action == "seed":
        return engine.seed(fixture_notices(), json.loads((ROOT / "fixtures" / "inventory.json").read_text(encoding="utf-8")))
    if action == "load_recorded_demo":
        from .recorded_demo import install, read_package
        return install(engine, read_package(ROOT))
    if action == "import_notices":
        return engine.import_notices(payload["notices"])
    if action == "import_lots":
        return engine.import_lots(payload["lots"])
    if action == "prepare_run":
        if payload.get("audit_cycle_id"):
            from .monitor import prepare_auto_run
            return prepare_auto_run(engine, payload, os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
                                    int(os.environ.get("MAX_AGENT_RUNS_PER_DAY", "5")), provider_ready())
        if os.environ.get("FREE_TIER_CONFIRMED", "false").lower() != "true":
            return {"allowed": False, "reason": "FREE_TIER_NOT_CONFIRMED", "paid_fallback": False}
        if not os.environ.get("GEMINI_API_KEY"):
            return {"allowed": False, "reason": "GEMINI_KEY_MISSING", "paid_fallback": False}
        if os.environ.get("AGENT_MODE", "disabled") != "live":
            return {"allowed": False, "reason": "LIVE_MODE_REQUIRED", "paid_fallback": False}
        return engine.prepare_run(payload["notice_id"], model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
                                  limit=int(os.environ.get("MAX_AGENT_RUNS_PER_DAY", "5")))
    if action == "tool":
        return engine.tool(payload["run_id"], payload["name"], payload.get("arguments"))
    if action == "submit":
        return engine.submit(payload["run_id"], payload["assessments"])
    if action == "revalidate_run":
        return engine.revalidate_run(payload["run_id"])
    if action == "finish_run":
        run = engine.finish_run(payload["run_id"], payload.get("usage"), redact(payload["error"]) if payload.get("error") else None)
        from .monitor import complete_auto_run
        complete_auto_run(engine, run)
        return run
    if action == "transact":
        return engine.transact(payload)
    if action == "review":
        return engine.review(payload, payload.get("authenticated_reviewer", ""))
    if action == "refresh_failed":
        if recorded or engine._meta().get("experience_mode") == "inventory-bridge":
            return {"skipped": True, "reason": "RECORDED_DEMO_EVIDENCE_FIXED"}
        return engine.refresh_failed(redact(payload.get("error", "CPSC refresh failed.")))
    raise ValueError("Unsupported Recall-to-Inventory Bridge action.")


def invoke(action, payload_json="{}"):
    try:
        result = dispatch(action, json.loads(payload_json))
        # Keep the ObjectScript/AI Hub string boundary ASCII-only. JSON readers
        # recover the original Unicode, including exact source evidence quotes.
        return json.dumps({"ok": True, "result": result}, ensure_ascii=True)
    except (ValueError, KeyError, TypeError, TimeoutError) as exc:
        return json.dumps({"ok": False, "error": redact(exc), "error_type": type(exc).__name__})


def fetch_sources():
    if Engine(IrisStore())._meta().get("experience_mode") in {"recorded-demo", "inventory-bridge"}:
        raise ValueError("Curated demo refresh is unavailable in this workspace; no CPSC request was made.")
    return json.dumps({"notices": fetch_curated()}, ensure_ascii=False)


def source_action(action, payload_json="{}"):
    """Executed only in the queued CPSC operation, never inside an agent worker."""
    from .discovery import discover, select_candidates
    if action not in {"discover", "select_candidates", "audit_now", "audit_tick"}:
        raise ValueError("Unsupported inventory-driven source action.")
    engine = Engine(IrisStore())
    payload = json.loads(payload_json)
    with engine.store.atomic():
        meta = engine._meta()
        if meta.get("experience_mode") != "inventory-bridge":
            raise ValueError("Inventory-driven retrieval requires an inventory bridge workspace.")
        meta["source_task"] = {"action": action, "status": "RUNNING", "request_id": payload.get("request_id")}
        engine.store.put("meta", "state", meta)
    if action in {"audit_now", "audit_tick"}:
        from .monitor import run_cycle
        result = run_cycle(engine, payload, timer=action == "audit_tick", provider_ready=provider_ready())
    else:
        function = discover if action == "discover" else select_candidates
        result = function(engine, payload)
    with engine.store.atomic():
        meta = engine._meta()
        meta["source_task"].update(status="COMPLETED", discovery_id=result.get("discovery_id"), selected=result.get("selected", []),
                                   cycle_id=result.get("cycle_id"), reason=result.get("reason"))
        engine.store.put("meta", "state", meta)
    return json.dumps({"ok": True, "result": result}, ensure_ascii=True)
