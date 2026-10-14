"""S4 single-process bounded worker over S2 leased delivery tasks.

This worker is opt-in and intentionally not launched by app.main. No send
occurs until a caller explicitly injects already-authorized adapters. Normal
work receives at least one scheduling turn for every four urgent turns.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable

from app.delivery import CoreStore, DeliveryTask, TaskStatus
from app.notifiers import AppriseNotifier, Notification, SendResult, TelegramNotifier
from app.route_store import Channel, RouteStore
from app.routing import Priority, decide_route, enqueue_route


@dataclass(frozen=True, slots=True)
class BatchReport:
    claimed: int
    sent: int
    retry_wait: int
    failed_permanent: int
    suppressed: int
    expired: int
    unresolved: int


class DeliveryWorker:
    """A single dispatch coordinator, with independent in-flight targets.

    Assumes the approved one-process deployment. Atomic S2 claims still fence
    duplicate workers but running multiple coordinators can weaken per-target
    rate limiting: production runner ownership must be validated separately.
    """

    def __init__(
        self, core: CoreStore, routes: RouteStore,
        telegram: TelegramNotifier, apprise: AppriseNotifier,
        *, now: Callable[[], int] | None = None,
        parallel: int = 4, lease_seconds: int = 30,
        timeout_seconds: int = 8, normal_every: int = 5,
    ):
        if (type(parallel) is not int or not 1 <= parallel <= 20
                or type(lease_seconds) is not int or not 10 <= lease_seconds <= 300
                or type(timeout_seconds) is not int or not 1 <= timeout_seconds < lease_seconds
                or type(normal_every) is not int or not 2 <= normal_every <= 20):
            raise ValueError("invalid worker limits")
        self.core, self.routes = core, routes
        self.telegram, self.apprise = telegram, apprise
        self.now = now or (lambda: int(time.time()))
        self.parallel = parallel
        self.lease_seconds = lease_seconds
        self.timeout_seconds = timeout_seconds
        self.normal_every = normal_every
        self._turn = 0
        self._batch_lock = asyncio.Lock()

    def _clock(self) -> int:
        current = self.now()
        if type(current) is not int or current < 0:
            raise ValueError("worker clock must be nonnegative UTC epoch seconds")
        return current

    async def route_post(self, user_id: int, post_id: int,
                         *, ttl_seconds: int = 1800) -> int:
        """Take a current policy snapshot and enqueue once per target."""
        post = await self.core.get_post(post_id)
        if post is None:
            raise ValueError("post has not been observed")
        policy = await self.routes.load_policy(user_id)
        _, added = await enqueue_route(
            self.core, post, policy, now=self._clock(),
            ttl_seconds=ttl_seconds,
        )
        return added

    async def _take(self, blocked: set[int]) -> DeliveryTask | None:
        # Every Nth *claim* prefers normal, so urgent floods cannot starve it.
        preference = (
            Priority.NORMAL if self._turn % self.normal_every == self.normal_every - 1
            else Priority.URGENT
        )
        for priority in (preference, Priority(1 - preference.value)):
            tasks = await self.core.claim(
                now=self._clock(), lease_seconds=self.lease_seconds,
                limit=1, priority=priority,
                exclude_target_ids=tuple(sorted(blocked)),
            )
            if tasks:
                self._turn += 1
                return tasks[0]
        return None

    async def _deliver(self, task: DeliveryTask) -> TaskStatus | None:
        now = self._clock()
        token = task.lease_token
        if not token:
            return None
        try:
            post = await self.core.get_post(task.post_id)
            policy = await self.routes.load_policy(task.user_id)
            if post is None or not decide_route(post, policy).includes(task.target_id):
                ok = await self.core.suppress_leased(task.id, token, now=now)
                return TaskStatus.SUPPRESSED if ok else None
            target = await self.routes.channel_for(task.user_id, task.target_id)
            if target is None:
                ok = await self.core.suppress_leased(task.id, token, now=now)
                return TaskStatus.SUPPRESSED if ok else None

            message = Notification.from_post(post)
            adapter = (self.telegram if target.channel is Channel.TELEGRAM
                       else self.apprise)
            try:
                result = await asyncio.wait_for(
                    adapter.send(target, message),
                    timeout=self.timeout_seconds,
                )
            except asyncio.TimeoutError:
                result = SendResult.failure("send_timeout", retryable=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                result = SendResult.failure("send_error", retryable=True)

            now = self._clock()
            if not isinstance(result, SendResult):
                result = SendResult.failure("invalid_send_result", retryable=True)
            if result.accepted:
                # Mark accepted by API, not actually delivered to mobile.
                ok = await self.core.mark_sent(task.id, token, now=now)
                if ok:
                    await self.routes.extend_cooldown(
                        target.target_id,
                        until=now + (1 if target.channel is Channel.TELEGRAM else 2),
                    )
                    return TaskStatus.SENT
                return None

            state = await self.core.mark_failed(
                task.id, token, now=now,
                retryable=result.retryable,
                error_code=result.error_code or "send_error",
                retry_after_seconds=result.retry_after_seconds,
            )
            if (state is not None and result.error_code == "http_429"):
                await self.routes.extend_cooldown(
                    target.target_id, until=now + max(1, result.retry_after_seconds)
                )
            return state
        except asyncio.CancelledError:
            # No unsafe forced commit: a lease timeout will restore it.
            raise
        except Exception:
            # If policy storage is corrupt/unavailable, don't send blindly.
            return await self.core.mark_failed(
                task.id, token, now=self._clock(),
                retryable=True, error_code="worker_error",
            )

    async def run_once(self) -> BatchReport:
        """Bounded parallel sends, never two concurrent tasks per target.

        No lock is held across external sends in SQLite. This method's
        coordinator lock prevents overlapping cycles on one instance.
        """
        async with self._batch_lock:
            excluded = await self.routes.blocked_targets(now=self._clock())
            tasks: list[DeliveryTask] = []
            for _ in range(self.parallel):
                task = await self._take(excluded)
                if task is None:
                    break
                excluded.add(task.target_id)
                tasks.append(task)
            if not tasks:
                return BatchReport(0, 0, 0, 0, 0, 0, 0)
            results = await asyncio.gather(
                *(self._deliver(task) for task in tasks)
            )
            return BatchReport(
                claimed=len(tasks),
                sent=results.count(TaskStatus.SENT),
                retry_wait=results.count(TaskStatus.RETRY_WAIT),
                failed_permanent=results.count(TaskStatus.FAILED_PERMANENT),
                suppressed=results.count(TaskStatus.SUPPRESSED),
                expired=results.count(TaskStatus.EXPIRED),
                unresolved=results.count(None),
            )

    async def run_forever(self, stop: asyncio.Event, interval: float = 1.0) -> None:
        if not 0.5 <= interval <= 60.0:
            raise ValueError("invalid polling interval")
        while not stop.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Lifecycle supervisor may surface a sanitized health code;
                # never log exception strings that may contain secret URLs.
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
