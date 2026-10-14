"""S2-02 atomic task queue: multi-user, lease fencing, failures, migration.

No real Telegram or network operations are used. Times are virtual seconds,
all data are stored in isolated disposable SQLite databases.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db import Database
from app.delivery import CoreStore, TaskStatus
from app.domain import Source, SourceObservation


TIME = 1000
OBSERVED = datetime(2026, 10, 14, tzinfo=timezone.utc)


def event(post_id=123, source=Source.RSS, event_id=None):
    return SourceObservation(
        source=source, event_id=event_id or f"{source.value}-{post_id}",
        post_id=post_id, observed_at=OBSERVED, title="DMIT post",
    )


class AtomicDeliveryContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory(prefix="seekpulse-s2-delivery-")
        self.addAsyncCleanup(self._cleanup)
        self.path = Path(self.temp.name) / "queue.db"
        self.db = Database(self.path)
        await self.db.init()
        self.store = CoreStore(self.path)
        await self.store.init()
        self.user = await self.db.ensure_user_profile(
            101, 1101, None, "A", None, "private",
        )
        targets = await self.db.list_targets_by_tg_user(101)
        self.target = targets[0]
        await self.store.observe(event())

    async def _cleanup(self):
        self.temp.cleanup()

    async def second_target(self):
        await self.db.add_target(
            self.user.id, -1009001, chat_title="Channel", chat_type="channel"
        )
        return (await self.db.list_targets_by_tg_user(101))[-1]

    async def test_same_user_post_target_is_unique_even_after_both_sources(self):
        self.assertEqual(await self.store.enqueue(
            self.user.id, 123, [self.target.id], now=TIME
        ), 1)
        await self.store.observe(event(source=Source.TELEGRAM))
        self.assertEqual(await self.store.enqueue(
            self.user.id, 123, [self.target.id, self.target.id], now=TIME + 1
        ), 0)
        tasks = await self.store.list_tasks(self.user.id)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].status, TaskStatus.PENDING)

    async def test_later_urgent_route_upgrades_pending_without_duplication(self):
        self.assertEqual(await self.store.enqueue(
            self.user.id, 123, [self.target.id], now=TIME,
            ttl_seconds=300, priority=0
        ), 1)
        first = (await self.store.list_tasks(self.user.id))[0]
        self.assertEqual(first.priority, 0)
        self.assertEqual(await self.store.enqueue(
            self.user.id, 123, [self.target.id], now=TIME + 5,
            ttl_seconds=900, priority=1
        ), 0)
        after = (await self.store.list_tasks(self.user.id))[0]
        self.assertEqual(after.id, first.id)
        self.assertEqual(after.expires_at, first.expires_at)
        self.assertEqual(after.attempts, 0)
        self.assertEqual(after.priority, 1)
        leased = (await self.store.claim(now=TIME + 6))[0]
        self.assertTrue(await self.store.mark_sent(
            leased.id, leased.lease_token, now=TIME + 7
        ))
        self.assertEqual(await self.store.enqueue(
            self.user.id, 123, [self.target.id], now=TIME + 8, priority=1
        ), 0)
        self.assertEqual((await self.store.list_tasks(self.user.id))[0].status,
                         TaskStatus.SENT)

    async def test_two_targets_get_independent_terminal_states_and_no_redelivery(self):
        other = await self.second_target()
        self.assertEqual(await self.store.enqueue(
            self.user.id, 123, [self.target.id, other.id], now=TIME
        ), 2)
        tasks = await self.store.claim(now=TIME, limit=2)
        self.assertEqual({t.target_id for t in tasks}, {self.target.id, other.id})
        one = next(t for t in tasks if t.target_id == self.target.id)
        two = next(t for t in tasks if t.target_id == other.id)
        self.assertTrue(await self.store.mark_sent(one.id, one.lease_token, now=TIME + 1))
        self.assertEqual(await self.store.mark_failed(
            two.id, two.lease_token, now=TIME + 1, retryable=True,
            error_code="network",
        ), TaskStatus.RETRY_WAIT)
        states = {t.target_id: t.status for t in await self.store.list_tasks(self.user.id)}
        self.assertEqual(states[self.target.id], TaskStatus.SENT)
        self.assertEqual(states[other.id], TaskStatus.RETRY_WAIT)
        self.assertEqual(await self.store.claim(now=TIME + 1), [])
        retry = await self.store.claim(now=TIME + 11)
        self.assertEqual([t.id for t in retry], [two.id])
        self.assertTrue(await self.store.mark_sent(retry[0].id, retry[0].lease_token,
                                                   now=TIME + 12))
        self.assertEqual(await self.store.claim(now=TIME + 12), [])
        self.assertEqual(await self.store.enqueue(
            self.user.id, 123, [one.target_id, two.target_id], now=TIME + 13
        ), 0)

    async def test_two_users_with_distinct_target_ownership(self):
        second = await self.db.ensure_user_profile(
            202, 2202, None, "B", None, "private",
        )
        own_target = (await self.db.list_targets_by_tg_user(202))[0]
        with self.assertRaisesRegex(ValueError, "does not belong"):
            await self.store.enqueue(self.user.id, 123, [self.target.id, own_target.id],
                                     now=TIME)
        self.assertEqual(await self.store.list_tasks(self.user.id), [])
        self.assertEqual(await self.store.enqueue(
            self.user.id, 123, [self.target.id], now=TIME
        ), 1)
        self.assertEqual(await self.store.enqueue(
            second.id, 123, [own_target.id], now=TIME
        ), 1)
        self.assertEqual(len(await self.store.claim(now=TIME, limit=2)), 2)

    async def test_cross_user_suppress_does_not_touch_another_user(self):
        second = await self.db.ensure_user_profile(
            202, 2202, None, "B", None, "private",
        )
        their_target = (await self.db.list_targets_by_tg_user(202))[0]
        await self.store.enqueue(self.user.id, 123, [self.target.id], now=TIME)
        await self.store.enqueue(second.id, 123, [their_target.id], now=TIME)
        self.assertEqual(await self.store.suppress(self.user.id, now=TIME + 1), 1)
        self.assertEqual(len(await self.store.claim(now=TIME + 2)), 1)
        self.assertEqual((await self.store.list_tasks(self.user.id))[0].status,
                         TaskStatus.SUPPRESSED)

    async def test_concurrent_enqueuers_insert_one_task(self):
        inserted = await asyncio.gather(*(self.store.enqueue(
            self.user.id, 123, [self.target.id], now=TIME
        ) for _ in range(16)))
        self.assertEqual(sum(inserted), 1)
        self.assertEqual(len(await self.store.list_tasks(self.user.id)), 1)

    async def test_atomic_claim_two_workers_do_not_receive_same_task(self):
        await self.store.enqueue(self.user.id, 123, [self.target.id], now=TIME)
        # A second independent store has its own in-process lock. This test
        # proves SQLite BEGIN IMMEDIATE is still the cross-instance fence.
        other_instance = CoreStore(self.path)
        a, b = await asyncio.gather(
            self.store.claim(now=TIME), other_instance.claim(now=TIME)
        )
        self.assertEqual(len(a) + len(b), 1)
        claimed = (a or b)[0]
        self.assertEqual(claimed.attempts, 1)
        self.assertEqual(len(claimed.lease_token), 32)

    async def test_expired_lease_recovery_fences_late_worker(self):
        await self.store.enqueue(self.user.id, 123, [self.target.id], now=TIME)
        first = (await self.store.claim(now=TIME, lease_seconds=5))[0]
        self.assertEqual((await self.store.recover(now=TIME + 4)).leases_requeued, 0)
        reopened = CoreStore(self.path)
        summary = await reopened.recover(now=TIME + 5)
        self.assertEqual(summary.leases_requeued, 1)
        self.assertFalse(await self.store.mark_sent(
            first.id, first.lease_token, now=TIME + 5
        ))
        second = (await reopened.claim(now=TIME + 5))[0]
        self.assertNotEqual(first.lease_token, second.lease_token)
        self.assertEqual(second.attempts, 2)
        self.assertFalse(await self.store.mark_sent(
            first.id, first.lease_token, now=TIME + 6
        ))
        self.assertTrue(await reopened.mark_sent(
            second.id, second.lease_token, now=TIME + 6
        ))

    async def test_lease_exhaustion_becomes_permanent_failure_not_infinite_retry(self):
        await self.store.enqueue(
            self.user.id, 123, [self.target.id], now=TIME, max_attempts=1
        )
        task = (await self.store.claim(now=TIME, lease_seconds=2))[0]
        self.assertEqual(task.attempts, 1)
        recovered = await CoreStore(self.path).recover(now=TIME + 2)
        self.assertEqual(recovered.leases_exhausted, 1)
        self.assertEqual(await self.store.claim(now=TIME + 3), [])
        record = (await self.store.list_tasks(self.user.id))[0]
        self.assertEqual(record.status, TaskStatus.FAILED_PERMANENT)
        self.assertEqual(record.last_error_code, "lease_exhausted")

    async def test_retryable_failures_backoff_then_exhaust_attempts(self):
        await self.store.enqueue(
            self.user.id, 123, [self.target.id], now=TIME,
            max_attempts=2, ttl_seconds=1000,
        )
        attempt = (await self.store.claim(now=TIME))[0]
        state = await self.store.mark_failed(
            attempt.id, attempt.lease_token, now=TIME + 1,
            retryable=True, error_code="timeout", backoff_base=5,
        )
        self.assertEqual(state, TaskStatus.RETRY_WAIT)
        self.assertEqual(await self.store.claim(now=TIME + 5), [])
        retry = (await self.store.claim(now=TIME + 6))[0]
        self.assertEqual(retry.attempts, 2)
        self.assertEqual(await self.store.mark_failed(
            retry.id, retry.lease_token, now=TIME + 7,
            retryable=True, error_code="timeout",
        ), TaskStatus.FAILED_PERMANENT)
        self.assertEqual(await self.store.claim(now=TIME + 20), [])

    async def test_retry_after_seconds_respected_without_platform_limit_bypass(self):
        await self.store.enqueue(self.user.id, 123, [self.target.id],
                                 now=TIME, ttl_seconds=1000)
        task = (await self.store.claim(now=TIME))[0]
        self.assertEqual(await self.store.mark_failed(
            task.id, task.lease_token, now=TIME + 1, retryable=True,
            error_code="http_429", retry_after_seconds=300
        ), TaskStatus.RETRY_WAIT)
        self.assertEqual(await self.store.claim(now=TIME + 300), [])
        self.assertEqual(len(await self.store.claim(now=TIME + 301)), 1)

    async def test_nonretryable_failure_is_terminal(self):
        await self.store.enqueue(self.user.id, 123, [self.target.id], now=TIME)
        task = (await self.store.claim(now=TIME))[0]
        self.assertEqual(await self.store.mark_failed(
            task.id, task.lease_token, now=TIME + 1,
            retryable=False, error_code="forbidden",
        ), TaskStatus.FAILED_PERMANENT)
        self.assertEqual(await self.store.claim(now=TIME + 2), [])

    async def test_errors_are_sanitized_codes_not_raw_token_bearing_messages(self):
        await self.store.enqueue(self.user.id, 123, [self.target.id], now=TIME)
        task = (await self.store.claim(now=TIME))[0]
        with self.assertRaisesRegex(ValueError, "safe short category"):
            await self.store.mark_failed(
                task.id, task.lease_token, now=TIME + 1,
                retryable=True, error_code="Bearer secret-token-123",
            )
        self.assertEqual((await self.store.list_tasks(self.user.id))[0].status,
                         TaskStatus.LEASED)

    async def test_expiration_preserves_audit_and_prevents_send(self):
        await self.store.enqueue(
            self.user.id, 123, [self.target.id], now=TIME, ttl_seconds=30
        )
        stats = await self.store.recover(now=TIME + 30)
        self.assertEqual(stats.expired, 1)
        task = (await self.store.list_tasks(self.user.id))[0]
        self.assertEqual(task.status, TaskStatus.EXPIRED)
        self.assertEqual(await self.store.claim(now=TIME + 31), [])
        self.assertEqual(await self.store.enqueue(
            self.user.id, 123, [self.target.id], now=TIME + 40
        ), 0)

    async def test_suppress_only_unclaimed_never_unwinds_inflight_or_sent(self):
        second = await self.second_target()
        await self.store.enqueue(
            self.user.id, 123, [self.target.id, second.id], now=TIME
        )
        inflight = (await self.store.claim(now=TIME, limit=1))[0]
        self.assertEqual(await self.store.suppress(
            self.user.id, now=TIME + 1, post_id=123
        ), 1)
        self.assertTrue(await self.store.mark_sent(
            inflight.id, inflight.lease_token, now=TIME + 2
        ))
        self.assertEqual(await self.store.suppress(
            self.user.id, now=TIME + 3
        ), 0)
        self.assertCountEqual(
            [t.status for t in await self.store.list_tasks(self.user.id)],
            [TaskStatus.SENT, TaskStatus.SUPPRESSED],
        )

    async def test_pause_and_disable_target_prevent_claim_but_do_not_erase_task(self):
        await self.store.enqueue(self.user.id, 123, [self.target.id], now=TIME)
        await self.db.set_user_enabled(101, False)
        self.assertEqual(await self.store.claim(now=TIME), [])
        self.assertEqual((await self.store.list_tasks(self.user.id))[0].status,
                         TaskStatus.PENDING)
        await self.db.set_user_enabled(101, True)
        await self.db.set_target_enabled(self.user.id, self.target.id, False)
        self.assertEqual(await self.store.claim(now=TIME), [])
        await self.db.set_target_enabled(self.user.id, self.target.id, True)
        self.assertEqual(len(await self.store.claim(now=TIME)), 1)

    async def test_priority_precedes_oldest_normal_pending(self):
        await self.store.observe(event(post_id=124))
        await self.store.enqueue(self.user.id, 123, [self.target.id], now=TIME, priority=0)
        await self.store.enqueue(self.user.id, 124, [self.target.id],
                                 now=TIME + 1, priority=1)
        queue = await self.store.claim(now=TIME + 2, limit=2)
        self.assertEqual([t.post_id for t in queue], [124, 123])

    async def test_enqueue_unknown_post_rejected_and_duplicate_init_safe(self):
        with self.assertRaisesRegex(ValueError, "not observed"):
            await self.store.enqueue(self.user.id, 999, [self.target.id], now=TIME)
        await self.store.init()
        await self.store.init()
        self.assertEqual(await self.store.list_tasks(self.user.id), [])

    async def test_retry_later_than_expiry_marks_expired_immediately(self):
        await self.store.enqueue(self.user.id, 123, [self.target.id],
                                 now=TIME, ttl_seconds=20)
        task = (await self.store.claim(now=TIME))[0]
        self.assertEqual(await self.store.mark_failed(
            task.id, task.lease_token, now=TIME + 1,
            retryable=True, error_code="http_429", retry_after_seconds=600
        ), TaskStatus.EXPIRED)
        self.assertEqual(await self.store.claim(now=TIME + 2), [])


if __name__ == "__main__":
    unittest.main()
