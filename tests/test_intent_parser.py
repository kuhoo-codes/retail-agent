from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.intent_parser import MAY_2026, parse_analytics_intent


class IntentParserTests(unittest.TestCase):
    def test_sarah_spend_last_month(self) -> None:
        parsed = parse_analytics_intent("How much did Sarah Chen spend last month?")
        self.assertEqual(["revenue_net"], parsed["metrics"])
        self.assertEqual({"customer_name": "Sarah Chen"}, parsed["filters"])
        self.assertEqual(["customer"], parsed["group_by"])
        self.assertEqual(MAY_2026, parsed["date_range"])

    def test_sales_by_variant_last_month(self) -> None:
        parsed = parse_analytics_intent("Show sales by variant last month.")
        self.assertEqual(["revenue_gross", "units_sold"], parsed["metrics"])
        self.assertEqual(["variant"], parsed["group_by"])
        self.assertEqual(MAY_2026, parsed["date_range"])

    def test_revenue_by_category_in_may(self) -> None:
        parsed = parse_analytics_intent("Show revenue by category in May.")
        self.assertEqual(["revenue_net"], parsed["metrics"])
        self.assertEqual(["category"], parsed["group_by"])

    def test_top_customers(self) -> None:
        parsed = parse_analytics_intent("Top customers by spend in May.")
        self.assertEqual("revenue_net", parsed["sort_by"])
        self.assertEqual(5, parsed["limit"])

    def test_card_vs_cash(self) -> None:
        parsed = parse_analytics_intent("Card vs cash sales last month.")
        self.assertEqual(["revenue_net", "order_count"], parsed["metrics"])
        self.assertEqual(["payment_method"], parsed["group_by"])

    def test_units_by_sku(self) -> None:
        parsed = parse_analytics_intent("Show units sold by SKU.")
        self.assertEqual(["units_sold"], parsed["metrics"])
        self.assertEqual(["sku"], parsed["group_by"])

    def test_apparel_by_variant(self) -> None:
        parsed = parse_analytics_intent("Sales for apparel by variant in May.")
        self.assertEqual({"category": "apparel"}, parsed["filters"])
        self.assertEqual(["variant"], parsed["group_by"])

    def test_non_analytics_prompt_is_not_routed(self) -> None:
        self.assertIsNone(parse_analytics_intent("Ring up one tote."))


if __name__ == "__main__":
    unittest.main()
