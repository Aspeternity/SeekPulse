"""Offline S0 Apprise result-contract checks. No real network."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from scripts.s0_apprise_smoke import classify_case, result_summary


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


class ClassificationTests(unittest.TestCase):
    def test_success_requires_exactly_one_post_and_one_successful_service(self):
        self.assertTrue(classify_case(True, True, 1, {
            "ok": True, "services": 1, "status": "SUCCESS",
        }))
        self.assertFalse(classify_case(True, True, 0, {
            "ok": True, "services": 1, "status": "SUCCESS",
        }))
        self.assertFalse(classify_case(True, False, 1, {
            "ok": True, "services": 1, "status": "SUCCESS",
        }))

    def test_negative_http_cases_require_failure_result(self):
        self.assertTrue(classify_case(False, True, 1, {
            "ok": False, "services": 1, "status": "FAILURE",
        }))
        self.assertFalse(classify_case(False, True, 1, {
            "ok": True, "services": 1, "status": "SUCCESS",
        }))
        self.assertFalse(classify_case(False, True, 2, {
            "ok": False, "services": 1, "status": "FAILURE",
        }))

    def test_local_hard_timeout_is_explicit_not_reported_as_success(self):
        self.assertTrue(classify_case(False, True, 1, {
            "ok": False, "services": 0, "status": "LOCAL_DEADLINE_TIMEOUT",
        }))
        self.assertFalse(classify_case(True, True, 1, {
            "ok": False, "services": 0, "status": "LOCAL_DEADLINE_TIMEOUT",
        }))

    def test_no_unknown_result_without_services_can_pass(self):
        self.assertFalse(classify_case(False, True, 1, {
            "ok": False, "services": 0, "status": "CONFIG_REJECTED",
        }))


if __name__ == "__main__":
    unittest.main()
