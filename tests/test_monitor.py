# SPDX-License-Identifier: MPL-2.0
"""Recurring audit boundaries, failures and automatic-model budget guards."""
import copy
import json
import unittest
from unittest.mock import patch

from recall_guard.engine import Engine
from recall_guard.inventory import import_snapshot, preview
from recall_guard.discovery import search_plan
from recall_guard.monitor import (configure, config, due, run_cycle, pending,
                                  prepare_auto_run, complete_auto_run, view, claim_tick)
from recall_guard.storage import MemoryStore
from recall_guard.runtime import fixture_notices
from test_engine import notice, assessment


class StrictKeyStore(MemoryStore):
    """Mirror the SQL document store's string-key boundary."""
    def get(self, kind, key):
        if not isinstance(key, str):raise TypeError("SQL document keys must be strings")
        return super().get(kind, key)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(StrictKeyStore())
        self.req = {"source_system": "example-erp", "import_id": "snapshot-one", "items": [{
            "external_id": "0001", "sku": "001234", "name": "DREO heater", "brand": "DREO",
            "model": "DR-HSH015", "manufactured_month": "2025-04", "quantity": 47}]}
        self.imported(self.req)
        self.raw = next(n["raw_api"] for n in fixture_notices() if n["source_id"] == "11038")
        self.note = notice()
        self.clock = patch("recall_guard.monitor.now", return_value="2026-11-04T12:00:00+00:00")
        self.instant = self.clock.start()
        self.addCleanup(self.clock.stop)

    def imported(self, req):
        checked = preview(self.engine, req)
        return import_snapshot(self.engine, req | {k: checked[k] for k in ("preview_hash", "workspace_revision")})

    def policy(self, enabled=True, auto_ai=False, **extra):
        return configure(self.engine, {"enabled": enabled, "auto_ai": auto_ai, "interval_seconds": 60,
                         "plan_hash": search_plan(self.engine)["plan_hash"], **extra}, provider_ready=True)

    def cycle(self, request_id="audit-request-one", **kwargs):
        with patch("recall_guard.discovery.fetch", return_value=json.dumps([self.raw]).encode()), \
             patch("recall_guard.monitor.fetch_notice", return_value=copy.deepcopy(self.note)):
            return run_cycle(self.engine, {"request_id": request_id}, **kwargs)

    def select(self):
        self.engine.import_notices([self.note])

    def test_default_has_no_timer_or_side_effects(self):
        before = copy.deepcopy(self.engine.store.records)
        self.assertFalse(due(self.engine))
        self.assertFalse(config(self.engine)["auto_ai"])
        self.assertEqual(before, self.engine.store.records)

    def test_queue_claim_is_atomic_and_expires_if_delivery_is_lost(self):
        from concurrent.futures import ThreadPoolExecutor
        self.policy()
        self.instant.return_value = "2026-11-04T12:01:00+00:00"
        with ThreadPoolExecutor(max_workers=8) as pool:
            claimed = list(pool.map(lambda _: claim_tick(self.engine), range(20)))
        self.assertEqual(sum(claimed), 1)
        self.instant.return_value = "2026-11-04T12:01:59+00:00"
        self.assertFalse(claim_tick(self.engine))
        self.instant.return_value = "2026-11-04T12:02:00+00:00"
        self.assertTrue(claim_tick(self.engine))

    def test_policy_requires_current_terms_and_real_free_tier_gate(self):
        for req in ({"enabled": True, "auto_ai": False, "plan_hash": "old"},
                    {"enabled": True, "auto_ai": False, "interval_seconds": 1},
                    {"enabled": 1, "auto_ai": False}, {"enabled": False, "auto_ai": "false"}):
            with self.assertRaises(ValueError):configure(self.engine, req)
        with self.assertRaises(ValueError):
            configure(self.engine, {"enabled": False, "auto_ai": True})
        self.assertFalse(config(self.engine)["enabled"])

    def test_timer_due_and_new_import_persist_due_without_consuming_stock(self):
        self.policy()
        self.assertFalse(due(self.engine))
        self.instant.return_value = "2026-11-04T12:01:00+00:00"
        self.assertTrue(due(self.engine))
        self.instant.return_value = "2026-11-04T12:00:10+00:00"
        self.imported(self.req | {"import_id": "snapshot-two"})
        self.assertTrue(due(self.engine))
        self.assertEqual(self.engine.store.scan("lot")[0]["quantity"], 47)

    def test_no_key_manual_audit_finds_candidates_without_selecting_or_running_ai(self):
        result = self.cycle()
        cycle = self.engine.store.get("audit_cycle", result["cycle_id"])
        self.assertEqual(cycle["new_candidate_ids"], ["US-CPSC:11038"])
        self.assertFalse(self.engine.store.scan("notice"))
        self.assertFalse(self.engine.store.scan("run"))
        self.assertEqual(len(cycle["advisory_changes"]), 1)
        self.assertFalse(cycle["complete_recall_coverage"])

    def test_idempotency_cooldown_and_single_active_lease(self):
        result = self.cycle()
        with patch("recall_guard.monitor.discover") as http:
            replay = run_cycle(self.engine, {"request_id": "audit-request-one"})
            self.assertTrue(replay["replayed"])
            self.assertEqual(run_cycle(self.engine, {"request_id": "audit-request-two"})["reason"], "AUDIT_COOLDOWN_60_SECONDS")
            http.assert_not_called()
        self.select();self.policy(auto_ai=True)
        self.instant.return_value = "2026-11-04T12:02:00+00:00"
        active = self.cycle("audit-awaiting-ai", provider_ready=True)
        self.assertEqual(active["status"], "AWAITING_AI")
        self.assertEqual(self.cycle("audit-other-active")["reason"], "AUDIT_ALREADY_RUNNING")
        self.assertFalse(due(self.engine))

    def test_selected_original_change_invalidates_old_assessment_before_ai(self):
        self.select()
        lot = self.engine.store.scan("lot")[0]
        run = self.engine.prepare_run(self.note["notice_id"])
        self.engine.tool(run["run_id"], "ReadContext")
        self.engine.submit(run["run_id"], [assessment(lot, self.note)])
        self.engine.finish_run(run["run_id"])
        old = self.engine.store.get("notice", self.note["notice_id"])["version"]
        self.note["snapshots"][0]["text"] += " Updated official notice."
        result = self.cycle()
        cycle = self.engine.store.get("audit_cycle", result["cycle_id"])
        self.assertNotEqual(old, self.engine.store.get("notice", self.note["notice_id"])["version"])
        self.assertEqual(cycle["changed_notice_ids"], [self.note["notice_id"]])
        self.assertEqual(cycle["pending_evaluations"][0]["pending_records"], 1)
        self.assertEqual(len(self.engine.store.scan("run")), 1)

    def test_auto_ai_skips_current_results_and_quantity_only_changes(self):
        self.select();self.policy(auto_ai=True)
        active = self.cycle(provider_ready=True)
        prepared = prepare_auto_run(self.engine, {"notice_id": self.note["notice_id"], "audit_cycle_id": active["cycle_id"]}, "test-model", 5, True)
        self.assertTrue(prepared["allowed"])
        self.engine.tool(prepared["run_id"], "ReadContext")
        self.engine.submit(prepared["run_id"], [assessment(self.engine.store.scan("lot")[0], self.note)])
        complete_auto_run(self.engine, self.engine.finish_run(prepared["run_id"]))
        cycle = self.engine.store.get("audit_cycle", active["cycle_id"])
        self.assertTrue(cycle["advisory_changes"])
        self.assertFalse(cycle["pending_evaluations"])
        changed = copy.deepcopy(self.req);changed["import_id"] = "quantity-update";changed["items"][0]["quantity"] = 46
        self.imported(changed)
        self.instant.return_value = "2026-11-04T12:02:00+00:00"
        again = self.cycle("audit-second-cycle", provider_ready=True)
        self.assertNotIn("ai_notice_id", again)
        self.assertEqual(len(self.engine.store.scan("run")), 1)

    def test_auto_ai_rechecks_policy_inventory_and_daily_cap_at_dispatch(self):
        original = copy.deepcopy(self.engine.store.records)
        for change, reason in (("policy", "AUDIT_INPUT_OR_POLICY_CHANGED"), ("inventory", "AUDIT_INPUT_OR_POLICY_CHANGED"),
                               ("provider", "AUDIT_INPUT_OR_POLICY_CHANGED"), ("budget", "DAILY_RUN_LIMIT")):
            with self.subTest(change=change):
                self.engine = Engine(StrictKeyStore());self.engine.store.records = copy.deepcopy(original)
                self.instant.return_value = "2026-11-04T12:00:00+00:00"
                self.select();self.policy(auto_ai=True)
                active = self.cycle(provider_ready=True)
                ready = True
                if change == "policy":self.policy(enabled=False, auto_ai=False)
                if change == "inventory":
                    changed = copy.deepcopy(self.req);changed["import_id"] = "identity-update";changed["items"][0]["manufactured_month"] = "2025-05";self.imported(changed)
                if change == "provider":ready = False
                if change == "budget":
                    for i in range(5):self.engine.store.put("run", str(i), {"run_id": str(i), "notice_id": "OTHER", "created_at": __import__('recall_guard.engine',fromlist=['now']).now(), "status": "FAILED"})
                result = prepare_auto_run(self.engine, {"notice_id": self.note["notice_id"], "audit_cycle_id": active["cycle_id"]}, "model", 5, ready)
                self.assertFalse(result["allowed"]);self.assertEqual(result["reason"], reason)
                self.assertIsNone(config(self.engine)["active_cycle_id"])

    def test_failed_unchanged_input_requires_manual_retry(self):
        self.select();self.policy(auto_ai=True)
        active = self.cycle(provider_ready=True)
        p = prepare_auto_run(self.engine, {"notice_id": self.note["notice_id"], "audit_cycle_id": active["cycle_id"]}, "model", 5, True)
        complete_auto_run(self.engine, self.engine.finish_run(p["run_id"], error="invalid agent response"))
        self.instant.return_value = "2026-11-04T12:02:00+00:00"
        again = self.cycle("audit-failed-input", provider_ready=True)
        cycle = self.engine.store.get("audit_cycle", again["cycle_id"])
        self.assertEqual(cycle["ai_deferred_reason"], "UNCHANGED_INPUT_REQUIRES_MANUAL_RETRY")
        self.assertEqual(len(self.engine.store.scan("run")), 1)

    def test_source_failures_are_visible_and_not_clearance(self):
        self.select();self.policy(auto_ai=True)
        with patch("recall_guard.discovery.fetch", side_effect=OSError("offline")), \
             patch("recall_guard.monitor.fetch_notice", side_effect=OSError("offline")):
            result = run_cycle(self.engine, {"request_id": "audit-source-failure"}, provider_ready=True)
        cycle = self.engine.store.get("audit_cycle", result["cycle_id"])
        self.assertEqual(cycle["status"], "PARTIAL")
        self.assertTrue(cycle["errors"]);self.assertTrue(cycle["limitations"])
        self.assertFalse(self.engine.store.scan("run"))

    def test_old_cycle_lease_expires_and_new_policy_can_resume(self):
        self.select();self.policy(auto_ai=True)
        active = self.cycle(provider_ready=True)
        self.instant.return_value = "2026-11-04T12:11:00+00:00"
        self.assertTrue(due(self.engine))
        self.policy(auto_ai=False)
        self.cycle("audit-after-timeout")
        self.assertEqual(self.engine.store.get("audit_cycle", active["cycle_id"])["status"], "TIMED_OUT")

    def test_monitor_is_in_feed_and_preserves_read_only_authority(self):
        from recall_guard.advisories import feed
        self.cycle()
        document = feed(self.engine)
        self.assertEqual(document["monitor"]["authority"], "ADVISORY_ONLY")
        self.assertNotIn("baseline", document["monitor"]["cycles"][0])
        with self.assertRaises(ValueError):self.engine.transact({})

    def test_manual_only_audit_recovers_expired_lease_without_enabling_timer(self):
        self.select();self.policy(enabled=False, auto_ai=True)
        active = self.cycle(provider_ready=True)
        self.instant.return_value = "2026-11-04T12:11:00+00:00"
        self.assertFalse(due(self.engine))
        self.assertIsNone(config(self.engine)["active_cycle_id"])
        self.assertEqual(self.engine.store.get("audit_cycle", active["cycle_id"])["status"], "TIMED_OUT")

    def test_duplicate_dispatch_cannot_create_second_native_run(self):
        self.select();self.policy(auto_ai=True)
        active = self.cycle(provider_ready=True)
        req = {"notice_id": self.note["notice_id"], "audit_cycle_id": active["cycle_id"]}
        self.assertTrue(prepare_auto_run(self.engine, req, "model", 5, True)["allowed"])
        self.assertFalse(prepare_auto_run(self.engine, req, "model", 5, True)["allowed"])
        self.assertEqual(len(self.engine.store.scan("run")), 1)

    def test_incomplete_audit_routes_stored_exclusion_back_to_receiving_review(self):
        import importlib.util
        from pathlib import Path
        from recall_guard.advisories import feed
        changed = copy.deepcopy(self.req);changed["items"][0]["manufactured_month"] = "2025-03";changed["import_id"] = "earlier-month";self.imported(changed)
        self.select();lot = self.engine.store.scan("lot")[0]
        run = self.engine.prepare_run(self.note["notice_id"]);self.engine.tool(run["run_id"], "ReadContext")
        self.engine.submit(run["run_id"], [assessment(lot, self.note, "NO_MATCH_FOR_NOTICE")]);self.engine.finish_run(run["run_id"])
        with patch("recall_guard.discovery.fetch", side_effect=OSError("offline")), patch("recall_guard.monitor.fetch_notice", side_effect=OSError("offline")):
            run_cycle(self.engine, {"request_id": "audit-exclusion-failed"})
        document = feed(self.engine)
        self.assertEqual(document["items"][0]["advisory"], "NO_MATCH_IN_SELECTED_NOTICES")
        self.assertTrue(document["items"][0]["audit_attention"])
        spec = importlib.util.spec_from_file_location("receiver", Path(__file__).resolve().parents[1]/"examples/review_consumer.py")
        receiver = importlib.util.module_from_spec(spec);spec.loader.exec_module(receiver)
        self.assertEqual(len(receiver.worklist(document)["tasks"]), 1)


if __name__ == "__main__":unittest.main()
