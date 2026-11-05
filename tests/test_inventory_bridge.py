# SPDX-License-Identifier: MPL-2.0
import copy
import csv
import io
import json
import unittest

from recall_guard.engine import Engine
from recall_guard.inventory import InventoryConflict, import_snapshot, parse_inventory, preview
from recall_guard.advisories import export, feed
from recall_guard.storage import MemoryStore


def request(rows=None, **kwargs):
    return {"source_system": "warehouse-system", "format": "json", "import_id": "capture-001",
            "content": json.dumps(rows or [{"external_id": "0001", "sku": "001234", "name": "DREO heater",
                "brand": "DREO", "model": "DR-HSH015", "quantity": 12, "manufactured_month": "2025-04"}]), **kwargs}


def capture(engine, req):
    checked = preview(engine, req)
    return import_snapshot(engine, req | {k: checked[k] for k in ("preview_hash", "workspace_revision")})


class InventoryBridgeTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.engine = Engine(self.store)

    def test_csv_aliases_leading_zeros_and_explicit_mapping(self):
        req = request(format="csv", content='Record,Product Code,Description,On Hand,warehouse\n0007,00123,"Heater, portable",12,EAST\n',
                      mapping={"external_id": "Record", "sku": "Product Code", "name": "Description", "quantity": "On Hand"})
        p = preview(self.engine, req)
        self.assertFalse(self.store.records)
        self.assertTrue(p["valid"])
        capture(self.engine, req)
        row = self.store.scan("lot")[0]
        self.assertEqual((row["external_id"], row["sku"], row["name"], row["quantity"]), ("0007", "00123", "Heater, portable", 12))
        self.assertTrue(row["read_only_snapshot"])

    def test_bom_semicolon_and_json_envelope(self):
        p = parse_inventory(request(format="csv", delimiter=";", content='\ufeffsku;name;quantity\n0007;Heater;3\n'))
        self.assertEqual(p["rows"][0]["sku"], "0007")
        r = request();r["content"] = json.dumps({"items": json.loads(r["content"])})
        self.assertTrue(parse_inventory(r)["valid"])

    def test_native_json_contract_and_data_classification_change(self):
        native={"source_system":"erp","items":[{"sku":"0001","name":"Heater","quantity":5}],"import_id":"native-001"}
        capture(self.engine,native);first=self.store.scan("lot")[0]
        capture(self.engine,native|{"import_id":"native-002","data_classification":"synthetic-example"})
        second=self.store.scan("lot")[0]
        self.assertNotEqual(first["version"],second["version"])
        with self.assertRaises(ValueError):parse_inventory(native|{"content":"[]"})

    def test_invalid_row_prevents_entire_import_and_reports_row(self):
        req = request(rows=[{"sku": "A", "name": "Valid", "quantity": 2}, {"sku": "B", "name": "Invalid", "quantity": -1}])
        p = preview(self.engine, req)
        self.assertFalse(p["valid"])
        self.assertEqual(p["errors"][0]["row"], 2)
        with self.assertRaises(ValueError):capture(self.engine, req)
        self.assertFalse(self.store.records)

    def test_no_silent_numeric_identifier_conversion_or_ambiguous_headers(self):
        req = request(rows=[{"sku": 123, "name": "Heater", "quantity": 1}])
        self.assertFalse(parse_inventory(req)["valid"])
        for content in ('sku,sku,name,quantity\na,b,N,1', 'sku,item_code,name,quantity\na,b,N,1'):
            with self.assertRaises(ValueError):parse_inventory(request(format="csv", content=content))

    def test_distinct_lots_locations_and_source_systems_do_not_collide(self):
        rows=[{"sku": "A", "name": "Heater", "quantity": 3, "lot_number": "L1", "location": "EAST"},
              {"sku": "A", "name": "Heater", "quantity": 4, "lot_number": "L1", "location": "WEST"}]
        capture(self.engine, request(rows=rows))
        capture(self.engine, request(rows=rows, source_system="another-system"))
        self.assertEqual(len(self.store.scan("lot")), 4)
        with self.assertRaises(ValueError):
            capture(self.engine, request(rows=[rows[0], rows[0]], import_id="duplicate"))

    def test_idempotent_retry_and_conflicting_reuse_do_not_write(self):
        req=request();p=preview(self.engine, req);payload=req | {k:p[k] for k in ("preview_hash","workspace_revision")}
        first=import_snapshot(self.engine,payload);before=copy.deepcopy(self.store.records)
        self.assertTrue(import_snapshot(self.engine,payload)["replayed"])
        self.assertEqual(self.store.records,before)
        changed=request(rows=[{"external_id":"0001","sku":"NEW","name":"New","quantity":3}])
        with self.assertRaises(InventoryConflict):capture(self.engine,changed)
        self.assertEqual(self.store.records,before)
        self.assertFalse(first["external_inventory_updated"])

    def test_file_change_and_concurrent_import_require_new_preview(self):
        req=request();p=preview(self.engine,req)
        with self.assertRaisesRegex(ValueError,"Preview"):
            import_snapshot(self.engine,req|{"preview_hash":"changed","workspace_revision":p["workspace_revision"]})
        capture(self.engine,request(source_system="other"))
        with self.assertRaises(InventoryConflict):import_snapshot(self.engine,req|{k:p[k] for k in ("preview_hash","workspace_revision")})

    def test_reported_quantity_updates_but_omissions_never_delete_and_identity_is_versioned(self):
        capture(self.engine,request())
        original=self.store.scan("lot")[0]
        row=json.loads(request()["content"])[0];row["quantity"]=9
        capture(self.engine,request(rows=[row],import_id="capture-002"))
        updated=self.store.scan("lot")[0]
        self.assertEqual(updated["quantity"],9);self.assertEqual(updated["version"],original["version"])
        row["model"]="CHANGED";capture(self.engine,request(rows=[row],import_id="capture-003"))
        self.assertNotEqual(self.store.scan("lot")[0]["version"],original["version"])
        capture(self.engine,request(rows=[{"sku":"B","name":"Other","quantity":1}],import_id="capture-004"))
        self.assertEqual(len(self.store.scan("lot")),2)

    def test_older_source_and_same_timestamp_conflict_roll_back(self):
        row=json.loads(request()["content"])[0];row["source_updated_at"]="2026-11-04T08:00:00Z"
        capture(self.engine,request(rows=[row]));before=copy.deepcopy(self.store.records)
        for timestamp in ("2026-11-04T07:00:00Z","2026-11-04T08:00:00Z",None):
            with self.subTest(timestamp=timestamp):
                row.update(quantity=2,source_updated_at=timestamp)
                with self.assertRaises(InventoryConflict):capture(self.engine,request(rows=[row],import_id="older"))
                self.assertEqual(self.store.records,before)

    def test_real_and_example_snapshots_cannot_invoke_simulator_even_when_eligible(self):
        for classification in ("user-provided","synthetic-example"):
            engine=Engine(MemoryStore());capture(engine,request(data_classification=classification))
            before=copy.deepcopy(engine.store.records)
            lot=engine.store.scan("lot")[0]
            with self.assertRaisesRegex(ValueError,"advisory-only"):
                engine.transact({"kind":"sale","idempotency_key":"try-sale","lines":[{"lot_id":lot["lot_id"],"quantity":1}]})
            self.assertEqual(engine.store.records,before)
            self.assertEqual(engine.snapshot()["lots"][0]["status"],"PENDING_EVALUATION")

    def test_demo_and_imported_workspace_cannot_be_mixed(self):
        capture(self.engine,request());before=copy.deepcopy(self.store.records)
        with self.assertRaises(ValueError):self.engine.seed([],[])
        with self.assertRaises(ValueError):self.engine.import_lots([])
        self.assertEqual(self.store.records,before)

    def test_exports_are_advisory_only_unassessed_and_spreadsheet_safe(self):
        capture(self.engine,request(rows=[{"sku":"=HYPERLINK(\"evil\")","name":"Heater","quantity":2}]))
        before=copy.deepcopy(self.store.records);document=feed(self.engine)
        self.assertEqual(document["authority"],"ADVISORY_ONLY")
        self.assertFalse(document["scope"]["complete_recall_coverage"])
        self.assertEqual(document["items"][0]["advisory"],"NOT_EVALUATED")
        rows=list(csv.DictReader(io.StringIO(export(self.engine,"csv")["content"])))
        self.assertTrue(rows[0]["sku"].startswith("'="))
        self.assertEqual(rows[0]["external_inventory_updated"],"false")
        self.assertEqual(rows[0]["decision"],"NOT_EVALUATED")
        self.assertEqual(self.store.records,before)

    def test_import_and_document_size_bounds_fail_without_partial_writes(self):
        with self.assertRaises(ValueError):capture(self.engine,request(rows=[{"sku":str(i),"name":"Heater","quantity":1} for i in range(101)]))
        with self.assertRaises(ValueError):parse_inventory(request(content="x"*100001))
        self.assertFalse(self.store.records)


if __name__=="__main__":unittest.main()
