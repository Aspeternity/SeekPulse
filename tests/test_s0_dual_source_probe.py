"""S0-02 isolated offline observations: no HTTP requests or Telegram logins."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from xml.etree.ElementTree import ParseError

from scripts.s0_dual_source_probe import (
    ComparisonStore, fetch_rss, percentile, reconcile_tg,
)


def message(mid, post):
    return SimpleNamespace(id=mid, raw_text=f"https://nodeseek.com/post-{post}-1",
                           entities=[], date=datetime(2026, 10, 13, tzinfo=timezone.utc))


def rss(ids, when="2026-10-13T16:00:00+00:00"):
    return {"status": "ok", "ids": set(ids), "observed_utc": when,
            "duration_ms": 20, "http_status": 200}


class FakeClient:
    def __init__(self, messages):
        self.messages = messages

    async def iter_messages(self, channel, min_id, reverse, limit):
        for item in self.messages:
            if item.id > min_id:
                yield item


class Observations(unittest.TestCase):
    def test_first_rss_feed_is_baseline_not_fresh(self):
        with TemporaryDirectory() as d:
            s = ComparisonStore(Path(d) / "sample.db")
            self.assertEqual(s.observe_rss(rss({"100", "101"}), baseline=True)["new_ids"], 2)
            s.observe_tg(message(1, 100), "tg_live")
            r = s.report()
            self.assertEqual(r["matched_nonbaseline_post_ids"], 0)
            self.assertEqual(r["provisional_source_only_post_ids"], {"tg_only": 0, "rss_only": 0})
            s.close()

    def test_tg_duplicate_and_same_post_across_messages(self):
        with TemporaryDirectory() as d:
            s = ComparisonStore(Path(d) / "sample.db")
            self.assertTrue(s.observe_tg(message(10, 200), "tg_live",
                                         "2026-10-13T16:00:00+00:00"))
            self.assertFalse(s.observe_tg(message(10, 200), "tg_history"))
            self.assertTrue(s.observe_tg(message(11, 200), "tg_history"))
            s.observe_rss(rss({"200"}, "2026-10-13T16:00:10+00:00"))
            r = s.report()
            self.assertEqual(r["telegram_observed_messages"], 2)
            self.assertEqual(r["matched_nonbaseline_post_ids"], 1)
            self.assertEqual(r["clean_observed_rss_minus_tg_seconds"]["p50"], 10)
            s.close()

    def test_tg_first_or_rss_first_is_signed(self):
        with TemporaryDirectory() as d:
            s = ComparisonStore(Path(d) / "sample.db")
            s.observe_tg(message(1, 200), "tg_live", "2026-10-13T16:00:00+00:00")
            s.observe_tg(message(2, 201), "tg_live", "2026-10-13T16:00:05+00:00")
            s.observe_rss(rss({"200", "201"}, "2026-10-13T16:00:03+00:00"))
            r = s.report()
            self.assertEqual(r["matched_live_tg_and_normal_rss_poll"], 2)
            self.assertEqual(r["clean_observed_rss_minus_tg_seconds"]["p50"], 0.5)
            self.assertEqual(r["clean_observed_rss_minus_tg_seconds"]["tg_seen_before_rss"], 1)
            self.assertEqual(r["clean_observed_rss_minus_tg_seconds"]["rss_seen_before_tg"], 1)
            s.close()

    def test_recovered_sources_excluded_from_speed(self):
        with TemporaryDirectory() as d:
            s = ComparisonStore(Path(d) / "sample.db")
            s.observe_tg(message(1, 300), "tg_history")
            s.observe_tg(message(2, 301), "tg_live")
            s.observe_rss(rss({"300"}))
            s.observe_rss(rss({"300", "301"}, "2026-10-13T16:01:00+00:00"),
                          resumed=True)
            r = s.report()
            self.assertEqual(r["matched_nonbaseline_post_ids"], 2)
            self.assertEqual(r["matched_live_tg_and_normal_rss_poll"], 0)
            s.close()

    def test_rss_window_gap_and_http_error_do_not_mean_absence(self):
        with TemporaryDirectory() as d:
            s = ComparisonStore(Path(d) / "sample.db")
            s.observe_rss(rss({"1", "2"}), baseline=True)
            self.assertEqual(s.observe_rss(rss({"3", "4"}))["overlap"], 0)
            s.observe_rss({"status": "error", "ids": set(),
                           "observed_utc": "2026-10-13T16:03:00+00:00",
                           "duration_ms": 13, "error_type": "HTTPError",
                           "http_status": 429})
            r = s.report()
            self.assertEqual(r["rss_window_no_overlap_count"], 1)
            self.assertEqual(r["rss_poll_results"], {"ok": 2, "error": 1})
            self.assertEqual(r["provisional_source_only_post_ids"]["rss_only"], 2)
            s.close()

    def test_24h_requires_completed_continuous_run(self):
        with TemporaryDirectory() as d:
            s = ComparisonStore(Path(d) / "sample.db")
            run = s.begin_run(60, 86400)
            self.assertFalse(s.report()["continuous_24h_observed"])
            s.finish_run(run, 86401, completed=True)
            self.assertTrue(s.report()["continuous_24h_observed"])
            bad = s.begin_run(60, 86400)
            s.finish_run(bad, 50, completed=False)
            self.assertEqual(s.report()["interrupted_runs_or_in_progress"], 1)
            s.close()

    def test_percentile_boundaries(self):
        self.assertIsNone(percentile([], .5))
        self.assertEqual(percentile([0, 10, 20], .5), 10)
        self.assertEqual(percentile([1, 2, 3], .95), 2.9)

    def test_rss_bad_xml_classified_without_leaking_message(self):
        with patch("scripts.s0_dual_source_probe.urlopen",
                   side_effect=ParseError("secret_text")):
            r = fetch_rss()
        self.assertEqual(r["error_type"], "ParseError")
        self.assertNotIn("secret_text", str(r))

    def test_http_429_classified(self):
        with patch("scripts.s0_dual_source_probe.urlopen",
                   side_effect=HTTPError("https://secret", 429, "hidden", {}, None)):
            r = fetch_rss()
        self.assertEqual(r["http_status"], 429)
        self.assertEqual(r["error_type"], "HTTPError")
        self.assertNotIn("secret", str(r))


class Recovery(unittest.IsolatedAsyncioTestCase):
    async def test_restart_reconciles_and_retains_cursor(self):
        with TemporaryDirectory() as d:
            s = ComparisonStore(Path(d) / "sample.db")
            s.set("tg_cursor", "100")
            client = FakeClient([message(101, 201), message(102, 202)])
            self.assertEqual((await reconcile_tg(client, object(), s))["new_message_ids"], 2)
            self.assertEqual(s.get("tg_cursor"), "102")
            self.assertEqual((await reconcile_tg(client, object(), s))["new_message_ids"], 0)
            self.assertEqual(s.report()["telegram_message_methods"], {"tg_history": 2})
            s.close()

    async def test_overflow_keeps_old_cursor(self):
        with TemporaryDirectory() as d:
            s = ComparisonStore(Path(d) / "sample.db")
            s.set("tg_cursor", "5")
            result = await reconcile_tg(FakeClient([
                message(6, 206), message(7, 207), message(8, 208)
            ]), object(), s, limit=2)
            self.assertEqual(result["status"], "overflow")
            self.assertEqual(s.get("tg_cursor"), "5")
            self.assertEqual(s.report()["telegram_observed_messages"], 0)
            self.assertEqual(s.report()["warnings"], {"TG_BACKFILL_LIMIT_EXCEEDED": 1})
            s.close()


if __name__ == "__main__":
    unittest.main()
