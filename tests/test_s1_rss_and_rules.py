"""S1 upstream RSS / matching characterization: offline, deterministic, no API calls.

These assert observed AI-XMLY behavior; they do not implement proposed V1.1 rules.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.bot import _split_combo_terms, _split_keywords
from app.categories import category_label, normalize_category_slug
from app.rss import FeedClient, match_keyword_rules, match_keywords
from app.utils import normalize_keywords, strip_html, truncate_text


RSS_FIXTURE = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>NodeSeek &amp; News</title>
<item><guid isPermaLink="false">post-101</guid>
<title>DMIT &amp; VPS</title>
<link>https://example.invalid/post-101</link>
<description><![CDATA[<p>Test <b>Chinese &#34917;&#36135;</b></p>]]></description>
<category>&#20132;&#26131;</category>
<pubDate>Wed, 02 Oct 2024 10:00:00 GMT</pubDate>
</item>
<item><title>Unknown Category</title>
<link>https://example.invalid/post-102</link>
<description>Simple description</description>
<category>unlisted-topic</category></item>
<item><title>Extra Entry</title><link>https://example.invalid/post-103</link></item>
</channel></rss>
"""

ATOM_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Updates</title>
<entry><id>tag:example.invalid,2024:201</id><title>Oracle new</title>
<link href="https://example.invalid/201"/>
<summary type="html">&lt;b&gt;Now available&lt;/b&gt;</summary>
<category term="tech"/><updated>2024-10-02T10:00:00Z</updated></entry>
</feed>
"""


class FakeResponse:
    def __init__(self, data: bytes, error: Exception | None = None) -> None:
        self.data = data
        self.error = error
        self.checked = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def raise_for_status(self) -> None:
        self.checked = True
        if self.error is not None:
            raise self.error

    async def read(self) -> bytes:
        return self.data


class FakeSession:
    def __init__(self, response: FakeResponse, calls: list) -> None:
        self.response = response
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def get(self, url: str):
        self.calls.append(url)
        return self.response


class FeedParsingTests(unittest.IsolatedAsyncioTestCase):
    async def test_rss_extracts_identity_category_description_and_limits(self):
        urls = []
        response = FakeResponse(RSS_FIXTURE)
        kwargs_seen = []

        def session_factory(**kwargs):
            kwargs_seen.append(kwargs)
            return FakeSession(response, urls)

        with patch("app.rss.aiohttp.ClientSession", side_effect=session_factory):
            result = await FeedClient(timeout_seconds=3, max_entries_per_feed=2).fetch(
                "https://example.invalid/rss"
            )

        self.assertEqual(urls, ["https://example.invalid/rss"])
        self.assertTrue(response.checked)
        self.assertEqual(len(kwargs_seen), 1)
        self.assertEqual(kwargs_seen[0]["timeout"].total, 3)
        self.assertIn("User-Agent", kwargs_seen[0]["headers"])
        self.assertEqual(result.feed_title, "NodeSeek & News")
        self.assertEqual(len(result.entries), 2)
        first, second = result.entries
        self.assertEqual(first.item_key, "post-101")
        self.assertEqual(first.title, "DMIT & VPS")
        self.assertEqual(first.link, "https://example.invalid/post-101")
        self.assertEqual(first.summary, "Test Chinese 补货")
        self.assertEqual(first.category_slug, "trade")
        self.assertEqual(first.category_name, "交易")
        self.assertIn("dmit", first.source_text)
        self.assertIn("补货", first.source_text)
        self.assertIn("交易", first.source_text)
        self.assertIn("2024", first.published_at)
        self.assertEqual(second.item_key, "https://example.invalid/post-102")
        self.assertIsNone(second.category_slug)
        self.assertEqual(second.category_name, "未分类")
        self.assertIn("unlisted-topic", second.source_text)

    async def test_atom_id_and_category_are_supported_without_network(self):
        with patch("app.rss.aiohttp.ClientSession",
                   side_effect=lambda **_kwargs: FakeSession(FakeResponse(ATOM_FIXTURE), [])):
            result = await FeedClient(3, 30).fetch("https://example.invalid/atom")
        entry = result.entries[0]
        self.assertEqual(entry.item_key, "tag:example.invalid,2024:201")
        self.assertEqual(entry.category_slug, "tech")
        self.assertEqual(entry.summary, "Now available")
        self.assertEqual(entry.link, "https://example.invalid/201")

    async def test_http_failure_propagates_without_partial_entries(self):
        with patch("app.rss.aiohttp.ClientSession",
                   side_effect=lambda **_kwargs: FakeSession(
                       FakeResponse(RSS_FIXTURE, ValueError("simulated http failure")), [])):
            with self.assertRaisesRegex(ValueError, "simulated"):
                await FeedClient(3, 30).fetch("https://example.invalid/rss")


class RuleContractTests(unittest.TestCase):
    def test_plain_keyword_or_semantics_are_case_insensitive(self):
        self.assertEqual(match_keywords("DMIT and Oracle", ["dmit", "ORACLE", "none"]),
                         ["dmit", "ORACLE"])
        self.assertEqual(match_keywords("no matching terms", ["dmit"]), [])

    def test_matching_multiple_independent_rules_is_or(self):
        dmit = SimpleNamespace(required_keywords="dmit", normalized_keyword="dmit")
        oracle = SimpleNamespace(required_keywords="oracle", normalized_keyword="oracle")
        combo = SimpleNamespace(required_keywords="dmit,补货", normalized_keyword="dmit + 补货")
        rules = [dmit, oracle, combo]
        self.assertEqual(match_keyword_rules("Oracle sale", rules), [oracle])
        self.assertEqual(match_keyword_rules("DMIT 补货 available", rules), [dmit, combo])
        self.assertEqual(match_keyword_rules("not present", rules), [])

    def test_combo_requires_every_term_and_is_case_insensitive(self):
        combo = SimpleNamespace(required_keywords="dmit,补货", normalized_keyword="dmit + 补货")
        self.assertEqual(match_keyword_rules("DMIT 促销", [combo]), [])
        self.assertEqual(match_keyword_rules("今天补货 DMIT", [combo]), [combo])

    def test_legacy_single_rule_falls_back_to_normalized_keyword(self):
        rule = SimpleNamespace(required_keywords="", normalized_keyword="dmit")
        self.assertEqual(match_keyword_rules("DMIT", [rule]), [rule])

    def test_plain_and_combo_input_normalization(self):
        self.assertEqual(_split_keywords(" DMIT,oracle,dmit,,Oracle, 补货 "),
                         ["DMIT", "oracle", "补货"])
        self.assertEqual(_split_combo_terms("DMIT,oracle,dmit"),
                         ["DMIT", "oracle"])
        self.assertEqual(_split_combo_terms(" DMIT + 补货 + dmit "),
                         ["DMIT", "补货"])
        self.assertEqual(normalize_keywords("A, a, , 甲"), ["a", "甲"])

    def test_categories_and_unknowns(self):
        self.assertEqual(normalize_category_slug(" 交易 "), "trade")
        self.assertEqual(normalize_category_slug("TECH"), "tech")
        self.assertEqual(normalize_category_slug("promotion"), "promo")
        self.assertIsNone(normalize_category_slug("not-a-category"))
        self.assertEqual(category_label(None), "未分类")

    def test_feed_text_escaping_and_truncation(self):
        self.assertEqual(strip_html("  &amp; <b>热</b>  "), "& 热")
        self.assertEqual(truncate_text(" abcdef ", 5), "abcd…")


if __name__ == "__main__":
    unittest.main()
