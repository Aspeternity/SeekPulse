"""Very small non-mutating smoke tests for the *unchanged upstream* logic.

S1 will expand tests after G0 acceptance; these tests preserve G0 boundaries.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.categories import normalize_category_slug
from app.rss import match_keyword_rules, match_keywords


class UpstreamMatchingTests(unittest.TestCase):
    def test_basic_keyword_is_case_insensitive(self) -> None:
        self.assertEqual(match_keywords("new dmit vps", ["DMIT", "RackNerd"]), ["DMIT"])

    def test_combo_requires_all_terms(self) -> None:
        rules = [SimpleNamespace(required_keywords="dmit,补货", normalized_keyword="dmit,补货")]
        self.assertEqual(match_keyword_rules("DMIT vps", rules), [])
        self.assertEqual(match_keyword_rules("DMIT 本次补货", rules), rules)

    def test_existing_trade_category(self) -> None:
        self.assertEqual(normalize_category_slug("交易"), "trade")


if __name__ == "__main__":
    unittest.main()
