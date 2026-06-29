from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_store.agent import RetailAgent
from retail_store.database import connect
from retail_store.intent_parser import parse_intent_without_llm
from retail_store.memory import SessionMemory
from retail_store.seed import seed_database


class HiddenPromptVariationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.memory = SessionMemory()

    def assert_tool(self, text: str, expected: str) -> dict:
        parsed = parse_intent_without_llm(text, self.memory)
        self.assertEqual(expected, parsed["tool_name"], text)
        return parsed

    def test_sale_verb_and_walk_in_variations(self) -> None:
        for verb in ("sell", "checkout", "ring up", "buy"):
            for customer in ("customer is walk in", "no customer", "walk-in"):
                parsed = self.assert_tool(
                    f"{verb} one canvas bag, {customer}, cash",
                    "ring_up_order",
                )
                self.assertIsNone(parsed["arguments"]["customer_name"])
                self.assertEqual("cash", parsed["arguments"]["payment_method"])
                self.assertEqual(
                    "Canvas Tote",
                    parsed["arguments"]["items"][0]["product_description"],
                )

    def test_size_and_product_alias_variations(self) -> None:
        for size_text, expected_size in (
            ("medium", "M"),
            ("med", "M"),
            ("M", "M"),
            ("large", "L"),
            ("L", "L"),
        ):
            parsed = self.assert_tool(
                f"sell one Blue {size_text} classic tee", "ring_up_order"
            )
            self.assertEqual(expected_size, parsed["arguments"]["items"][0]["size"])

        aliases = {
            "tee": "Classic Tee",
            "tees": "Classic Tee",
            "t-shirt": "Classic Tee",
            "classic tee": "Classic Tee",
            "hoodie": "hoodie",
            "hoodies": "hoodie",
            "sweatshirt": "hoodie",
            "bag": "Canvas Tote",
            "canvas bag": "Canvas Tote",
            "tote": "Canvas Tote",
        }
        for alias, expected in aliases.items():
            parsed = self.assert_tool(f"sell one {alias}", "ring_up_order")
            self.assertEqual(
                expected, parsed["arguments"]["items"][0]["product_description"]
            )

    def test_return_wording_and_condition_variations(self) -> None:
        for phrase in ("refund", "return", "came back"):
            parsed = self.assert_tool(
                f"{phrase} the tote from order O-1006, damaged",
                "process_return",
            )
            self.assertEqual("damaged", parsed["arguments"]["condition"])
        good = self.assert_tool(
            "the Navy L hoodie came back from order O-1006 in good condition",
            "process_return",
        )
        self.assertEqual("good", good["arguments"]["condition"])
        self.assertEqual("L", good["arguments"]["size"])

    def test_date_analytics_and_inventory_variations(self) -> None:
        for period in ("last month", "May", "May 2026"):
            parsed = self.assert_tool(
                f"show top products by profit for {period}",
                "top_products_by_profit_margin",
            )
            self.assertEqual("2026-05-01", parsed["arguments"]["start_date"])
            self.assertEqual("2026-05-31", parsed["arguments"]["end_date"])

        for phrase in (
            "what is about to stock out",
            "show stockout risk",
            "show low inventory",
        ):
            self.assert_tool(phrase, "get_stockout_risk")

        for phrase in (
            "reorder items below reorder point",
            "reorder low stock",
            "restock the store",
        ):
            self.assert_tool(phrase, "reorder_low_stock")

        for date_phrase in ("today", "dated today"):
            parsed = self.assert_tool(
                f"sell one tote {date_phrase}", "ring_up_order"
            )
            self.assertEqual("2026-06-19", parsed["arguments"]["order_date"])


class HiddenPromptAgentBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "retail.db"
        seed_database(ROOT / "data", self.database)
        self.connection = connect(self.database)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.agent = RetailAgent(self.connection)

    def tearDown(self) -> None:
        self.env.stop()
        self.connection.close()
        self.temp_dir.cleanup()

    def test_ambiguity_unknown_product_and_stock_errors_are_clear(self) -> None:
        ambiguous = self.agent.handle_user_message(
            "checkout one medium hoodie for Sarah Chen"
        )
        self.assertIn("clarification", ambiguous.casefold())
        self.assertIn("ambiguous", ambiguous.casefold())

        unclear = self.agent.handle_user_message("buy one gadget")
        self.assertIn("specify which item", unclear.casefold())

        insufficient = self.agent.handle_user_message("sell ten canvas bags")
        self.assertIn("insufficient inventory", insufficient.casefold())

    def test_unclear_return_requests_item_and_missing_key_never_crashes(self) -> None:
        order = self.agent.handle_user_message(
            "checkout one tote and one mug, no customer"
        )
        self.assertIn("Order O-1016", order)
        response = self.agent.handle_user_message("now return that")
        self.assertIn("item or SKU", response)
        self.assertNotIn("Traceback", response)


if __name__ == "__main__":
    unittest.main()
