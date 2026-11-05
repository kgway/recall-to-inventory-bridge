# SPDX-License-Identifier: MPL-2.0
"""Critical safety properties, independent of a paid or live model."""

import copy
import threading
import unittest
from datetime import datetime, timedelta, timezone

from recall_guard.engine import Engine
from recall_guard.storage import MemoryStore

TEXT = "DREO space heaters, model number DR-HSH015. Only units manufactured from April 2025 through January 2026 are included."


def notice(key="US-CPSC:11038", text=TEXT):
    return {"notice_id": key, "title": "DREO heater recall", "url": "https://cpsc.gov/Recalls/example",
            "snapshots": [{"id": "api:" + key, "text": text}], "source_conflict": False}


def lot(key="lot-1", manufactured="2025-04", model="DR-HSH015", quantity=10):
    return {"lot_id": key, "sku": "synthetic-sku", "name": "DREO heater", "brand": "DREO",
            "model": model, "manufactured_month": manufactured, "quantity": quantity, "synthetic": True}


def assessment(item, note, decision="MATCH_RECALL"):
    evidence = {"snapshot_id": note["snapshots"][0]["id"], "quote": note["snapshots"][0]["text"]}
    return {"lot_id": item["lot_id"], "decision": decision, "reason": "Model and manufacturing scope checked.",
            "checks": [{"field": "model", "operator": "equals", "value": "DR-HSH015", "evidence": evidence},
                       {"field": "manufactured_month", "operator": "between_inclusive", "value": ["2025-04", "2026-01"], "evidence": evidence}],
            "missing_fields": []}


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.engine = Engine(self.store)
        self.note = notice()
        self.engine.import_notices([self.note])
        self.engine.import_lots([lot()])

    def evaluate(self, proposed, note=None, finish=True, model="test-model"):
        note = note or self.note
        run = self.engine.prepare_run(note["notice_id"], model=model, limit=20)
        self.assertTrue(run["allowed"])
        self.engine.tool(run["run_id"], "ReadRecallEvidence")
        self.engine.tool(run["run_id"], "ReadInventoryCandidates")
        self.engine.submit(run["run_id"], proposed)
        if finish:
            self.engine.finish_run(run["run_id"])
        return run

    def status(self, key="lot-1"):
        return next(l for l in self.engine.snapshot()["lots"] if l["lot_id"] == key)["status"]

    def review_request(self):
        current = next(a for a in self.engine.snapshot()["assessments"] if a["lot_id"] == "lot-1")
        return {**{field: current[field] for field in ("notice_id", "lot_id", "notice_version", "inventory_version", "run_id")},
                "decision": "EXCLUDE_FOR_NOTICE", "reason": "Synthetic label inspection proves this unit is outside the notice scope."}

    def evaluate_ambiguous(self, **kwargs):
        return self.evaluate([{"lot_id": "lot-1", "decision": "INSUFFICIENT_EVIDENCE", "reason": "Need to inspect the label.",
                               "checks": [], "missing_fields": ["label"]}], **kwargs)

    def generation_case(self, actual, expected="first generation", decision="NO_MATCH_FOR_NOTICE", conflict=False):
        self.note = notice(text="DREO model DR-HSH015. Only first-generation units are recalled.")
        self.note["source_conflict"] = conflict
        self.engine.import_notices([self.note])
        item = {**lot(), "generation": actual}
        self.engine.import_lots([item])
        value = assessment(item, self.note, decision)
        value["checks"] = value["checks"][:1] + [{"field": "generation", "operator": "equals", "value": expected,
                                                 "evidence": value["checks"][0]["evidence"]}]
        return value

    def transact(self, key="request-1", kind="shipment", quantity=1, lines=None):
        return self.engine.transact({"idempotency_key": key, "kind": kind,
                                    "lines": lines or [{"lot_id": "lot-1", "quantity": quantity}]})

    def test_unassessed_sale_and_shipment_are_blocked(self):
        for kind in ("sale", "shipment"):
            self.assertFalse(self.transact(key=kind, kind=kind)["allowed"])

    def test_both_manufacturing_boundaries_are_included(self):
        lots = [lot("april", "2025-04"), lot("january", "2026-01")]
        self.engine.import_lots(lots)
        all_lots = self.store.scan("lot")
        self.evaluate([assessment(l, self.note) for l in all_lots])
        self.assertEqual(self.status("april"), "HOLD_RECALL")
        self.assertEqual(self.status("january"), "HOLD_RECALL")

    def test_month_outside_range_allows_only_loaded_scope(self):
        outside = lot(manufactured="2026-02")
        self.engine.import_lots([outside])
        self.evaluate([assessment(outside, self.note, "NO_MATCH_FOR_NOTICE")])
        self.assertEqual(self.status(), "ELIGIBLE_IN_DEMO_SCOPE")
        self.assertTrue(self.transact()["allowed"])

    def test_unknown_month_cannot_be_no_match(self):
        unknown = lot(manufactured=None)
        self.engine.import_lots([unknown])
        self.evaluate([assessment(unknown, self.note, "NO_MATCH_FOR_NOTICE")])
        self.assertEqual(self.status(), "HOLD_REVIEW")
        self.assertFalse(self.transact()["allowed"])

    def test_fabricated_quote_cannot_clear_inventory(self):
        value = assessment(lot(), self.note, "NO_MATCH_FOR_NOTICE")
        value["checks"][0]["evidence"] = {"snapshot_id": "fabricated", "quote": "DR-HSH999"}
        self.evaluate([value])
        self.assertEqual(self.status(), "HOLD_REVIEW")

    def test_omitted_manufacturing_constraint_is_not_a_match(self):
        value = assessment(lot(), self.note)
        value["checks"] = value["checks"][:1]
        self.evaluate([value])
        self.assertEqual(self.status(), "HOLD_REVIEW")

    def test_unfinished_or_failed_agent_cannot_authorize(self):
        outside = lot(manufactured="2026-02")
        self.engine.import_lots([outside])
        run = self.evaluate([assessment(outside, self.note, "NO_MATCH_FOR_NOTICE")], finish=False)
        self.assertFalse(self.transact("before-finish")["allowed"])
        self.engine.finish_run(run["run_id"], error="provider quota exceeded")
        self.assertFalse(self.transact("after-failure")["allowed"])

    def test_new_notice_version_invalidates_previous_clearance(self):
        outside = lot(manufactured="2026-02")
        self.engine.import_lots([outside])
        self.evaluate([assessment(outside, self.note, "NO_MATCH_FOR_NOTICE")])
        updated = notice(text=TEXT + " Scope has been amended.")
        self.engine.import_notices([updated])
        self.assertEqual(self.status(), "PENDING_EVALUATION")
        self.assertFalse(self.transact()["allowed"])

    def test_new_lot_attributes_invalidate_previous_clearance(self):
        outside = lot(manufactured="2026-02")
        self.engine.import_lots([outside])
        self.evaluate([assessment(outside, self.note, "NO_MATCH_FOR_NOTICE")])
        self.engine.import_lots([lot(manufactured="2026-01")])
        self.assertEqual(self.status(), "PENDING_EVALUATION")

    def test_stale_live_run_cannot_submit(self):
        run = self.engine.prepare_run(self.note["notice_id"], model="test", limit=20)
        self.engine.tool(run["run_id"], "ReadRecallEvidence")
        self.engine.tool(run["run_id"], "ReadInventoryCandidates")
        self.engine.import_lots([lot(manufactured="2026-02")])
        with self.assertRaisesRegex(ValueError, "Inventory changed"):
            self.engine.submit(run["run_id"], [assessment(lot(), self.note)])

    def test_one_notice_no_match_does_not_release_another_hold(self):
        second = notice("US-CPSC:second")
        self.engine.import_notices([second])
        self.evaluate([assessment(lot(), self.note)])
        mismatch = lot(model="DIFFERENT-MODEL")
        # The second source's tested model differs; first notice's valid hold stays.
        other = assessment(lot(), second, "NO_MATCH_FOR_NOTICE")
        other["checks"] = [{"field": "model", "operator": "equals", "value": "DIFFERENT-MODEL",
                            "evidence": {"snapshot_id": second["snapshots"][0]["id"], "quote": "DIFFERENT-MODEL"}}]
        # Amend the second notice to supply real evidence, independently of the first.
        second = notice("US-CPSC:second", TEXT + " DIFFERENT-MODEL")
        self.engine.import_notices([second])
        self.evaluate([other], note=second)
        self.assertEqual(self.status(), "HOLD_RECALL")

    def test_conflicting_sources_require_review_for_a_match(self):
        self.note["source_conflict"] = True
        self.engine.import_notices([self.note])
        self.evaluate([assessment(lot(), self.note)])
        self.assertEqual(self.status(), "HOLD_REVIEW")

    def test_serial_qualifier_requires_review(self):
        self.note = notice(text=TEXT + " Only qualifying serial numbers are included.")
        self.engine.import_notices([self.note])
        self.evaluate([assessment(lot(), self.note)])
        self.assertEqual(self.status(), "HOLD_REVIEW")

    def test_duplicate_idempotency_key_cannot_consume_stock_twice(self):
        outside = lot(manufactured="2026-02")
        self.engine.import_lots([outside])
        self.evaluate([assessment(outside, self.note, "NO_MATCH_FOR_NOTICE")])
        first, replay = self.transact(), self.transact()
        self.assertTrue(first["allowed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(self.store.get("lot", "lot-1")["quantity"], 9)
        with self.assertRaisesRegex(ValueError, "another request"):
            self.transact(kind="sale")

    def test_reimport_does_not_reset_sold_stock(self):
        outside = lot(manufactured="2026-02")
        self.engine.import_lots([outside])
        self.evaluate([assessment(outside, self.note, "NO_MATCH_FOR_NOTICE")])
        self.transact(quantity=2)
        self.engine.import_lots([outside])
        self.assertEqual(self.store.get("lot", "lot-1")["quantity"], 8)

    def test_mixed_order_is_atomic(self):
        second = lot("lot-2", "2026-02")
        self.engine.import_lots([second])
        self.evaluate([assessment(lot(), self.note), assessment(second, self.note, "NO_MATCH_FOR_NOTICE")])
        result = self.transact(lines=[{"lot_id": "lot-1", "quantity": 1}, {"lot_id": "lot-2", "quantity": 1}])
        self.assertFalse(result["allowed"])
        self.assertEqual(self.store.get("lot", "lot-2")["quantity"], 10)

    def test_concurrent_shipments_cannot_oversell(self):
        outside = lot(manufactured="2026-02", quantity=1)
        # Seed one unit before any simulated transaction.
        with self.store.atomic():
            self.store.put("lot", "lot-1", {**self.store.get("lot", "lot-1"), "quantity": 1})
        self.engine.import_lots([outside])
        self.evaluate([assessment(outside, self.note, "NO_MATCH_FOR_NOTICE")])
        results = []
        threads = [threading.Thread(target=lambda k=k: results.append(self.transact(str(k)))) for k in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(r["allowed"] for r in results), 1)
        self.assertEqual(self.store.get("lot", "lot-1")["quantity"], 0)

    def test_invalid_inventory_import_rolls_back_all_rows(self):
        with self.assertRaises(ValueError):
            self.engine.import_lots([lot("new"), {**lot("bad"), "manufactured_month": "2026-13"}])
        self.assertIsNone(self.store.get("lot", "new"))

    def test_incomplete_duplicate_or_out_of_scope_assessments_are_rejected(self):
        run = self.engine.prepare_run(self.note["notice_id"], model="test", limit=20)
        self.engine.tool(run["run_id"], "ReadRecallEvidence")
        self.engine.tool(run["run_id"], "ReadInventoryCandidates")
        for values in ([], [assessment(lot(), self.note)] * 2, [assessment(lot("outside"), self.note)]):
            with self.assertRaisesRegex(ValueError, "exactly one"):
                self.engine.submit(run["run_id"], values)

    def test_daily_limit_does_not_fall_back_to_a_paid_provider(self):
        self.assertTrue(self.engine.prepare_run(self.note["notice_id"], limit=1)["allowed"])
        result = self.engine.prepare_run(self.note["notice_id"], model="another-free-model", limit=1)
        self.assertFalse(result["allowed"])
        self.assertFalse(result["paid_fallback"])

    def test_combined_context_preserves_all_source_text_and_scoped_identity(self):
        self.note["raw_api"] = {"duplicate_field": "not needed by matching"}
        self.note["title"] = "Updated context projection notice"
        self.engine.import_notices([self.note])
        self.assertIn("raw_api", self.store.get("notice", self.note["notice_id"]))
        run = self.engine.prepare_run(self.note["notice_id"], limit=20)
        context = self.engine.tool(run["run_id"], "ReadContext")
        self.assertEqual(context["notice"]["snapshots"], self.note["snapshots"])
        self.assertNotIn("raw_api", context["notice"])
        self.assertEqual(context["lots"][0]["lot_id"], "lot-1")
        self.assertEqual(context["lots"][0]["manufactured_month"], "2025-04")
        self.engine.submit(run["run_id"], [assessment(lot(), self.note)])
        self.engine.finish_run(run["run_id"])
        self.assertEqual(self.status(), "HOLD_RECALL")
        saved = self.store.get("run", run["run_id"])
        self.assertEqual([tool["name"] for tool in saved["tool_calls"]], ["ReadContext"])
        self.assertEqual(saved["validation"]["assessment_count"], 1)

    def test_combined_context_rejects_changed_inventory(self):
        run = self.engine.prepare_run(self.note["notice_id"], limit=20)
        self.engine.import_lots([lot(manufactured="2026-02")])
        with self.assertRaisesRegex(ValueError, "Inventory changed"):
            self.engine.tool(run["run_id"], "ReadContext")

    def test_crashed_run_times_out_even_when_a_late_tool_is_rejected(self):
        run = self.engine.prepare_run(self.note["notice_id"], model="test-model", limit=20)
        with self.store.atomic():
            stored = self.store.get("run", run["run_id"])
            stored["created_at"] = (datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
            self.store.put("run", run["run_id"], stored)
        with self.assertRaisesRegex(ValueError, "No active run"):
            self.engine.tool(run["run_id"], "ReadRecallEvidence")
        self.assertEqual(self.store.get("run", run["run_id"])["status"], "FAILED")
        self.assertFalse(self.transact()["allowed"])
        replacement = self.engine.prepare_run(self.note["notice_id"], model="test-model", limit=20)
        self.assertTrue(replacement["allowed"])
        self.assertNotEqual(replacement["run_id"], run["run_id"])

    def test_late_finish_cannot_activate_an_expired_submission(self):
        outside = lot(manufactured="2026-02")
        self.engine.import_lots([outside])
        run = self.evaluate([assessment(outside, self.note, "NO_MATCH_FOR_NOTICE")], finish=False)
        with self.store.atomic():
            stored = self.store.get("run", run["run_id"])
            stored["created_at"] = (datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
            self.store.put("run", run["run_id"], stored)
        finished = self.engine.finish_run(run["run_id"])
        self.assertEqual(finished["status"], "FAILED")
        self.assertIn("deadline", finished["error"])
        self.assertEqual(self.engine.finish_run(run["run_id"])["status"], "FAILED")
        self.assertFalse(self.transact()["allowed"])

    def test_duplicate_completed_response_is_idempotent(self):
        outside = lot(manufactured="2026-02")
        self.engine.import_lots([outside])
        run = self.evaluate([assessment(outside, self.note, "NO_MATCH_FOR_NOTICE")])
        again = self.engine.finish_run(run["run_id"])
        self.assertEqual(again["status"], "COMPLETED")
        self.assertTrue(self.transact()["allowed"])

    def test_same_input_does_not_start_another_live_run(self):
        first = self.engine.prepare_run(self.note["notice_id"], model="test-model", limit=20)
        duplicate = self.engine.prepare_run(self.note["notice_id"], model="test-model", limit=20)
        self.assertFalse(duplicate["allowed"])
        self.assertEqual(duplicate["reason"], "ALREADY_PENDING")
        self.engine.tool(first["run_id"], "ReadRecallEvidence")
        self.engine.tool(first["run_id"], "ReadInventoryCandidates")
        self.engine.submit(first["run_id"], [assessment(lot(), self.note)])
        self.engine.finish_run(first["run_id"])
        cached = self.engine.prepare_run(self.note["notice_id"], model="test-model", limit=20)
        self.assertFalse(cached["allowed"])
        self.assertEqual(cached["reason"], "CURRENT_ASSESSMENT_REUSED")
        self.assertEqual(len(self.store.scan("run")), 1)

    def test_failed_refresh_blocks_previous_clearance_until_success(self):
        outside = lot(manufactured="2026-02")
        self.engine.import_lots([outside])
        self.evaluate([assessment(outside, self.note, "NO_MATCH_FOR_NOTICE")])
        self.engine.refresh_failed("CPSC source is unavailable")
        self.assertFalse(self.transact("during-outage")["allowed"])
        self.engine.import_notices([self.note])
        self.assertTrue(self.transact("after-refresh")["allowed"])

    def test_seed_cannot_replace_already_initialized_live_sources(self):
        updated = notice(text=TEXT + " Changed scope.")
        self.engine.import_notices([updated])
        before = self.store.get("notice", self.note["notice_id"])["version"]
        result = self.engine.seed([self.note], [lot()])
        self.assertTrue(result["already_initialized"])
        self.assertEqual(self.store.get("notice", self.note["notice_id"])["version"], before)

    def test_human_can_resolve_only_a_completed_ambiguous_case(self):
        self.evaluate_ambiguous()
        review = self.engine.review(self.review_request(), "DemoReviewer")
        self.assertEqual(review["reviewer"], "DemoReviewer")
        self.assertTrue(self.transact()["allowed"])
        self.assertEqual(len(self.engine.snapshot()["reviews"]), 1)

    def test_review_cannot_release_a_confirmed_recall_hold(self):
        self.evaluate([assessment(lot(), self.note)])
        with self.assertRaisesRegex(ValueError, "Only ambiguous"):
            self.engine.review(self.review_request(), "DemoReviewer")
        self.assertFalse(self.transact()["allowed"])

    def test_human_review_requires_all_displayed_version_tokens(self):
        self.evaluate_ambiguous()
        for field in ("notice_version", "inventory_version", "run_id"):
            request = self.review_request()
            del request[field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "assessment changed"):
                self.engine.review(request, "DemoReviewer")
        self.assertEqual(self.engine.snapshot()["reviews"], [])
        self.assertFalse(self.transact()["allowed"])

    def test_review_of_an_older_notice_cannot_release_a_new_case(self):
        self.evaluate_ambiguous()
        request = self.review_request()
        self.note = notice(text=TEXT + " New source evidence.")
        self.engine.import_notices([self.note])
        self.evaluate_ambiguous()
        with self.assertRaisesRegex(ValueError, "assessment changed"):
            self.engine.review(request, "DemoReviewer")
        self.assertEqual(self.status(), "HOLD_REVIEW")
        self.assertEqual(self.engine.snapshot()["reviews"], [])

    def test_review_of_an_older_lot_cannot_release_a_new_case(self):
        self.evaluate_ambiguous()
        request = self.review_request()
        self.engine.import_lots([lot(manufactured="2026-01")])
        self.evaluate_ambiguous()
        with self.assertRaisesRegex(ValueError, "assessment changed"):
            self.engine.review(request, "DemoReviewer")
        self.assertFalse(self.transact()["allowed"])

    def test_review_of_a_superseded_agent_run_is_rejected(self):
        self.evaluate_ambiguous()
        request = self.review_request()
        self.evaluate_ambiguous(model="test-model-v2")
        with self.assertRaisesRegex(ValueError, "assessment changed"):
            self.engine.review(request, "DemoReviewer")
        self.assertFalse(self.transact()["allowed"])

    def test_unknown_model_suffix_is_not_a_proven_exclusion(self):
        variant = lot(model="DR-HSH015-B")
        self.engine.import_lots([variant])
        self.evaluate([assessment(variant, self.note, "NO_MATCH_FOR_NOTICE")])
        self.assertEqual(self.status(), "HOLD_REVIEW")

    def test_adapter_recall_cannot_exclude_using_host_product_model(self):
        adapter_notice = notice(text="Hatch power adapters have model CYAP05 050100U.")
        adapter_notice["target_component"] = "power_adapter"
        self.engine.import_notices([adapter_notice])
        value = {"lot_id": "lot-1", "decision": "NO_MATCH_FOR_NOTICE", "reason": "Host product model differs.", "missing_fields": [],
                 "checks": [{"field": "model", "operator": "equals", "value": "CYAP05 050100U", "evidence": {"snapshot_id": adapter_notice["snapshots"][0]["id"], "quote": adapter_notice["snapshots"][0]["text"]}}]}
        self.evaluate([value], note=adapter_notice)
        self.assertEqual(self.status(), "HOLD_REVIEW")

    def test_generation_wording_is_not_a_proven_exclusion(self):
        value = self.generation_case("1")
        self.evaluate([value])
        self.assertEqual(self.status(), "HOLD_REVIEW")
        self.assertFalse(self.transact()["allowed"])

    def test_generation_aliases_can_support_a_matching_constraint(self):
        value = self.generation_case("1st generation", expected="1", decision="MATCH_RECALL")
        self.evaluate([value])
        self.assertEqual(self.status(), "HOLD_RECALL")

    def test_unrecognized_generation_remains_unknown(self):
        value = self.generation_case("unverified edition")
        self.evaluate([value])
        self.assertEqual(self.status(), "HOLD_REVIEW")

    def test_conflicting_source_generation_cannot_clear_a_lot(self):
        value = self.generation_case("2", conflict=True)
        self.evaluate([value])
        self.assertEqual(self.status(), "HOLD_REVIEW")

    def test_unrelated_brand_can_be_excluded_despite_scope_conflict(self):
        self.note["source_conflict"] = True
        self.engine.import_notices([self.note])
        item = {**lot(), "brand": "DemoCo"}
        self.engine.import_lots([item])
        value = assessment(item, self.note, "NO_MATCH_FOR_NOTICE")
        value["checks"] = [{"field": "brand", "operator": "equals", "value": "DREO",
                            "evidence": value["checks"][0]["evidence"]}]
        self.evaluate([value])
        self.assertEqual(self.status(), "ELIGIBLE_IN_DEMO_SCOPE")

    def test_old_validation_policy_blocks_clearance_and_requires_a_new_run(self):
        outside = lot(manufactured="2026-02")
        self.engine.import_lots([outside])
        run = self.evaluate([assessment(outside, self.note, "NO_MATCH_FOR_NOTICE")])
        with self.store.atomic():
            previous_run = self.store.get("run", run["run_id"])
            previous_run["policy_version"] = "retired-policy"
            self.store.put("run", run["run_id"], previous_run)
            previous_assessment = self.store.scan("assessment")[0]
            previous_assessment["policy_version"] = "retired-policy"
            from recall_guard.engine import digest
            self.store.put("assessment", digest([self.note["notice_id"], "lot-1"]), previous_assessment)
        self.assertEqual(self.status(), "PENDING_EVALUATION")
        self.assertFalse(self.transact()["allowed"])
        current_run = self.engine.prepare_run(self.note["notice_id"], model="test-model", limit=20)
        self.assertTrue(current_run["allowed"])
        self.assertNotEqual(current_run["run_id"], run["run_id"])

    def test_old_policy_in_flight_run_cannot_submit_results(self):
        run = self.engine.prepare_run(self.note["notice_id"], model="test-model", limit=20)
        self.engine.tool(run["run_id"], "ReadRecallEvidence")
        self.engine.tool(run["run_id"], "ReadInventoryCandidates")
        with self.store.atomic():
            previous = self.store.get("run", run["run_id"])
            previous["policy_version"] = "retired-policy"
            self.store.put("run", run["run_id"], previous)
        with self.assertRaisesRegex(ValueError, "policy changed"):
            self.engine.submit(run["run_id"], [assessment(lot(), self.note)])
        self.assertEqual(self.engine.snapshot()["assessments"], [])


if __name__ == "__main__":
    unittest.main()
