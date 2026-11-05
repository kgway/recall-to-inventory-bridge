# SPDX-License-Identifier: MPL-2.0
"""CSV/JSON inventory snapshots. No connection or write credential to an ERP/WMS."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re

from .engine import digest, now, required_text
from .policy import month

MODE = "inventory-bridge"
MAX_ROWS = 100
MAX_BYTES = 100_000
ALIASES = {
    "external_id": ("external_id", "record_id", "inventory_id"),
    "sku": ("sku", "item_code", "product_code"),
    "name": ("name", "product_name", "description"),
    "quantity": ("quantity", "qty", "on_hand", "qty_on_hand"),
    "brand": ("brand",), "model": ("model", "model_number"),
    "manufacturer": ("manufacturer",), "product_type": ("product_type", "category"),
    "upc": ("upc", "gtin"), "location": ("location", "warehouse", "warehouse_code"),
    "lot_number": ("lot_number", "lot", "batch_number"),
    "manufactured_month": ("manufactured_month", "manufacture_month"),
    "adapter_model": ("adapter_model",), "generation": ("generation",),
    "source_updated_at": ("source_updated_at", "updated_at"),
}
IDENTITY = ("sku", "name", "brand", "model", "manufacturer", "product_type", "upc",
            "lot_number", "manufactured_month", "adapter_model", "generation")


class InventoryConflict(ValueError):
    """The source revision or idempotency key conflicts with an existing capture."""


def text(value, field, required=False):
    if value is None or value == "":
        if required:
            raise ValueError("Required field is missing: " + field)
        return None
    if not isinstance(value, str) or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError(field + " must be text without control characters; preserve identifier leading zeros.")
    return required_text(value, field, 300 if field == "name" else 160)


def parse_inventory(request):
    if "content" in request and "items" in request:
        raise ValueError("Supply file content or native JSON items, not both.")
    if "content" not in request and "items" in request:
        request = {**request, "format": "json", "content": json.dumps({"items": request["items"]}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))}
    source = text(request.get("source_system"), "source_system", True)
    classification = request.get("data_classification", "user-provided")
    if classification not in {"user-provided", "synthetic-example"}:
        raise ValueError("Choose user-provided or synthetic-example data classification.")
    content = request.get("content")
    if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Provide a nonempty UTF-8 inventory file up to 100,000 bytes.")
    content = content.lstrip("\ufeff")
    format_ = request.get("format")
    if format_ == "csv":
        delimiter = request.get("delimiter", ",")
        if delimiter not in (",", ";", "\t"):
            raise ValueError("Choose comma, semicolon or tab as the delimiter.")
        reader = csv.reader(io.StringIO(content, newline=""), delimiter=delimiter, strict=True)
        try:
            headers = next(reader)
            records = []
            for line in reader:
                if not any(v.strip() for v in line):
                    continue
                if len(line) != len(headers):
                    raise ValueError("CSV row has a different number of cells than the header.")
                records.append(dict(zip(headers, line)))
                if len(records) > MAX_ROWS:
                    raise ValueError("Import at most 100 rows per workspace.")
        except (csv.Error, StopIteration) as exc:
            raise ValueError("Invalid CSV file or missing header.") from exc
    elif format_ == "json":
        try:
            records = json.loads(content)
        except ValueError as exc:
            raise ValueError("Invalid inventory JSON.") from exc
        if isinstance(records, dict):
            records = records.get("items")
        if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
            raise ValueError("JSON must be an object array or an object with an items array.")
        headers = list(dict.fromkeys(k for row in records for k in row))
    else:
        raise ValueError("Choose csv or json.")
    if not 1 <= len(records) <= MAX_ROWS or not headers or len(headers) > 60:
        raise ValueError("Provide 1–100 inventory rows with at most 60 columns.")
    normalized = [h.strip().lower() for h in headers]
    if len(set(normalized)) != len(headers) or any(not h for h in normalized):
        raise ValueError("Duplicate or empty column names are not accepted.")
    mapping = request.get("mapping", {})
    if not isinstance(mapping, dict) or set(mapping) - set(ALIASES):
        raise ValueError("Mapping keys must be documented inventory fields.")
    resolved = {}
    for field, aliases in ALIASES.items():
        if field in mapping:
            column = mapping[field]
            if not isinstance(column, str) or column not in headers:
                raise ValueError("Mapped column does not exist: " + field)
            resolved[field] = column
        else:
            matches = [h for h in headers if h.strip().lower() in aliases]
            if len(matches) > 1:
                raise ValueError("Ambiguous columns; provide an explicit mapping for " + field)
            if matches:
                resolved[field] = matches[0]
    if len(set(resolved.values())) != len(resolved):
        raise ValueError("Map each input column to only one field.")
    if not {"sku", "name", "quantity"} <= set(resolved):
        raise ValueError("Map sku, name and quantity columns before import.")
    items, errors, seen = [], [], set()
    for index, record in enumerate(records, 1):
        try:
            row = {field: record.get(column) for field, column in resolved.items()}
            item = {field: text(row.get(field), field, field in {"sku", "name"})
                    for field in ALIASES if field != "quantity"}
            quantity = row.get("quantity")
            if isinstance(quantity, str) and re.fullmatch(r"\d{1,10}", quantity.strip()):
                quantity = int(quantity)
            if type(quantity) is not int or not 0 <= quantity <= 1_000_000_000:
                raise ValueError("quantity must be a nonnegative whole-unit count.")
            if item["manufactured_month"] and not month(item["manufactured_month"]):
                raise ValueError("manufactured_month must be YYYY-MM or empty.")
            if item["upc"] and not re.fullmatch(r"\d{8}|\d{12,14}", item["upc"]):
                raise ValueError("upc must contain 8, 12, 13 or 14 digits, as text.")
            if item["source_updated_at"]:
                from datetime import datetime
                instant = datetime.fromisoformat(item["source_updated_at"].replace("Z", "+00:00"))
                if instant.tzinfo is None:
                    raise ValueError("source_updated_at needs an explicit timezone.")
            external_id = item["external_id"] or "derived:" + digest([item["sku"], item["lot_number"], item["location"]])[:32]
            key = "inventory-" + digest([source, external_id])[:32]
            if key in seen:
                raise ValueError("Duplicate source record; distinguish lots/locations with external_id or lot_number.")
            seen.add(key)
            items.append({**item, "external_id": external_id, "source_system": source,
                          "lot_id": key, "quantity": quantity, "synthetic": classification == "synthetic-example",
                          "data_classification": classification, "read_only_snapshot": True})
        except (ValueError, TypeError) as exc:
            errors.append({"row": index, "error": str(exc)})
    return {"schema": "inventory-snapshot-v1", "source_system": source, "rows": items,
            "source_document_sha256": hashlib.sha256(request["content"].encode("utf-8")).hexdigest(),
            "row_count": len(records), "mapping": resolved,
            "ignored_columns": [h for h in headers if h not in resolved.values()], "errors": errors,
            "valid": not errors, "authority": "ADVISORY_ONLY"}


def revision(engine):
    return digest({x["lot_id"]: x.get("source_row_hash", x["version"]) for x in engine.store.scan("lot")})


def preview(engine, request):
    parsed = parse_inventory(request)
    return {k: v for k, v in parsed.items() if k != "rows"} | {"preview": parsed["rows"][:5],
            "preview_hash": digest(parsed), "workspace_revision": revision(engine), "imported": False}


def import_snapshot(engine, request):
    parsed = parse_inventory(request)
    if not parsed["valid"]:
        raise ValueError("Inventory was not imported. Fix row errors shown by the preview.")
    fingerprint = digest(parsed)
    if request.get("preview_hash") != fingerprint:
        raise ValueError("Preview this exact file and mapping before importing.")
    import_id = required_text(request.get("import_id"), "import_id", 100)
    key = digest([parsed["source_system"], import_id])
    with engine.store.atomic():
        meta = engine._meta()
        if meta.get("experience_mode") != MODE and any(engine.store.scan(k) for k in ("notice", "lot", "run")):
            raise ValueError("Use a separate empty instance for inventory snapshots; demo data is preserved.")
        previous_batch = engine.store.get("inventory_import", key)
        if previous_batch:
            if previous_batch["fingerprint"] != fingerprint:
                raise InventoryConflict("import_id was already used with different content.")
            return {**previous_batch, "replayed": True}
        if request.get("workspace_revision") != revision(engine):
            raise InventoryConflict("Inventory changed after preview. Preview again before importing.")
        current = {x["lot_id"]: x for x in engine.store.scan("lot")}
        if len(set(current) | {x["lot_id"] for x in parsed["rows"]}) > MAX_ROWS:
            raise ValueError("This bounded workspace supports at most 100 inventory records.")
        changed, captured_at = [], now()
        for item in parsed["rows"]:
            previous = current.get(item["lot_id"])
            if previous and previous.get("source_updated_at"):
                from datetime import datetime
                parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
                if not item.get("source_updated_at") or parse(item["source_updated_at"]) < parse(previous["source_updated_at"]):
                    raise InventoryConflict("Source update is older than the stored snapshot, or its timestamp is missing.")
                if (parse(item["source_updated_at"]) == parse(previous["source_updated_at"])
                        and digest(item) != previous.get("source_row_hash")):
                    raise InventoryConflict("Same source timestamp has conflicting content.")
            version = digest({k: item[k] for k in (*IDENTITY, "data_classification")})
            if not previous or previous["version"] != version:
                changed.append(item["lot_id"])
            engine.store.put("lot", item["lot_id"], {**item, "version": version, "received_at": captured_at,
                             "source_row_hash": digest(item), "import_id": import_id})
        meta.update(experience_mode=MODE, scope="inventory-driven-cpsc-candidates", initialized=True,
                    epoch=meta["epoch"] + bool(changed), authority="ADVISORY_ONLY")
        engine.store.put("meta", "state", meta)
        batch = {"import_id": import_id, "source_system": parsed["source_system"], "fingerprint": fingerprint,
                 "source_document_sha256": parsed["source_document_sha256"],
                 "rows": len(parsed["rows"]), "identity_changed": changed, "at": captured_at,
                 "semantics": "UPSERT_SNAPSHOT", "omitted_records_deleted": False,
                 "external_inventory_updated": False, "replayed": False}
        engine.store.put("inventory_import", key, batch)
        from .monitor import inventory_updated
        inventory_updated(engine)
        engine._event("inventory_snapshot_imported", {"import_id": import_id, "rows": batch["rows"]})
        return batch
