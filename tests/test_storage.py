# SPDX-License-Identifier: MPL-2.0
"""Fault injection for transaction cleanup; not an IRIS runtime test."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from recall_guard.storage import IrisStore


class TransactionCleanupTest(unittest.TestCase):
    def setUp(self):
        self.store = IrisStore.__new__(IrisStore)
        self.store.depth = 0
        self.store.iris = SimpleNamespace(lock=Mock(return_value=True), unlock=Mock(),
                                          tstart=Mock(), tcommit=Mock(), trollbackone=Mock())

    def test_failed_transaction_start_releases_the_acquired_mutex(self):
        self.store.iris.tstart.side_effect = RuntimeError("Cannot start a transaction.")
        with self.assertRaisesRegex(RuntimeError, "Cannot start"):
            with self.store.atomic():
                self.fail("A failed transaction must not enter the protected operation.")
        self.store.iris.unlock.assert_called_once_with(["^RecallGuardMutex"])
        self.store.iris.trollbackone.assert_not_called()
        self.store.iris.tcommit.assert_not_called()
        self.assertEqual(self.store.depth, 0)

    def test_failed_nested_operation_rolls_back_and_releases_once(self):
        with self.assertRaisesRegex(ValueError, "Invalid inventory"):
            with self.store.atomic(), self.store.atomic():
                raise ValueError("Invalid inventory.")
        self.store.iris.tstart.assert_called_once()
        self.store.iris.trollbackone.assert_called_once()
        self.store.iris.unlock.assert_called_once()
        self.store.iris.tcommit.assert_not_called()
        self.assertEqual(self.store.depth, 0)

    def test_lock_timeout_does_not_release_an_unowned_mutex(self):
        self.store.iris.lock.return_value = False
        with self.assertRaises(TimeoutError):
            with self.store.atomic():
                self.fail("An unlocked operation must not start.")
        self.store.iris.unlock.assert_not_called()
        self.store.iris.tstart.assert_not_called()


if __name__ == "__main__":
    unittest.main()
