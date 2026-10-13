"""Offline S0 probe tests. No network access, secrets, or production changes."""

from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts.s0_public_probe import post_id_from_url, rss_ids, sample_source, telegram_ids


class SourceProbeTests(unittest.TestCase):
    def test_canonical_url_and_query(self) -> None:
        self.assertEqual(post_id_from_url("https://www.nodeseek.com/post-981300-1"), "981300")
        self.assertEqual(post_id_from_url("https://nodeseek.com/post-981314-1?via=tg"), "981314")
        self.assertEqual(post_id_from_url("http://nodeseek.com/post-42"), "42")

    def test_reject_wrong_sites_schemes_and_paths(self) -> None:
        for value in [
            "https://nodeseek.com.evil.net/post-42-1",
            "https://evil.net/post-42-1",
            "https://nodeseek.com@evil.net/post-42-1",
            "javascript:alert(1)",
            "https://nodeseek.com/posts-42-1",
            "https://nodeseek.com/post-42-1/fake",
            "https://nodeseek.com:9000/post-42-1",
            "https://nodeseek.com:invalid/post-42-1",
            "https://t.me/nodeseekc/42",
        ]:
            with self.subTest(value=value):
                self.assertIsNone(post_id_from_url(value))

    def test_telegram_anchor_list_and_duplicate(self) -> None:
        html = '''<div><a href="https://www.nodeseek.com/post-981300-1">A</a>
        <a href="https://www.nodeseek.com/post-981300-1">A again</a>
        <a href="https://www.nodeseek.com/post-981314-1">B</a>
        <a href="https://evil.invalid/post-56-1">no</a></div>'''
        self.assertEqual(telegram_ids(html), {"linked_post_count": 3, "unique_post_ids": ["981300", "981314"]})

    def test_rss_20_links(self) -> None:
        xml = b'''<?xml version="1.0"?><rss version="2.0"><channel><title>NodeSeek</title>
        <item><link>https://www.nodeseek.com/post-981300-1</link></item>
        <item><guid>https://www.nodeseek.com/post-981314-1</guid></item>
        <item><link>https://other.example/post-43-1</link></item></channel></rss>'''
        self.assertEqual(rss_ids(xml), {"feed_type": "rss", "entry_count": 3, "unique_post_ids": ["981300", "981314"]})

    def test_atom_links(self) -> None:
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <link href="https://nodeseek.com/post-333-1" /></entry></feed>'''
        self.assertEqual(rss_ids(xml), {"feed_type": "feed", "entry_count": 1, "unique_post_ids": ["333"]})

    def test_invalid_feed_rejected(self) -> None:
        with self.assertRaises(ValueError):
            rss_ids(b"<not-a-feed/>")

    def test_http_error_is_redacted_and_nonfatal(self) -> None:
        with patch("scripts.s0_public_probe.urlopen", side_effect=HTTPError("https://example.invalid/token", 403, "Forbidden", {}, None)):
            result = sample_source("rss", "https://rss.nodeseek.com/", 2)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["http_status"], 403)
        self.assertNotIn("example.invalid", str(result))


if __name__ == "__main__":
    unittest.main()
