"""Offline S0 MTProto test harness tests; no Telethon login or network."""

from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from scripts.s0_mtproto_probe import (
    ObservationStore,
    format_reconcile_line,
    initialize_baseline,
    log_callback_observation,
    post_id_from_message,
    private_state_dir,
    reconcile,
)


class FakeClient:
    def __init__(self, messages):
        self.messages = messages

    async def get_messages(self, channel, limit=1):
        return list(reversed(self.messages))[:limit]

    async def iter_messages(self, channel, min_id=0, reverse=True, limit=501):
        self.last_query = (min_id, reverse, limit)
        for msg in [m for m in self.messages if m.id > min_id][:limit]:
            yield msg


def msg(mid, text="", entities=None):
    return SimpleNamespace(id=mid, raw_text=text, entities=entities or [],
                           date=datetime(2026, 10, 13, tzinfo=timezone.utc))


class TestIdentifiers(unittest.TestCase):
    def test_text_url_entity(self):
        m = msg(1, "New discounted VPS", [SimpleNamespace(url="https://www.nodeseek.com/post-12345-1")])
        self.assertEqual(post_id_from_message(m), "12345")

    def test_plain_text_link(self):
        self.assertEqual(post_id_from_message(msg(2, "https://nodeseek.com/post-789-1?via=tg")), "789")

    def test_impostor_hosts(self):
        self.assertIsNone(post_id_from_message(msg(4, "https://nodeseek.com.evil.invalid/post-123-1")))

    def test_private_folder_outside_repo(self):
        with self.assertRaises(ValueError):
            private_state_dir(Path(__file__).resolve().parents[1] / "data" / "private")


class TestRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_initial_baseline_skips_history_then_new_messages(self):
        with TemporaryDirectory() as temp:
            store = ObservationStore(Path(temp) / "sample.sqlite3")
            client = FakeClient([msg(100, "https://nodeseek.com/post-100-1")])
            self.assertTrue(await initialize_baseline(client, object(), store))
            self.assertEqual(store.cursor(), 100)
            self.assertEqual(store.report()["total_message_ids"], 0)
            client.messages.append(msg(101, "https://nodeseek.com/post-101-1"))
            result = await reconcile(client, object(), store)
            self.assertEqual(result["new"], 1)
            self.assertEqual(store.cursor(), 101)
            store.close()

    async def test_reconcile_after_restart_and_event_dedup(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "sample.sqlite3"
            store = ObservationStore(path)
            store.set_cursor(10)
            store.insert(msg(12, "https://nodeseek.com/post-12-1"), "event_callback")
            client = FakeClient([msg(11, "https://nodeseek.com/post-11-1"), msg(12, "https://nodeseek.com/post-12-1")])
            result = await reconcile(client, object(), store)
            self.assertEqual(result["new"], 1)
            self.assertEqual(store.report()["first_observed_via"], {"event_callback": 1, "history": 1})
            store.close()
            resumed = ObservationStore(path)
            self.assertEqual(resumed.cursor(), 12)
            self.assertEqual((await reconcile(client, object(), resumed))["retrieved"], 0)
            resumed.close()

    async def test_overflow_does_not_advance_watermark(self):
        with TemporaryDirectory() as temp:
            store = ObservationStore(Path(temp) / "sample.sqlite3")
            store.set_cursor(1)
            client = FakeClient([msg(2), msg(3), msg(4)])
            res = await reconcile(client, object(), store, limit=2)
            self.assertEqual(res["status"], "INCOMPLETE_CURSOR_UNCHANGED")
            self.assertEqual(store.cursor(), 1)
            self.assertEqual(store.report()["total_message_ids"], 0)
            store.close()

    async def test_exception_keeps_cursor(self):
        with TemporaryDirectory() as temp:
            store = ObservationStore(Path(temp) / "sample.sqlite3")
            store.set_cursor(15)
            class BadClient:
                async def iter_messages(self, *args, **kwargs):
                    yield msg(16)
                    raise RuntimeError("connection cut")
            with self.assertRaises(RuntimeError):
                await reconcile(BadClient(), object(), store)
            self.assertEqual(store.cursor(), 15)
            store.close()


class TestObservationOutput(unittest.TestCase):
    def test_live_event_logs_new_and_duplicate_without_message_content(self):
        with TemporaryDirectory() as temp:
            store = ObservationStore(Path(temp) / "sample.sqlite3")
            raw = "PRIVATE MESSAGE TEXT https://nodeseek.com/post-1234-1"
            message = msg(77, raw)
            buffer = StringIO()
            with redirect_stdout(buffer):
                self.assertTrue(log_callback_observation(store, message, "event_callback"))
                self.assertFalse(log_callback_observation(store, message, "event_callback"))
            lines = buffer.getvalue().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertTrue(all(line.startswith("[LIVE]") for line in lines))
            self.assertIn("message_id=77", lines[0])
            self.assertIn("post_id=1234", lines[0])
            self.assertIn("stored=new", lines[0])
            self.assertIn("stored=already_recorded", lines[1])
            self.assertNotIn("PRIVATE MESSAGE TEXT", buffer.getvalue())
            self.assertEqual(store.total_messages(), 1)
            store.close()

    def test_catchup_callback_not_mislabeled_live(self):
        with TemporaryDirectory() as temp:
            store = ObservationStore(Path(temp) / "sample.sqlite3")
            buffer = StringIO()
            with redirect_stdout(buffer):
                self.assertTrue(log_callback_observation(
                    store, msg(78, "https://nodeseek.com/post-5678-1"), "catchup_callback"
                ))
            self.assertTrue(buffer.getvalue().startswith("[CATCHUP] "))
            self.assertNotIn("[LIVE]", buffer.getvalue())
            store.close()

    def test_check_separates_fetched_new_and_previously_recorded(self):
        line = format_reconcile_line(
            {"status": "ok", "retrieved": 2, "new": 0, "cursor": 942537},
            total_stored=7,
        )
        self.assertEqual(
            line,
            "[CHECK] fetched=2 history_new=0 already_recorded=2 total_stored=7 cursor=942537",
        )
        line = format_reconcile_line(
            {"status": "ok", "retrieved": 11, "new": 11, "cursor": 942564},
            total_stored=34, startup=True,
        )
        self.assertEqual(
            line,
            "[STARTUP_CHECK] fetched=11 history_new=11 already_recorded=0 total_stored=34 cursor=942564",
        )

    def test_overflow_is_explicit_and_never_claims_success(self):
        line = format_reconcile_line(
            {"status": "INCOMPLETE_CURSOR_UNCHANGED", "retrieved": 501, "cursor": 100},
            total_stored=15,
        )
        self.assertIn("status=INCOMPLETE_CURSOR_UNCHANGED", line)
        self.assertIn("backfill=INCOMPLETE", line)
        self.assertNotIn("history_new=", line)


if __name__ == "__main__":
    unittest.main()
