# SPDX-License-Identifier: MPL-2.0
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from recall_guard.engine import Engine
from recall_guard.recorded_demo import install, read_package
from recall_guard.storage import MemoryStore
from recall_guard import runtime

ROOT = Path(__file__).resolve().parents[1]


class RecordedDemoTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.engine = Engine(self.store)
        self.package = read_package(ROOT)
        self.mode = patch.dict("os.environ", {"AGENT_MODE": "disabled"}, clear=True)
        self.mode.start()
        self.addCleanup(self.mode.stop)

    def test_revalidated_decisions_match_independent_labels_and_keep_provenance(self):
        result = install(self.engine, self.package)
        self.assertFalse(result["llm_called"])
        state = self.engine.snapshot()
        expected = json.loads((ROOT / "fixtures/expected_decisions.json").read_text())
        observed = {(a["lot_id"], a["notice_id"]): a["decision"] for a in state["assessments"]}
        for case in expected["cases"]:
            for notice, decision in zip(expected["notice_order"], case["decisions"], strict=True):
                self.assertEqual(observed[case["lot_id"], notice], decision)
        self.assertEqual(len(observed), 36)
        self.assertEqual({run["mode"] for run in state["runs"]}, {"recorded-demo"})
        self.assertTrue(all(not run["tool_calls"] and run["usage"] is None for run in state["runs"]))
        self.assertTrue(all(run["recorded_origin"]["run"]["mode"] == "live" for run in state["runs"]))
        self.assertFalse(any(event["kind"] == "agent_started" for event in state["events"]))

    def test_live_configuration_cannot_load_a_recorded_package(self):
        with patch.dict("os.environ", {"AGENT_MODE": "live"}):
            with self.assertRaisesRegex(ValueError, "AGENT_MODE=disabled"):
                install(self.engine, self.package)
        self.assertFalse(self.store.records)

    def test_existing_data_and_repeat_load_cannot_replenish_stock(self):
        install(self.engine, self.package)
        request = {"kind": "sale", "idempotency_key": "recorded-sale",
                   "lines": [{"lot_id": "DREO-before", "quantity": 1}]}
        self.assertTrue(self.engine.transact(request)["allowed"])
        self.assertTrue(self.engine.transact(request)["replayed"])
        before = copy.deepcopy(self.store.records)
        with self.assertRaisesRegex(ValueError, "empty instance"):
            install(self.engine, self.package)
        self.assertEqual(before, self.store.records)
        self.assertEqual(self.store.get("lot", "DREO-before")["quantity"], 4)
        self.assertFalse(self.engine.transact({**request, "idempotency_key": "held",
            "lines": [{"lot_id": "DREO-start", "quantity": 1}]})["allowed"])

    def test_failed_late_context_check_rolls_back_all_imports(self):
        self.package["investigations"][-1]["original_run"]["tool_calls"][0]["result_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "native tool hash"):
            install(self.engine, self.package)
        self.assertFalse(self.store.records)

    def test_incomplete_proposals_and_policy_drift_roll_back(self):
        self.package["investigations"][-1]["proposals"].pop()
        with self.assertRaisesRegex(ValueError, "exactly once"):
            install(self.engine, self.package)
        self.assertFalse(self.store.records)
        self.package["policy_version"] = "future-policy"
        with self.assertRaisesRegex(ValueError, "versions"):
            install(self.engine, self.package)

    def test_pinned_file_rejects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fixtures/recorded-demo/package.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(self.package) + " ", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                read_package(Path(folder))

    def test_recorded_instance_cannot_start_live_runs_or_fetch_sources(self):
        install(self.engine, self.package)
        with self.assertRaisesRegex(ValueError, "separate empty instance"):
            self.engine.prepare_run("US-CPSC:11038")
        before = copy.deepcopy(self.store.records)
        with patch.object(runtime, "IrisStore", return_value=self.store), patch.object(runtime, "fetch_curated") as fetch:
            with self.assertRaisesRegex(ValueError, "no CPSC request"):
                runtime.fetch_sources()
            with self.assertRaisesRegex(ValueError, "evidence is fixed"):
                runtime.dispatch("import_notices", {"notices": []})
            runtime.dispatch("refresh_failed", {"error": "rejected refresh"})
            fetch.assert_not_called()
        self.assertEqual(before, self.store.records)


if __name__ == "__main__":
    unittest.main()
