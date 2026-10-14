"""S4 pure per-user rule routing; no network or database ownership.

Uses S2's fail-closed three-state RuleSet. The same post+user+target gets
one CoreStore task, irrespective of source count and matching rule count.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from app.domain import CanonicalPost, RuleOutcome, RuleSet, evaluate_rules


class Priority(int, Enum):
    NORMAL = 0
    URGENT = 1


@dataclass(frozen=True, slots=True)
class RuleRoute:
    keyword_id: int
    rules: RuleSet
    priority: Priority = Priority.NORMAL
    override_targets: tuple[int, ...] | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if type(self.keyword_id) is not int or self.keyword_id <= 0:
            raise ValueError("invalid keyword ID")
        if not isinstance(self.rules, RuleSet):
            raise ValueError("rules must be a RuleSet")
        if not isinstance(self.priority, Priority):
            raise ValueError("invalid priority")
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be boolean")
        if self.override_targets is not None:
            _targets(self.override_targets)


@dataclass(frozen=True, slots=True)
class UserPolicy:
    user_id: int
    default_targets: tuple[int, ...]
    rules: tuple[RuleRoute, ...]
    enabled: bool = True

    def __post_init__(self) -> None:
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("invalid user ID")
        _targets(self.default_targets)
        if len({rule.keyword_id for rule in self.rules}) != len(self.rules):
            raise ValueError("duplicate keyword ID")
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be boolean")


def _targets(ids: Sequence[int]) -> None:
    if any(type(x) is not int or x <= 0 for x in ids):
        raise ValueError("invalid target ID")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate target ID")


@dataclass(frozen=True, slots=True)
class RouteDecision:
    user_id: int
    post_id: int
    targets: tuple[tuple[int, Priority], ...]
    matched_rule_ids: tuple[int, ...] = ()
    insufficient_rule_ids: tuple[int, ...] = ()

    def includes(self, target_id: int) -> bool:
        return any(target == target_id for target, _ in self.targets)


def decide_route(post: CanonicalPost, policy: UserPolicy) -> RouteDecision:
    """Safely combine every matching rule and promote priority per target.

    A rule with missing blocker/category/summary remains INSUFFICIENT_DATA and
    does not route yet. Other complete matching rules may still route.
    """
    if not policy.enabled:
        return RouteDecision(policy.user_id, post.post_id, ())
    selected: dict[int, Priority] = {}
    matched: list[int] = []
    missing: list[int] = []
    for rule in policy.rules:
        if not rule.enabled:
            continue
        decision = evaluate_rules(post, rule.rules)
        if decision.outcome is RuleOutcome.INSUFFICIENT_DATA:
            missing.append(rule.keyword_id)
            continue
        if decision.outcome is not RuleOutcome.MATCHED:
            continue
        matched.append(rule.keyword_id)
        targets = (policy.default_targets if rule.override_targets is None
                   else rule.override_targets)
        for target in targets:
            selected[target] = max(rule.priority, selected.get(target, Priority.NORMAL))
    return RouteDecision(
        user_id=policy.user_id,
        post_id=post.post_id,
        targets=tuple(sorted(selected.items())),
        matched_rule_ids=tuple(matched),
        insufficient_rule_ids=tuple(missing),
    )


async def enqueue_route(core, post: CanonicalPost, policy: UserPolicy,
                        *, now: int, ttl_seconds: int = 1800) -> tuple[RouteDecision, int]:
    """Write a route to the existing S2 SQLite queue, never send anything."""
    decision = decide_route(post, policy)
    inserted = 0
    for priority in (Priority.URGENT, Priority.NORMAL):
        selected = [tid for tid, level in decision.targets if level is priority]
        if selected:
            inserted += await core.enqueue(
                policy.user_id, post.post_id, selected, now=now,
                ttl_seconds=ttl_seconds, priority=int(priority),
            )
    return decision, inserted
