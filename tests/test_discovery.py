# SPDX-License-Identifier: MPL-2.0
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from recall_guard.engine import Engine, PROMPT_VERSION
from recall_guard.discovery import discover, plan, search_plan, select_candidates
from recall_guard.inventory import import_snapshot, preview
from recall_guard.storage import MemoryStore
from recall_guard.runtime import fixture_notices

ROOT=Path(__file__).resolve().parents[1]


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.engine=Engine(MemoryStore())
        req={"format":"json","source_system":"erp-private","import_id":"capture-one","content":json.dumps([
             {"external_id":"PRIVATE-ID","sku":"PRIVATE-SKU","name":"DREO heater","brand":"DREO",
              "model":"DR-HSH015","location":"PRIVATE-WAREHOUSE","quantity":17,"manufactured_month":"2025-04"}])}
        p=preview(self.engine,req);import_snapshot(self.engine,req|{k:p[k] for k in ("preview_hash","workspace_revision")})
        self.raw=next(n["raw_api"] for n in fixture_notices() if n["source_id"]=="11038")

    def retrieve(self):
        p=search_plan(self.engine)
        with patch('recall_guard.discovery.fetch',return_value=json.dumps([self.raw]).encode()) as http:
            result=discover(self.engine,{"request_id":"request-12345","plan_hash":p["plan_hash"]})
        return result,http

    def test_plan_discloses_only_public_terms_and_has_explicit_limits(self):
        p=search_plan(self.engine);encoded=json.dumps(p)
        for private in ("PRIVATE-ID","PRIVATE-SKU","PRIVATE-WAREHOUSE","erp-private"):
            self.assertNotIn(private,encoded)
        self.assertEqual({q["field"] for q in p["queries"]},{"RecallTitle","RecallDescription"})
        lots=[{"lot_id":str(i),"brand":"Brand"+str(i),"model":"M"+str(i)} for i in range(20)]
        limited=plan(lots)
        self.assertEqual(len(limited["queries"]),8);self.assertEqual(limited["omitted_queries"],32)
        self.assertFalse(limited["complete_recall_coverage"])

    def test_common_model_names_are_combined_with_brand_without_merging_other_brands(self):
        p=plan([{"lot_id":"one","brand":"Hatch","model":"Rest"},{"lot_id":"two","brand":"Other","model":"Rest"}])
        models=[q for q in p["queries"] if q["field"]=="RecallDescription"]
        self.assertEqual(len(models),2)
        self.assertEqual({q["filters"]["RecallTitle"] for q in models},{"Hatch","Other"})
        self.assertTrue(all(len(q["lot_ids"])==1 for q in models))

    def test_candidates_are_not_assessments_and_search_retry_has_no_network(self):
        record,http=self.retrieve();self.assertEqual(http.call_count,2)
        self.assertEqual(record["candidates"][0]["classification"],"CANDIDATE_ONLY")
        self.assertFalse(self.engine.store.scan("notice"));self.assertFalse(self.engine.store.scan("assessment"))
        before=copy.deepcopy(self.engine.store.records)
        with patch('recall_guard.discovery.fetch') as again:
            same=discover(self.engine,{"request_id":"request-12345","plan_hash":record["plan_hash"]})
            again.assert_not_called()
        self.assertEqual(record,same);self.assertEqual(self.engine.store.records,before)

    def test_zero_result_and_failed_query_never_imply_clearance(self):
        p=search_plan(self.engine)
        with patch('recall_guard.discovery.fetch',side_effect=[b'[]',OSError('offline')]):
            result=discover(self.engine,{"request_id":"request-no-results","plan_hash":p["plan_hash"]})
        self.assertEqual(result["status"],"COMPLETED_WITH_LIMITS")
        self.assertFalse(result["candidates"])
        self.assertEqual(self.engine.snapshot()["lots"][0]["status"],"PENDING_EVALUATION")

    def test_ignored_search_parameter_response_is_rejected(self):
        unrelated={**self.raw,"Title":"Unrelated","Description":"Nothing relevant"}
        with patch('recall_guard.discovery.fetch',return_value=json.dumps([unrelated]).encode()):
            result=discover(self.engine,{"request_id":"request-ignored-param","plan_hash":search_plan(self.engine)["plan_hash"]})
        self.assertFalse(result["candidates"])
        self.assertTrue(all(q["rejected_records"]==1 for q in result["query_results"]))

    def test_selection_is_bound_to_captured_candidates_and_inventory_versions(self):
        record,_=self.retrieve();note=next(n for n in fixture_notices() if n["source_id"]=="11038")
        with patch('recall_guard.discovery.fetch_notice',return_value=note) as fetch:
            result=select_candidates(self.engine,{"discovery_id":record["discovery_id"],"notice_ids":[note["notice_id"]]})
            self.assertEqual(fetch.call_args.args,(11038,))
        self.assertFalse(result["external_inventory_updated"])
        self.assertEqual(self.engine.store.scan("notice")[0]["inventory_candidate_ids"],[self.engine.store.scan("lot")[0]["lot_id"]])
        before=copy.deepcopy(self.engine.store.records)
        with patch('recall_guard.discovery.fetch_notice') as fetch:
            with self.assertRaises(ValueError):select_candidates(self.engine,{"discovery_id":record["discovery_id"],"notice_ids":["US-CPSC:999999"]})
            fetch.assert_not_called()
        self.assertEqual(before,self.engine.store.records)

    def test_inventory_change_during_evidence_fetch_rolls_back_selection(self):
        record,_=self.retrieve();lot=self.engine.store.scan("lot")[0]
        note=next(n for n in fixture_notices() if n["source_id"]=="11038")
        def changing(_):
            lot["version"]="changed";self.engine.store.put("lot",lot["lot_id"],lot);return note
        with patch('recall_guard.discovery.fetch_notice',side_effect=changing):
            with self.assertRaisesRegex(ValueError,"while obtaining"):
                select_candidates(self.engine,{"discovery_id":record["discovery_id"],"notice_ids":[note["notice_id"]]})
        self.assertFalse(self.engine.store.scan("notice"))

    def test_agent_context_excludes_business_references_and_run_is_advisory_version(self):
        record,_=self.retrieve();note=next(n for n in fixture_notices() if n["source_id"]=="11038")
        with patch('recall_guard.discovery.fetch_notice',return_value=note):
            select_candidates(self.engine,{"discovery_id":record["discovery_id"],"notice_ids":[note["notice_id"]]})
        prepared=self.engine.prepare_run(note["notice_id"])
        self.assertEqual(prepared["prompt_version"],PROMPT_VERSION)
        context=self.engine.tool(prepared["run_id"],"ReadContext")
        encoded=json.dumps(context)
        for value in ("PRIVATE-ID","PRIVATE-SKU","PRIVATE-WAREHOUSE","erp-private","received_at","quantity","import_id"):
            self.assertNotIn(value,encoded)
        self.assertIn("DR-HSH015",encoded)

    def test_candidates_export_before_ai_and_stale_identity_drops_them(self):
        from recall_guard.advisories import feed
        record,_=self.retrieve();document=feed(self.engine)
        self.assertEqual(document["items"][0]["advisory"],"CANDIDATES_FOUND")
        self.assertEqual(document["items"][0]["candidate_notices"][0]["classification"],"CANDIDATE_ONLY")
        self.assertFalse(document["items"][0]["assessments"])
        item=self.engine.store.scan("lot")[0];item["version"]="changed";self.engine.store.put("lot",item["lot_id"],item)
        self.assertEqual(feed(self.engine)["items"][0]["advisory"],"NOT_EVALUATED")

    def test_live_batches_are_bounded_and_advance_only_after_completed_validation(self):
        from recall_guard.inventory import import_snapshot,preview
        engine=Engine(MemoryStore());req={"source_system":"erp","items":[{"external_id":str(i),"sku":str(i),"name":"DREO heater","brand":"DREO","model":"DR-HSH015","quantity":1} for i in range(21)],"import_id":"batch-21"}
        p=preview(engine,req);import_snapshot(engine,req|{k:p[k] for k in ("preview_hash","workspace_revision")})
        note=next(n for n in fixture_notices() if n["source_id"]=="11038")
        engine.import_notices([note]);first=engine.prepare_run(note["notice_id"])
        self.assertEqual(len(first["lot_versions"]),20)
        self.assertEqual(engine.prepare_run(note["notice_id"])["reason"],"ALREADY_PENDING")
        engine.tool(first["run_id"],"ReadContext")
        # Test-only proposals do not impersonate an actual native agent execution.
        engine.submit(first["run_id"],[{"lot_id":key,"decision":"INSUFFICIENT_EVIDENCE","reason":"Manufacturing evidence is absent.","checks":[],"missing_fields":["manufactured_month"]} for key in first["lot_versions"]])
        engine.finish_run(first["run_id"])
        second=engine.prepare_run(note["notice_id"])
        self.assertEqual(len(second["lot_versions"]),1)
        self.assertFalse(set(first["lot_versions"]) & set(second["lot_versions"]))


if __name__=="__main__":unittest.main()
