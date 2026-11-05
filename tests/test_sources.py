# SPDX-License-Identifier: MPL-2.0
import json
import unittest
from pathlib import Path

from recall_guard.runtime import fixture_notices
from recall_guard.sources import RecallPageText, normalize_cpsc, validate_url


class SourceTest(unittest.TestCase):
    def test_real_api_fixture_is_not_misrepresented_as_structured_model_data(self):
        note = next(n for n in fixture_notices() if n["source_id"] == "11038")
        self.assertIn("DR-HSH015", note["snapshots"][0]["text"])
        self.assertEqual(note["raw_api"]["Products"][0]["Model"], "")
        self.assertEqual(note["raw_api"]["ProductUPCs"], [])

    def test_hatch_is_a_component_recall_with_unresolved_source_difference(self):
        note = next(n for n in fixture_notices() if n["source_id"] == "9996")
        self.assertEqual(note["target_component"], "power_adapter")
        self.assertTrue(note["source_conflict"])

    def test_parse_detail_stops_before_other_recalls_and_discards_scripts(self):
        parser = RecallPageText()
        parser.feed("<nav>menu</nav><h1>Notice</h1><p>Only these units.</p><script>evil()</script><h2>Related Recalls</h2><p>Unrelated scope</p>")
        text = parser.text()
        self.assertIn("Only these units.", text)
        self.assertNotIn("Unrelated", text)
        self.assertNotIn("evil", text)
        self.assertNotIn("menu", text)

    def test_source_allowlist_rejects_other_hosts_ports_and_credentials(self):
        for url in ("http://www.cpsc.gov/Recalls/a", "https://evil.test/Recalls/a", "https://www.cpsc.gov:8443/Recalls/a", "https://user:secret@www.cpsc.gov/Recalls/a", "https://www.cpsc.gov/admin"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_url(url)
        validate_url("https://www.saferproducts.gov/RestWebServices/Recall?format=json&RecallID=9996")
        validate_url("https://cpsc.gov/Recalls/2027/example")

    def test_every_inventory_lot_is_explicitly_synthetic_and_has_no_real_serial(self):
        records = json.loads((Path(__file__).resolve().parents[1] / "fixtures/inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(len(records), 12)
        self.assertEqual(len({r["lot_id"] for r in records}), 12)
        self.assertTrue(all(r["synthetic"] is True and "serial_number" not in r for r in records))


if __name__ == "__main__":
    unittest.main()
