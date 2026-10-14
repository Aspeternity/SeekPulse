"""S2-01 canonical identity, provenance, and fail-closed rule engine.

All fixtures are synthetic, tests are deterministic and perform no I/O.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.domain import (
    CanonicalPost, RuleOutcome, RuleSet, Source, SourceObservation,
    canonical_post_url, evaluate_rules, post_id_from_url,
)


NOW = datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc)


def observed(post_id=1234, source=Source.RSS, event_id="rss-1", **fields):
    return SourceObservation(
        source=source, event_id=event_id, post_id=post_id,
        observed_at=fields.pop("observed_at", NOW), **fields,
    )


def post(**fields):
    return CanonicalPost.from_observation(observed(**fields))


class NodeSeekIdentityTests(unittest.TestCase):
    def test_official_link_forms_have_same_canonical_id(self):
        for url in (
            "https://www.nodeseek.com/post-1234-1",
            "https://nodeseek.com/post-1234",
            "http://www.nodeseek.com/post-1234-2/",
            "https://www.nodeseek.com:443/post-1234-1?x=2#reply",
        ):
            with self.subTest(url=url):
                self.assertEqual(post_id_from_url(url), 1234)
        self.assertEqual(canonical_post_url(1234),
                         "https://www.nodeseek.com/post-1234-1")

    def test_reject_phishing_private_or_unrecognized_links(self):
        for url in (
            "https://nodeseek.com.evil.invalid/post-1234-1",
            "https://evil.invalid/nodeseek.com/post-1234-1",
            "https://user:password@nodeseek.com/post-1234-1",
            "https://rss.nodeseek.com/post-1234-1",
            "https://nodeseek.com:8080/post-1234-1",
            "file:///post-1234-1",
            "https://nodeseek.com/post-1234-1/other",
            "https://nodeseek.com/post-0-1",
            "https://nodeseek.com/post-title-1",
            "https://nodeseek.com/post-9223372036854775808-1",
            "https://nodeseek.com/post-1-1",
        ):
            if url == "https://nodeseek.com/post-1-1":
                continue
            with self.subTest(url=url):
                self.assertIsNone(post_id_from_url(url))

    def test_unbounded_external_numeric_id_fails_closed(self):
        long_link = "https://www.nodeseek.com/post-" + "9" * 5000 + "-1"
        self.assertIsNone(post_id_from_url(long_link))

    def test_reject_invalid_post_ids(self):
        for value in (0, -1, True, "123", 2**63):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    canonical_post_url(value)

    def test_extract_from_link_no_fuzzy_title_fallback(self):
        item = SourceObservation.from_url(
            Source.TELEGRAM, "msg-42", "https://nodeseek.com/post-1234-3",
            NOW, title="DMIT announcement",
        )
        self.assertEqual(item.post_id, 1234)
        self.assertEqual(item.source, Source.TELEGRAM)
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            SourceObservation.from_url(Source.TELEGRAM, "m2", "https://evil.invalid/1234",
                                       NOW, title="DMIT announcement")

    def test_explicit_post_id_conflicting_link_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "same NodeSeek post"):
            observed(link="https://www.nodeseek.com/post-999-1")

    def test_naive_time_and_unknown_source_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            observed(observed_at=datetime(2026, 10, 14))
        with self.assertRaisesRegex(ValueError, "unsupported source"):
            observed(source="rss")

    def test_observation_time_is_utc(self):
        east = timezone(timedelta(hours=8))
        when = datetime(2026, 10, 14, 8, 0, tzinfo=east)
        item = observed(observed_at=when)
        self.assertEqual(item.observed_at, NOW)


class CanonicalAggregationTests(unittest.TestCase):
    def test_first_known_field_wins_and_later_source_only_fills_absent_fields(self):
        tg = observed(
            source=Source.TELEGRAM, event_id="tg-5",
            observed_at=NOW, title=" First <b>title</b> ", summary=None,
            category=None,
        )
        rss = observed(
            source=Source.RSS, event_id="rss-5",
            observed_at=NOW + timedelta(seconds=2), title="later title",
            summary="Second &amp; summary", category="交易",
        )
        first = CanonicalPost.from_observation(tg)
        final = first.enrich(rss)
        self.assertEqual(first.title, "First title")
        self.assertIsNone(first.summary)
        self.assertEqual(final.title, "First title")
        self.assertEqual(final.summary, "Second & summary")
        self.assertEqual(final.category_slug, "trade")
        self.assertEqual(final.origin_for("title").source, Source.TELEGRAM)
        self.assertEqual(final.origin_for("summary").source, Source.RSS)
        self.assertEqual(final.origin_for("category_slug").event_id, "rss-5")
        self.assertEqual(len(final.observations), 2)
        self.assertEqual(final.url, canonical_post_url(1234))

    def test_same_source_event_replay_is_idempotent(self):
        x = observed(title="Known", event_id="event-1")
        p = CanonicalPost.from_observation(x)
        duplicate = observed(title="Changed", event_id="event-1")
        self.assertIs(p.enrich(duplicate), p)

    def test_one_source_event_must_not_merge_different_post_id(self):
        p = post(title="A")
        with self.assertRaisesRegex(ValueError, "different"):
            p.enrich(observed(post_id=4321, title="A"))

    def test_same_title_different_post_id_remains_distinct(self):
        a = post(post_id=1234, title="DMIT")
        b = post(post_id=4321, title="DMIT")
        self.assertNotEqual(a.post_id, b.post_id)
        self.assertNotEqual(a.url, b.url)

    def test_source_first_seen_times_and_earliest_observed_clock(self):
        rss = observed(source=Source.RSS, event_id="rss-3",
                       observed_at=NOW + timedelta(seconds=10))
        tg = observed(source=Source.TELEGRAM, event_id="tg-3",
                      observed_at=NOW + timedelta(seconds=4))
        again = observed(source=Source.RSS, event_id="rss-4",
                         observed_at=NOW + timedelta(seconds=20))
        p = CanonicalPost.from_observation(rss).enrich(tg).enrich(again)
        self.assertEqual(p.first_seen_at, NOW + timedelta(seconds=4))
        self.assertEqual(p.first_seen_by_source(), {
            Source.RSS: NOW + timedelta(seconds=10),
            Source.TELEGRAM: NOW + timedelta(seconds=4),
        })

    def test_unknown_category_is_not_guessed(self):
        p = post(title="DMIT", category="not-an-official-category")
        self.assertIsNone(p.category_slug)
        self.assertEqual(p.observations[0].category, "not-an-official-category")
        p2 = p.enrich(observed(
            source=Source.TELEGRAM, event_id="tg-known",
            title="DMIT", category="技术",
        ))
        self.assertEqual(p2.category_slug, "tech")

    def test_known_empty_summary_is_distinct_from_unobserved(self):
        p = post(title="DMIT", summary="")
        self.assertEqual(p.summary, "")
        self.assertIsNotNone(p.origin_for("summary"))

    def test_two_sources_1000_posts_collate_without_title_based_merge(self):
        merged = {}
        for index in range(1, 1001):
            a = observed(post_id=index, event_id=f"rss-{index}", title="identical")
            b = observed(
                post_id=index, event_id=f"tg-{index}",
                source=Source.TELEGRAM, title="identical", summary="补货",
            )
            merged[index] = CanonicalPost.from_observation(a).enrich(b).enrich(a)
        self.assertEqual(len(merged), 1000)
        self.assertTrue(all(len(p.observations) == 2 for p in merged.values()))


class RuleDecisionTests(unittest.TestCase):
    def test_or_across_keywords(self):
        p = post(title="Oracle VPS", summary="available")
        rules = RuleSet(clauses=(("dmit",), ("ORACLE",)))
        result = evaluate_rules(p, rules)
        self.assertEqual(result.outcome, RuleOutcome.MATCHED)
        self.assertEqual(result.matched_clauses, (1,))

    def test_and_requires_all_terms(self):
        rules = RuleSet(clauses=(("DMIT", "补货"),))
        self.assertEqual(evaluate_rules(
            post(title="DMIT", summary="刚刚补货"), rules
        ).outcome, RuleOutcome.MATCHED)
        self.assertEqual(evaluate_rules(
            post(title="DMIT", summary="促销"), rules
        ).outcome, RuleOutcome.NOT_MATCHED)

    def test_negative_match_with_unknown_summary_is_not_final(self):
        rules = RuleSet(clauses=(("dmit",),))
        decision = evaluate_rules(post(title="Oracle", summary=None), rules)
        self.assertEqual(decision.outcome, RuleOutcome.INSUFFICIENT_DATA)
        self.assertEqual(decision.missing_fields, ("summary",))
        self.assertEqual(evaluate_rules(
            post(title="Oracle", summary=""), rules
        ).outcome, RuleOutcome.NOT_MATCHED)

    def test_positive_match_with_no_blocks_can_proceed_before_summary(self):
        self.assertEqual(evaluate_rules(
            post(title="DMIT", summary=None), RuleSet(clauses=(("dmit",),))
        ).outcome, RuleOutcome.MATCHED)

    def test_blockers_take_precedence_over_matching_keywords(self):
        rules = RuleSet(clauses=(("dmit",),), blocked=("求购",))
        self.assertEqual(evaluate_rules(
            post(title="DMIT 求购", summary=None), rules
        ).outcome, RuleOutcome.NOT_MATCHED)

    def test_unknown_summary_prevents_clearing_unseen_blockers(self):
        rules = RuleSet(clauses=(("dmit",),), blocked=("求购",))
        p = post(title="DMIT", summary=None)
        result = evaluate_rules(p, rules)
        self.assertEqual(result.outcome, RuleOutcome.INSUFFICIENT_DATA)
        self.assertEqual(result.matched_clauses, (0,))
        verified = p.enrich(observed(event_id="rss-later", summary="正常出售"))
        self.assertEqual(evaluate_rules(verified, rules).outcome, RuleOutcome.MATCHED)

    def test_category_filter_missing_must_wait_even_when_keyword_matches(self):
        rules = RuleSet(clauses=(("dmit",),), allowed_categories=frozenset({"交易"}))
        r = evaluate_rules(post(title="DMIT", summary="available", category=None), rules)
        self.assertEqual(r.outcome, RuleOutcome.INSUFFICIENT_DATA)
        self.assertEqual(r.missing_fields, ("category_slug",))

    def test_category_mismatch_is_final_even_if_summary_unknown(self):
        rules = RuleSet(clauses=(("dmit",),), allowed_categories=frozenset({"trade"}))
        p = post(title="DMIT", summary=None, category="技术")
        self.assertEqual(evaluate_rules(p, rules).outcome, RuleOutcome.NOT_MATCHED)

    def test_source_enrichment_unlocks_category_filtered_match(self):
        p = post(title="DMIT", summary="补货", category=None)
        rule = RuleSet(clauses=(("dmit", "补货"),), allowed_categories=frozenset({"trade"}))
        self.assertEqual(evaluate_rules(p, rule).outcome, RuleOutcome.INSUFFICIENT_DATA)
        q = p.enrich(observed(source=Source.TELEGRAM, event_id="tg-2", category="交易"))
        self.assertEqual(evaluate_rules(q, rule).outcome, RuleOutcome.MATCHED)

    def test_blocks_match_against_summary_even_if_title_is_unknown(self):
        rules = RuleSet(clauses=(("dmit",),), blocked=("求购",))
        self.assertEqual(evaluate_rules(
            post(title=None, summary="DMIT 求购"), rules
        ).outcome, RuleOutcome.NOT_MATCHED)

    def test_missing_title_and_incomplete_and_clause_requires_more_data(self):
        rules = RuleSet(clauses=(("dmit", "补货"),))
        r = evaluate_rules(post(title=None, summary="DMIT"), rules)
        self.assertEqual(r.outcome, RuleOutcome.INSUFFICIENT_DATA)
        self.assertEqual(r.missing_fields, ("title",))

    def test_no_rules_is_not_matched(self):
        self.assertEqual(
            evaluate_rules(post(title=None, summary=None), RuleSet(clauses=())).outcome,
            RuleOutcome.NOT_MATCHED,
        )

    def test_invalid_rule_categories_and_empty_clause_rejected(self):
        with self.assertRaises(ValueError):
            RuleSet(clauses=(("dmit",),), allowed_categories=frozenset({"unknown"}))
        with self.assertRaises(ValueError):
            RuleSet(clauses=((),))

    def test_rule_terms_are_casefolded_and_deduplicated(self):
        rules = RuleSet(clauses=((" ORACLE ", "oracle", "DMIT"),), blocked=(" spam ", "SPAM"))
        self.assertEqual(rules.clauses, (("oracle", "dmit"),))
        self.assertEqual(rules.blocked, ("spam",))


if __name__ == "__main__":
    unittest.main()
