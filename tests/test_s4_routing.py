"""S4 rules/default overrides and S2 queue integration, all offline SQLite."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db import Database
from app.delivery import CoreStore, TaskStatus
from app.domain import (
    RuleOutcome, RuleSet, Source, SourceObservation,
    CanonicalPost, evaluate_rules,
)
from app.routing import (
    Priority, RuleRoute, UserPolicy, decide_route, enqueue_route,
)
from app.route_store import Channel, RouteStore

OBS_TIME = datetime(2026, 10, 14, tzinfo=timezone.utc)
NOW = 1000


def observation(post_id=200, *, title="DMIT 补货", summary="交易",
                category="交易", source=Source.RSS, event_id=None):
    return SourceObservation(
        source=source, event_id=event_id or f"{source.value}-{post_id}",
        post_id=post_id, observed_at=OBS_TIME,
        title=title, summary=summary, category=category,
    )


class PureRouteTests(unittest.TestCase):
    def test_union_and_highest_priority_without_duplicate_target(self):
        post = CanonicalPost.from_observation(observation())
        p = UserPolicy(
            1, (7, 8),
            (
                RuleRoute(1, RuleSet((("dmit",),)), Priority.NORMAL),
                RuleRoute(2, RuleSet((("补货",),)), Priority.URGENT, (8, 9)),
            ),
        )
        result = decide_route(post, p)
        self.assertEqual(result.targets, (
            (7, Priority.NORMAL), (8, Priority.URGENT), (9, Priority.URGENT),
        ))
        self.assertEqual(result.matched_rule_ids, (1, 2))

    def test_incomplete_category_or_blocker_never_routes(self):
        post = CanonicalPost.from_observation(
            observation(summary=None, category=None)
        )
        p = UserPolicy(1, (7,), (
            RuleRoute(1, RuleSet((("dmit",),), blocked=("求购",),
                                allowed_categories=frozenset({"trade"}))),
        ))
        result = decide_route(post, p)
        self.assertEqual(result.targets, ())
        self.assertEqual(result.insufficient_rule_ids, (1,))
        self.assertEqual(
            evaluate_rules(post, p.rules[0].rules).outcome,
            RuleOutcome.INSUFFICIENT_DATA,
        )

    def test_empty_override_and_disabled_user_route_nothing(self):
        post = CanonicalPost.from_observation(observation())
        rule = RuleRoute(1, RuleSet((("dmit",),)), override_targets=())
        self.assertFalse(decide_route(post, UserPolicy(1, (7,), (rule,))).targets)
        self.assertFalse(
            decide_route(post, UserPolicy(1, (7,), (rule,), enabled=False)).targets
        )

    def test_disabled_rule_cannot_send(self):
        post = CanonicalPost.from_observation(observation())
        policy = UserPolicy(1, (7,), (
            RuleRoute(1, RuleSet((("dmit",),)), enabled=False),
        ))
        self.assertEqual(decide_route(post, policy).targets, ())

    def test_invalid_ids_and_priorities_fail_closed(self):
        for f in (
            lambda: UserPolicy(0, (), ()),
            lambda: UserPolicy(1, (7, 7), ()),
            lambda: UserPolicy(1, (True,), ()),
            lambda: UserPolicy(1, (), (
                RuleRoute(1, RuleSet((("dmit",),))),
                RuleRoute(1, RuleSet((("补货",),))),
            )),
            lambda: RuleRoute(1, RuleSet((("dmit",),)), priority=1),
            lambda: RuleRoute(1, RuleSet((("dmit",),)), override_targets=(7, 7)),
        ):
            with self.subTest(func=f), self.assertRaises(ValueError):
                f()


class SqliteRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory(prefix="seekpulse-s4-routes-")
        self.addAsyncCleanup(self._clean)
        self.path = Path(self.folder.name) / "test.sqlite3"
        self.db = Database(self.path)
        await self.db.init()
        self.core = CoreStore(self.path)
        await self.core.init()
        self.routes = RouteStore(self.path)
        await self.routes.init()
        self.user = await self.db.ensure_user_profile(
            101, 1101, None, "A", None, "private"
        )
        await self.db.add_target(self.user.id, 2202,
                                 chat_title="B", chat_type="private")
        await self.db.add_target(self.user.id, 3303,
                                 chat_title="C", chat_type="private")
        self.targets = await self.db.list_targets_by_tg_user(101)
        _, self.dmit = await self.db.add_keyword(101, "dmit")
        _, self.stock = await self.db.add_keyword(101, "补货")
        await self.core.observe(observation())

    async def _clean(self):
        self.folder.cleanup()

    async def test_default_routes_all_targets_and_reopen_persists(self):
        policy = await self.routes.load_policy(self.user.id)
        self.assertEqual(policy.default_targets,
                         tuple(t.id for t in self.targets))
        plan, added = await enqueue_route(
            self.core, await self.core.get_post(200), policy, now=NOW
        )
        self.assertEqual(added, 3)
        self.assertEqual(len(plan.targets), 3)
        self.assertEqual((await RouteStore(self.path).load_policy(self.user.id)).rules,
                         policy.rules)
        _, second = await enqueue_route(
            self.core, await self.core.get_post(200), policy, now=NOW
        )
        self.assertEqual(second, 0)

    async def test_default_and_per_rule_overrides_union_with_priority(self):
        ids = [t.id for t in self.targets]
        await self.routes.set_defaults(self.user.id, [ids[0], ids[1]])
        await self.routes.set_rule(
            self.user.id, self.stock.id,
            priority=Priority.URGENT, override_targets=[ids[1], ids[2]],
        )
        policy = await self.routes.load_policy(self.user.id)
        self.assertEqual(decide_route(
            await self.core.get_post(200), policy,
        ).targets, ((ids[0], Priority.NORMAL),
                    (ids[1], Priority.URGENT),
                    (ids[2], Priority.URGENT)))
        _, count = await enqueue_route(
            self.core, await self.core.get_post(200), policy, now=NOW
        )
        self.assertEqual(count, 3)
        tasks = await self.core.list_tasks(self.user.id, 200)
        self.assertEqual([t.priority for t in tasks], [0, 1, 1])

    async def test_empty_override_is_not_the_legacy_default(self):
        await self.routes.set_defaults(self.user.id, [])
        p = await self.routes.load_policy(self.user.id)
        self.assertEqual(p.default_targets, ())
        self.assertEqual(decide_route(
            await self.core.get_post(200), p,
        ).targets, ())
        await self.routes.set_defaults(self.user.id, None)
        self.assertEqual(
            len((await self.routes.load_policy(self.user.id)).default_targets), 3
        )

    async def test_last_known_first_and_category_filter_require_completion(self):
        await self.db.set_user_categories(101, ["trade"])
        await self.core.observe(
            observation(
                201, source=Source.TELEGRAM, event_id="tg201",
                title="DMIT", summary=None, category=None,
            )
        )
        policy = await self.routes.load_policy(self.user.id)
        self.assertEqual(decide_route(
            await self.core.get_post(201), policy
        ).targets, ())
        await self.core.observe(
            observation(
                201, source=Source.RSS, event_id="rss201",
                title="later", summary="补货", category="交易",
            )
        )
        _, count = await enqueue_route(
            self.core, await self.core.get_post(201), policy, now=NOW
        )
        self.assertEqual(count, 3)
        self.assertEqual((await self.core.get_post(201)).title, "DMIT")

    async def test_block_word_overrides_positive_rule_and_disabled_rule(self):
        await self.db.add_block_keyword(101, "求购")
        await self.core.observe(observation(202, title="DMIT 求购"))
        policy = await self.routes.load_policy(self.user.id)
        self.assertFalse(decide_route(await self.core.get_post(202), policy).targets)
        await self.db.set_keyword_enabled(101, self.dmit.id, False)
        await self.core.observe(observation(203, title="DMIT", summary="normal"))
        self.assertFalse(decide_route(await self.core.get_post(203),
                                      await self.routes.load_policy(self.user.id)).targets)

    async def test_disabled_target_not_selected_and_user_pause(self):
        await self.db.set_target_enabled(self.user.id, self.targets[0].id, False)
        self.assertEqual(
            len((await self.routes.load_policy(self.user.id)).default_targets), 2
        )
        await self.db.set_user_enabled(101, False)
        policy = await self.routes.load_policy(self.user.id)
        self.assertFalse(policy.enabled)
        self.assertEqual(decide_route(await self.core.get_post(200), policy).targets, ())

    async def test_cross_user_target_and_keyword_rejected_transactionally(self):
        other = await self.db.ensure_user_profile(
            202, 1202, None, "B", None, "private"
        )
        other_target = (await self.db.list_targets_by_tg_user(202))[0]
        _, other_rule = await self.db.add_keyword(202, "vps")
        old = await self.routes.load_policy(self.user.id)
        with self.assertRaises(ValueError):
            await self.routes.set_defaults(
                self.user.id, [self.targets[0].id, other_target.id]
            )
        with self.assertRaises(ValueError):
            await self.routes.set_rule(
                self.user.id, other_rule.id,
                priority=Priority.URGENT,
            )
        with self.assertRaises(ValueError):
            await self.routes.bind_channel(
                self.user.id, other_target.id, Channel.BARK, "BARK_SECRET"
            )
        self.assertEqual((await self.routes.load_policy(self.user.id)).rules,
                         old.rules)
        self.assertEqual((await self.routes.load_policy(other.id)).default_targets,
                         (other_target.id,))

    async def test_channel_binding_has_secret_reference_only(self):
        ids = [t.id for t in self.targets]
        await self.routes.bind_channel(
            self.user.id, ids[1], Channel.BARK, "BARK_SECRET"
        )
        await self.routes.bind_channel(
            self.user.id, ids[2], Channel.NTFY, "NTFY_TOPIC"
        )
        self.assertEqual(
            (await self.routes.channel_for(self.user.id, ids[0])).channel,
            Channel.TELEGRAM,
        )
        self.assertEqual(
            (await self.routes.channel_for(self.user.id, ids[1])).secret_ref,
            "BARK_SECRET",
        )
        self.assertEqual(
            (await self.routes.channel_for(self.user.id, ids[2])).channel,
            Channel.NTFY,
        )
        for bad in ("bark://api.day.app/device-key", "x\npath", "", "TOKEN=aaa"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                await self.routes.bind_channel(
                    self.user.id, ids[1], Channel.BARK, bad
                )

    async def test_target_cooldown_extends_and_survives_restart(self):
        tid = self.targets[0].id
        await self.routes.extend_cooldown(tid, until=100)
        await RouteStore(self.path).extend_cooldown(tid, until=90)
        self.assertIn(tid, await RouteStore(self.path).blocked_targets(now=99))
        self.assertNotIn(tid, await self.routes.blocked_targets(now=100))
        await self.routes.extend_cooldown(tid, until=300)
        self.assertIn(tid, await self.routes.blocked_targets(now=299))

    async def test_priority_and_exclusion_claims_keep_s2_default_contract(self):
        ids = [t.id for t in self.targets]
        await self.core.enqueue(self.user.id, 200, ids[:2],
                                now=NOW, priority=0)
        await self.core.enqueue(self.user.id, 200, [ids[2]],
                                now=NOW, priority=1)
        urgent = await self.core.claim(
            now=NOW, priority=1, exclude_target_ids=(ids[1],),
        )
        self.assertEqual([t.target_id for t in urgent], [ids[2]])
        self.assertEqual((await self.core.claim(now=NOW, priority=1)), [])
        normal = await self.core.claim(
            now=NOW, priority=0, exclude_target_ids=(ids[0],),
        )
        self.assertEqual([t.target_id for t in normal], [ids[1]])
        with self.assertRaises(ValueError):
            await self.core.claim(now=NOW, priority=2)
        with self.assertRaises(ValueError):
            await self.core.claim(now=NOW, exclude_target_ids=(True,))

    async def test_suppress_leased_requires_fresh_fenced_token(self):
        await self.core.enqueue(
            self.user.id, 200, [self.targets[0].id], now=NOW
        )
        task = (await self.core.claim(now=NOW))[0]
        self.assertFalse(await self.core.suppress_leased(task.id, "bad", now=NOW+1))
        self.assertTrue(await self.core.suppress_leased(
            task.id, task.lease_token, now=NOW+1
        ))
        self.assertFalse(await self.core.mark_sent(task.id, task.lease_token, now=NOW+2))
        self.assertEqual(
            (await self.core.list_tasks(self.user.id))[0].status,
            TaskStatus.SUPPRESSED,
        )

    async def test_concurrent_repeat_rule_route_still_enqueues_once_per_target(self):
        post = await self.core.get_post(200)
        policy = await self.routes.load_policy(self.user.id)
        results = await asyncio.gather(*(
            enqueue_route(self.core, post, policy, now=NOW)
            for _ in range(8)
        ))
        self.assertEqual(sum(n for _, n in results), 3)
        self.assertEqual(len(await self.core.list_tasks(self.user.id, 200)), 3)


if __name__ == "__main__":
    unittest.main()
