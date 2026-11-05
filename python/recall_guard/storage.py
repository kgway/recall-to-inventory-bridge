# SPDX-License-Identifier: MPL-2.0
"""IRIS SQL-backed documents; an in-memory implementation is for unit tests only."""

from __future__ import annotations

import copy
import json
import threading
from contextlib import contextmanager


class MemoryStore:
    backend = "unit-test-memory"

    def __init__(self):
        self.records = {}
        self.mutex = threading.RLock()

    @contextmanager
    def atomic(self):
        with self.mutex:
            snapshot = copy.deepcopy(self.records)
            try:
                yield
            except Exception:
                self.records = snapshot
                raise

    def get(self, kind, key):
        return copy.deepcopy(self.records.get((kind, key)))

    def put(self, kind, key, value):
        self.records[kind, key] = copy.deepcopy(value)

    def scan(self, kind):
        return [copy.deepcopy(value) for (k, _), value in sorted(self.records.items()) if k == kind]


class IrisStore:
    backend = "intersystems-iris"

    def __init__(self):
        import iris
        self.iris = iris
        self.record = iris.cls("RecallGuard.Data.Record")
        self.depth = 0

    @contextmanager
    def atomic(self):
        # The demo is intentionally small: one shared mutex serializes recall
        # activation, inventory changes, review and final retailer transactions.
        # Inference and network access always happen outside this transaction.
        if self.depth:
            self.depth += 1
            try:
                yield
            finally:
                self.depth -= 1
            return
        if not self.iris.lock(["^RecallGuardMutex"], 10):
            raise TimeoutError("Recall-to-Inventory Bridge is busy; retry the request.")
        started = False
        try:
            self.iris.tstart()
            started = True
            self.depth = 1
            yield
            self.iris.tcommit()
        except Exception:
            if started:
                self.iris.trollbackone()
            raise
        finally:
            self.depth = 0
            self.iris.unlock(["^RecallGuardMutex"])

    def get(self, kind, key):
        raw = self.record.ReadJSON(kind + ":" + key)
        return json.loads(raw) if raw else None

    def put(self, kind, key, value):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > 1_000_000:
            raise ValueError("Document exceeds the demo storage limit.")
        self.iris.check_status(self.record.WriteJSON(kind + ":" + key, kind, text))

    def scan(self, kind):
        keys = json.loads(self.record.ListKeys(kind))
        return [self.get(kind, key[len(kind) + 1:]) for key in keys]
