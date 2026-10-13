"""Offline S0 Apprise result-contract checks. No real network."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from scripts.s0_apprise_smoke import result_summary


class FakeService:
    def __init__(self, ok: bool):
        self.ok = ok

    def __bool__(self):
        return self.ok


class FakeResult:
    def __init__(self, ok: bool, services: list[FakeService]):
        self.ok = ok
        self.services = services
        self.status = SimpleNamespace(name="SUCCESS" if ok else "FAIL")

    def __bool__(self):
        return self.ok

    def __iter__(self):
        return iter(self.services)


class AppriseResultContractTests(unittest.TestCase):
    def test_per_service_results_preserved(self):
        result = result_summary(FakeResult(False, [FakeService(True), FakeService(False)]))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["services"], 2)
        self.assertEqual(result["service_results"], [True, False])

    def test_result_object_not_identity_true(self):
        fake = FakeResult(True, [FakeService(True)])
        self.assertIsNot(fake, True)
        self.assertTrue(result_summary(fake)["ok"])
        self.assertEqual(result_summary(fake)["status"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
