"""Issue seed and idempotency marker regression tests."""

from __future__ import annotations

import unittest

from scripts.bootstrap_issues import bootstrap, load_seed, recorded_keys, task_body


class BootstrapTests(unittest.TestCase):
    def test_seed_unique_and_s0_blocked(self) -> None:
        tasks = load_seed()
        self.assertGreaterEqual(len(tasks), 10)
        self.assertEqual(len({task["key"] for task in tasks}), len(tasks))
        for task in tasks:
            if not task["key"].startswith("G0-"):
                self.assertIn("status:blocked", task["labels"])
                self.assertIn("未授权", task["body"])

    def test_round_trip_marker(self) -> None:
        task = load_seed()[0]
        self.assertEqual(recorded_keys([{"body": task_body(task)}]), {task["key"]})

    def test_existing_task_is_not_recreated(self) -> None:
        tasks = load_seed()[:2]

        class FakeClient:
            def __init__(self):
                self.writes = []

            def get_all_issues(self):
                return [{"body": task_body(tasks[0])}]

            def label_exists(self, name):
                return True

            def request(self, method, path, obj=None):
                self.writes.append((method, path, obj))
                return {"html_url": "https://github.com/example/repo/issues/2"}, ""

        fake = FakeClient()
        messages = bootstrap(fake, tasks)
        self.assertEqual([w[1] for w in fake.writes], ["/issues"])
        self.assertIn(tasks[0]["key"], messages[-1])
        self.assertIn(tasks[1]["key"], messages[0])

    def test_other_issues_are_not_treated_as_owned(self) -> None:
        self.assertEqual(recorded_keys([{"body": "Unrelated GitHub issue"}]), set())


if __name__ == "__main__":
    unittest.main()
