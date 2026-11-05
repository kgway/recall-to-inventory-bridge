# SPDX-License-Identifier: MPL-2.0
"""Keep the actual 109 citation failure conservative, without another model call."""
import copy
import json
import unittest
from pathlib import Path

from recall_guard.engine import Engine
from recall_guard.recorded_demo import read_package
from recall_guard.storage import MemoryStore

ROOT = Path(__file__).resolve().parents[1]


class LiveCitationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(MemoryStore())
        package = read_package(ROOT)
        self.engine.seed(package["notices"], package["lots"])
        proof = json.loads((ROOT / "research/evidence/iris-build109-native.json").read_text())
        self.hatch = next(r for r in proof["records"] if r["notice_id"] == "US-CPSC:9996")
        self.note = self.engine.store.get("notice", "US-CPSC:9996")

    def test_observed_brand_value_without_supporting_quote_stays_on_review(self):
        extra_reviews = {c["lot_id"] for c in self.hatch["comparisons"] if not c["passed"]}
        blocked = [a for a in self.hatch["assessments"] if a["lot_id"] in extra_reviews
                   and a["proposed_assessment"]["decision"] == "NO_MATCH_FOR_NOTICE"
                   and a["decision"] == "INSUFFICIENT_EVIDENCE"]
        self.assertEqual(len(blocked), 9)
        for previous in blocked:
            result = self.engine._validated_record(previous["proposed_assessment"],
                self.engine.store.get("lot", previous["lot_id"]), self.note, "unit-test-only")
            self.assertEqual(result["decision"], "INSUFFICIENT_EVIDENCE")
            self.assertEqual(result["reason"], "Identifier is absent from the cited evidence.")

    def test_a_shortened_related_brand_cannot_be_treated_as_unrelated(self):
        # A better quote alone must not turn Hatch versus Hatch Baby into a
        # definite brand exclusion for the related adapter lot.
        proposal = copy.deepcopy(next(a["proposed_assessment"] for a in self.hatch["assessments"]
                                     if a["lot_id"] == "HATCH-generation-2"))
        source = next(s for s in self.note["snapshots"] if s["kind"] == "cpsc-api")
        proposal["checks"][0]["evidence"] = {"snapshot_id": source["id"], "quote": self.note["title"]}
        self.assertIn(self.note["title"], source["text"])
        result = self.engine._validated_record(proposal, self.engine.store.get("lot", "HATCH-generation-2"),
                                               self.note, "unit-test-only")
        self.assertEqual(result["decision"], "INSUFFICIENT_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
