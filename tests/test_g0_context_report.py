"""Offline governance tests; these never access the user's GitHub account."""

from __future__ import annotations

import unittest

from scripts.context_report import (
    classify_checks,
    collect_report,
    extract_repo_from_remote,
    render_markdown,
)


class RemoteTests(unittest.TestCase):
    def test_remote_formats(self) -> None:
        self.assertEqual(
            extract_repo_from_remote("git@github.com:Aspeternity/SeekPulse.git"),
            "Aspeternity/SeekPulse",
        )
        self.assertEqual(
            extract_repo_from_remote("https://github.com/Aspeternity/SeekPulse.git"),
            "Aspeternity/SeekPulse",
        )
        self.assertIsNone(extract_repo_from_remote("https://example.com/owner/repo"))

    def test_offline_never_claims_remote_green(self) -> None:
        report = collect_report(offline=True)
        self.assertEqual(report["github"]["verification"], "UNKNOWN")
        self.assertIn("stage G0", report["recorded_approval"]["summary"])
        content = render_markdown(report)
        self.assertIn("UNKNOWN", content)
        self.assertIn("不得自动开发", content)

    def test_no_check_runs_is_unknown(self) -> None:
        value = classify_checks({"total_count": 0, "check_runs": []}, {"statuses": []})
        self.assertEqual(value["state"], "UNKNOWN")

    def test_pending_and_failure_override_passes(self) -> None:
        good = {"name": "unit", "status": "completed", "conclusion": "success"}
        in_progress = {"name": "build", "status": "in_progress", "conclusion": None}
        self.assertEqual(
            classify_checks({"total_count": 2, "check_runs": [good, in_progress]}, {"statuses": []})["state"],
            "PENDING",
        )
        fail = {"name": "lint", "status": "completed", "conclusion": "failure"}
        self.assertEqual(
            classify_checks({"total_count": 2, "check_runs": [good, fail]}, {"statuses": []})["state"],
            "FAILED",
        )

    def test_paginated_checks_are_unknown(self) -> None:
        value = classify_checks({"total_count": 2, "check_runs": [{"status": "completed", "conclusion": "success"}]}, {"statuses": []})
        self.assertEqual(value["state"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
