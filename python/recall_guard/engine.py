# SPDX-License-Identifier: MPL-2.0
"""Versioned recall advice with a separate synthetic downstream simulator."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from .policy import POLICY_VERSION, InvalidAssessment, month, validate_assessment
from .assessment_input import FORMAT_VERSION, canonicalize_assessment

PROMPT_VERSION = "investigator-v7-advisory"
RUN_TIMEOUT_SECONDS = 300


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def required_text(value, name, max_length=160):
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValueError(f"Invalid {name}.")
    return value.strip()


class Engine:
    def __init__(self, store):
        self.store = store

    def _meta(self):
        return self.store.get("meta", "state") or {"epoch": 0, "scope": "selected-cpsc-demo", "initialized": False}

    def _event(self, kind, data):
        key = uuid.uuid4().hex
        self.store.put("event", key, {"event_id": key, "at": now(), "kind": kind, **data})

    def _expire_pending_runs(self):
        # Commit recovery separately from a tool/submit operation that may reject
        # its caller. That rejection must not roll the timeout record back.
        instant = datetime.fromisoformat(now())
        with self.store.atomic():
            for run in self.store.scan("run"):
                if run["status"] not in {"RUNNING", "SUBMITTED"}:
                    continue
                try:
                    age = (instant - datetime.fromisoformat(run["created_at"])).total_seconds()
                except (ValueError, TypeError, KeyError):
                    age = RUN_TIMEOUT_SECONDS
                if age < RUN_TIMEOUT_SECONDS:
                    continue
                run.update(status="FAILED", finished_at=instant.isoformat(),
                           error="Agent run exceeded its 300-second deadline; inventory remains blocked.")
                self.store.put("run", run["run_id"], run)
                self._event("agent_timed_out", {"run_id": run["run_id"], "status": "FAILED"})

    def seed(self, notices, lots):
        with self.store.atomic():
            if self._meta().get("experience_mode") == "inventory-bridge":
                raise ValueError("Synthetic seed cannot replace an inventory bridge workspace.")
            if self._meta()["initialized"]:
                return {"already_initialized": True}
            return {"notices": self.import_notices(notices), "inventory": self.import_lots(lots)}

    def import_notices(self, notices):
        if not isinstance(notices, list) or not 1 <= len(notices) <= 100:
            raise ValueError("Import between 1 and 100 notices.")
        changed = []
        with self.store.atomic():
            meta = self._meta()
            for item in notices:
                notice_id = required_text(item.get("notice_id"), "notice_id")
                if not notice_id.startswith("US-CPSC:"):
                    raise ValueError("This demo supports only US-CPSC notices.")
                if not item.get("snapshots") or any(not s.get("text") or not s.get("id") for s in item["snapshots"]):
                    raise ValueError("Each notice requires source snapshots.")
                content = {k: item.get(k) for k in ("notice_id", "title", "url", "source_conflict", "target_component")}
                content["snapshots"] = [{k: s.get(k) for k in ("id", "kind", "url", "text")} for s in item["snapshots"]]
                version = digest(content)
                previous = self.store.get("notice", notice_id)
                if previous and previous["version"] == version:
                    continue
                notice = {**item, "version": version, "stored_at": now()}
                self.store.put("notice", notice_id, notice)
                changed.append(notice_id)
            if changed:
                meta["epoch"] += 1
                self._event("recalls_changed", {"notice_ids": changed, "epoch": meta["epoch"]})
            meta["refresh_error"] = None
            self.store.put("meta", "state", meta)
        return {"changed": changed}

    def refresh_failed(self, error):
        with self.store.atomic():
            meta = self._meta()
            meta["refresh_error"] = str(error)[:500]
            self.store.put("meta", "state", meta)
            self._event("refresh_failed", {"error": meta["refresh_error"]})
            return {"refresh_error": meta["refresh_error"]}

    def import_lots(self, lots):
        if self._meta().get("experience_mode") == "inventory-bridge":
            raise ValueError("Use the inventory snapshot import in this workspace.")
        if not isinstance(lots, list) or not 1 <= len(lots) <= 100:
            raise ValueError("Import between 1 and 100 synthetic lots.")
        changed = []
        seen = set()
        with self.store.atomic():
            for item in lots:
                lot_id = required_text(item.get("lot_id"), "lot_id")
                if lot_id in seen:
                    raise ValueError("Duplicate lot ID in import.")
                seen.add(lot_id)
                if item.get("synthetic") is not True:
                    raise ValueError("Only explicitly synthetic inventory is accepted by this demo.")
                required_text(item.get("sku"), "SKU")
                required_text(item.get("name"), "product name", 300)
                quantity = item.get("quantity")
                if type(quantity) is not int or not 0 <= quantity <= 100_000:
                    raise ValueError("Quantity must be a nonnegative integer.")
                if item.get("manufactured_month") not in (None, "") and not month(item["manufactured_month"]):
                    raise ValueError("Manufacturing month must be YYYY-MM or unknown.")
                previous = self.store.get("lot", lot_id)
                attrs = {k: v for k, v in item.items() if k not in {"quantity", "version", "received_at"}}
                version = digest(attrs)
                if previous and previous["version"] == version:
                    # Imports never replenish sold inventory by resetting quantity.
                    continue
                if previous:
                    quantity = previous["quantity"]
                self.store.put("lot", lot_id, {**attrs, "quantity": quantity, "version": version, "received_at": now()})
                changed.append(lot_id)
            meta = self._meta()
            meta["initialized"] = bool(self.store.scan("notice") and self.store.scan("lot"))
            self.store.put("meta", "state", meta)
            self._event("inventory_imported", {"lot_ids": changed})
        return {"changed": changed}

    def prepare_run(self, notice_id, mode="live", model="", limit=5):
        if self._meta().get("experience_mode") == "recorded-demo":
            raise ValueError("This is a recorded demo. Use a separate empty instance for live investigations.")
        self._expire_pending_runs()
        if mode != "live":
            raise ValueError("Recorded inference is not implemented; live mode is required.")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Invalid daily live-run limit.")
        with self.store.atomic():
            notice = self.store.get("notice", notice_id)
            if not notice:
                raise ValueError("Unknown notice.")
            lots = self.store.scan("lot")
            if self._meta().get("experience_mode") == "inventory-bridge":
                for previous in self.store.scan("run"):
                    if previous["notice_id"] == notice_id and previous["status"] in {"RUNNING", "SUBMITTED"}:
                        return {"allowed": False, "reason": "ALREADY_PENDING", "reused_run_id": previous["run_id"], "paid_fallback": False}
                candidates = set(notice.get("inventory_candidate_ids", [lot["lot_id"] for lot in lots]))
                lots = [lot for lot in lots if lot["lot_id"] in candidates]
                pending = []
                for lot in lots:
                    a = self.store.get("assessment", digest([notice_id, lot["lot_id"]]))
                    run = self.store.get("run", a["run_id"]) if a else None
                    if (not a or a["inventory_version"] != lot["version"] or a["notice_version"] != notice["version"]
                            or a.get("policy_version") != POLICY_VERSION or not run or run["status"] != "COMPLETED"):
                        pending.append(lot)
                if not pending:
                    return {"allowed": False, "reason": "CURRENT_ASSESSMENT_REUSED", "paid_fallback": False}
                lots = pending[:20]
            if not lots:
                raise ValueError("No inventory to evaluate.")
            versions = {lot["lot_id"]: lot["version"] for lot in lots}
            for previous in self.store.scan("run"):
                same_input = (previous["notice_id"] == notice_id and previous["notice_version"] == notice["version"]
                              and previous["lot_versions"] == versions and previous["model"] == model
                              and previous["prompt_version"] == PROMPT_VERSION
                              and previous.get("policy_version") == POLICY_VERSION)
                if not same_input:
                    continue
                if previous["status"] in {"RUNNING", "SUBMITTED"}:
                    return {"allowed": False, "reason": "ALREADY_PENDING", "reused_run_id": previous["run_id"], "paid_fallback": False}
                if previous["status"] == "COMPLETED":
                    active = [self.store.get("assessment", digest([notice_id, lot_id])) for lot_id in versions]
                    if all(a and a["run_id"] == previous["run_id"] and a.get("policy_version") == POLICY_VERSION for a in active):
                        return {"allowed": False, "reason": "CURRENT_ASSESSMENT_REUSED", "reused_run_id": previous["run_id"], "paid_fallback": False}
            existing = [r for r in self.store.scan("run") if r["created_at"][:10] == now()[:10]]
            if len(existing) >= limit:
                return {"allowed": False, "reason": "DAILY_RUN_LIMIT", "paid_fallback": False}
            run_id = uuid.uuid4().hex
            run = {"run_id": run_id, "notice_id": notice_id, "notice_version": notice["version"],
                   "lot_versions": versions,
                   "created_at": now(), "status": "RUNNING", "mode": "live", "provider": "gemini",
                   "model": model, "prompt_version": PROMPT_VERSION, "policy_version": POLICY_VERSION,
                   "tool_calls": [], "usage": None}
            self.store.put("run", run_id, run)
            self._event("agent_started", {"run_id": run_id, "notice_id": notice_id})
            return {"allowed": True, **run}

    def tool(self, run_id, name, arguments=None):
        self._expire_pending_runs()
        with self.store.atomic():
            run = self.store.get("run", run_id)
            if not run or run["status"] != "RUNNING":
                raise ValueError("No active run with that ID.")
            if len(run["tool_calls"]) >= 12:
                raise ValueError("Tool-call limit reached.")
            notice = self.store.get("notice", run["notice_id"])
            if notice["version"] != run["notice_version"]:
                raise ValueError("Recall changed while the agent was running.")
            if name == "ReadRecallEvidence":
                result = notice
            elif name in {"ReadInventoryCandidates", "ReadContext"}:
                result = [self.store.get("lot", key) for key in run["lot_versions"]]
                if any(lot["version"] != run["lot_versions"][lot["lot_id"]] for lot in result):
                    raise ValueError("Inventory changed while the agent was running.")
                if name == "ReadContext":
                    # Preserve complete source snapshots and matching attributes;
                    # omit duplicated raw API fields and fulfillment-only data.
                    result = {"notice": {key: notice.get(key) for key in
                              ("notice_id", "agency", "jurisdiction", "title", "url", "version",
                               "target_component", "source_conflict", "snapshots")},
                              "lots": [{key: value for key, value in lot.items()
                                        if key not in {"quantity", "received_at"}} for lot in result]}
                    if self._meta().get("experience_mode") == "inventory-bridge":
                        # Business references stay local; only recall identity attributes
                        # and an opaque lot ID are needed by the inference provider.
                        allowed = {"lot_id", "version", "name", "brand", "model", "manufactured_month",
                                   "generation", "adapter_model", "manufacturer", "product_type", "upc"}
                        result["lots"] = [{k: v for k, v in lot.items() if k in allowed} for lot in result["lots"]]
            elif name == "ReadInventoryLot":
                lot_id = (arguments or {}).get("lot_id")
                if lot_id not in run["lot_versions"]:
                    raise ValueError("Lot is outside the run scope.")
                result = self.store.get("lot", lot_id)
                if result["version"] != run["lot_versions"][lot_id]:
                    raise ValueError("Inventory changed while the agent was running.")
            else:
                raise ValueError("Unsupported read tool.")
            run["tool_calls"].append({"name": name, "at": now(), "arguments": arguments or {}, "result_sha256": digest(result)})
            self.store.put("run", run_id, run)
            return result

    def submit(self, run_id, assessments):
        self._expire_pending_runs()
        with self.store.atomic():
            run = self.store.get("run", run_id)
            if not run or run["status"] != "RUNNING":
                raise ValueError("Run is not active.")
            if run.get("policy_version") != POLICY_VERSION:
                raise ValueError("Validation policy changed; start a current investigation.")
            read_tools = {t["name"] for t in run["tool_calls"]}
            if "ReadContext" not in read_tools and not {"ReadRecallEvidence", "ReadInventoryCandidates"} <= read_tools:
                raise ValueError("Read source evidence and inventory before submitting.")
            if not isinstance(assessments, list):
                raise ValueError("Assessments must be an array.")
            ids = [a.get("lot_id") for a in assessments if isinstance(a, dict)]
            if len(ids) != len(assessments) or len(ids) != len(set(ids)) or set(ids) != set(run["lot_versions"]):
                raise ValueError("Submit exactly one assessment for every scoped lot.")
            notice = self.store.get("notice", run["notice_id"])
            if notice["version"] != run["notice_version"]:
                raise ValueError("Notice changed; results cannot be applied.")
            accepted = []
            for proposed in assessments:
                lot = self.store.get("lot", proposed["lot_id"])
                if not lot or lot["version"] != run["lot_versions"][proposed["lot_id"]]:
                    raise ValueError("Inventory changed; results cannot be applied.")
                key = digest([notice["notice_id"], lot["lot_id"]])
                assessment = self._validated_record(proposed, lot, notice, run_id)
                self.store.put("assessment", key, assessment)
                accepted.append(assessment)
            run["status"] = "SUBMITTED"
            run["submitted_at"] = now()
            run["validation"] = {"at": now(), "assessment_count": len(accepted),
                                 "input_format_version": FORMAT_VERSION, "revision": 1}
            self.store.put("run", run_id, run)
            self._event("assessment_submitted", {"run_id": run_id, "count": len(accepted)})
            return {"accepted": len(accepted), "review_required": sum(a["decision"] == "INSUFFICIENT_EVIDENCE" for a in accepted)}

    def _validated_record(self, proposed, lot, notice, run_id, mode="live"):
        canonical, normalizations = canonicalize_assessment(proposed)
        try:
            validated = validate_assessment(canonical, lot, notice)
            decision, reason, checks, missing = validated.decision, validated.reason, validated.checks, validated.missing_fields
        except InvalidAssessment as exc:
            decision, reason, checks, missing = "INSUFFICIENT_EVIDENCE", str(exc), [], ["validated_evidence"]
        return {"notice_id": notice["notice_id"], "notice_version": notice["version"],
                "lot_id": lot["lot_id"], "inventory_version": lot["version"],
                "decision": decision, "reason": reason, "checks": checks, "missing_fields": missing,
                "run_id": run_id, "at": now(), "mode": mode, "policy_version": POLICY_VERSION,
                "proposed_assessment": proposed, "input_format_version": FORMAT_VERSION,
                "input_normalizations": normalizations}

    def revalidate_run(self, run_id):
        """Explicitly recheck stored real output; never create or impersonate an inference."""
        self._expire_pending_runs()
        with self.store.atomic():
            run = self.store.get("run", run_id)
            if not run or run["status"] != "COMPLETED" or run.get("mode") != "live":
                raise ValueError("Revalidation requires an actually completed live run.")
            if run.get("policy_version") != POLICY_VERSION:
                raise ValueError("The evidence policy changed; a new investigation is required.")
            notice = self.store.get("notice", run["notice_id"])
            if not notice or notice["version"] != run["notice_version"]:
                raise ValueError("Source evidence changed; a new investigation is required.")
            scoped = []
            for lot_id, version in run["lot_versions"].items():
                lot = self.store.get("lot", lot_id)
                previous = self.store.get("assessment", digest([run["notice_id"], lot_id]))
                if not lot or lot["version"] != version:
                    raise ValueError("Inventory identity changed; a new investigation is required.")
                if (not previous or previous["run_id"] != run_id
                        or previous.get("notice_version") != notice["version"]
                        or previous.get("inventory_version") != version
                        or previous.get("policy_version") != POLICY_VERSION
                        or not isinstance(previous.get("proposed_assessment"), dict)):
                    raise ValueError("The stored assessment was superseded or is incomplete.")
                if previous.get("review_id") or previous.get("origin") == "human-review":
                    raise ValueError("Revalidation cannot overwrite an operator review.")
                scoped.append((lot, previous))
            if all(previous.get("input_format_version") == FORMAT_VERSION for _, previous in scoped):
                return {"run_id": run_id, "reused": True, "without_inference": True, "validation": run.get("validation")}
            revision = run.get("validation", {}).get("revision", 1) + 1
            changes = []
            for lot, previous in scoped:
                updated = self._validated_record(previous["proposed_assessment"], lot, notice, run_id)
                updated["revalidation"] = {"revision": revision, "without_inference": True, "at": now()}
                self.store.put("assessment_revision", digest([run_id, lot["lot_id"], revision]), previous)
                self.store.put("assessment", digest([run["notice_id"], lot["lot_id"]]), updated)
                changes.append({"lot_id": lot["lot_id"], "previous": previous["decision"], "current": updated["decision"],
                                "input_normalizations": updated["input_normalizations"]})
            run["validation"].update(revision=revision, revalidated_at=now(), input_format_version=FORMAT_VERSION,
                                     without_additional_inference=True)
            self.store.put("run", run_id, run)
            self._event("assessment_revalidated", {"run_id": run_id, "revision": revision, "without_inference": True})
            return {"run_id": run_id, "reused": False, "without_inference": True,
                    "inference_prompt_version": run["prompt_version"], "validation": run["validation"], "changes": changes}

    def finish_run(self, run_id, usage=None, error=None):
        self._expire_pending_runs()
        with self.store.atomic():
            run = self.store.get("run", run_id)
            if not run:
                raise ValueError("Unknown run.")
            if run["status"] in {"COMPLETED", "FAILED"}:
                return run
            run["finished_at"] = now()
            run["usage"] = usage
            if error:
                run["error"] = str(error)[:500]
                run["status"] = "FAILED"
            elif run["status"] == "SUBMITTED":
                run["status"] = "COMPLETED"
            else:
                run["status"] = "FAILED"
                run["error"] = "The agent did not submit a complete assessment."
            self.store.put("run", run_id, run)
            self._event("agent_finished", {"run_id": run_id, "status": run["status"]})
            return run

    def _lot_status(self, lot, notices):
        if not notices:
            return {"status": "PENDING_EVALUATION", "reasons": [{"notice_id": None, "reason": "No recall notices have been selected for assessment."}]}
        reasons, pending, recalled = [], False, False
        for notice in notices:
            assessment = self.store.get("assessment", digest([notice["notice_id"], lot["lot_id"]]))
            if not assessment or assessment["notice_version"] != notice["version"] or assessment["inventory_version"] != lot["version"] or assessment.get("policy_version") != POLICY_VERSION:
                pending = True
                reasons.append({"notice_id": notice["notice_id"], "reason": "Assessment is missing or out of date."})
                continue
            run = self.store.get("run", assessment["run_id"])
            if not run or run["status"] != "COMPLETED":
                pending = True
                reasons.append({"notice_id": notice["notice_id"], "reason": "Live run has not completed successfully."})
            elif assessment["decision"] != "NO_MATCH_FOR_NOTICE":
                recalled |= assessment["decision"] == "MATCH_RECALL"
                reasons.append({"notice_id": notice["notice_id"], "reason": assessment["reason"]})
        status = "HOLD_RECALL" if recalled else "PENDING_EVALUATION" if pending else "HOLD_REVIEW" if reasons else "ELIGIBLE_IN_DEMO_SCOPE"
        return {"status": status, "reasons": reasons}

    def snapshot(self):
        self._expire_pending_runs()
        with self.store.atomic():
            notices = self.store.scan("notice")
            lots = [{**lot, **self._lot_status(lot, notices)} for lot in self.store.scan("lot")]
            result = {"backend": self.store.backend, "meta": self._meta(), "notices": notices, "lots": lots,
                    "runs": self.store.scan("run"), "transactions": self.store.scan("transaction"),
                    "assessments": self.store.scan("assessment"),
                    "reviews": self.store.scan("review"),
                    "events": sorted(self.store.scan("event"), key=lambda e: e["at"])[-100:]}
            if self._meta().get("experience_mode") == "inventory-bridge":
                from .monitor import view
                result["monitor"] = view(self)
                result.update(authority="ADVISORY_ONLY", external_inventory_updated=False,
                              inventory_imports=self.store.scan("inventory_import"),
                              discoveries=sorted(self.store.scan("discovery"), key=lambda x: x["at"])[-1:])
                latest = result["discoveries"][-1] if result["discoveries"] else None
                for lot in lots:
                    lot["candidate_notice_ids"] = [c["notice_id"] for c in latest["candidates"]
                        if lot["lot_id"] in c["lot_ids"] and latest["inventory_versions"].get(lot["lot_id"]) == lot["version"]] if latest else []
            return result

    def review(self, request, reviewer):
        reviewer = required_text(reviewer, "authenticated reviewer")
        reason = required_text(request.get("reason"), "review reason", 1200)
        if len(reason) < 20:
            raise ValueError("Record at least 20 characters explaining the reviewed evidence.")
        decision = request.get("decision")
        if decision not in {"CONFIRM_RECALL", "EXCLUDE_FOR_NOTICE"}:
            raise ValueError("Choose a specific human review action.")
        with self.store.atomic():
            note = self.store.get("notice", request.get("notice_id", ""))
            lot = self.store.get("lot", request.get("lot_id", ""))
            if not note or not lot:
                raise ValueError("Unknown notice or lot.")
            key = digest([note["notice_id"], lot["lot_id"]])
            assessment = self.store.get("assessment", key)
            if not assessment or assessment["notice_version"] != note["version"] or assessment["inventory_version"] != lot["version"] or assessment.get("policy_version") != POLICY_VERSION:
                raise ValueError("Run a current agent assessment before human review.")
            if any(request.get(field) != assessment[field] for field in ("notice_version", "inventory_version", "run_id")):
                raise ValueError("The reviewed evidence or assessment changed. Refresh and review the current case.")
            run = self.store.get("run", assessment["run_id"])
            if not run or run["status"] != "COMPLETED":
                raise ValueError("The underlying live agent run has not completed.")
            if assessment["decision"] != "INSUFFICIENT_EVIDENCE":
                raise ValueError("Only ambiguous cases can be resolved here; confirmed holds require new evidence and reevaluation.")
            review_id = uuid.uuid4().hex
            review = {"review_id": review_id, "notice_id": note["notice_id"], "lot_id": lot["lot_id"],
                      "notice_version": note["version"], "inventory_version": lot["version"],
                      "reviewer": reviewer, "reason": reason, "decision": decision, "at": now()}
            self.store.put("review", review_id, review)
            assessment.update(decision="MATCH_RECALL" if decision == "CONFIRM_RECALL" else "NO_MATCH_FOR_NOTICE",
                              reason=reason, review_id=review_id, origin="human-review", at=now())
            self.store.put("assessment", key, assessment)
            self._event("human_reviewed", {"review_id": review_id, "reviewer": reviewer})
            return review

    def transact(self, request):
        if self._meta().get("experience_mode") == "inventory-bridge":
            raise ValueError("Inventory bridge is advisory-only. Sale, shipment and quantity mutation are unavailable.")
        key = required_text(request.get("idempotency_key"), "idempotency key", 100)
        kind, lines = request.get("kind"), request.get("lines")
        if kind not in {"sale", "shipment"} or not isinstance(lines, list) or not 1 <= len(lines) <= 20:
            raise ValueError("Invalid retailer transaction.")
        ids = []
        for line in lines:
            ids.append(required_text(line.get("lot_id"), "lot ID"))
            if type(line.get("quantity")) is not int or not 1 <= line["quantity"] <= 100_000:
                raise ValueError("Line quantity must be a positive integer.")
        if len(ids) != len(set(ids)):
            raise ValueError("A lot must occur only once per transaction.")
        fingerprint = digest({"kind": kind, "lines": sorted(lines, key=lambda line: line["lot_id"])})
        with self.store.atomic():
            existing = self.store.get("transaction", key)
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ValueError("Idempotency key has already been used for another request.")
                return {**existing, "replayed": True}
            meta, notices = self._meta(), self.store.scan("notice")
            blocked, updates = [], []
            if not meta["initialized"] or not notices:
                blocked.append({"reason": "DEMO_SCOPE_NOT_INITIALIZED"})
            if meta.get("refresh_error"):
                blocked.append({"reason": "CPSC_REFRESH_FAILED"})
            for line in lines:
                lot = self.store.get("lot", line["lot_id"])
                if not lot:
                    blocked.append({"lot_id": line["lot_id"], "reason": "UNKNOWN_LOT"})
                    continue
                if lot.get("synthetic") is not True or lot.get("read_only_snapshot"):
                    raise ValueError("The downstream simulator accepts only explicitly synthetic demo inventory.")
                status = self._lot_status(lot, notices)
                if status["status"] != "ELIGIBLE_IN_DEMO_SCOPE":
                    blocked.append({"lot_id": line["lot_id"], **status})
                if lot["quantity"] < line["quantity"]:
                    blocked.append({"lot_id": line["lot_id"], "reason": "INSUFFICIENT_STOCK"})
                updates.append((lot, line["quantity"]))
            result = {"idempotency_key": key, "fingerprint": fingerprint, "kind": kind, "lines": lines,
                      "allowed": not blocked, "blocked": blocked, "epoch": meta["epoch"], "at": now(),
                      "synthetic": True, "replayed": False}
            if not blocked:
                for lot, quantity in updates:
                    # Sale and shipment are independent simulated fulfillment
                    # requests, each consuming stock; there is no real OMS here.
                    lot["quantity"] -= quantity
                    self.store.put("lot", lot["lot_id"], lot)
            self.store.put("transaction", key, result)
            self._event("retailer_transaction", {"key": key, "allowed": result["allowed"], "kind": kind})
            return result
