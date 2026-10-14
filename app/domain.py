"""S2 canonical NodeSeek observations and safe three-state rule evaluation.

Pure domain code only. S3 will adapt real RSS/Telegram inputs; S4 will route
matched decisions into durable delivery tasks. The legacy poller is untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from urllib.parse import urlsplit

from app.categories import normalize_category_slug
from app.utils import strip_html


_POST_PATH = re.compile(r"^/post-(\d+)(?:-\d+)?/?$")
_ALLOWED_HOSTS = frozenset({"nodeseek.com", "www.nodeseek.com"})
_MAX_POST_ID = 2**63 - 1


def post_id_from_url(url: str) -> int | None:
    """Recognize only public NodeSeek post links (never fuzzy-title identities)."""
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme not in {"http", "https"}
        or (parts.hostname or "").lower() not in _ALLOWED_HOSTS
        or parts.username is not None
        or parts.password is not None
        or port not in {None, 80, 443}
    ):
        return None
    match = _POST_PATH.fullmatch(parts.path)
    if match is None:
        return None
    digits = match.group(1)
    # Reject unbounded integers before int() (Python 3.11+ limits huge
    # decimal conversions; outside input must fail closed, not raise).
    if len(digits) > 19:
        return None
    post_id = int(digits)
    return post_id if 0 < post_id <= _MAX_POST_ID else None


def canonical_post_url(post_id: int) -> str:
    if type(post_id) is not int or not 0 < post_id <= _MAX_POST_ID:
        raise ValueError("NodeSeek post_id must be a positive signed-64-bit integer")
    return f"https://www.nodeseek.com/post-{post_id}-1"


class Source(str, Enum):
    RSS = "rss"
    TELEGRAM = "telegram"


@dataclass(frozen=True, slots=True)
class SourceObservation:
    """One public source event, with observed time from the collector's clock.

    None means a field was NOT OBSERVED; an empty string is a KNOWN empty field.
    The event ID belongs to the source namespace (TG channel msg id or RSS id).
    """

    source: Source
    event_id: str
    post_id: int
    observed_at: datetime
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    link: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, Source):
            raise ValueError("unsupported source")
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("source event_id is required")
        canonical_post_url(self.post_id)
        if not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None:
            raise ValueError("observation time must be timezone-aware")
        if self.observed_at.utcoffset() is None:
            raise ValueError("observation time must have a valid UTC offset")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(timezone.utc))
        object.__setattr__(self, "event_id", self.event_id.strip())
        for key in ("title", "summary"):
            value = getattr(self, key)
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError(f"{key} must be str or None")
                object.__setattr__(self, key, strip_html(value))
        if self.category is not None and not isinstance(self.category, str):
            raise ValueError("category must be str or None")
        if self.link is not None and post_id_from_url(self.link) != self.post_id:
            raise ValueError("post URL must identify the same NodeSeek post")

    @property
    def category_slug(self) -> str | None:
        return normalize_category_slug(self.category)

    @classmethod
    def from_url(
        cls, source: Source, event_id: str, url: str, observed_at: datetime,
        *, title: str | None = None, summary: str | None = None,
        category: str | None = None,
    ) -> "SourceObservation":
        post_id = post_id_from_url(url)
        if post_id is None:
            raise ValueError("unrecognized public NodeSeek post URL")
        return cls(
            source=source, event_id=event_id, post_id=post_id,
            observed_at=observed_at, title=title, summary=summary,
            category=category, link=url,
        )


@dataclass(frozen=True, slots=True)
class FieldOrigin:
    field: str
    source: Source
    event_id: str


@dataclass(frozen=True, slots=True)
class CanonicalPost:
    """One post across sources; never overwrite already observed known fields."""

    post_id: int
    title: str | None
    summary: str | None
    category_slug: str | None
    observations: tuple[SourceObservation, ...]
    origins: tuple[FieldOrigin, ...]

    @classmethod
    def from_observation(cls, observation: SourceObservation) -> "CanonicalPost":
        return cls(
            post_id=observation.post_id,
            title=None, summary=None, category_slug=None,
            observations=(), origins=(),
        ).enrich(observation)

    @property
    def url(self) -> str:
        return canonical_post_url(self.post_id)

    @property
    def first_seen_at(self) -> datetime:
        return min(obs.observed_at for obs in self.observations)

    def first_seen_by_source(self) -> dict[Source, datetime]:
        times: dict[Source, datetime] = {}
        for obs in self.observations:
            if obs.source not in times or obs.observed_at < times[obs.source]:
                times[obs.source] = obs.observed_at
        return times

    def origin_for(self, field: str) -> FieldOrigin | None:
        return next((origin for origin in self.origins if origin.field == field), None)

    def enrich(self, observation: SourceObservation) -> "CanonicalPost":
        if self.post_id != observation.post_id:
            raise ValueError("cannot merge different NodeSeek post IDs")
        if any(
            obs.source == observation.source and obs.event_id == observation.event_id
            for obs in self.observations
        ):
            return self

        changes: dict[str, str] = {}
        origins = list(self.origins)
        fields = {
            "title": observation.title,
            "summary": observation.summary,
            "category_slug": observation.category_slug,
        }
        for field, value in fields.items():
            if getattr(self, field) is None and value is not None:
                changes[field] = value
                origins.append(FieldOrigin(field, observation.source, observation.event_id))
        return replace(
            self,
            **changes,
            observations=self.observations + (observation,),
            origins=tuple(origins),
        )


class RuleOutcome(str, Enum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    INSUFFICIENT_DATA = "insufficient_data"


def _normalize_terms(values: tuple[str, ...]) -> tuple[str, ...]:
    if any(not isinstance(x, str) for x in values):
        raise ValueError("keyword terms must be text")
    return tuple(dict.fromkeys(x.strip().casefold() for x in values if x.strip()))


@dataclass(frozen=True, slots=True)
class RuleSet:
    """OR across clauses, AND within a clause; block and category are mandatory.

    Example: (("oracle",), ("dmit", "补货")) means oracle OR (dmit AND 补货).
    An unknown summary means an absent word or blocker is NOT provably absent.
    """

    clauses: tuple[tuple[str, ...], ...]
    blocked: tuple[str, ...] = ()
    allowed_categories: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        clauses = tuple(_normalize_terms(terms) for terms in self.clauses)
        if any(not terms for terms in clauses):
            raise ValueError("empty AND clause")
        object.__setattr__(self, "clauses", clauses)
        object.__setattr__(self, "blocked", _normalize_terms(self.blocked))
        categories = frozenset(normalize_category_slug(c) for c in self.allowed_categories)
        if None in categories:
            raise ValueError("unrecognized category in filter")
        object.__setattr__(self, "allowed_categories", categories)


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    outcome: RuleOutcome
    matched_clauses: tuple[int, ...] = ()
    missing_fields: tuple[str, ...] = ()
    reason: str = ""


def evaluate_rules(post: CanonicalPost, rules: RuleSet) -> RuleEvaluation:
    """Fail closed for missing summary/blocker/category information.

    NOT_MATCHED is definitive; INSUFFICIENT_DATA means wait for another source.
    A definitive blocker/category mismatch overrides partial positive matches.
    """
    if not rules.clauses:
        return RuleEvaluation(RuleOutcome.NOT_MATCHED, reason="no_enabled_rules")

    if rules.allowed_categories:
        if post.category_slug is None:
            return RuleEvaluation(
                RuleOutcome.INSUFFICIENT_DATA,
                missing_fields=("category_slug",), reason="category_unknown",
            )
        if post.category_slug not in rules.allowed_categories:
            return RuleEvaluation(RuleOutcome.NOT_MATCHED, reason="category_filtered")

    parts = (post.title, post.summary)
    text = " ".join(part for part in parts if part is not None).casefold()
    missing = tuple(name for name, part in zip(("title", "summary"), parts) if part is None)

    if any(block in text for block in rules.blocked):
        return RuleEvaluation(RuleOutcome.NOT_MATCHED, reason="blocked")

    matched = tuple(
        index for index, terms in enumerate(rules.clauses)
        if all(term in text for term in terms)
    )

    # A blocker cannot safely be pronounced absent until all searchable
    # fields have been observed, even if a positive keyword already matched.
    if missing and (bool(rules.blocked) or not matched):
        return RuleEvaluation(
            RuleOutcome.INSUFFICIENT_DATA,
            matched_clauses=matched, missing_fields=missing,
            reason="text_fields_missing",
        )
    if matched:
        return RuleEvaluation(RuleOutcome.MATCHED, matched_clauses=matched)
    return RuleEvaluation(RuleOutcome.NOT_MATCHED, reason="keywords_not_matched")
