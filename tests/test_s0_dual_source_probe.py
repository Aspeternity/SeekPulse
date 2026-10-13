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
    rss_access_stop_reason, validate_rss_interval,
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

    def test_24h_is_optional_not_eligibility_gate(self):
        with TemporaryDirectory() as d:
            s = ComparisonStore(Path(d) / "sample.db")
            run = s.begin_run(60, 86400)
            self.assertFalse(s.report()["optional_24h_stability_run_observed"])
            self.assertFalse(s.report()["study_sample_guidance"]["both_10s_and_60s_above_suggested_min"])
            s.finish_run(run, 86401, completed=True)
            self.assertTrue(s.report()["optional_24h_stability_run_observed"])
            self.assertFalse(s.report()["study_sample_guidance"]["both_10s_and_60s_above_suggested_min"])
            bad = s.begin_run(60, 86400)
            s.finish_run(bad, 50, completed=False)
            self.assertEqual(s.report()["interrupted_runs_or_in_progress"], 1)
            s.close()


    def test_10s_requires_explicit_ack_and_is_time_bounded(self):
        with self.assertRaisesRegex(ValueError, "ack-10s-rss"):
            validate_rss_interval(10, False, 60)
        with self.assertRaisesRegex(ValueError, "90 minutes"):
            validate_rss_interval(10, True, 91)
        validate_rss_interval(10, True, 60)
        validate_rss_interval(60, False, 60)
        with self.assertRaises(ValueError):
            validate_rss_interval(30, False, 60)

    def test_rss_429_or_403_stop_without_continued_polling(self):
        for status, reason in [
            (429, "RSS_RATE_LIMIT_STOP"), (403, "RSS_ACCESS_DENIED_STOP")
        ]:
            self.assertEqual(rss_access_stop_reason(
                {"status": "error", "http_status": status}
            ), reason)
        self.assertIsNone(rss_access_stop_reason(
            {"status": "error", "http_status": 200}
        ))
        self.assertIsNone(rss_access_stop_reason(
            {"status": "ok", "http_status": 200}
        ))

    def test_report_separates_60s_and_10s_first_seen_cohorts(self):
        with TemporaryDirectory() as d:
            s = ComparisonStore(Path(d) / "sample.db")
            r60 = s.begin_run(60, 300)
            s.finish_run(r60, 300, completed=True)
            r10 = s.begin_run(10, 300)
            s.finish_run(r10, 300, completed=True)
            with s.conn:
                s.conn.execute(
                    "UPDATE runs SET started_utc=?, finished_utc=? WHERE id=?",
                    ("2026-10-13T16:00:00+00:00",
                     "2026-10-13T16:05:00+00:00", r60)
                )
                s.conn.execute(
                    "UPDATE runs SET started_utc=?, finished_utc=? WHERE id=?",
                    ("2026-10-13T16:10:00+00:00",
                     "2026-10-13T16:15:00+00:00", r10)
                )
            s.observe_tg(message(10, 700), "tg_live", "2026-10-13T16:01:00+00:00")
            s.observe_rss(rss({"700"}, "2026-10-13T16:01:40+00:00"))
            s.observe_tg(message(11, 701), "tg_live", "2026-10-13T16:11:00+00:00")
            s.observe_rss(rss({"701"}, "2026-10-13T16:11:05+00:00"))
            # Both ends must be from the SAME run; this must not be counted.
            s.observe_tg(message(12, 702), "tg_live", "2026-10-13T16:04:00+00:00")
            s.observe_rss(rss({"702"}, "2026-10-13T16:12:00+00:00"))
            result = s.report()
            by_interval = result["comparison_by_rss_interval_seconds"]
            self.assertEqual(by_interval["60"]["clean_matched_posts"], 1)
            self.assertEqual(by_interval["10"]["clean_matched_posts"], 1)
            self.assertEqual(by_interval["60"]["rss_minus_tg_p50_seconds"], 40)
            self.assertEqual(by_interval["10"]["rss_minus_tg_p50_seconds"], 5)
            self.assertEqual(result["matched_live_tg_and_normal_rss_poll"], 2)
            self.assertEqual(result["rss_poll_health_by_interval_seconds"]["60"]["ok"], 1)
            self.assertEqual(result["rss_poll_health_by_interval_seconds"]["10"]["ok"], 2)
            self.assertIsNone(result["clean_observed_rss_minus_tg_seconds"]["p50"])
            self.assertFalse(result["study_sample_guidance"]["both_10s_and_60s_above_suggested_min"])
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
