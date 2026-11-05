# SPDX-License-Identifier: MPL-2.0
"""Install a pinned, clearly labelled validation demo into an empty store.

This never starts an agent. Original live-run metadata remains provenance;
new records describe only revalidation of those captured proposals.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from .engine import digest, now
from .policy import POLICY_VERSION

PACKAGE_SHA256 = "90aa482beb7342759d4afeb382e6e22639cd2c6fe24a50694c96614e6b4bce62"
MODE = "recorded-demo"
# Frozen inference provenance is independent of a newer live prompt. The
# validator policy and pinned original context still have to match exactly.
PROMPT_VERSION = "investigator-v6"


def read_package(root: Path):
    raw = (root / "fixtures" / "recorded-demo" / "package.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != PACKAGE_SHA256:
        raise ValueError("Recorded demo package differs from its pinned SHA-256.")
    return json.loads(raw)


def install(engine, package):
    if os.environ.get("AGENT_MODE", "disabled") != "disabled":
        raise ValueError("Set AGENT_MODE=disabled before loading the recorded demo.")
    if (package.get("schema") != 1 or package.get("prompt_version") != PROMPT_VERSION
            or package.get("policy_version") != POLICY_VERSION):
        raise ValueError("Recorded demo versions do not match this validation policy.")
    with engine.store.atomic():
        if any(engine.store.scan(kind) for kind in
               ("meta", "notice", "lot", "run", "assessment", "transaction", "review", "event")):
            raise ValueError("Recorded demo requires an empty instance. Existing data was preserved; use a separate instance.")
        engine.seed(package["notices"], package["lots"])
        notes = {n["notice_id"]: n for n in engine.store.scan("notice")}
        lots = {lot["lot_id"]: lot for lot in engine.store.scan("lot")}
        investigations = package["investigations"]
        if (len(investigations) != len(notes)
                or {item["original_run"]["notice_id"] for item in investigations} != set(notes)):
            raise ValueError("Recorded investigations do not cover the source set.")
        loaded = []
        for item in investigations:
            original = item["original_run"]
            note = notes[original["notice_id"]]
            if (original["mode"] != "live" or original["status"] != "COMPLETED"
                    or original["prompt_version"] != PROMPT_VERSION
                    or original["policy_version"] != POLICY_VERSION
                    or original["notice_version"] != note["version"]
                    or original["lot_versions"] != {key: lot["version"] for key, lot in lots.items()}):
                raise ValueError("Recorded source or inventory versions differ from the original live run.")
            # Match the v6 ReadContext projection, including its original lot order.
            context = {"notice": {key: note.get(key) for key in
                       ("notice_id", "agency", "jurisdiction", "title", "url", "version",
                        "target_component", "source_conflict", "snapshots")},
                       "lots": [{key: value for key, value in lots[lot_id].items()
                                 if key not in {"quantity", "received_at"}}
                                for lot_id in original["lot_versions"]]}
            calls = original["tool_calls"]
            if (len(calls) != 1 or calls[0]["name"] != "ReadContext"
                    or calls[0]["result_sha256"] != digest(context)):
                raise ValueError("Recorded context does not match the captured native tool hash.")
            proposals = item["proposals"]
            if (len(proposals) != len(lots)
                    or {p["lot_id"] for p in proposals} != set(lots)):
                raise ValueError("Recorded proposals must cover each synthetic lot exactly once.")
            run_id, instant = "replay-" + uuid.uuid4().hex, now()
            for proposal in proposals:
                lot = lots[proposal["lot_id"]]
                record = engine._validated_record(proposal, lot, note, run_id, mode=MODE)
                engine.store.put("assessment", digest([note["notice_id"], lot["lot_id"]]), record)
            run = {"run_id": run_id, "notice_id": note["notice_id"],
                   "notice_version": note["version"], "lot_versions": original["lot_versions"],
                   "created_at": instant, "finished_at": now(), "status": "COMPLETED", "mode": MODE,
                   "provider": "recorded", "model": original["model"],
                   "prompt_version": PROMPT_VERSION, "policy_version": POLICY_VERSION,
                   "tool_calls": [], "usage": None,
                   "validation": {"at": now(), "assessment_count": len(proposals), "revision": 1,
                                  "without_additional_inference": True},
                   "recorded_origin": {"run": original, "iris_version": item["iris_version"],
                                       "evidence_file": item["evidence_file"],
                                       "evidence_sha256": item["evidence_sha256"]}}
            engine.store.put("run", run_id, run)
            engine._event("recorded_proposals_revalidated", {"run_id": run_id,
                          "original_run_id": original["run_id"], "llm_called": False})
            loaded.append(run_id)
        meta = engine._meta()
        meta.update(experience_mode=MODE, recorded_package_id=package["package_id"],
                    recorded_package_sha256=PACKAGE_SHA256)
        engine.store.put("meta", "state", meta)
        return {"mode": MODE, "runs": loaded, "llm_called": False,
                "message": "Saved genuine proposals revalidated. Retailer requests use this real IRIS instance and synthetic stock."}
